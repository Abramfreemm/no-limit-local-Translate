"""M0 原型 2 —— RapidOCR（ONNX）离线 OCR 验证。

验证目标（docs/06 的 M0.4）：
  1. RapidOCR 能在纯 CPU 下加载并识别（模型随包，无需联网下载）
  2. 输出包含：文本、四点坐标、置信度 —— 满足 DocIR 的 bbox/confidence 需求
  3. 中英文混排可用；测量单页耗时以核对"≤2s/页"的性能目标

用法：
    python prototypes/p02_ocr.py            # 用合成图测试
    python prototypes/p02_ocr.py some.png   # 用指定图片

输出到：%TEMP%/lf_proto/ocr/
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(os.environ.get("TEMP", ".")) / "lf_proto" / "ocr"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def find_font(size: int, prefer_cjk: bool = True):
    """找一个可用的字体（Windows 优先微软雅黑）。"""
    candidates = []
    windir = os.environ.get("WINDIR", r"C:\Windows")
    if prefer_cjk:
        candidates += [
            Path(windir) / "Fonts" / "msyh.ttc",
            Path(windir) / "Fonts" / "msyhl.ttc",
            Path(windir) / "Fonts" / "simsun.ttc",
        ]
    candidates += [
        Path(windir) / "Fonts" / "arial.ttf",
        Path(windir) / "Fonts" / "segoeui.ttf",
    ]
    for p in candidates:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default(size)


def make_sample(path: Path) -> Path:
    """合成一张"扫描件风格"的测试图：标题 + 中英混排段落 + 编号列表。"""
    W, H = 1240, 880
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f_title = find_font(46)
    f_body = find_font(30)
    f_small = find_font(26)

    d.text((80, 60), "Operating Manual — Chapter 3", font=f_title, fill="black")
    d.line((80, 130, W - 80, 130), fill="black", width=3)

    lines = [
        "The thermal efficiency of the control cabinet reaches 42.7% at full load.",
        "请在通电前检查控制柜的接线端子是否紧固。",
        "Warning: Do not open the enclosure while the device is running.",
        "1. Turn off the main switch and wait 60 seconds.",
        "2. 确认设备已完全断电后再进行维护操作。",
        "3. Record the ambient temperature before measurement.",
    ]
    y = 180
    for i, ln in enumerate(lines):
        d.text((80, y), ln, font=(f_body if i < 3 else f_small), fill="black")
        y += 62

    d.text((80, H - 90), "Page 12 / Model: XJ-2000 / Rev. C", font=f_small, fill="black")
    img.save(path)
    return path


def main() -> int:
    print("=" * 68)
    print("M0 原型 2 · RapidOCR 离线 OCR 验证")
    print("=" * 68)

    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        print("[失败] rapidocr_onnxruntime 未安装：pip install rapidocr-onnxruntime")
        return 1

    if len(sys.argv) > 1:
        src = Path(sys.argv[1])
        if not src.exists():
            print(f"[失败] 图片不存在: {src}")
            return 1
    else:
        src = make_sample(OUT_DIR / "sample_page.png")
        print(f"[合成测试图] {src}")

    print("[加载引擎] RapidOCR (ONNXRuntime, CPU) …")
    t0 = time.time()
    engine = RapidOCR()
    print(f"[加载耗时] {time.time() - t0:.2f}s")

    img = Image.open(src).convert("RGB")
    print(f"[图像] {img.size[0]}x{img.size[1]}")
    print("[识别中] …")
    t1 = time.time()
    result, _elapse = engine(str(src))
    dt = time.time() - t1

    print(f"\n[耗时] {dt:.2f}s  （目标 ≤2.00s/页 @CPU）")
    if not result:
        print("[失败] 未识别到任何文本")
        return 1

    print(f"[识别行数] {len(result)}\n")
    print(f"{'文本':<52} {'置信度':>7}   坐标(x0,y0,x1,y1)")
    print("-" * 100)
    for item in result:
        box, text, score = item[0], item[1], item[2]
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        bbox = (round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys)))
        print(f"{text[:50]:<52} {score:>7.3f}   {bbox}")

    avg = sum(i[2] for i in result) / len(result)
    print("-" * 100)
    print(f"[平均置信度] {avg:.3f}")
    print(f"[性能目标] {'达成 ✅' if dt <= 2.0 else '未达成 ⚠️（CPU 环境可放宽，或降低 DPI）'}")
    print(f"[结构校验] 文本+坐标+置信度三要素齐全 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
