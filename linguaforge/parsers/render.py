"""PDF 页面位图渲染（pypdfium2，BSD-3-Clause）。供 OCR 与预览使用。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pypdfium2 as pdfium


class PDFRenderer:
    """持有 PDF 句柄，按需渲染指定页。用完必须 close()。"""

    def __init__(self, path: str | Path, dpi: int = 200) -> None:
        self.dpi = dpi
        self._doc = pdfium.PdfDocument(str(path))

    @property
    def page_count(self) -> int:
        return len(self._doc)

    def render(self, index: int, dpi: Optional[int] = None) -> "Image.Image":  # noqa: F821
        from PIL import Image  # noqa: F401  (确保 Pillow 可用)

        d = dpi or self.dpi
        page = self._doc[index]
        bmp = page.render(scale=d / 72.0)
        return bmp.to_pil()

    def render_bytes(self, index: int, dpi: Optional[int] = None, fmt: str = "PNG") -> bytes:
        import io

        img = self.render(index, dpi)
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        return buf.getvalue()

    def close(self) -> None:
        try:
            self._doc.close()
        except Exception:
            pass

    def __enter__(self) -> "PDFRenderer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def render_pdf_page(path: str | Path, index: int, dpi: int = 200) -> "Image.Image":  # noqa: F821
    """一次性渲染单页（无句柄复用，适合临时调用）。"""
    with PDFRenderer(path, dpi) as r:
        return r.render(index, dpi)
