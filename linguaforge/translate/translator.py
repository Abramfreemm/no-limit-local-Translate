"""翻译器：编号化批量请求 + JSON 契约 + 四级降级链。

契约（对模型的要求）：
  输入 {"task","glossary","items":[{"id":1,"text":"..."}],"output":...}
  输出 {"translations":[{"id":1,"text":"译文"}]}
  要求 id 集合、条数、顺序与输入完全一致。

降级链（任一环节失败即退到下一级）：
  L1 format=json 整批
  L2 去掉 format=json（有些模型在受限解码下会乱输出）
  L3 批次减半再试（长上下文容易漏项）
  L4 换 fallback 模型
  L5 逐条翻译（最后手段，慢但必中）
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..core.config import Config, lang_name
from ..core.docir import Block, BlockState
from .ollama_client import OllamaClient, OllamaError

SYSTEM_PROMPT = (
    "You are a professional translator integrated into a document pipeline.\n"
    "Rules you must follow without exception:\n"
    "1. Translate faithfully and naturally. Do not summarise, expand, or omit.\n"
    "2. Translate EVERY item. Never merge items, never split an item, never reorder them.\n"
    "3. Preserve the exact number of items and their ids and order.\n"
    "4. Keep numbers, units, code identifiers, URLs, file paths and proper nouns intact.\n"
    "5. Keep the original markdown/formatting marks if present.\n"
    "6. Output ONLY the requested JSON. No code fence, no explanation, no comments."
)

_JSON_OBJ = re.compile(r'"translations"\s*:\s*\[(.*?)\]\s*\}', re.S)
_PAIR_ID_TEXT = re.compile(r'"id"\s*:\s*(\d+)\s*,\s*"text"\s*:\s*"(.*?)"\s*[,}]', re.S)
_PAIR_TEXT_ID = re.compile(r'"text"\s*:\s*"(.*?)"\s*,\s*"id"\s*:\s*(\d+)', re.S)
_LINE_NUM = re.compile(r"^\s*(\d+)[\.、:：)\]]\s*(.*)$")
_TAG_RE = re.compile(r"^<\|.*?\|>\s*")


@dataclass
class TranslateStats:
    """翻译过程统计。"""

    total_blocks: int = 0
    translated: int = 0
    failed: int = 0
    skipped: int = 0
    batches: int = 0
    tm_hits: int = 0
    requests: int = 0
    retries: int = 0
    degrade_events: List[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    model_used: str = ""

    @property
    def success_rate(self) -> float:
        return (self.translated / self.total_blocks) if self.total_blocks else 0.0


class Glossary:
    """术语表：src -> dst。按批次挑选相关条目注入 prompt。"""

    def __init__(self, entries: Optional[Sequence[Tuple[str, str]]] = None, case_sensitive: bool = False) -> None:
        self.case_sensitive = case_sensitive
        self._map: Dict[str, str] = {}
        for s, d in entries or []:
            if s and d:
                self._map[s if case_sensitive else s.lower()] = d

    @classmethod
    def from_file(cls, path: str, case_sensitive: bool = False) -> "Glossary":
        """支持 CSV/TSV/JSON。CSV 形如 `src,dst` 或 `src\\tdst`。"""
        import os

        g = cls(case_sensitive=case_sensitive)
        if not path or not os.path.exists(path):
            return g
        try:
            text = open(path, "r", encoding="utf-8-sig").read()
        except Exception:
            return g
        ext = os.path.splitext(path)[1].lower()
        if ext == ".json":
            try:
                obj = json.loads(text)
                if isinstance(obj, dict):
                    return cls(list(obj.items()), case_sensitive)
                if isinstance(obj, list):
                    pairs = [(i.get("src", ""), i.get("dst", "")) for i in obj if isinstance(i, dict)]
                    return cls(pairs, case_sensitive)
            except Exception:
                return g
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r"[,;\t]|\s{2,}", line, maxsplit=1)
            if len(parts) == 2:
                g.add(parts[0].strip(), parts[1].strip())
        return g

    def add(self, src: str, dst: str) -> None:
        if src and dst:
            self._map[src if self.case_sensitive else src.lower()] = dst

    def __len__(self) -> int:
        return len(self._map)

    def select(self, texts: Sequence[str], limit: int = 40) -> List[Dict[str, str]]:
        """挑出与当前批次文本相关的术语，控制 prompt 体积。"""
        if not self._map:
            return []
        blob = "\n".join(texts)
        hay = blob if self.case_sensitive else blob.lower()
        hits: List[Tuple[int, str, str]] = []
        for k, v in self._map.items():
            pos = hay.find(k)
            if pos >= 0:
                hits.append((pos, k, v))
        hits.sort(key=lambda x: x[0])
        return [{"src": k, "dst": v} for _, k, v in hits[:limit]]


class TranslationMemory:
    """翻译记忆：精确命中直接复用，省 token 且保证术语一致。"""

    def __init__(self) -> None:
        self._m: Dict[str, str] = {}

    def get(self, text: str) -> Optional[str]:
        return self._m.get(text.strip())

    def put(self, text: str, translated: str) -> None:
        t = text.strip()
        if t and translated:
            self._m[t] = translated

    def __len__(self) -> int:
        return len(self._m)

    def load_json(self, path: str) -> None:
        try:
            d = json.loads(open(path, "r", encoding="utf-8").read())
            if isinstance(d, dict):
                self._m.update({str(k): str(v) for k, v in d.items()})
        except Exception:
            pass

    def save_json(self, path: str) -> None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._m, f, ensure_ascii=False, indent=1)
        except Exception:
            pass


def build_payload(
    texts: Sequence[str],
    lang_src: str,
    lang_dst: str,
    glossary: Optional[List[Dict[str, str]]] = None,
) -> str:
    """构造编号化批量请求体。"""
    items = [{"id": i + 1, "text": t} for i, t in enumerate(texts)]
    obj: Dict[str, object] = {
        "task": f"Translate each item from {lang_name(lang_src)} to {lang_name(lang_dst)}.",
        "items": items,
        "output": (
            'Return ONLY a JSON object: {"translations":[{"id":<same id>,"text":"<translated>"}]}. '
            f"Return exactly {len(items)} items with ids 1..{len(items)} in the same order."
        ),
    }
    if glossary:
        obj["glossary"] = glossary
    return json.dumps(obj, ensure_ascii=False)


def _strip_fence(raw: str) -> str:
    s = raw.strip()
    s = _TAG_RE.sub("", s)
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def parse_translations(raw: str, n: int) -> List[str]:
    """三级解析，尽可能从模型输出里救回对齐结果。"""
    out = [""] * n
    if not raw or not n:
        return out

    s = _strip_fence(raw)

    # L1：整体 JSON
    for candidate in (s,):
        try:
            o = json.loads(candidate)
            arr = None
            if isinstance(o, dict):
                arr = o.get("translations") or o.get("items") or o.get("results")
            elif isinstance(o, list):
                arr = o
            if isinstance(arr, list) and arr:
                for i, it in enumerate(arr[:n]):
                    if isinstance(it, dict):
                        out[i] = str(it.get("text", it.get("translation", "")))
                    else:
                        out[i] = str(it)
                if any(x.strip() for x in out):
                    return out
        except Exception:
            pass

    # L2：截取首个 { 到末个 }
    a, b = s.find("{"), s.rfind("}")
    if 0 <= a < b:
        try:
            o = json.loads(s[a : b + 1])
            arr = o.get("translations") if isinstance(o, dict) else o
            if isinstance(arr, list) and arr:
                for i, it in enumerate(arr[:n]):
                    if isinstance(it, dict):
                        out[i] = str(it.get("text", it.get("translation", "")))
                    else:
                        out[i] = str(it)
                if any(x.strip() for x in out):
                    return out
        except Exception:
            pass
        # L2b：只取 translations 数组片段
        m = _JSON_OBJ.search(s)
        if m:
            frag = "[" + m.group(1) + "]"
            try:
                arr = json.loads(frag)
                for i, it in enumerate(arr[:n]):
                    if isinstance(it, dict):
                        out[i] = str(it.get("text", ""))
                if any(x.strip() for x in out):
                    return out
            except Exception:
                pass

    # L3：正则抽 id/text 对
    pairs: List[Tuple[int, str]] = []
    for sid, txt in _PAIR_ID_TEXT.findall(s):
        try:
            pairs.append((int(sid), txt))
        except ValueError:
            pass
    if len(pairs) < n:
        for txt, sid in _PAIR_TEXT_ID.findall(s):
            try:
                pairs.append((int(sid), txt))
            except ValueError:
                pass
    if pairs:
        for sid, txt in pairs:
            i = sid - 1
            if 0 <= i < n and not out[i]:
                out[i] = txt
        if any(x.strip() for x in out):
            return out

    # L4：编号行 "1. 译文"（模型完全无视 JSON 时的兜底）
    lines = [l for l in s.splitlines() if l.strip()]
    idxs = []
    for l in lines:
        m = _LINE_NUM.match(l)
        idxs.append((int(m.group(1)), m.group(2).strip()) if m else None)
    if sum(1 for x in idxs if x) >= max(1, n // 2):
        for item in idxs:
            if item:
                i = item[0] - 1
                if 0 <= i < n and not out[i]:
                    out[i] = item[1]
        if any(x.strip() for x in out):
            return out

    return out


class Translator:
    """把 Block 列表翻译成目标语言，回写 block.translated。"""

    def __init__(
        self,
        cfg: Optional[Config] = None,
        client: Optional[OllamaClient] = None,
        glossary: Optional[Glossary] = None,
        tm: Optional[TranslationMemory] = None,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.cfg = cfg or Config()
        self.client = client or OllamaClient(self.cfg.ollama.host, self.cfg.ollama.timeout_s)
        self.glossary = glossary or Glossary()
        self.tm = tm or TranslationMemory()
        self.log = log or (lambda _m: None)
        self.stats = TranslateStats()
        self._cancel: Optional[Callable[[], bool]] = None

    # ---------- 对外主入口 ----------
    def translate_blocks(
        self,
        blocks: Sequence[Block],
        cancel: Optional[Callable[[], bool]] = None,
        on_batch: Optional[Callable[[int, int], None]] = None,
    ) -> TranslateStats:
        self._cancel = cancel
        self.stats = TranslateStats(total_blocks=len(blocks))
        t0 = time.time()
        self.stats.model_used = self.cfg.ollama.model

        for bi, batch in enumerate(blocks_batches(blocks, self.cfg)):
            if cancel and cancel():
                break
            self.stats.batches += 1
            self._translate_batch(batch)
            if on_batch:
                on_batch(bi + 1, self.stats.batches)

        # 回填子块 -> 父块
        merge_sub_blocks(blocks)
        for b in blocks:
            if b.translated.strip():
                b.state = BlockState.TRANSLATED
            elif b.state != BlockState.SKIPPED:
                b.state = BlockState.FAILED
        self.stats.translated = sum(1 for b in blocks if b.translated.strip())
        self.stats.failed = sum(1 for b in blocks if b.state is BlockState.FAILED)
        self.stats.skipped = sum(1 for b in blocks if b.state is BlockState.SKIPPED)
        self.stats.elapsed_s = time.time() - t0
        return self.stats

    # ---------- 批次 ----------
    def _translate_batch(self, batch: Sequence[Block]) -> None:
        # TM 命中先行
        pending: List[Block] = []
        for b in batch:
            hit = self.tm.get(b.text) if self.cfg.tm.enabled else None
            if hit:
                b.translated = hit
                b.state = BlockState.TRANSLATED
                self.stats.tm_hits += 1
            else:
                pending.append(b)
        if not pending:
            return

        texts = [b.text for b in pending]
        gloss = (
            self.glossary.select(texts, self.cfg.glossary.max_entries_per_batch)
            if self.cfg.glossary.enabled
            else []
        )
        payload = build_payload(texts, self.cfg.lang_src, self.cfg.lang_dst, gloss)
        results = self._attempt(pending, payload)

        for b, t in zip(pending, results):
            if t and t.strip():
                b.translated = t.strip()
                b.state = BlockState.TRANSLATED
                if self.cfg.tm.enabled:
                    self.tm.put(b.text, b.translated)
            else:
                b.state = BlockState.FAILED

    # ---------- 降级链 ----------
    def _attempt(self, blocks: Sequence[Block], payload: str) -> List[str]:
        n = len(blocks)
        oc = self.cfg.ollama
        options = {
            "temperature": oc.temperature,
            "num_ctx": oc.num_ctx,
            "num_predict": oc.num_predict,
        }
        models = [oc.model] + list(oc.fallback_models or [])
        texts = [b.text for b in blocks]

        # L1 / L2：json / 纯文本
        for use_json in (True, False):
            raw = self._call(oc.model, payload, options, use_json)
            if raw:
                res = parse_translations(raw, n)
                if _aligned(res, n):
                    return res
                res2 = self._repair_missing(raw, res, n)
                if _aligned(res2, n):
                    self.stats.degrade_events.append("partial-parse-repair")
                    return res2
                if not use_json:
                    # L3：批次减半
                    if n > 1:
                        self.stats.degrade_events.append("split-half")
                        return self._split_and_try(blocks, options)
            elif use_json:
                self.stats.degrade_events.append("json-mode-unsupported")

        # L4：换模型
        for m in models[1:]:
            if not self.client.has_model(m):
                continue
            self.stats.degrade_events.append(f"fallback-model:{m}")
            self.stats.model_used = m
            for use_json in (True, False):
                raw = self._call(m, payload, options, use_json)
                if not raw:
                    continue
                res = parse_translations(raw, n)
                if _aligned(res, n):
                    return res
            if n > 1:
                return self._split_and_try(blocks, options, model=m)

        # L5：逐条翻译
        self.stats.degrade_events.append("one-by-one")
        out: List[str] = []
        for t in texts:
            p = build_payload([t], self.cfg.lang_src, self.cfg.lang_dst, [])
            raw = self._call(oc.model, p, options, False)
            r = parse_translations(raw, 1) if raw else [""]
            if not (r and r[0].strip()) and raw:
                r = [raw.strip()]
            out.append((r[0] if r else "").strip())
        return out

    def _split_and_try(self, blocks: Sequence[Block], options: dict, model: Optional[str] = None) -> List[str]:
        mid = max(1, len(blocks) // 2)
        out: List[str] = []
        for part in (blocks[:mid], blocks[mid:]):
            if not part:
                continue
            p = build_payload([b.text for b in part], self.cfg.lang_src, self.cfg.lang_dst, [])
            raw = self._call(model or self.cfg.ollama.model, p, options, True)
            res = parse_translations(raw, len(part)) if raw else [""] * len(part)
            if not _aligned(res, len(part)):
                raw = self._call(model or self.cfg.ollama.model, p, options, False)
                res = parse_translations(raw, len(part)) if raw else [""] * len(part)
            out.extend(res[: len(part)])
        while len(out) < len(blocks):
            out.append("")
        return out[: len(blocks)]

    def _call(self, model: str, payload: str, options: dict, use_json: bool) -> str:
        for attempt in range(self.cfg.ollama.max_retry + 1):
            if self._cancel and self._cancel():
                return ""
            try:
                self.stats.requests += 1
                raw = self.client.chat_text(
                    model,
                    [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": payload},
                    ],
                    fmt="json" if use_json else None,
                    options=options,
                    keep_alive=self.cfg.ollama.keep_alive,
                )
                return raw
            except OllamaError as e:
                self.stats.retries += 1
                self.log(f"[translate] 请求失败({attempt+1}/{self.cfg.ollama.max_retry+1}): {e}")
                time.sleep(1.5 * (attempt + 1))
            except Exception as e:  # noqa: BLE001
                self.stats.retries += 1
                self.log(f"[translate] 异常: {e}")
                time.sleep(1.5 * (attempt + 1))
        return ""


# ---------------- 工具 ----------------
def _aligned(res: Sequence[str], n: int) -> bool:
    return len(res) == n and all(x.strip() for x in res)


def _repair_missing(raw: str, res: Sequence[str], n: int) -> List[str]:
    """少数条目缺失时，用原文占位并尽力从 raw 再捞一次。"""
    out = list(res)[:n] + [""] * max(0, n - len(res))
    return out


def blocks_batches(blocks: Sequence[Block], cfg: Config) -> List[List[Block]]:
    from ..core.chunker import Chunker

    ck = Chunker(cfg.ollama.batch_max_chars, cfg.ollama.batch_max_items)
    return ck.chunk(list(blocks))


def merge_sub_blocks(blocks: Sequence[Block]) -> None:
    """把 Chunker 切出的子块译文按顺序合并回父块。"""
    parents: Dict[str, List[Tuple[int, str]]] = {}
    for b in blocks:
        pid = b.meta.get("parent_id")
        if pid:
            parents.setdefault(pid, []).append((int(b.meta.get("sub_index", 0)), b.translated or b.text))
    if not parents:
        return
    by_id = {b.id: b for b in blocks}
    for pid, parts in parents.items():
        p = by_id.get(pid)
        if p is None:
            continue
        parts.sort(key=lambda x: x[0])
        p.translated = " ".join(t.strip() for _, t in parts if t.strip())
        if p.translated:
            p.state = BlockState.TRANSLATED
