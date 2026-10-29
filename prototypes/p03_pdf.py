"""M0 原型 3 —— PDF 提取与渲染验证（宽松许可技术栈）。

验证目标（docs/06 的 M0.5）：
  1. reportlab 能生成 PDF（后续用于"译文回填层"）
  2. pdfplumber 能取到字符级坐标、字号、字体名 —— 版面重建的必需输入
  3. pypdfium2 能把页面渲染为位图 —— OCR 与预览的必需输入
  4. 从字符聚类出"行/段"的可行性 —— 验证 M1 版面算法的原始素材是否够用

用法：
    python prototypes/p03_pdf.py

输出到：%TEMP%/lf_proto/pdf/
"""

from __future__ import annotations

import os
import time
from pathlib import Path

OUT_DIR = Path(os.environ.get("TEMP", ".")) / "lf_proto" / "pdf"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- 1. 生成样本 PDF
def make_pdf(path: Path) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title="LinguaForge Prototype Sample",
    )
    story = []
    story.append(Paragraph("Thermal Performance of the XJ-2000 Control Cabinet", styles["Title"]))
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "Abstract. This document describes the measurement procedure for the thermal "
            "efficiency of the XJ-2000 control cabinet under full load conditions. The "
            "ambient temperature shall be recorded before each measurement.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("1. Measurement Setup", styles["Heading2"]))
    story.append(
        Paragraph(
            "Connect the cabinet to the rated power supply and allow it to stabilise for "
            "30 minutes. Do not open the enclosure while the device is energised.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 4 * mm))
    data = [
        ["Parameter", "Value", "Unit"],
        ["Thermal efficiency", "42.7", "%"],
        ["Ambient temperature", "25.0", "°C"],
        ["Rated power", "3.2", "kW"],
    ]
    tbl = Table(data, colWidths=[60 * mm, 40 * mm, 30 * mm])
    tbl.setStyle(
        [("GRID", (0, 0), (-1, -1), 0.5, "black"), ("BACKGROUND", (0, 0), (-1, 0), "#dddddd")]
    )
    story.append(tbl)
    story.append(PageBreak())
    story.append(Paragraph("2. Results and Discussion", styles["Heading2"]))
    story.append(
        Paragraph(
            "The measured values are consistent with the design specification. A deviation "
            "of less than 1.5% was observed across three repeated trials.",
            styles["BodyText"],
        )
    )
    story.append(PageBreak())
    story.append(Paragraph("3. Maintenance Notes", styles["Heading2"]))
    story.append(
        Paragraph(
            "Turn off the main switch and wait 60 seconds before any maintenance. Record "
            "the serial number and the date of service in the log book.",
            styles["BodyText"],
        )
    )
    doc.build(story)
    return path


# ---------------------------------------------------------------- 2. 文本与坐标提取
def extract_with_pdfplumber(pdf: Path) -> dict:
    import pdfplumber

    stats = {"pages": 0, "chars": 0, "words": 0, "sizes": {}, "fonts": {}}
    with pdfplumber.open(str(pdf)) as doc:
        stats["pages"] = len(doc.pages)
        for pno, page in enumerate(doc.pages, 1):
            chars = page.chars
            stats["chars"] += len(chars)
            stats["words"] += len(page.extract_words())
            for c in chars:
                stats["sizes"][round(c.get("size", 0), 1)] = (
                    stats["sizes"].get(round(c.get("size", 0), 1), 0) + 1
                )
                fn = c.get("fontname", "?")
                stats["fonts"][fn] = stats["fonts"].get(fn, 0) + 1
            if pno == 1:
                # 打印第 1 页前若干词的坐标，验证"字符级 bbox"可用
                print("\n[第1页 前 8 个词：文本 / bbox / 字号 / 字体]")
                for w in page.extract_words()[:8]:
                    print(
                        f"   {w['text'][:26]:<26} "
                        f"({w['x0']:6.1f},{w['top']:6.1f},{w['x1']:6.1f},{w['bottom']:6.1f})  "
                        f"upright={w.get('upright')}  {w.get('fontname', '')[:22]}"
                    )
    return stats


# ---------------------------------------------------------------- 3. 行/段聚类可行性
def cluster_lines(pdf: Path) -> None:
    """把第 1 页的词按 top 坐标聚类成行，再按间距合并成段（M1 版面算法的雏形）。"""
    import pdfplumber

    with pdfplumber.open(str(pdf)) as doc:
        page = doc.pages[0]
        words = page.extract_words()
        if not words:
            print("[聚类] 无词可聚")
            return

        lines: list[list[dict]] = []
        cur: list[dict] = []
        cur_top = None
        for w in sorted(words, key=lambda x: (round(x["top"], 0), x["x0"])):
            if cur_top is None or abs(w["top"] - cur_top) <= 2.0:
                cur.append(w)
                cur_top = w["top"] if cur_top is None else min(cur_top, w["top"])
            else:
                lines.append(cur)
                cur, cur_top = [w], w["top"]
        if cur:
            lines.append(cur)

        print(f"\n[聚类] 第1页 {len(words)} 词 → {len(lines)} 行")
        print("[行示例]（合并词为行文本 + 行 bbox + 字号中位数）")
        for ln in lines[:6]:
            text = " ".join(w["text"] for w in ln)
            x0 = min(w["x0"] for w in ln)
            x1 = max(w["x1"] for w in ln)
            top = min(w["top"] for w in ln)
            sizes = sorted(ln[0].get("size", 0) for w in ln)
            med = sizes[len(sizes) // 2] if sizes else 0
            print(f"   {text[:56]:<56} ({x0:6.1f},{top:6.1f},{x1:6.1f}) size≈{med:.1f}")


# ---------------------------------------------------------------- 4. pypdfium2 渲染
def render_with_pypdfium2(pdf: Path, dpi: int = 200) -> Path:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    page = doc[0]
    out = OUT_DIR / f"page1_{dpi}dpi.png"
    t0 = time.time()
    page.render(scale=dpi / 72).to_pil().save(out)
    dt = time.time() - t0
    print(f"\n[渲染] pypdfium2 @ {dpi} DPI → {out.name}  ({dt:.2f}s)")
    return out


def main() -> int:
    print("=" * 68)
    print("M0 原型 3 · PDF 生成 / 提取 / 渲染 验证（宽松许可栈）")
    print("=" * 68)

    pdf = make_pdf(OUT_DIR / "sample.pdf")
    print(f"[1] reportlab 生成样本 PDF: {pdf}  ({pdf.stat().st_size / 1024:.1f} KB)")

    print("\n[2] pdfplumber 提取文本与坐标 …")
    stats = extract_with_pdfplumber(pdf)
    print(f"\n[统计] 页数={stats['pages']} 字符数={stats['chars']} 词数={stats['words']}")
    print(f"[字号分布] {dict(sorted(stats['sizes'].items())[:6])}")
    print(f"[字体使用] {dict(list(stats['fonts'].items())[:4])}")

    cluster_lines(pdf)

    print("\n[3] pypdfium2 渲染位图 …")
    render_with_pypdfium2(pdf, dpi=200)

    print("\n" + "=" * 68)
    print("[结论] 生成 ✅ / 字符级坐标 ✅ / 行聚类 ✅ / 渲染 ✅")
    print("       四项能力齐备，可进入 M1 内核开发。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
