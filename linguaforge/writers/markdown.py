"""Markdown 输出。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence

from ..core.docir import Block, BlockType, DocIR, Page

_SKIP = {BlockType.HEADER, BlockType.FOOTER, BlockType.PAGE_NUMBER}


def _heading_level(b: Block) -> int:
    if b.style.level:
        return max(1, min(6, b.style.level))
    return 2


def _escape_cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def render_markdown(doc: DocIR, bilingual: bool = False, include_skipped: bool = False) -> str:
    """把 DocIR 渲染成 Markdown 文本（全量，适合小文件）。"""
    return render_pages(doc.title, doc.pages, doc.page_count, bilingual, include_skipped)


def render_pages(
    title: str = "",
    pages: Sequence[Page] = (),
    page_count: int = 0,
    bilingual: bool = False,
    include_skipped: bool = False,
) -> str:
    """渲染一批页面。流水线按窗口流式调用它，避免整篇驻留内存。"""
    out: List[str] = []
    if title:
        out.append(f"# {title}")
        out.append("")

    for page in pages:
        blocks = [b for b in page.blocks_sorted if include_skipped or b.type not in _SKIP]
        if not blocks:
            continue
        # 表格按 table_id 聚合
        tables: Dict[str, List[Block]] = {}
        for b in blocks:
            if b.type is BlockType.TABLE_CELL and b.table_id:
                tables.setdefault(b.table_id, []).append(b)
        emitted_tables: set = set()

        pending_page_mark = False
        prev_was_list = False
        for b in blocks:
            if b.type is BlockType.TABLE_CELL:
                if b.table_id in emitted_tables:
                    continue
                emitted_tables.add(b.table_id)
                if prev_was_list:
                    out.append("")
                    prev_was_list = False
                out.extend(_render_table(tables.get(b.table_id, []), bilingual))
                out.append("")
                continue

            txt = b.out_text.strip()
            if not txt:
                continue
            # 列表后紧跟普通块必须补空行，否则会被 Markdown 吞进上一项
            if prev_was_list and b.type is not BlockType.LIST_ITEM:
                out.append("")
                prev_was_list = False
            if not pending_page_mark and page_count > 1:
                out.append(f"<!-- page {page.index + 1} -->")
                out.append("")
            pending_page_mark = True

            if b.type is BlockType.TITLE:
                out.append(f"# {txt}")
            elif b.type is BlockType.HEADING:
                out.append(f"{'#' * _heading_level(b)} {txt}")
            elif b.type is BlockType.LIST_ITEM:
                # 列表项之间不留空行，否则 Markdown 会渲染成松散列表（间距过大）
                out.append(f"- {txt}")
                if bilingual and b.translated.strip():
                    out.append(f"  > {b.text.strip()}")
                prev_was_list = True
                continue
            elif b.type is BlockType.CAPTION:
                out.append(f"*{txt}*")
            elif b.type is BlockType.CODE:
                out.append("```")
                out.append(txt)
                out.append("```")
            else:
                out.append(txt)
            if bilingual and b.translated.strip():
                out.append("")
                out.append(f"> {b.text.strip()}")
            out.append("")

        if page.meta.get("need_ocr") and page.ocr_used:
            out.append(f"<!-- page {page.index + 1}: OCR -->")
            out.append("")

    text = "\n".join(out)
    # 压缩 3 行以上空行
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")
    return text.strip() + "\n"


def _render_table(cells: List[Block], bilingual: bool) -> List[str]:
    if not cells:
        return []
    rows: Dict[int, Dict[int, Block]] = {}
    for c in cells:
        rows.setdefault(c.row, {})[c.col] = c
    max_col = max((max(r.keys()) for r in rows.values() if r), default=0)
    out: List[str] = []
    for ri in sorted(rows.keys()):
        row = rows[ri]
        line = "| " + " | ".join(_escape_cell(row.get(ci, Block()).out_text.strip()) for ci in range(max_col + 1)) + " |"
        out.append(line)
        if ri == sorted(rows.keys())[0]:
            out.append("|" + "---|" * (max_col + 1))
    return out


def write_markdown(doc: DocIR, path: str | Path, bilingual: bool = False) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_markdown(doc, bilingual), encoding="utf-8")
    return p
