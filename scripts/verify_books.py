#!/usr/bin/env python3
"""用真实英文书做端到端验证（13 号旅程 A/B + 08 号验收）。

对指定目录下每本书抽取前 N 页跑完整流水线（解析 -> OCR -> 翻译 -> 写盘），
统计块数、已译数、耗时与错误码，用于判断「能不能发给别人用」。

用法:
    python scripts/verify_books.py                     # 默认目录 + 前 5 页
    python scripts/verify_books.py --pages 0-8        # 前 8 页
    python scripts/verify_books.py --dir <路径>
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linguaforge.core.config import Config  # noqa: E402
from linguaforge.core.problems import problems_to_text  # noqa: E402
from linguaforge.pipeline import SUPPORTED_IN, Pipeline  # noqa: E402

DEFAULT_DIR = Path("D:/A-小匠/workbuddyproject/英文版-待翻译测试")
DEFAULT_OUT = Path("D:/lfdev/out_test")


def parse_range(text: str) -> tuple[int, int] | None:
    a, _, b = text.partition("-")
    try:
        return (int(a), int(b) if b.strip() else int(a) + 1)
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--pages", default="0-5")
    ap.add_argument("--ocr", action="store_true", help="开启 OCR（默认关闭，跑得更快）")
    args = ap.parse_args()

    rng = parse_range(args.pages)
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(
        p for p in args.dir.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_IN
    )
    if not files:
        print(f"[warn] 目录中无受支持文件: {args.dir}")
        return 0

    print(f"待验证 {len(files)} 个文件 | 页码范围 {rng} | OCR={'开' if args.ocr else '关'}\n")
    rows = []
    for f in files:
        cfg = Config()
        cfg.ocr.enabled = bool(args.ocr)
        cfg.output.fmt = "markdown"
        pipe = Pipeline(cfg)

        # 预检查先行：能在开始前发现的错误不留到跑到一半
        pre = pipe.precheck()
        if pre:
            rows.append((f.name, "阻断", 0, 0, 0.0, pre))
            print(f"[PRECHECK-FAIL] {f.name}")
            for line in problems_to_text(pre):
                print(f"    {line}")
            pipe.close()
            continue

        out = out_dir / f"{f.stem}_sample.md"
        t0 = time.time()
        try:
            res = pipe.run(f, out=out, fmt="markdown", page_range=rng)
            el = time.time() - t0
            status = "OK" if res.ok else "失败"
            rows.append((f.name, status, res.pages, res.translated, el, res.errors))
        except Exception as exc:  # noqa: BLE001
            el = time.time() - t0
            from linguaforge.core.problems import from_exception

            pr = from_exception(exc)
            rows.append((f.name, "异常", 0, 0, el, [pr]))
            status = "异常"
        finally:
            pipe.close()

        errs = rows[-1][5]
        tail = ""
        if errs:
            tail = " | " + "; ".join(problems_to_text(errs)[:2])
        print(
            f"[{status}] {f.name[:48]:<50} 页={rows[-1][2]:<4} 译={rows[-1][3]:<4} {el:6.1f}s{tail}"
        )

    ok = sum(1 for r in rows if r[1] == "OK")
    print(f"\n===== 汇总：{ok}/{len(rows)} 通过 =====")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
