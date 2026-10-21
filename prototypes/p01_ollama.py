"""M0 原型 1 —— Ollama 连通性 / 模型发现 / 编号化批量翻译 + JSON 校验与降级链。

验证目标（对应 docs/06 的 M0.3）：
  1. 能探测本机 Ollama 服务（127.0.0.1:11434）
  2. 能列出已安装模型及其参数规模
  3. 编号化批量请求 + JSON 结构化输出，能做到"条数对齐"
  4. 触发一次降级路径（去掉 format:json 后仍能解析）

用法：
    python prototypes/p01_ollama.py                # 自动选第一个可用模型
    python prototypes/p01_ollama.py qwen3:8b       # 指定模型

退出码：0=全部通过  2=Ollama 未就绪（环境问题，非代码问题）  1=验证失败
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

import httpx

BASE = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
TIMEOUT = 120.0

SYSTEM_PROMPT = (
    "You are a professional translator. Translate faithfully and naturally. "
    "Never merge, split, drop or reorder items. Never add explanations. "
    "Keep numbers, units, code identifiers and proper nouns intact. "
    "Output strictly JSON."
)


def probe() -> str | None:
    """探测 Ollama 服务，返回版本号。"""
    try:
        r = httpx.get(f"{BASE}/api/version", timeout=3.0)
        return r.json().get("version")
    except Exception as exc:  # noqa: BLE001
        print(f"[probe] 无法连接 {BASE} :: {type(exc).__name__}: {exc}")
        return None


def list_models() -> list[dict]:
    r = httpx.get(f"{BASE}/api/tags", timeout=10.0)
    r.raise_for_status()
    return r.json().get("models", [])


def chat(model: str, user: str, use_json_format: bool = True, temperature: float = 0.15) -> str:
    """调用 /api/chat，返回模型输出文本。"""
    payload = {
        "model": model,
        "stream": False,
        "keep_alive": "10m",
        "options": {"temperature": temperature, "num_ctx": 4096},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    }
    if use_json_format:
        payload["format"] = "json"

    t0 = time.time()
    r = httpx.post(f"{BASE}/api/chat", json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    dt = time.time() - t0
    msg = data.get("message", {}).get("content", "")
    print(
        f"[chat] {dt:5.1f}s  prompt_tok={data.get('prompt_eval_count')} "
        f"gen_tok={data.get('eval_count')}"
    )
    return msg


def build_payload(items: list[str], src: str, dst: str, glossary: list[tuple[str, str]]) -> str:
    """编号化批量输入（docs/05 §2.3 契约）。"""
    body = {
        "task": f"Translate each item from {src} to {dst}.",
        "glossary": [{"src": s, "dst": d} for s, d in glossary],
        "items": [{"id": i + 1, "text": t} for i, t in enumerate(items)],
        "output": (
            'Return JSON: {"translations":[{"id":<int>,"text":"<translated>"}]}. '
            "Keep exactly the same id set, count and order."
        ),
    }
    return json.dumps(body, ensure_ascii=False, indent=1)


def parse_translations(raw: str, expected: int) -> list[str]:
    """三级解析：直接 JSON → 抽取首个 JSON 对象 → 正则兜底。失败返回空列表。"""
    raw = raw.strip()
    # 1) 直接解析
    try:
        obj = json.loads(raw)
        return _extract(obj, expected)
    except Exception:  # noqa: BLE001
        pass
    # 2) 截取花括号包裹的最外层 JSON
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return _extract(json.loads(raw[start : end + 1]), expected)
        except Exception:  # noqa: BLE001
            pass
    # 3) 正则兜底：抓 {"id":n,"text":"..."}
    pairs = re.findall(r'"id"\s*:\s*(\d+)\s*,\s*"text"\s*:\s*"(.*?)"', raw, re.S)
    if pairs:
        out = [""] * expected
        for sid, text in pairs:
            idx = int(sid) - 1
            if 0 <= idx < expected:
                out[idx] = text
        return out
    return []


def _extract(obj, expected: int) -> list[str]:
    arr = obj.get("translations") if isinstance(obj, dict) else obj
    if not isinstance(arr, list):
        return []
    out = [""] * expected
    for i, item in enumerate(arr[:expected]):
        out[i] = item.get("text", "") if isinstance(item, dict) else str(item)
    return out


def main() -> int:
    print("=" * 68)
    print("M0 原型 1 · Ollama 连通性与批量翻译验证")
    print("=" * 68)

    ver = probe()
    if not ver:
        print("\n[结果] Ollama 未运行。请启动后再跑本脚本：")
        print("  - Windows: 开始菜单启动 Ollama，或终端执行 `ollama serve`")
        print("  - 验证:    curl http://127.0.0.1:11434/api/version")
        return 2
    print(f"[probe] Ollama version = {ver}")

    models = list_models()
    print(f"[models] 本机已安装 {len(models)} 个模型：")
    for m in models:
        gb = m.get("size", 0) / 1e9
        det = m.get("details", {})
        print(
            f"   - {m.get('name'):32s} {gb:6.2f} GB  "
            f"{det.get('parameter_size', '?')}  {det.get('family', '')}"
        )
    if not models:
        print("\n[结果] 本机没有任何模型。先拉取一个，例如：")
        print("   ollama pull qwen3:8b      # Apache-2.0，商用友好")
        print("   ollama pull translategemma:4b")
        return 2

    target = sys.argv[1] if len(sys.argv) > 1 else models[0]["name"]
    print(f"\n[使用模型] {target}")

    samples = [
        "The measured thermal efficiency reached 42.7% under full load.",
        "Please refer to Figure 3 for the wiring diagram of the control cabinet.",
        "This warranty does not cover damage caused by unauthorized modification.",
    ]
    glossary = [("thermal efficiency", "热效率"), ("control cabinet", "控制柜")]
    payload = build_payload(samples, "English", "Simplified Chinese", glossary)

    ok = True
    try:
        raw = chat(target, payload, use_json_format=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[chat] 请求失败 :: {exc}")
        return 1

    print("\n[原始输出]")
    print(raw[:800])

    result = parse_translations(raw, len(samples))
    if not any(result):
        print("\n[降级] JSON 模式无有效结果，去掉 format:json 重试一次 …")
        raw2 = chat(target, payload, use_json_format=False)
        result = parse_translations(raw2, len(samples))

    print("\n[解析结果]")
    for i, (src, dst) in enumerate(zip(samples, result), 1):
        flag = "OK " if dst else "MISS"
        print(f"  {flag} [{i}] {src}")
        print(f"        → {dst}")
        if not dst:
            ok = False

    aligned = len(result) == len(samples)
    print(f"\n[校验] 条数对齐: {aligned} ({len(result)}/{len(samples)})")
    print(f"[结论] {'通过 ✅' if ok and aligned else '未通过 ❌'}")
    return 0 if (ok and aligned) else 1


if __name__ == "__main__":
    raise SystemExit(main())
