"""PDF 解析与 OCR 的实测用例（需要真实依赖，不联网）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from linguaforge.core.config import Config
from linguaforge.core.docir import BlockType, Page
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
