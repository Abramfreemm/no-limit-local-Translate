"""图片 -> DocIR 解析器（走现有 OCR 通道）。

把一张图片当作一个单页 Page：
- page.image_path = 图片绝对路径（供 OCR / 预览使用）；
- page.meta["need_ocr"] = True —— pipeline 正是靠这个标记触发 OCR（见 pipeline.run）；
- 不产出任何 Block，文本完全交给 OCR 引擎填充（ocr.fill_page）。

关键取舍：
1. 自身不做识别，避免与 OCR 模块职责重叠；只负责把「这是一张待识别的图」表达清楚。
2. 页面尺寸按图片 DPI 换算成 DocIR 的点（point = px * 72 / dpi），
   OCR 回填的 bbox 才能与后续渲染对齐；图片无 DPI 信息时按 96dpi。
3. 提供 load_image()，供集成方把位图交给 OCR，省去各自重复打开。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ..core.config import Config
from ..core.docir import DocIR, Page
from ..core.problems import DocumentParseError
from ..core.safeguards import guard_input

_DEFAULT_DPI = 96.0


class ImageParseError(DocumentParseError):
    """IMAGE 解析失败。

    ADR-016：原 6 个 ``*ParseError`` 除名字外完全一致却各自演化，
    现统一继承 :class:`~linguaforge.core.problems.DocumentParseError`，
    仅保留 ``fmt="image"`` 作为格式标签，上层可一次捕获。
    """

    def __init__(self, message: str = "", **kw) -> None:
        super().__init__(message, fmt="image", **kw)


class ImageParser:
    """解析 .png / .jpg / .jpeg / .tif / .tiff / .bmp / .webp。用法：

    with ImageParser(cfg) as p:
        p.open(path)
        for page in p.iter_pages():
            if page.meta.get("need_ocr"):
                img = load_image(page)
                ocr.fill_page(page, img, dpi)
    """

    extensions: set = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

    def __init__(self, cfg=None) -> None:
        self.cfg = cfg or Config()
        self.path: str = ""
        self._page_count: int = 1
        self._title: str = ""
        self._width_pt: float = 0.0
        self._height_pt: float = 0.0
        self._dpi: float = _DEFAULT_DPI
        self._px: tuple = (0, 0)

    # ---------------- 生命周期 ----------------
    def supports(self, path) -> bool:
        return Path(path).suffix.lower() in self.extensions

    def open(self, path) -> ImageParser:
        guard_input(path, "image")
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        if not self.supports(p):
            raise ImageParseError(
                f"ImageParser 不支持扩展名 {p.suffix or '(无)'}，仅支持 {sorted(self.extensions)}"
            )
        try:
            from PIL import Image

            with Image.open(str(p)) as im:
                self._px = (int(im.size[0]), int(im.size[1]))
                dpi = im.info.get("dpi") if isinstance(im.info, dict) else None
        except ImportError as e:
            raise ImageParseError(f"缺少 Pillow，无法读取图片：{e}") from e
        except Exception as e:
            raise ImageParseError(f"无法读取图片：{p.name}（文件损坏或格式不受支持）: {e}") from e
        if self._px[0] <= 0 or self._px[1] <= 0:
            raise ImageParseError(f"图片尺寸非法：{p.name} -> {self._px}")

        dpi_x = float(dpi[0]) if isinstance(dpi, (tuple, list)) and dpi and dpi[0] else _DEFAULT_DPI
        if dpi_x <= 0:
            dpi_x = _DEFAULT_DPI
        self._dpi = dpi_x
        self._width_pt = self._px[0] * 72.0 / dpi_x
        self._height_pt = self._px[1] * 72.0 / dpi_x
        self.path = str(p)
        self._page_count = 1
        self._title = p.stem
        return self

    def close(self) -> None:
        self._px = (0, 0)
        self._page_count = 1

    def __enter__(self) -> ImageParser:
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
    def dpi(self) -> float:
        """图片自身的 DPI（缺失时 96）。"""
        return self._dpi

    # ---------------- 逐页解析 ----------------
    def parse_page(self, index: int = 0) -> Page:
        if index != 0:
            raise IndexError(f"单张图片只有 1 页，越界: {index}")
        page = Page(index=0, width=self._width_pt, height=self._height_pt)
        page.image_path = self.path
        page.meta["need_ocr"] = True
        page.meta["source_format"] = Path(self.path).suffix.lower().lstrip(".")
        page.meta["image_size"] = [self._px[0], self._px[1]]
        page.meta["image_dpi"] = self._dpi
        page.meta["block_count"] = 0
        return page

    def iter_pages(self, start: int = 0, end: int | None = None) -> Iterator[Page]:
        stop = self._page_count if end is None else min(end, self._page_count)
        for i in range(max(0, start), stop):
            yield self.parse_page(i)

    def to_docir(self, max_pages: int | None = None) -> DocIR:
        doc = DocIR(source_path=self.path, source_format="image", title=self.title)
        for p in self.iter_pages(end=max_pages):
            doc.pages.append(p)
        return doc


def load_image(page: Page):
    """打开 Page 指向的图片并返回 PIL.Image（RGB）。

    供集成方在 OCR 前取位图：ocr.fill_page(page, load_image(page), dpi)。
    调用方负责关闭返回的对象。
    """
    if not page.image_path:
        raise ImageParseError("Page.image_path 为空，无法加载位图")
    try:
        from PIL import Image
    except ImportError as e:
        raise ImageParseError(f"缺少 Pillow，无法加载位图：{e}") from e
    try:
        im = Image.open(page.image_path)
    except OSError as e:
        raise ImageParseError(f"打开位图失败：{page.image_path}: {e}") from e
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    return im
