"""命令行入口。

    python -m linguaforge.cli doctor
    python -m linguaforge.cli models
    python -m linguaforge.cli translate input.pdf [-o out.md] [--fmt markdown|txt]
                                  [--dst zh-Hans] [--src auto] [--model translategemma:12b]
                                  [--bilingual] [--glossary terms.csv] [--tm tm.json] [--no-ocr]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import __version__
from .core.config import Config
from .pipeline import Pipeline
from .translate.ollama_client import OllamaClient


def _print(m: str) -> None:
    print(m, flush=True)


def cmd_doctor(cfg: Config) -> int:
    _print("=" * 62)
    _print(f"LinguaForge {__version__} 环境自检")
    _print("=" * 62)
    ok = True
    try:
        with OllamaClient(cfg.ollama.host, timeout=10) as c:
            v = c.version()
            _print(f"[OK]   Ollama {v} @ {cfg.ollama.host}")
            models = c.list_models()
            _print(f"[OK]   已装模型: {', '.join(models) if models else '(无)'}")
            if cfg.ollama.model in models:
                _print(f"[OK]   默认模型已就绪: {cfg.ollama.model}")
            else:
                ok = False
                _print(f"[MISS] 默认模型未安装: {cfg.ollama.model}")
                _print(f"       执行: ollama pull {cfg.ollama.model}")
    except Exception as e:  # noqa: BLE001
        ok = False
        _print(f"[FAIL] Ollama 不可用: {e}")

    # OCR
    try:
        from .ocr import RapidOCREngine

        eng = RapidOCREngine(cfg)
        if eng.available:
            _print("[OK]   OCR 引擎可用 (RapidOCR/ONNX)")
        else:
            _print("[WARN] OCR 引擎不可用（扫描件将跳过）")
    except Exception as e:  # noqa: BLE001
        _print(f"[WARN] OCR 不可用: {e}")

    # PDF 栈
    try:
        import pdfplumber, pypdfium2, pypdf, reportlab  # noqa: F401

        _print("[OK]   PDF 栈: pdfplumber + pypdfium2 + pypdf + reportlab")
    except Exception as e:  # noqa: BLE001
        ok = False
        _print(f"[FAIL] PDF 栈: {e}")

    _print("=" * 62)
    _print("结论: " + ("就绪" if ok else "存在问题，请按提示处理"))
    return 0 if ok else 1


def cmd_models(cfg: Config) -> int:
    with OllamaClient(cfg.ollama.host, timeout=15) as c:
        for m in c.list_models():
            _print(m)
    return 0


def cmd_translate(args: argparse.Namespace, cfg: Config) -> int:
    src = Path(args.input)
    if not src.exists():
        _print(f"[FAIL] 文件不存在: {src}")
        return 2

    if args.model:
        cfg.ollama.model = args.model
    if args.src:
        cfg.lang_src = args.src
    if args.dst:
        cfg.lang_dst = args.dst
    if args.bilingual:
        cfg.output.bilingual = True
    if args.no_ocr:
        cfg.ocr.enabled = False
    if args.window:
        cfg.perf.window_pages = args.window

    p = Pipeline(cfg, log=_print)

    problems = p.precheck()
    if problems:
        for s in problems:
            _print(f"[FAIL] {s}")
        return 1

    if args.glossary:
        from .translate.translator import Glossary

        g = Glossary.from_file(args.glossary, cfg.glossary.case_sensitive)
        _print(f"[glossary] 载入 {len(g)} 条术语")
        p.translator.glossary = g
    if args.tm:
        p.translator.tm.load_json(args.tm)
        _print(f"[tm] 载入 {len(p.translator.tm)} 条记忆")

    _print(f"[run] {src.name} -> {cfg.lang_dst}  model={cfg.ollama.model}")

    t0 = time.time()
    last = [0.0]

    def on_progress(stage: str, cur: int, total: int, msg: str) -> None:
        now = time.time()
        if now - last[0] > 0.4 or stage == "done":
            last[0] = now
            bar = f"{cur}/{total}" if total else str(cur)
            _print(f"  [{stage:<9}] {bar:<11} {msg}")

    res = p.run(src, args.output, fmt=args.fmt, on_progress=on_progress)

    if args.tm:
        p.translator.tm.save_json(args.tm)

    _print("-" * 62)
    _print(res.summary())
    if res.stats and res.stats.degrade_events:
        _print(f"  降级事件: {', '.join(res.stats.degrade_events[:8])}")
    for e in res.errors[:10]:
        _print(f"  ! {e}")
    return 0 if res.ok else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="linguaforge", description="LinguaForge 本地离线文档翻译器")
    ap.add_argument("--version", action="version", version=f"LinguaForge {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="环境自检")

    sub.add_parser("models", help="列出 Ollama 已装模型")

    t = sub.add_parser("translate", help="翻译文档")
    t.add_argument("input", help="输入文件（PDF / TXT / MD）")
    t.add_argument("-o", "--output", help="输出文件路径")
    t.add_argument("--fmt", default="markdown", choices=["markdown", "txt"], help="输出格式")
    t.add_argument("--src", default="auto", help="源语言（auto 为自动）")
    t.add_argument("--dst", default="zh-Hans", help="目标语言")
    t.add_argument("--model", help=f"覆盖默认模型")
    t.add_argument("--bilingual", action="store_true", help="双语对照输出")
    t.add_argument("--glossary", help="术语表 CSV/JSON")
    t.add_argument("--tm", help="翻译记忆 JSON（自动读写）")
    t.add_argument("--no-ocr", action="store_true", help="禁用 OCR")
    t.add_argument("--window", type=int, help="流式窗口页数（默认 20）")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = Config.load()
    if args.cmd == "doctor":
        return cmd_doctor(cfg)
    if args.cmd == "models":
        return cmd_models(cfg)
    if args.cmd == "translate":
        return cmd_translate(args, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
