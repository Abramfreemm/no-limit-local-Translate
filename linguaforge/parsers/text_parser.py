"""纯文本 / Markdown 解析器。用于 TXT、MD 及 OCR 兜底文本。

按空行切段，按行首标记识别标题与列表；不产生 bbox（此类格式无版面概念）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator, List

from ..core.docir import Block, BlockState, BlockType, DocIR, Origin, Page, Style

_RE_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_RE_LIST = re.compile(r"^\s*(?:[-*+•·]|\d+[.)、]|[a-zA-Z][.)])\s+(.*)$")
_RE_TABLE_ROW = re.compile(r"^\|.*\|$")


class TextParser:
    """解析 .txt / .md / .markdown。"""

    def __init__(self, config=None) -> None:
        self.path = ""
        self.lines: List[str] = []
        self.page_count = 1

    def open(self, path: str | Path) -> "TextParser":
        self.path = str(path)
        self.lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        return self

    def close(self) -> None:
        self.lines = []

    def __enter__(self) -> "TextParser":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def iter_pages(self, start: int = 0, end=None) -> Iterator[Page]:
        page = self.parse_page(0)
        yield page

    def parse_page(self, index: int = 0) -> Page:
        page = Page(index=index, width=595.0, height=842.0)
        order = 0
        para_buf: List[str] = []
        para_type = BlockType.PARAGRAPH

        def flush() -> None:
            nonlocal para_buf, para_type, order
            if not para_buf:
                return
            text = "\n".join(para_buf).strip()
            para_buf = []
            if not text:
                return
            b = Block(
                page_index=index,
                text=text,
                type=para_type,
                style=Style(size=11.0),
                reading_order=order,
                origin=Origin.TEXT_LAYER,
                confidence=1.0,
            )
            b.state = BlockState.EXTRACTED if b.is_translatable else BlockState.SKIPPED
            page.blocks.append(b)
            order += 1
            para_type = BlockType.PARAGRAPH

        in_code = False
        for raw in self.lines:
            line = raw.rstrip()
            if line.strip().startswith("```"):
                if in_code:
                    flush()
                    in_code = False
                else:
                    flush()
                    in_code = True
                continue
            if in_code:
                para_buf.append(line)
                para_type = BlockType.CODE
                continue

            if not line.strip():
                flush()
                continue

            m = _RE_HEADING.match(line)
            if m:
                flush()
                level = len(m.group(1))
                b = Block(
                    page_index=index,
                    text=m.group(2).strip(),
                    type=BlockType.TITLE if level == 1 else BlockType.HEADING,
                    style=Style(size={1: 24.0, 2: 18.0, 3: 15.0}.get(level, 13.0), level=level),
                    reading_order=order,
                )
                b.state = BlockState.EXTRACTED if b.is_translatable else BlockState.SKIPPED
                page.blocks.append(b)
                order += 1
                continue

            m = _RE_LIST.match(line)
            if m:
                flush()
                b = Block(
                    page_index=index,
                    text=m.group(0).strip(),
                    type=BlockType.LIST_ITEM,
                    style=Style(size=11.0),
                    reading_order=order,
                )
                b.state = BlockState.EXTRACTED if b.is_translatable else BlockState.SKIPPED
                page.blocks.append(b)
                order += 1
                continue

            if _RE_TABLE_ROW.match(line.strip()):
                flush()
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                for ci, c in enumerate(cells):
                    if not c or set(c) <= set("-: "):
                        continue
                    b = Block(
                        page_index=index,
                        text=c,
                        type=BlockType.TABLE_CELL,
                        style=Style(size=11.0),
                        reading_order=order,
                        table_id=f"t{order}",
                        row=0,
                        col=ci,
                    )
                    b.state = BlockState.EXTRACTED if b.is_translatable else BlockState.SKIPPED
                    page.blocks.append(b)
                order += 1
                continue

            para_buf.append(line)

        flush()
        return page

    def to_docir(self) -> DocIR:
        doc = DocIR(
            source_path=self.path,
            source_format=Path(self.path).suffix.lower().lstrip("."),
            title=Path(self.path).stem,
        )
        doc.pages.append(self.parse_page(0))
        return doc
