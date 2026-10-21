"""DocIR 序列化、Chunker 分批、翻译结果解析的单元测试（不联网、不依赖 Ollama）。"""

from __future__ import annotations

from linguaforge.core.chunker import Chunker, split_sentences
from linguaforge.core.docir import Block, BlockState, BlockType, DocIR, Origin, Page, Run, Style
from linguaforge.translate.translator import build_payload, parse_translations


# ---------------- DocIR ----------------
def test_block_translatable_rules():
    assert Block(text="Hello world").is_translatable
    assert not Block(text="42.7").is_translatable          # 纯数字
    assert not Block(text="").is_translatable
    assert not Block(text="图 3", type=BlockType.PAGE_NUMBER).is_translatable


def test_block_out_text():
    b = Block(text="Hello", translated="你好")
    assert b.out_text == "你好"
    assert Block(text="Hello").out_text == "Hello"


def test_docir_roundtrip():
    doc = DocIR(source_path="a.pdf", source_format="pdf", title="T", lang_dst="zh-Hans")
    p = Page(index=0, width=595, height=842)
    b = Block(text="Hello", type=BlockType.HEADING, bbox=(1.0, 2.0, 3.0, 4.0),
              runs=[Run(text="Hello", font="Arial-Bold", size=18, bold=True)],
              style=Style(size=18, bold=True, level=2), state=BlockState.TRANSLATED,
              origin=Origin.OCR, confidence=0.9, translated="你好")
    p.blocks.append(b)
    doc.pages.append(p)

    d = doc.to_dict()
    doc2 = DocIR.from_dict(d)

    assert doc2.title == "T"
    assert doc2.page_count == 1 and doc2.block_count == 1
    bb = doc2.pages[0].blocks[0]
    assert bb.type is BlockType.HEADING
    assert bb.state is BlockState.TRANSLATED
    assert bb.origin is Origin.OCR
    assert bb.style.bold and bb.style.level == 2
    assert bb.runs[0].font == "Arial-Bold"
    assert bb.translated == "你好"
    assert doc2.translated_count == 1


def test_docir_stats_and_iter():
    doc = DocIR()
    for i in range(3):
        p = Page(index=i)
        p.blocks = [Block(text=f"a{i}", translated="译"), Block(text="123")]
        doc.pages.append(p)
    assert doc.page_count == 3 and doc.block_count == 6
    assert doc.translatable_count == 3
    assert doc.translated_count == 3
    assert sum(1 for _ in doc.iter_blocks()) == 6


# ---------------- Chunker ----------------
def test_chunker_respects_limits():
    ck = Chunker(max_chars=100, max_items=3)
    blocks = [Block(text="x" * 30) for _ in range(10)]
    batches = ck.chunk(blocks)
    assert all(len(b) <= 3 for b in batches)
    assert sum(len(b) for b in batches) == 10


def test_chunker_splits_huge_block():
    ck = Chunker(max_chars=200, max_items=5, hard_max_chars=400)
    huge = Block(text=" ".join(["word"] * 300))  # ~1500 chars
    batches = ck.chunk([huge])
    flat = [b for batch in batches for b in batch]
    assert len(flat) > 1
    assert all(len(b.text) <= 400 for b in flat)
    assert all(b.meta.get("parent_id") == huge.id for b in flat)


def test_split_sentences():
    parts = split_sentences("First sentence. Second sentence. Third one.", 20)
    assert len(parts) >= 3
    assert all(len(p) <= 20 for p in parts)


# ---------------- 翻译结果解析 ----------------
def test_parse_clean_json():
    raw = '{"translations":[{"id":1,"text":"你好"},{"id":2,"text":"世界"}]}'
    assert parse_translations(raw, 2) == ["你好", "世界"]


def test_parse_code_fence():
    raw = '```json\n{"translations":[{"id":1,"text":"你好"}]}\n```'
    assert parse_translations(raw, 1) == ["你好"]


def test_parse_with_preamble():
    raw = '当然，这是结果：\n{"translations":[{"id":1,"text":"你好"},{"id":2,"text":"世界"}]}\n希望有用'
    assert parse_translations(raw, 2) == ["你好", "世界"]


def test_parse_numbered_lines_fallback():
    raw = "1. 你好\n2. 世界\n3. 再见"
    assert parse_translations(raw, 3) == ["你好", "世界", "再见"]


def test_parse_broken_json_pairs():
    raw = '{"translations":[{"id":1,"text":"你好"},{"id":2,"text":"世界"}]'
    assert parse_translations(raw, 2) == ["你好", "世界"]


def test_parse_empty_returns_blank():
    assert parse_translations("", 2) == ["", ""]
    assert parse_translations("乱码", 2) == ["", ""]


def test_build_payload_ids():
    p = build_payload(["a", "b", "c"], "en", "zh-Hans", [{"src": "cabinet", "dst": "控制柜"}])
    assert '"id": 1' in p and '"id": 3' in p and "控制柜" in p
