"""分块器：把待翻译块切成符合预算的批次。

目标：
  1. 批次尽量大（减少请求次数、提升上下文连贯）；
  2. 绝不超字符/条数预算（防 Ollama 截断与显存溢出）；
  3. 单块超长时按句再切，保证编号一一对应。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .docir import Block

# 句子切分：优先在句末标点后切，中文另算
_RE_SENT_SPLIT = re.compile(
    r"(?<=[.!?。！？…])\s+(?=[^\s])|(?<=[。！？])(?=[^\s])|(?<=[.!?])\s*(?=[A-Z\"'（(])"
)
_RE_LONG_BREAK = re.compile(r"[;；,，]\s+")


def split_sentences(text: str, max_chars: int) -> list[str]:
    """把超长文本切成 <= max_chars 的若干片段，尽量在句边界。"""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    parts = [p.strip() for p in _RE_SENT_SPLIT.split(text) if p and p.strip()]
    if not parts:
        parts = [text]
    out: list[str] = []
    buf = ""
    for p in parts:
        while len(p) > max_chars:
            # 极端长句：按逗号再切，仍不行就硬切
            sub = _RE_LONG_BREAK.split(p)
            if len(sub) > 1:
                p, rest = sub[0], " ".join(sub[1:])
                if buf:
                    out.append(buf.strip())
                    buf = ""
                if p.strip():
                    out.append(p.strip())
                p = rest
                continue
            if buf:
                out.append(buf.strip())
                buf = ""
            out.append(p[:max_chars])
            p = p[max_chars:]
        cand = (buf + " " + p).strip() if buf else p
        if len(cand) <= max_chars:
            buf = cand
        else:
            if buf:
                out.append(buf.strip())
            buf = p
    if buf:
        out.append(buf.strip())
    return [o for o in out if o]


class Chunker:
    """贪心装填批次。"""

    def __init__(
        self, max_chars: int = 1200, max_items: int = 12, hard_max_chars: int = 4000
    ) -> None:
        self.max_chars = max_chars
        self.max_items = max_items
        self.hard_max_chars = hard_max_chars

    def chunk(self, blocks: Sequence[Block]) -> list[list[Block]]:
        """输入块列表，输出批次的批次。

        说明：返回的 Block 可能是为超长文本生成的“子块副本”，
        其 meta["parent_id"] 指向原块，翻译完成后由 Translator 回写合并。
        """
        batches: list[list[Block]] = []
        cur: list[Block] = []
        cur_chars = 0

        def flush() -> None:
            nonlocal cur, cur_chars
            if cur:
                batches.append(cur)
                cur, cur_chars = [], 0

        for b in blocks:
            text = b.text or ""
            if not text.strip():
                continue
            # 超长块：先按句切成子块，再逐个子块装填
            if len(text) > self.hard_max_chars:
                flush()
                subs = split_sentences(text, self.max_chars)
                sub_blocks: list[Block] = []
                for i, s in enumerate(subs):
                    sb = Block(
                        id=f"{b.id}#{i}",
                        type=b.type,
                        text=s,
                        page_index=b.page_index,
                        style=b.style,
                        meta={**b.meta, "parent_id": b.id, "sub_index": i, "sub_total": len(subs)},
                    )
                    sub_blocks.append(sb)
                    cur_chars += len(s)
                    cur.append(sb)
                    if len(cur) >= self.max_items or cur_chars >= self.max_chars:
                        flush()
                continue

            if cur and (cur_chars + len(text) > self.max_chars or len(cur) >= self.max_items):
                flush()
            cur.append(b)
            cur_chars += len(text)
            if cur_chars >= self.max_chars or len(cur) >= self.max_items:
                flush()
        flush()
        return batches
