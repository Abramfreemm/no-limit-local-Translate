"""纯文本输出。"""

from __future__ import annotations

from pathlib import Path

from ..core.docir import BlockType, DocIR, Page

_SKIP = {BlockType.HEADER, BlockType.FOOTER, BlockType.PAGE_NUMBER}


def render_page_text(page: Page, bilingual: bool = False) -> list[str]:
    out: list[str] = []
    for b in page.blocks_sorted:
        if b.type in _SKIP:
            continue
        txt = b.out_text.strip()
        if not txt:
            continue
        if b.type in (BlockType.TITLE, BlockType.HEADING):
            out.append("")
            out.append(txt)
            out.append("=" * min(60, max(8, len(txt))))
        elif b.type is BlockType.LIST_ITEM:
            out.append(f"  - {txt}")
        elif b.type is BlockType.TABLE_CELL:
            out.append(f"  {txt}")
        else:
            out.append(txt)
        if bilingual and b.translated.strip():
            out.append(f"  [{b.text.strip()}]")
        out.append("")
    return out


def render_text(doc: DocIR, bilingual: bool = False) -> str:
    out: list[str] = []
    if doc.title:
        out.append(doc.title)
        out.append("=" * min(60, max(8, len(doc.title))))
        out.append("")
    for page in doc.pages:
        out.extend(render_page_text(page, bilingual))
        if page.meta.get("ocr_used"):
            out.append(f"[page {page.index + 1}: OCR]")
            out.append("")
    text = "\n".join(out)
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")
    return text.strip() + "\n"


def write_text(doc: DocIR, path: str | Path, bilingual: bool = False) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_text(doc, bilingual), encoding="utf-8")
    return p
