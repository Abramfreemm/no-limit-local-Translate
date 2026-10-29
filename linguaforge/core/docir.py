"""DocIR v1.0 —— 统一文档中间表示。

所有输入格式（PDF / DOCX / PPTX / XLSX / HTML / MD / TXT / ...）先归一为 DocIR，
N 种输入 × M 种输出 的复杂度降为 N + M。

层次：DocIR -> Page -> Block -> Run

坐标约定：bbox = (x0, top, x1, bottom)，单位为 PDF 点（point, 72dpi），
原点在页面左上角，y 轴向下。渲染 / 回填时乘以 scale 转像素。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

BBox = tuple[float, float, float, float]  # (x0, top, x1, bottom)

DOCIR_VERSION = "1.0"


class BlockType(StrEnum):
    """块类型。决定排版与翻译策略。"""

    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE_CELL = "table_cell"
    CAPTION = "caption"
    HEADER = "header"
    FOOTER = "footer"
    CODE = "code"
    FORMULA = "formula"
    IMAGE = "image"
    PAGE_NUMBER = "page_number"
    UNKNOWN = "unknown"

    @classmethod
    def coerce(cls, v: Any) -> BlockType:
        if isinstance(v, cls):
            return v
        try:
            return cls(str(v))
        except ValueError:
            return cls.UNKNOWN


class BlockState(StrEnum):
    """块的处理状态。断点续翻依赖它。"""

    PENDING = "pending"
    EXTRACTED = "extracted"  # 已抽取，待翻译
    TRANSLATED = "translated"  # 已翻译
    FAILED = "failed"  # 翻译失败，可重试
    SKIPPED = "skipped"  # 无需翻译（纯数字 / 空白 / 已为目标语言）

    @classmethod
    def coerce(cls, v: Any) -> BlockState:
        if isinstance(v, cls):
            return v
        try:
            return cls(str(v))
        except ValueError:
            return cls.PENDING


class Origin(StrEnum):
    """文本来源。"""

    TEXT_LAYER = "text_layer"  # PDF 内嵌文本层
    OCR = "ocr"  # 光栅 OCR 识别
    HYBRID = "hybrid"  # 同一页混合

    @classmethod
    def coerce(cls, v: Any) -> Origin:
        if isinstance(v, cls):
            return v
        try:
            return cls(str(v))
        except ValueError:
            return cls.TEXT_LAYER


@dataclass
class Run:
    """带样式的最小文本片段（同一字体/字号/粗细的连续字符）。"""

    text: str
    font: str = ""
    size: float = 0.0
    bold: bool = False
    italic: bool = False
    color: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Run:
        return cls(
            text=d.get("text", ""),
            font=d.get("font", ""),
            size=float(d.get("size", 0.0)),
            bold=bool(d.get("bold", False)),
            italic=bool(d.get("italic", False)),
            color=d.get("color", ""),
        )


@dataclass
class Style:
    """块级样式，用于回填排版。"""

    font: str = ""
    size: float = 0.0
    bold: bool = False
    italic: bool = False
    align: str = "left"  # left | center | right | justify
    color: str = ""
    line_height: float = 0.0
    space_before: float = 0.0
    space_after: float = 0.0
    level: int = 0  # 标题层级

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Style:
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        for f in ("size", "line_height", "space_before", "space_after"):
            if f in known:
                known[f] = float(known[f])
        if "level" in known:
            known["level"] = int(known["level"])
        return cls(**known)


@dataclass
class Block:
    """文档的最小语义单元（通常是一行 / 一个段落 / 一个单元格）。"""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    type: BlockType = BlockType.PARAGRAPH
    bbox: BBox = (0.0, 0.0, 0.0, 0.0)
    text: str = ""
    runs: list[Run] = field(default_factory=list)
    style: Style = field(default_factory=Style)
    translated: str = ""
    state: BlockState = BlockState.PENDING
    origin: Origin = Origin.TEXT_LAYER
    confidence: float = 0.0
    lang: str = ""
    page_index: int = 0
    reading_order: int = 0
    table_id: str = ""
    row: int = -1
    col: int = -1
    meta: dict[str, Any] = field(default_factory=dict)

    # ---- 派生属性 ----
    @property
    def char_len(self) -> int:
        return len(self.text)

    @property
    def is_translatable(self) -> bool:
        """纯数字 / 纯符号 / 空白不送翻译，省 token 也避免误翻。"""
        s = self.text.strip()
        if not s:
            return False
        if self.type in (BlockType.IMAGE, BlockType.FORMULA, BlockType.PAGE_NUMBER):
            return False
        core = s.replace(" ", "")
        if not any(ch.isalpha() for ch in core):
            return False
        return True

    @property
    def out_text(self) -> str:
        """对外呈现文本：有译文用译文，否则原文。"""
        return self.translated if self.translated else self.text

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "bbox": list(self.bbox),
            "text": self.text,
            "runs": [r.to_dict() for r in self.runs],
            "style": self.style.to_dict(),
            "translated": self.translated,
            "state": self.state.value,
            "origin": self.origin.value,
            "confidence": self.confidence,
            "lang": self.lang,
            "page_index": self.page_index,
            "reading_order": self.reading_order,
            "table_id": self.table_id,
            "row": self.row,
            "col": self.col,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Block:
        return cls(
            id=d.get("id", uuid.uuid4().hex[:16]),
            type=BlockType.coerce(d.get("type")),
            bbox=tuple(d.get("bbox", (0.0, 0.0, 0.0, 0.0))),  # type: ignore[arg-type]
            text=d.get("text", ""),
            runs=[Run.from_dict(r) for r in d.get("runs", [])],
            style=Style.from_dict(d.get("style", {})),
            translated=d.get("translated", ""),
            state=BlockState.coerce(d.get("state")),
            origin=Origin.coerce(d.get("origin")),
            confidence=float(d.get("confidence", 0.0)),
            lang=d.get("lang", ""),
            page_index=int(d.get("page_index", 0)),
            reading_order=int(d.get("reading_order", 0)),
            table_id=d.get("table_id", ""),
            row=int(d.get("row", -1)),
            col=int(d.get("col", -1)),
            meta=d.get("meta", {}),
        )


@dataclass
class Page:
    """一页。分页流式处理的核心单元。"""

    index: int = 0
    width: float = 595.0  # A4 @72dpi
    height: float = 842.0
    blocks: list[Block] = field(default_factory=list)
    ocr_used: bool = False
    rotation: int = 0
    image_path: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def blocks_sorted(self) -> list[Block]:
        return sorted(self.blocks, key=lambda b: b.reading_order)

    @property
    def translatable_blocks(self) -> list[Block]:
        return [b for b in self.blocks_sorted if b.is_translatable]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "width": self.width,
            "height": self.height,
            "blocks": [b.to_dict() for b in self.blocks],
            "ocr_used": self.ocr_used,
            "rotation": self.rotation,
            "image_path": self.image_path,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Page:
        return cls(
            index=int(d.get("index", 0)),
            width=float(d.get("width", 595.0)),
            height=float(d.get("height", 842.0)),
            blocks=[Block.from_dict(b) for b in d.get("blocks", [])],
            ocr_used=bool(d.get("ocr_used", False)),
            rotation=int(d.get("rotation", 0)),
            image_path=d.get("image_path", ""),
            meta=d.get("meta", {}),
        )


@dataclass
class DocIR:
    """一份文档。"""

    doc_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    source_path: str = ""
    source_format: str = ""
    title: str = ""
    lang_src: str = "auto"
    lang_dst: str = "zh-Hans"
    pages: list[Page] = field(default_factory=list)
    outline: list[dict[str, Any]] = field(default_factory=list)
    assets: dict[str, str] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    version: str = DOCIR_VERSION
    created_at: float = field(default_factory=time.time)

    # ---- 统计 ----
    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def block_count(self) -> int:
        return sum(len(p.blocks) for p in self.pages)

    @property
    def translatable_count(self) -> int:
        return sum(len(p.translatable_blocks) for p in self.pages)

    @property
    def translated_count(self) -> int:
        n = 0
        for p in self.pages:
            n += sum(1 for b in p.blocks if b.translated)
        return n

    @property
    def ocr_page_count(self) -> int:
        return sum(1 for p in self.pages if p.ocr_used)

    def iter_blocks(self) -> Iterable[Block]:
        """跨页迭代全部块（生成器，不额外占内存）。"""
        for p in self.pages:
            yield from p.blocks

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "source_path": self.source_path,
            "source_format": self.source_format,
            "title": self.title,
            "lang_src": self.lang_src,
            "lang_dst": self.lang_dst,
            "pages": [p.to_dict() for p in self.pages],
            "outline": self.outline,
            "assets": self.assets,
            "meta": self.meta,
            "version": self.version,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DocIR:
        return cls(
            doc_id=d.get("doc_id", uuid.uuid4().hex[:16]),
            source_path=d.get("source_path", ""),
            source_format=d.get("source_format", ""),
            title=d.get("title", ""),
            lang_src=d.get("lang_src", "auto"),
            lang_dst=d.get("lang_dst", "zh-Hans"),
            pages=[Page.from_dict(p) for p in d.get("pages", [])],
            outline=d.get("outline", []),
            assets=d.get("assets", {}),
            meta=d.get("meta", {}),
            version=d.get("version", DOCIR_VERSION),
            created_at=float(d.get("created_at", time.time())),
        )
