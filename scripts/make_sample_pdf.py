"""生成用于验收的英文技术手册 PDF（默认 20 页）。

用法：python scripts/make_sample_pdf.py [页数] [输出路径]
"""

from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

TITLE = "XJ-2000 Control Cabinet — Installation and Maintenance Manual"

PARAS = [
    "This manual describes the installation, commissioning and maintenance procedures for the "
    "XJ-2000 control cabinet. Read the safety instructions carefully before unpacking the equipment.",
    "The control cabinet must be installed in a dry, well-ventilated room where the ambient "
    "temperature remains between 5 °C and 40 °C and the relative humidity does not exceed 85 percent.",
    "Connect the cabinet to the rated power supply and allow it to stabilise for 30 minutes before "
    "any measurement is taken. Verify that the protective earth conductor is connected properly.",
    "The thermal efficiency reaches 42.7 percent at full load. Deviations of more than 2 percentage "
    "points indicate a blocked air filter or a defective cooling fan.",
    "Warning: do not open the enclosure while the equipment is running. Residual voltage remains on "
    "the DC bus capacitors for at least 60 seconds after the main switch has been turned off.",
    "Please refer to Figure 3 for the wiring diagram of the control cabinet. Terminal assignments are "
    "listed in Table 2. Tighten all screw terminals to a torque of 1.2 newton metres.",
    "Maintenance intervals depend on the duty cycle. Under continuous operation, inspect the cooling "
    "system every three months and replace the air filter at least once a year.",
    "The warranty does not cover damage caused by unauthorised modification, improper installation, "
    "or operation outside the specified ambient conditions.",
]

SECTIONS = [
    "Safety Instructions",
    "Technical Specifications",
    "Mechanical Installation",
    "Electrical Connection",
    "Commissioning Procedure",
    "Thermal Performance",
    "Maintenance Schedule",
    "Troubleshooting",
    "Spare Parts",
    "Disposal and Recycling",
]

TABLE_ROWS = [
    ["Parameter", "Value", "Unit"],
    ["Rated voltage", "400", "V AC"],
    ["Rated power", "3.2", "kW"],
    ["Thermal efficiency", "42.7", "%"],
    ["Protection class", "IP54", "-"],
    ["Weight", "38.5", "kg"],
]


def build(pages: int, out: Path) -> Path:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10, leading=14, spaceAfter=6)
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=17, leading=22, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, leading=17, spaceAfter=8)
    cap = ParagraphStyle("cap", parent=styles["Italic"], fontSize=9, textColor=colors.grey)
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=12, bulletIndent=2)

    out.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=22 * mm,
        bottomMargin=22 * mm,
        title="XJ-2000 Installation and Maintenance Manual",
        author="LinguaForge Test Fixture",
    )

    def header_footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(22 * mm, A4[1] - 14 * mm, "XJ-2000 Manual — Confidential")
        canvas.drawRightString(A4[0] - 22 * mm, 12 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    story = []
    for p in range(pages):
        sec = SECTIONS[p % len(SECTIONS)]
        if p == 0:
            story.append(Paragraph(TITLE, styles["Title"]))
            story.append(Spacer(1, 6 * mm))
            story.append(Paragraph("Document number: XJ2000-MAN-EN-04  |  Revision: C", cap))
            story.append(Spacer(1, 8 * mm))
        else:
            story.append(Paragraph(f"{p + 1}. {sec}", h1))
            story.append(Spacer(1, 2 * mm))

        story.append(Paragraph(f"{p + 1}.1 General", h2))
        for para in PARAS:
            story.append(Paragraph(para, body))

        story.append(Paragraph(f"{p + 1}.2 Checklist", h2))
        for i, item in enumerate(
            [
                "Verify the protective earth connection.",
                "Check the torque of all screw terminals.",
                "Record the ambient temperature and humidity.",
                "Confirm the firmware revision in the service log.",
            ],
            start=1,
        ):
            story.append(Paragraph(f"{i}. {item}", bullet))

        if p % 3 == 0:
            t = Table(TABLE_ROWS, colWidths=[58 * mm, 30 * mm, 28 * mm], hAlign="LEFT")
            t.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#666666")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ]
                )
            )
            story.append(
                KeepTogether([Paragraph("Table 2. Technical data", cap), Spacer(1, 2 * mm), t])
            )
            story.append(Spacer(1, 4 * mm))

        if p < pages - 1:
            story.append(PageBreak())

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    return out


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("samples/manual_en.pdf")
    p = build(n, dst)
    print(f"generated: {p}  ({p.stat().st_size / 1024:.1f} KB, {n} pages)")
