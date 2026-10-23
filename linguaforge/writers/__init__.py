"""输出层：Markdown / 纯文本 / PDF 原位回填 / DOCX / PPTX / XLSX / SRT。

流式 Writer 统一契约：
    render_pages(state, pages, total, bilingual) -> str   # 追加一个窗口
    finalize(state, out_path) -> str                      # 收尾落盘
一次性 Writer：
    write_all(pages, out_path, *, bilingual=False, title="") -> str
"""

from .docx_writer import finalize as docx_finalize
from .docx_writer import render_pages as docx_render_pages
from .docx_writer import write_all as write_docx
from .markdown import render_markdown, render_pages, write_markdown
from .pdf_rebuild import PDFRebuildWriter, rebuild_pdf
from .pptx_writer import finalize as pptx_finalize
from .pptx_writer import render_pages as pptx_render_pages
from .pptx_writer import write_all as write_pptx
from .srt_writer import finalize as srt_finalize
from .srt_writer import render_pages as srt_render_pages
from .srt_writer import write_all as write_srt
from .text import render_text, write_text
from .xlsx_writer import finalize as xlsx_finalize
from .xlsx_writer import render_pages as xlsx_render_pages
from .xlsx_writer import write_all as write_xlsx

__all__ = [
    "PDFRebuildWriter",
    "docx_finalize",
    "docx_render_pages",
    "pptx_finalize",
    "pptx_render_pages",
    "rebuild_pdf",
    "render_markdown",
    "render_pages",
    "render_text",
    "srt_finalize",
    "srt_render_pages",
    "write_docx",
    "write_markdown",
    "write_pptx",
    "write_srt",
    "write_text",
    "write_xlsx",
    "xlsx_finalize",
    "xlsx_render_pages",
]
