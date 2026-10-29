"""公共 fixtures：生成测试用 PDF / 图片。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table

BODY = [
    "The thermal efficiency reached 42.7% under full load.",
    "Connect the cabinet to the rated power supply and allow it to stabilise for 30 minutes.",
    "Please refer to Figure 3 for the wiring diagram of the control cabinet.",
    "Warning: do not open the enclosure while the equipment is running.",
]


@pytest.fixture(scope="session")
def sample_pdf(tmp_path_factory) -> Path:
    """3 页英文 PDF：标题 + 正文 + 表格 + 重复页眉页脚。"""
    out = tmp_path_factory.mktemp("pdf") / "sample.pdf"
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph("Thermal Performance of the XJ-2000 Control Cabinet", styles["Title"]))
    story.append(Spacer(1, 5 * mm))
    for s in BODY:
        story.append(Paragraph(s, styles["BodyText"]))
        story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("1. Measurement Setup", styles["Heading2"]))
    story.append(
        Paragraph("Record the ambient temperature before measurement.", styles["BodyText"])
    )
    story.append(Spacer(1, 4 * mm))
    tbl = Table(
        [
            ["Parameter", "Value", "Unit"],
            ["Thermal efficiency", "42.7", "%"],
            ["Rated power", "3.2", "kW"],
        ],
        colWidths=[55 * mm, 35 * mm, 25 * mm],
    )
    tbl.setStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)])
    story.append(tbl)
    for page in (2, 3):
        story.append(PageBreak())
        story.append(Paragraph(f"{page}. Section {page}", styles["Heading2"]))
        for s in BODY[:2]:
            story.append(Paragraph(s, styles["BodyText"]))
            story.append(Spacer(1, 3 * mm))
    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="Thermal Performance",
    )
    doc.build(story)
    return out


@pytest.fixture(scope="session")
def scan_like_png(tmp_path_factory) -> Path:
    """合成一张"扫描件"图片（白底黑字），供 OCR 测试。"""
    from PIL import Image, ImageDraw, ImageFont

    def font(size: int):
        w = os.environ.get("WINDIR", r"C:\Windows")
        for p in (Path(w) / "Fonts" / "msyh.ttc", Path(w) / "Fonts" / "arial.ttf"):
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), size)
                except Exception:
                    pass
        return ImageFont.load_default(size)

    out = tmp_path_factory.mktemp("img") / "scan.png"
    img = Image.new("RGB", (1240, 760), "white")
    d = ImageDraw.Draw(img)
    d.text((80, 60), "Operating Manual - Chapter 3", font=font(40), fill="black")
    y = 170
    for ln in BODY + ["1. Turn off the main switch and wait 60 seconds."]:
        d.text((80, y), ln, font=font(26), fill="black")
        y += 56
    img.save(out)
    return out
