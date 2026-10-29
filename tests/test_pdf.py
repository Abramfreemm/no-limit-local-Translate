"""PDF 解析与 OCR 的实测用例（需要真实依赖，不联网）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from linguaforge.core.config import Config
from linguaforge.core.docir import BlockType, Page
from linguaforge.core.problems import Code, DocumentParseError, Severity
from linguaforge.ocr import RapidOCREngine
from linguaforge.parsers import PDFParser


def test_pdf_parse_structure(sample_pdf: Path):
    cfg = Config()
    with PDFParser(cfg) as p:
        p.open(sample_pdf)
        assert p.page_count == 3, "应解析出 3 页"

        pages = []
        for pg in p.iter_pages():
            pages.append(pg)

    assert len(pages) == 3
    all_blocks = [b for pg in pages for b in pg.blocks]
    assert len(all_blocks) > 5

    types = {b.type for b in all_blocks}
    assert BlockType.TITLE in types or BlockType.HEADING in types, f"未识别标题: {types}"
    assert BlockType.TABLE_CELL in types, "未识别表格单元格"
    assert BlockType.PARAGRAPH in types

    blob = " ".join(b.text for b in all_blocks).lower()
    assert "thermal efficiency" in blob
    assert "42.7" in blob


def test_pdf_reading_order_monotonic(sample_pdf: Path):
    with PDFParser(Config()) as p:
        p.open(sample_pdf)
        pg = p.parse_page(0)
    orders = [b.reading_order for b in pg.blocks]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders)


def test_pdf_bbox_within_page(sample_pdf: Path):
    with PDFParser(Config()) as p:
        p.open(sample_pdf)
        pg = p.parse_page(0)
    for b in pg.blocks:
        x0, top, x1, bot = b.bbox
        assert 0 <= x0 <= x1 <= pg.width + 1
        assert 0 <= top <= bot <= pg.height + 1


def test_pdf_text_chars_flag(sample_pdf: Path):
    with PDFParser(Config()) as p:
        p.open(sample_pdf)
        pg = p.parse_page(0)
    assert pg.meta["text_chars"] > 100
    assert pg.meta["need_ocr"] is False, "文本型 PDF 不应触发 OCR"


def test_pdf_title_from_metadata(sample_pdf: Path):
    with PDFParser(Config()) as p:
        p.open(sample_pdf)
    assert "Thermal" in (p._title or "")


def test_ocr_scan_image(scan_like_png: Path):
    eng = RapidOCREngine(Config())
    if not eng.available:
        pytest.skip("RapidOCR 不可用")
    from PIL import Image

    img = Image.open(scan_like_png).convert("RGB")
    page = Page(index=0, width=595, height=842)
    n = eng.fill_page(page, img, 200)
    assert n >= 4, f"识别块过少: {n}"
    assert page.ocr_used is True
    blob = " ".join(b.text for b in page.blocks).lower()
    assert "efficiency" in blob or "manual" in blob
    assert all(0 <= b.confidence <= 1 for b in page.blocks)


# ---------------- 解析护栏 ----------------
def test_parse_timeout_is_structured(sample_pdf: Path):
    """超时守卫触发时必须抛出带 LF-D11 的结构化错误，不能卡死或抛裸异常。"""
    with PDFParser(Config()) as p:
        p.open(sample_pdf)
        # 人为把已用时间推过阈值，等价于解析耗时超限
        p._deadline._t0 -= 10_000
        with pytest.raises(DocumentParseError) as ei:
            list(p.iter_pages())
        prob = ei.value.problem
        assert prob.code == Code.PARSE_TIMEOUT
        assert prob.severity == Severity.FAILURE
        assert prob.params["last_page"] == 0


def test_oversized_page_is_skipped_not_fatal(tmp_path: Path):
    """超大页面属于降级级：跳过该页继续，而不是让整份文档报废。"""
    from reportlab.pdfgen import canvas

    p = tmp_path / "huge.pdf"
    # 200 英寸 ≈ 14400pt，超过 LIMITS["page_max_pt"] 的判定边界
    c = canvas.Canvas(str(p), pagesize=(20_000, 20_000))
    c.rect(50, 50, 200, 200, fill=0)
    c.showPage()
    c.save()

    with PDFParser(Config()) as parser:
        parser.open(p)
        pages = list(parser.iter_pages())  # 不应抛出
    assert pages == [] or len(pages) == 0
    assert any(pr.code == Code.PAGE_SIZE_EXCEEDED for pr in parser._skipped)


def test_deadline_reset_on_reopen(sample_pdf: Path):
    """同一实例重复 open 时要重置计时，否则第二次开必然立刻超时。"""
    p = PDFParser(Config())
    p.open(sample_pdf)
    p._deadline._t0 -= 10_000
    assert p._deadline.expired()
    p.close()
    p.open(sample_pdf)
    assert not p._deadline.expired()
    p.close()
