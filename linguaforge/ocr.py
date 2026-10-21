"""OCR 引擎（RapidOCR / ONNXRuntime，纯 CPU，离线）。

设计：
  - 延迟导入：只有真的需要 OCR 时才加载 ONNX 模型（首次约 1-2s）；
  - 输入 PIL 位图，输出带 bbox 与置信度的文本行；
  - fill_page() 把识别结果写回 Page，坐标从像素换算回 PDF 点。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Tuple

from .core.config import Config
from .core.docir import Block, BlockState, BlockType, Origin, Page, Style

if TYPE_CHECKING:  # pragma: no cover
    from PIL import Image


class OCRError(RuntimeError):
    pass


class RapidOCREngine:
    """RapidOCR（ONNX）封装。"""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.cfg = config or Config()
        self._engine = None
        self._loaded = False

    # ---------- 加载 ----------
    def load(self) -> None:
        if self._loaded:
            return
        try:
            from rapidocr_onnxruntime import RapidOCR
        except Exception as e:  # noqa: BLE001
            raise OCRError(f"未安装 rapidocr-onnxruntime：{e}") from e
        self._engine = RapidOCR()
        self._loaded = True

    @property
    def available(self) -> bool:
        try:
            self.load()
            return True
        except Exception:  # noqa: BLE001
            return False

    # ---------- 识别 ----------
    def ocr_image(self, image: "Image.Image") -> List[Tuple[str, Tuple[float, float, float, float], float]]:
        """返回 [(text, bbox_px, confidence)]，bbox_px = (x0, y0, x1, y1)。"""
        self.load()
        if self._engine is None:
            return []
        # RapidOCR 接受路径 / ndarray；统一转 RGB ndarray，避免 PIL 兼容问题
        import numpy as np

        arr = np.array(image.convert("RGB"))
        try:
            result, _ = self._engine(arr)
        except Exception as e:  # noqa: BLE001
            raise OCRError(f"OCR 失败：{e}") from e
        out: List[Tuple[str, Tuple[float, float, float, float], float]] = []
        if not result:
            return out
        for item in result:
            try:
                box, text, score = item[0], item[1], float(item[2])
            except Exception:  # noqa: BLE001
                continue
            if not text or not str(text).strip():
                continue
            if score < self.cfg.ocr.min_confidence:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            out.append((str(text).strip(), (min(xs), min(ys), max(xs), max(ys)), score))
        return out

    # ---------- 回填 Page ----------
    def fill_page(self, page: Page, image: "Image.Image", dpi: Optional[int] = None) -> int:
        """用 OCR 结果重建 page.blocks。返回写入的块数。"""
        dpi = dpi or self.cfg.ocr.dpi
        scale = 72.0 / float(dpi)  # 像素 -> PDF point
        lines = self.ocr_image(image)
        if not lines:
            return 0

        # 按 y 排序后做行聚类（OCR 已分行，此处合并同一行的多个片段）
        lines.sort(key=lambda t: (round(t[1][1] / 8), t[1][0]))
        rows: List[List[Tuple[str, Tuple[float, float, float, float], float]]] = []
        for ln in lines:
            if not rows:
                rows.append([ln])
                continue
            prev_y = rows[-1][-1][1][1]
            cur_y = ln[1][1]
            h = max(8.0, rows[-1][-1][1][3] - rows[-1][-1][1][1])
            if abs(cur_y - prev_y) <= h * 0.6:
                rows[-1].append(ln)
            else:
                rows.append([ln])
        rows.sort(key=lambda r: (round(r[0][1][1] / 8), r[0][1][0]))

        blocks: List[Block] = []
        for i, row in enumerate(rows):
            row.sort(key=lambda t: t[1][0])
            texts: List[str] = []
            for j, (text, bbox, _score) in enumerate(row):
                if j and texts:
                    prev_right = row[j - 1][1][2]
                    gap = bbox[0] - prev_right
                    h = max(8.0, bbox[3] - bbox[1])
                    if gap > h * 0.35:
                        texts.append(" ")
                texts.append(text)
            txt = "".join(texts).strip()
            if not txt:
                continue
            bbox = (
                min(r[1][0] for r in row) * scale,
                min(r[1][1] for r in row) * scale,
                max(r[1][2] for r in row) * scale,
                max(r[1][3] for r in row) * scale,
            )
            conf = sum(r[2] for r in row) / len(row)
            size = max(6.0, (bbox[3] - bbox[1]) * 0.72)
            b = Block(
                page_index=page.index,
                text=txt,
                bbox=bbox,
                type=BlockType.PARAGRAPH,
                style=Style(size=size),
                origin=Origin.OCR,
                confidence=round(conf, 3),
                reading_order=i,
            )
            b.state = BlockState.EXTRACTED if b.is_translatable else BlockState.SKIPPED
            blocks.append(b)

        if not blocks:
            return 0
        # 已有文本层且字符较多时做混合：保留原块 + 追加 OCR 块
        if page.blocks and page.meta.get("text_chars", 0) >= self.cfg.ocr.min_text_chars:
            base_order = max(b.reading_order for b in page.blocks) + 1
            for k, b in enumerate(blocks):
                b.reading_order = base_order + k
                b.origin = Origin.HYBRID
            page.blocks.extend(blocks)
        else:
            page.blocks = blocks
        page.ocr_used = True
        return len(blocks)
