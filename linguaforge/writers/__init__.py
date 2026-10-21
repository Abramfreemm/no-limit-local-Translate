"""输出层：Markdown / 纯文本（后续补 PDF 回填、DOCX、PPTX、XLSX）。"""

from .markdown import render_markdown, render_pages, write_markdown
from .text import render_text, write_text

__all__ = ["render_markdown", "render_pages", "write_markdown", "render_text", "write_text"]
