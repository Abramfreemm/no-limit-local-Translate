"""XLSX -> DocIR 解析器。

每个工作表 = 一个 Page；单元格归一为 TABLE_CELL 块（带 row / col）。

关键取舍：
1. data_only=True：取缓存值而非公式本身。翻译场景下要译的是「看到的值」，
   公式串（=SUM(A1:A2)）没有翻译意义。
2. 合并单元格：只有左上角格出块，其余被覆盖的坐标整体跳过，避免同一句话翻两遍。
   取值一律走左上角格（合并区的值挂在左上格）。
3. 全空行整体跳过，但行号保留原始绝对行号，写回时才能还原到原位置。
4. row / col 统一 0-based，与 pdf_parser 一致；写回时 +1 转 openpyxl 的 1-based。
5. 稀疏表（max_row 被格式撑到百万级）先按实际有值单元格求真实范围，避免空转。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from ..core.config import Config
from ..core.docir import Block, BlockState, BlockType, DocIR, Origin, Page, Style
from ..core.problems import DocumentParseError

# 超过此规模就先探测真实使用范围，避免遍历百万空行
_SPARSE_CELL_BUDGET = 2_000_000


class XlsxParseError(DocumentParseError):
    """XLSX 解析失败。

    ADR-016：原 6 个 ``*ParseError`` 除名字外完全一致却各自演化，
    现统一继承 :class:`~linguaforge.core.problems.DocumentParseError`，
    仅保留 ``fmt="xlsx"`` 作为格式标签，上层可一次捕获。
    """

    def __init__(self, message: str = "", **kw) -> None:
        super().__init__(message, fmt="xlsx", **kw)


class XlsxParser:
    """解析 .xlsx / .xlsm。用法：

    with XlsxParser(cfg) as p:
        p.open(path)
        for page in p.iter_pages():
            ...
    """

    extensions: set = {".xlsx", ".xlsm"}

    def __init__(self, cfg=None) -> None:
        self.cfg = cfg or Config()
        self.path: str = ""
        self._wb: Any | None = None
        self._sheets: list[str] = []
        self._page_count: int = 0
        self._title: str = ""

    # ---------------- 生命周期 ----------------
    def supports(self, path) -> bool:
        return Path(path).suffix.lower() in self.extensions

    def open(self, path) -> XlsxParser:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        if not self.supports(p):
            raise XlsxParseError(
                f"XlsxParser 不支持扩展名 {p.suffix or '(无)'}，仅支持 .xlsx / .xlsm"
            )
        try:
            self._wb = load_workbook(filename=str(p), data_only=True)
        except Exception as e:
            raise XlsxParseError(f"无法打开 XLSX：{p.name}（文件损坏或不是合法工作簿）: {e}") from e
        self.path = str(p)
        try:
            self._sheets = list(self._wb.sheetnames)
        except Exception:
            self._sheets = []
        self._page_count = len(self._sheets)
        self._title = self._detect_title()
        return self

    def close(self) -> None:
        try:
            if self._wb is not None:
                self._wb.close()
        except Exception:
            pass
        self._wb = None
        self._sheets = []
        self._page_count = 0

    def __enter__(self) -> XlsxParser:
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

    @property
    def sheet_names(self) -> list[str]:
        """工作表名称列表（与 Page 一一对应）。"""
        return list(self._sheets)

    # ---------------- 逐页解析 ----------------
    def _detect_title(self) -> str:
        assert self._wb is not None
        try:
            t = (self._wb.properties.title or "").strip()
        except Exception:
            t = ""
        if t:
            return t
        return Path(self.path).stem

    def parse_page(self, index: int = 0) -> Page:
        assert self._wb is not None, "parser not opened"
        if not 0 <= index < self._page_count:
            raise IndexError(f"工作表序号越界: {index}（共 {self._page_count} 个）")
        ws = self._wb[self._sheets[index]]
        page = Page(index=index, width=0.0, height=0.0)
        page.meta["source_format"] = "xlsx"
        page.meta["sheet_name"] = ws.title
        try:
            page.meta["sheet_state"] = str(ws.sheet_state or "visible")
        except Exception:
            page.meta["sheet_state"] = "visible"

        max_row, max_col = _used_range(ws)
        merge_map = _merge_map(ws)
        table_id = f"s{index}"
        order = 0
        rows_seen = 0

        for r in range(1, max_row + 1):
            row_texts: list[tuple[int, str, bool]] = []  # (col0, text, 是否左上角格)
            for c in range(1, max_col + 1):
                src = merge_map.get((r, c))
                is_anchor = src is None
                rr, cc = src if src else (r, c)
                try:
                    value = ws.cell(row=rr, column=cc).value
                except Exception:
                    value = None
                text = _fmt_value(value)
                if not text:
                    continue
                row_texts.append((c - 1, text, is_anchor))
            if not row_texts:
                continue  # 全空行：跳过，且不占用 reading_order
            rows_seen += 1
            for col0, text, is_anchor in row_texts:
                if not is_anchor:
                    continue  # 合并区的非左上角格：值重复，跳过
                b = Block(
                    type=BlockType.TABLE_CELL,
                    text=text,
                    style=Style(size=11.0),
                    page_index=index,
                    reading_order=order,
                    table_id=table_id,
                    row=r - 1,
                    col=col0,
                    origin=Origin.TEXT_LAYER,
                    confidence=1.0,
                )
                b.meta["header"] = rows_seen == 1
                b.meta["column"] = get_column_letter(col0 + 1)
                b.state = BlockState.EXTRACTED if b.is_translatable else BlockState.SKIPPED
                page.blocks.append(b)
                order += 1

        page.meta["block_count"] = len(page.blocks)
        page.meta["used_rows"] = rows_seen
        page.meta["used_cols"] = max_col
        return page

    def iter_pages(self, start: int = 0, end: int | None = None) -> Iterator[Page]:
        stop = self._page_count if end is None else min(end, self._page_count)
        for i in range(max(0, start), stop):
            yield self.parse_page(i)

    def to_docir(self, max_pages: int | None = None) -> DocIR:
        doc = DocIR(source_path=self.path, source_format="xlsx", title=self.title)
        for p in self.iter_pages(end=max_pages):
            doc.pages.append(p)
        return doc


# ---------------- 模块级工具 ----------------
def _used_range(ws: Any) -> tuple[int, int]:
    """返回 (max_row, max_col)。

    正常表直接用 sheet 声明的范围；被格式撑大的稀疏表改用实际有值单元格求范围，
    避免遍历上百万空行。
    """
    max_row = int(ws.max_row or 1)
    max_col = int(ws.max_column or 1)
    if max_row * max_col <= _SPARSE_CELL_BUDGET:
        return max_row, max_col
    cells = getattr(ws, "_cells", None)
    if not isinstance(cells, dict) or not cells:
        return max_row, max_col
    mr, mc = 1, 1
    for r, c in cells.keys():
        if r > mr:
            mr = r
        if c > mc:
            mc = c
    return mr, mc


def _merge_map(ws: Any) -> dict:
    """合并区覆盖到的坐标 -> 左上角坐标。"""
    out: dict = {}
    try:
        ranges = list(ws.merged_cells.ranges)
    except Exception:
        return out
    for rng in ranges:
        top_left = (int(rng.min_row), int(rng.min_col))
        for r in range(int(rng.min_row), int(rng.max_row) + 1):
            for c in range(int(rng.min_col), int(rng.max_col) + 1):
                if (r, c) != top_left:
                    out[(r, c)] = top_left
    return out


def _fmt_value(value: Any) -> str:
    """单元格值 -> 可翻译文本。空白值返回空串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.10g}"
    if isinstance(value, int):
        return str(value)
    return str(value).strip()
