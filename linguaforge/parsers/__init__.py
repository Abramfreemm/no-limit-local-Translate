"""解析器包：把各种输入格式归一为 DocIR 的 Page 流。"""

from .pdf_parser import PDFParser
from .text_parser import TextParser

__all__ = ["PDFParser", "TextParser"]
