"""解析器包：把各种输入格式归一为 DocIR 的 Page 流。

统一契约：
    open(path) -> self; page_count; title; iter_pages(start, end) -> Iterator[Page]; close()
"""

from .docx_parser import DocxParser
from .html_parser import HtmlParser
from .image_parser import ImageParser
from .pdf_parser import PDFParser
from .pptx_parser import PptxParser
from .srt_parser import SrtParser
from .text_parser import TextParser
from .xlsx_parser import XlsxParser

__all__ = [
    "DocxParser",
    "HtmlParser",
    "ImageParser",
    "PDFParser",
    "PptxParser",
    "SrtParser",
    "TextParser",
    "XlsxParser",
]
