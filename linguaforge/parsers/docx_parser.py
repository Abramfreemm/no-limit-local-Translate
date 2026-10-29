"""DOCX -> DocIR 解析器。

用 python-docx 读取段落 / 标题 / 列表 / 表格，归一为 DocIR 的 Page 流。

关键取舍：
1. DOCX 没有物理页概念。这里按「显式分页符（w:br w:type=page）」切页，无分页符时
   整篇为 1 页；这样窗口式流水线仍能按页分批，不受单页体积限制。
2. 段落与表格必须保持文档真实顺序：遍历 body 的子元素判断 w:p / w:tbl，
   而不是分别遍历 document.paragraphs / document.tables（后者会丢失交错顺序）。
3. run 级加粗 / 斜体 / 字体 / 字号 / 颜色保留到 Block.runs 与 Block.style。
4. 标题层级取自样式名（Heading N / 标题 N）与样式 ID（中文 Word 内置标题 ID 为数字），
   并沿 base_style 上溯 4 层，兼容自定义标题样式。
5. row / col 统一 0-based，与 pdf_parser 保持一致。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph
from docx.text.run import Run as DocxRun

from ..core.config import Config
from ..core.docir import Block, BlockState, BlockType, DocIR, Origin, Page, Run, Style
from ..core.problems import DocumentParseError

# 标题样式名：Heading 1 / heading1 / 标题 1 / Titre 1 / Überschrift 1
_RE_HEADING_NAME = re.compile(r"^\s*(?:heading|标题|標題|titre|überschrift)\s*(\d{1,2})\s*$", re.I)
_RE_HEADING_ID = re.compile(r"^heading(\d{1,2})$", re.I)
# 明确的项目符号 / 编号样式名（中英文）
_LIST_STYLE_NAMES = {
    "list bullet",
    "list bullet 2",
    "list bullet 3",
    "list number",
    "list number 2",
    "list number 3",
    "list paragraph",
    "list",
    "列表项目符号",
    "列表编号",
    "列表段落",
}

_ALIGN_MAP = {
    WD_ALIGN_PARAGRAPH.LEFT: "left",
    WD_ALIGN_PARAGRAPH.CENTER: "center",
    WD_ALIGN_PARAGRAPH.RIGHT: "right",
    WD_ALIGN_PARAGRAPH.JUSTIFY: "justify",
}


class DocxParseError(DocumentParseError):
    """DOCX 解析失败。

    ADR-016：原 6 个 ``*ParseError`` 除名字外完全一致却各自演化，
    现统一继承 :class:`~linguaforge.core.problems.DocumentParseError`，
    仅保留 ``fmt="docx"`` 作为格式标签，上层可一次捕获。
    """

    def __init__(self, message: str = "", **kw) -> None:
        super().__init__(message, fmt="docx", **kw)


class DocxParser:
    """解析 .docx。用法：

    with DocxParser(cfg) as p:
        p.open(path)
        for page in p.iter_pages():
            ...
    """

    extensions: set = {".docx"}

    def __init__(self, cfg=None) -> None:
        self.cfg = cfg or Config()
        self.path: str = ""
        self._doc: Any | None = None
        self._items: list[tuple[str, Any]] = []
        # 每个元素 = 该页结束后的 item 下标（不含），长度 = 分割次数
        self._splits: list[int] = []
        self._page_count: int = 1
        self._title: str = ""

    # ---------------- 生命周期 ----------------
    def supports(self, path) -> bool:
        """按扩展名判断是否支持（不检查文件是否存在）。"""
        return Path(path).suffix.lower() in self.extensions

    def open(self, path) -> DocxParser:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        if not self.supports(p):
            raise DocxParseError(f"DocxParser 不支持扩展名 {p.suffix or '(无)'}，仅支持 .docx")
        try:
            self._doc = Document(str(p))
        except Exception as e:  # python-docx 对损坏包抛 ValueError / KeyError
            raise DocxParseError(
                f"无法打开 DOCX：{p.name}（文件损坏或不是合法 OOXML 包）: {e}"
            ) from e
        self.path = str(p)
        try:
            self._scan_body()
        except Exception as e:
            raise DocxParseError(f"DOCX 结构解析失败：{p.name}: {e}") from e
        self._title = self._detect_title()
        return self

    def close(self) -> None:
        """python-docx 全量驻留内存，关闭即释放引用。"""
        self._doc = None
        self._items = []
        self._splits = []
        self._page_count = 1

    def __enter__(self) -> DocxParser:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------------- 属性 ----------------
    @property
    def page_count(self) -> int:
        return self._page_count

    @property
    def title(self) -> str:
        return self._title or (Path(self.path).stem if self.path else "")

    # ---------------- 扫描 ----------------
    def _scan_body(self) -> None:
        """按文档顺序收集段落与表格，并记录分页符位置。"""
        assert self._doc is not None, "parser not opened"
        items: list[tuple[str, Any]] = []
        splits: list[int] = []
        body = self._doc.element.body
        for child in body.iterchildren():
            tag = child.tag
            if tag == qn("w:p"):
                para = Paragraph(child, self._doc)
                items.append(("p", para))
                if _has_page_break(child):
                    splits.append(len(items))
            elif tag == qn("w:tbl"):
                items.append(("t", DocxTable(child, self._doc)))
        # 末尾紧跟的分页符不产生新页
        while splits and splits[-1] >= len(items):
            splits.pop()
        self._items = items
        self._splits = splits
        self._page_count = (len(splits) + 1) if items else 1

    def _detect_title(self) -> str:
        """标题优先级：core properties -> 首个一级标题/Title 样式段 -> 文件名 stem。"""
        assert self._doc is not None
        try:
            t = (self._doc.core_properties.title or "").strip()
        except Exception:
            t = ""
        if t:
            return t
        for kind, item in self._items:
            if kind != "p":
                continue
            try:
                name = (item.style.name or "").strip().lower()
            except Exception:
                name = ""
            if _heading_level(item) == 1 or name == "title":
                txt = (item.text or "").strip()
                if txt:
                    return txt[:200]
        return Path(self.path).stem

    # ---------------- 逐页解析 ----------------
    def _bounds(self, index: int) -> tuple[int, int]:
        start = self._splits[index - 1] if index > 0 else 0
        end = self._splits[index] if index < len(self._splits) else len(self._items)
        return start, end

    def parse_page(self, index: int = 0) -> Page:
        assert self._doc is not None, "parser not opened"
        if not 0 <= index < self._page_count:
            raise IndexError(f"页码越界: {index}（共 {self._page_count} 页）")
        start, end = self._bounds(index)
        page = Page(index=index, width=595.0, height=842.0)
        page.meta["source_format"] = "docx"
        order = 0
        table_seq = 0
        for kind, item in self._items[start:end]:
            if kind == "p":
                b = self._para_block(item, index, order)
                if b is not None:
                    page.blocks.append(b)
                    order += 1
            else:
                cells = self._table_blocks(item, index, order, f"t{index}_{table_seq}")
                table_seq += 1
                for b in cells:
                    page.blocks.append(b)
                    order += 1
        page.meta["block_count"] = len(page.blocks)
        return page

    def iter_pages(self, start: int = 0, end: int | None = None) -> Iterator[Page]:
        """逐页产出 Page（生成器）。"""
        stop = self._page_count if end is None else min(end, self._page_count)
        for i in range(max(0, start), stop):
            yield self.parse_page(i)

    def to_docir(self, max_pages: int | None = None) -> DocIR:
        """整体读成 DocIR（仅用于小文件 / 单测）。"""
        doc = DocIR(
            source_path=self.path,
            source_format="docx",
            title=self.title,
        )
        for p in self.iter_pages(end=max_pages):
            doc.pages.append(p)
        return doc

    # ---------------- 块构建 ----------------
    def _para_block(self, p: Paragraph, page_index: int, order: int) -> Block | None:
        """段落 -> Block。空段落直接丢弃（不产生噪音块）。"""
        runs = _runs_of(p)
        text = "".join(r.text for r in runs)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return None

        style = _style_of(p, runs)
        btype, level = self._classify(p, style)
        b = Block(
            type=btype,
            text=text,
            runs=runs,
            style=style,
            page_index=page_index,
            reading_order=order,
            origin=Origin.TEXT_LAYER,
            confidence=1.0,
        )
        b.style.level = level
        if btype is BlockType.LIST_ITEM:
            b.meta["list_level"] = _list_level(p)
        b.state = BlockState.EXTRACTED if b.is_translatable else BlockState.SKIPPED
        return b

    def _classify(self, p: Paragraph, style: Style) -> tuple[BlockType, int]:
        """段落类型推断：Title > Heading N > 列表 > 正文。"""
        try:
            name = (p.style.name or "").strip().lower()
        except Exception:
            name = ""
        if name == "title":
            return BlockType.TITLE, 1
        level = _heading_level(p)
        if level:
            return BlockType.HEADING, min(9, max(1, level))
        if name == "subtitle":
            return BlockType.HEADING, 2
        if _is_list(p):
            return BlockType.LIST_ITEM, 0
        return BlockType.PARAGRAPH, 0

    def _table_blocks(
        self, tbl: DocxTable, page_index: int, order: int, table_id: str
    ) -> list[Block]:
        """表格 -> TABLE_CELL 块列表。

        横向合并单元格在 python-docx 中会重复出现（同一 w:tc 对应多个网格列），
        这里按 tc 元素去重，避免同一句话被翻译两次。
        """
        out: list[Block] = []
        try:
            rows = tbl.rows
        except Exception:
            return out
        for r, row in enumerate(rows):
            seen: set = set()
            try:
                cells = row.cells
            except Exception:
                continue
            for c, cell in enumerate(cells):
                key = id(cell._tc)  # noqa: SLF001 —— python-docx 未提供公开 API 判断合并格
                if key in seen:
                    continue
                seen.add(key)
                text = re.sub(r"\s+", " ", (cell.text or "")).strip()
                if not text:
                    continue
                runs: list[Run] = []
                if cell.paragraphs:
                    runs = _runs_of(cell.paragraphs[0])
                style = Style(size=10.0)
                if runs:
                    style = _style_of(cell.paragraphs[0], runs)
                b = Block(
                    type=BlockType.TABLE_CELL,
                    text=text,
                    runs=runs,
                    style=style,
                    page_index=page_index,
                    reading_order=order + len(out),
                    table_id=table_id,
                    row=r,
                    col=c,
                    origin=Origin.TEXT_LAYER,
                    confidence=1.0,
                )
                b.meta["header"] = bool(_row_is_header(row))
                b.state = BlockState.EXTRACTED if b.is_translatable else BlockState.SKIPPED
                out.append(b)
        return out


# ---------------- 模块级工具 ----------------
def _has_page_break(p_el: Any) -> bool:
    """段落是否含显式分页符。"""
    for br in p_el.iter(qn("w:br")):
        if br.get(qn("w:type")) == "page":
            return True
    return False


def _style_name(p: Paragraph) -> str:
    try:
        return (p.style.name or "").strip()
    except Exception:
        return ""


def _heading_level(p: Paragraph) -> int:
    """标题层级（0 = 非标题）。沿 base_style 上溯，兼容自定义样式。"""
    style = None
    try:
        style = p.style
    except Exception:
        return 0
    for _ in range(4):
        if style is None:
            break
        name = ""
        sid = ""
        try:
            name = (style.name or "").strip()
        except Exception:
            name = ""
        try:
            sid = (style.style_id or "").strip()
        except Exception:
            sid = ""
        m = _RE_HEADING_NAME.match(name)
        if m:
            return int(m.group(1))
        m = _RE_HEADING_ID.match(sid)
        if m:
            return int(m.group(1))
        # 中文 Word 内置标题样式的 styleId 就是纯数字 "1".."9"
        if sid.isdigit() and 1 <= int(sid) <= 9:
            return int(sid)
        try:
            style = style.base_style
        except Exception:
            break
    return 0


def _is_list(p: Paragraph) -> bool:
    """是否列表项：样式名命中，或段落带 w:numPr（编号/项目符号）。"""
    if _style_name(p).strip().lower() in _LIST_STYLE_NAMES:
        return True
    pPr = p._p.pPr  # noqa: SLF001 —— 需读取 numPr，python-docx 无公开 API
    if pPr is None:
        return False
    return pPr.find(qn("w:numPr")) is not None


def _list_level(p: Paragraph) -> int:
    """列表缩进级别（0 起）。"""
    pPr = p._p.pPr  # noqa: SLF001
    if pPr is None:
        return 0
    numPr = pPr.find(qn("w:numPr"))
    if numPr is None:
        return 0
    ilvl = numPr.find(qn("w:ilvl"))
    if ilvl is None:
        return 0
    try:
        return int(ilvl.get(qn("w:val")))
    except (TypeError, ValueError):
        return 0


def _row_is_header(row: Any) -> bool:
    """表头行判定：w:trPr/w:tblHeader 或首行为 header 风格。"""
    try:
        trPr = row._tr.trPr  # noqa: SLF001
    except Exception:
        return False
    if trPr is None:
        return False
    return trPr.find(qn("w:tblHeader")) is not None


def _runs_of(p: Paragraph) -> list[Run]:
    """抽取段落内全部 w:r（含超链接内的 run，python-docx 的 p.runs 会漏掉它们）。"""
    out: list[Run] = []
    try:
        elements = list(p._p.iter(qn("w:r")))  # noqa: SLF001
    except Exception:
        return out
    for r_el in elements:
        try:
            dr = DocxRun(r_el, p)
        except Exception:
            continue
        text = dr.text or ""
        if not text:
            continue
        font = ""
        size = 0.0
        bold = False
        italic = False
        color = ""
        try:
            font = dr.font.name or ""
        except Exception:
            font = ""
        try:
            if dr.font.size is not None:
                size = float(dr.font.size.pt)
        except Exception:
            size = 0.0
        try:
            bold = bool(dr.font.bold)
            italic = bool(dr.font.italic)
        except Exception:
            bold = italic = False
        try:
            rgb = dr.font.color.rgb
            if rgb is not None:
                color = str(rgb)
        except (AttributeError, ValueError, TypeError):
            color = ""  # 主题色 / 自动色无 rgb，属正常情况
        out.append(Run(text=text, font=font, size=size, bold=bold, italic=italic, color=color))
    return out


def _style_of(p: Paragraph, runs: list[Run]) -> Style:
    """由段落与 run 汇总块级样式。"""
    align = "left"
    try:
        al = p.alignment
        if al in _ALIGN_MAP:
            align = _ALIGN_MAP[al]
    except Exception:
        align = "left"
    if not runs:
        return Style(size=11.0, align=align)
    font = ""
    for r in runs:
        if r.font:
            font = r.font
            break
    size = max((r.size for r in runs if r.size), default=0.0) or 11.0
    bold = any(r.bold for r in runs)
    italic = all(r.italic for r in runs) if runs else False
    color = next((r.color for r in runs if r.color), "")
    space_before = 0.0
    space_after = 0.0
    try:
        fmt = p.paragraph_format
        if fmt.space_before is not None:
            space_before = float(fmt.space_before.pt)
        if fmt.space_after is not None:
            space_after = float(fmt.space_after.pt)
    except Exception:
        space_before = space_after = 0.0
    return Style(
        font=font,
        size=size,
        bold=bold,
        italic=italic,
        align=align,
        color=color,
        space_before=space_before,
        space_after=space_after,
    )
