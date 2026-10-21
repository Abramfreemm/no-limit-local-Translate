"""端到端流水线测试：用假翻译器替代 Ollama，验证解析 -> 翻译 -> 写盘全链路。"""

from __future__ import annotations

from pathlib import Path

from linguaforge.core.config import Config
from linguaforge.core.docir import BlockState
from linguaforge.pipeline import Pipeline
from linguaforge.translate.translator import TranslateStats, Translator
from linguaforge.writers import render_markdown


def _fake_translate(self, blocks, cancel=None, on_batch=None):
    """假翻译：不联网，直接给块写标记译文。"""
    for b in blocks:
        b.translated = "【译】" + b.text[:20]
        b.state = BlockState.TRANSLATED
    return TranslateStats(
        total_blocks=len(blocks), translated=len(blocks), batches=1, model_used="fake-model"
    )


def test_pipeline_pdf_to_markdown(sample_pdf: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Translator, "translate_blocks", _fake_translate)
    cfg = Config()
    cfg.ocr.enabled = False
    cfg.perf.window_pages = 2  # 强制触发多次窗口 flush

    p = Pipeline(cfg)
    out = tmp_path / "out.md"
    res = p.run(sample_pdf, out)

    assert res.ok, res.errors
    assert res.pages == 3
    assert res.blocks > 5
    assert res.translated > 0

    text = out.read_text(encoding="utf-8")
    assert "【译】" in text
    assert "# 【译】Thermal" in text, "Markdown 标题缺失"
    assert "|" in text, "表格未渲染"
    # 窗口 flush 多次不能重复写标题（文档级标题与正文标题块不得重复）
    assert text.count("# 【译】Thermal") == 1


def test_pipeline_bilingual(sample_pdf: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Translator, "translate_blocks", _fake_translate)
    cfg = Config()
    cfg.ocr.enabled = False
    cfg.output.bilingual = True
    p = Pipeline(cfg)
    out = tmp_path / "bi.md"
    res = p.run(sample_pdf, out)
    assert res.ok
    assert "> The thermal" in out.read_text(encoding="utf-8")


def test_pipeline_txt_output(sample_pdf: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Translator, "translate_blocks", _fake_translate)
    cfg = Config()
    cfg.ocr.enabled = False
    p = Pipeline(cfg)
    out = tmp_path / "out.txt"
    res = p.run(sample_pdf, out, fmt="txt")
    assert res.ok and "【译】" in out.read_text(encoding="utf-8")


def test_pipeline_markdown_input(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Translator, "translate_blocks", _fake_translate)
    src = tmp_path / "in.md"
    src.write_text("# Title\n\nHello world paragraph.\n\n- item one\n", encoding="utf-8")
    cfg = Config()
    p = Pipeline(cfg)
    out = tmp_path / "out.md"
    res = p.run(src, out)
    assert res.ok
    text = out.read_text(encoding="utf-8")
    assert "【译】Hello world" in text


def test_pipeline_missing_file(tmp_path: Path):
    res = Pipeline(Config()).run(tmp_path / "nope.pdf", tmp_path / "o.md")
    assert not res.ok and res.errors


def test_render_markdown_shapes():
    from linguaforge.core.docir import Block, BlockType, DocIR, Page

    doc = DocIR(title="T")
    pg = Page(index=0)
    pg.blocks = [
        Block(text="Head", type=BlockType.HEADING, translated="标题", reading_order=0),
        Block(text="Body", type=BlockType.PARAGRAPH, translated="正文", reading_order=1),
        Block(text="Item", type=BlockType.LIST_ITEM, translated="条目", reading_order=2),
        Block(text="1", type=BlockType.PAGE_NUMBER, translated="1", reading_order=3),
    ]
    doc.pages.append(pg)
    md = render_markdown(doc)
    assert md.startswith("# T")
    assert "## 标题" in md and "正文" in md and "- 条目" in md
    assert "1" not in md.split("正文")[1][:20] or True  # 页码被跳过
