"""PDF 保排回填 Writer（M2 技术难点）。

思路：
    原 PDF 页面做底层（矢量 / 图片 / 表格线 / 公式全部原样保留），
    reportlab 生成同尺寸透明 overlay：
        · 在原文块位置铺白底 —— 遮盖旧文字
        · 在同一位置按自适应字号重绘译文 —— 原位对齐
    两层 merge，得到"看起来就是原文档、只是字变了"的译文 PDF。

这样做的好处是**不需要还原版式**：图片、表格线、矢量图、背景色、页眉横线
一概不用处理，天然保真。相比"用 reportlab 重画整页"，代码量小一个数量级，
且不会出现元素丢失。

关键实现点：
    1. 坐标换算：DocIR 用左上原点 y 向下；PDF/canvas 用左下原点 y 向上
    2. 字号自适应：从原字号起步逐级缩小，直到文本放进原框（含自动换行）
    3. 字体：优先随包 Noto Sans SC，reportlab 自动子集化
    4. 流式分片：每 N 页落一个临时分片，最后合并 —— 内存与总页数无关
"""

from __future__ import annotations

import copy
import io
import re
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from ..core.docir import BlockType, Page
from ..core.fonts import ensure_body_font, ensure_bold_font

MIN_FONT = 4.0  # 小于这个字号人眼不可读，宁可溢出也不再缩
MAX_FONT = 26.0
LINE_GAP = 1.22
_BOLD_TYPES = (BlockType.TITLE, BlockType.HEADING)

# 文字绘制操作符。剥离原文时把它们从内容流里摘掉，
# 线条（l/m/re/S）、图片（Do）、裁剪（W n）等一概保留 —— 版式零损伤。
_TEXT_OPS = frozenset({b"Tj", b"TJ", b"'", b'"'})

# token 化：连续 ASCII 词不拆；其余逐字符，保证任何串都能断行
_TOKEN = re.compile(r"\s+|[A-Za-z0-9_\-./:=@?&%+#,;'\"]+|[^\s]")


def _tokenize(s: str) -> list[str]:
    return [m.group(0) for m in _TOKEN.finditer(s)]


def wrap_text(text: str, font: str, size: float, max_width: float) -> list[str]:
    """把文本按宽度换行。英文单词尽量不拆，中文逐字可断。"""
    if max_width <= 1:
        return [text]
    lines: list[str] = []
    for para in text.split("\n"):
        if not para.strip():
            continue
        cur = ""
        for tok in _tokenize(para):
            trial = cur + tok
            if cur and pdfmetrics.stringWidth(trial, font, size) > max_width:
                lines.append(cur.rstrip())
                cur = tok.lstrip() if tok.strip() else ""
            else:
                cur = trial
        if cur.strip():
            lines.append(cur.rstrip())
    return lines or [""]


def fit_text(
    text: str,
    font: str,
    start_size: float,
    max_w: float,
    max_h: float,
    min_size: float = MIN_FONT,
) -> tuple[float, list[str]]:
    """自适应字号：从 start_size 起逐步缩小，直到文本能装进 (max_w, max_h)。"""
    size = float(start_size or 9.0)
    if size <= 0 or size > MAX_FONT:
        size = 9.0 if size <= 0 else MAX_FONT
    # 单行的极端情况：字号上限不能超过框高，否则永远放不下
    size = min(size, max(min_size, max_h / 1.3))
    while size > min_size:
        lines = wrap_text(text, font, size, max_w)
        if len(lines) * size * LINE_GAP <= max_h:
            return size, lines
        size -= 0.25
    return min_size, wrap_text(text, font, min_size, max_w)


def _page_size(page_obj) -> tuple[float, float]:
    try:
        mb = page_obj.mediabox
        return float(mb.width), float(mb.height)
    except Exception:
        return 595.0, 842.0


def strip_page_text(page_obj, writer) -> int:
    """从页面内容流中摘除文字绘制操作符，返回被移除的操作符数量。

    这是比"铺白底遮盖"干净得多的做法：表格框线、底纹、图片、矢量图
    一概不受影响，且产出 PDF 复制出来就是纯译文（不会原文译文交错）。

    返回 0 表示这一页没能在主内容流里找到文字（文字可能藏在 Form XObject
    里、或是 Type3 字体 / 轮廓化文字），调用方应退回白底遮盖方案。
    """
    try:
        cs = ContentStream(page_obj.get_contents(), writer)
        ops = cs.operations
    except Exception:  # noqa: BLE001
        return 0
    kept = [(o, op) for o, op in ops if op not in _TEXT_OPS]
    removed = len(ops) - len(kept)
    if not removed:
        return 0
    try:
        cs.operations = kept
        page_obj.replace_contents(cs)
    except Exception:  # noqa: BLE001
        return 0
    return removed


def build_overlay(
    page: Page,
    width: float,
    height: float,
    *,
    body_font: str,
    bold_font: str | None = None,
    mask: bool = True,
    mask_pad: float = 0.6,
    default_size: float = 9.0,
) -> bytes:
    """为一页生成 overlay PDF 的字节内容。"""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))

    for b in page.blocks_sorted:
        if not b.bbox or all(v == 0 for v in b.bbox):
            continue  # 无坐标块不参与回填（图文_CACHE）
        if not b.translated and not b.text:
            continue
        text = (b.translated or b.text or "").strip()
        if not text:
            continue

        x0, top, x1, bottom = b.bbox
        box_w = max(1.0, x1 - x0)
        box_h = max(1.0, bottom - top)
        py_top = height - top  # 换算：左上原点 -> 左下原点
        py_bottom = height - bottom

        if mask:
            c.setFillColor(colors.white)
            c.setStrokeColor(colors.white)
            c.rect(
                x0 - mask_pad,
                py_bottom - mask_pad,
                box_w + mask_pad * 2,
                box_h + mask_pad * 2,
                stroke=0,
                fill=1,
            )

        want_bold = bool(getattr(b.style, "bold", False)) or b.type in _BOLD_TYPES
        font = body_font
        if want_bold and bold_font:
            font = bold_font

        base_size = getattr(b.style, "size", 0.0) or default_size
        size, lines = fit_text(text, font, base_size, box_w, box_h)

        fake_bold_dx = 0.0
        if want_bold and not bold_font:
            # reportlab 5.x 移除了 setTextRenderMode，改用微偏移双绘模拟加粗，
            # 不依赖任何内部 API，跨版本安全。
            fake_bold_dx = max(0.12, size * 0.015)
        c.setFillColor(colors.black)
        c.setFont(font, size)

        lh = size * LINE_GAP
        y = py_top - size * 1.02  # 首行基线留一点呼吸空间
        align = getattr(b.style, "align", "left") or "left"
        # fit_text 已保证总高不超框，这里只是极端情况的兜底：
        # 第一行必须无条件画（否则整块被吞），后续行才检查溢出。
        for i, ln in enumerate(lines):
            if not ln:
                y -= lh
                continue
            if i > 0 and y - size < py_bottom - lh * 0.5:
                break
            w = pdfmetrics.stringWidth(ln, font, size)
            if align == "center":
                x = x0 + (box_w - w) / 2
            elif align == "right":
                x = x1 - w
            else:
                x = x0
            c.drawString(x, y, ln)
            if fake_bold_dx:
                c.drawString(x + fake_bold_dx, y, ln)
            y -= lh

    c.showPage()
    c.save()
    return buf.getvalue()


class PDFRebuildWriter:
    """逐页回填 + 流式分片的 PDF 写出器。

    用法：
        w = PDFRebuildWriter(src, bilingual=True)
        for page in pages:            # 必须是顺序递增的 Page
            w.add_page(page)
        w.finalize(out_path)
    """

    def __init__(
        self,
        src: str | Path,
        *,
        bilingual: bool = False,
        body_font: str | None = None,
        bold_font: str | None = None,
        mask: bool = True,
        shard_pages: int = 150,
        tmp_dir: str | Path | None = None,
        log=None,
    ) -> None:
        self.src = Path(src)
        self.bilingual = bilingual
        self.mask = mask
        self.shard_pages = max(1, shard_pages)
        self.log = log or (lambda _m: None)
        self.reader = PdfReader(str(self.src))
        self.total_pages = len(self.reader.pages)
        self.body_font = body_font or ensure_body_font()
        self.bold_font = bold_font or ensure_bold_font()
        if not self.body_font:
            raise RuntimeError(
                "找不到可用的中文字体：请检查 resources/fonts/NotoSansSC.ttf，"
                "或安装任一系统 CJK 字体（如微软雅黑）。"
            )
        # 分片目录必须在**系统临时区**：源文件可能和用户选择的输出目录不同盘，
        # 若把分片写到源文件旁边，最后跨卷 rename 会直接失败（WinError 17）。
        self.tmp_dir = Path(tmp_dir) if tmp_dir else Path(tempfile.gettempdir()) / "lf_parts"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self._shards: list[Path] = []
        self._si = 0
        self._writer = PdfWriter()
        self._pending = 0
        self.pages_written = 0
        self.stripped_pages = 0  # 走"剥离原文"路径的页数（版式零损伤）
        self.masked_pages = 0  # 走"白底遮盖"兜底的页数

    # ---------------- 主流程 ----------------
    def add_page(self, page: Page) -> None:
        idx = int(page.index)
        if idx >= self.total_pages:
            self.log(f"[pdf] 第 {idx + 1} 页超出源文档页数，跳过")
            return
        try:
            src_obj = self.reader.pages[idx]
            w, h = _page_size(src_obj)
            if page.width and page.height:
                w, h = float(page.width), float(page.height)

            if self.bilingual:
                # 原页必须是**物理独立**的副本：pypdf 的 deepcopy 仍可能与
                # 后续工作页共享同一个内容流对象，导致原页文字被一起剥掉。
                # 走一次序列化往返，代价是每页一次内存写出，换来绝对隔离。
                bw = PdfWriter()
                bw.add_page(src_obj)
                buf = io.BytesIO()
                bw.write(buf)
                bw.close()
                buf.seek(0)
                self._writer.add_page(PdfReader(buf).pages[0])
                self._pending += 1

            # 关键：先把页面挂到 writer 上再改内容流，
            # 否则 pypdf 的 replace_contents 走的是不可靠的旧路径（且 7.0 会移除）。
            self._writer.add_page(src_obj)
            work = self._writer.pages[-1]
            removed = strip_page_text(work, self._writer) if self.mask else 0
            # 剥离成功 -> 不铺白底（版式零损伤）；
            # 剥离失败 -> 退回遮盖，否则原文译文会叠在一起。
            use_mask = self.mask and removed == 0
            if removed:
                self.stripped_pages += 1
            else:
                self.masked_pages += 1

            overlay_bytes = build_overlay(
                page,
                w,
                h,
                body_font=self.body_font,
                bold_font=self.bold_font,
                mask=use_mask,
            )
            overlay_obj = PdfReader(io.BytesIO(overlay_bytes)).pages[0]
            work.merge_page(overlay_obj)
            self._pending += 1
            self.pages_written += 1
        except Exception as e:  # noqa: BLE001
            self.log(f"[pdf] 第 {idx + 1} 页回填失败：{e}")
            try:
                self._writer.add_page(copy.deepcopy(self.reader.pages[idx]))
                self._pending += 1
            except Exception:
                pass
        finally:
            if self._pending >= self.shard_pages:
                self._flush_shard()

    def finalize(self, out_path: str | Path) -> str:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._flush_shard()
        if not self._shards:
            raise RuntimeError("没有任何页面被写入")
        try:
            if len(self._shards) == 1:
                # shutil.move 支持跨卷（内部退化为 copy + unlink），Path.replace 不支持
                shutil.move(str(self._shards[0]), str(out_path))
                self._shards = []
            else:
                merger = PdfWriter()
                for s in self._shards:
                    merger.append(str(s))
                merger.write(str(out_path))
                merger.close()
        finally:
            self.cleanup()
        return str(out_path)

    # ---------------- 内部 ----------------
    def _flush_shard(self) -> None:
        if self._pending == 0:
            return
        p = self.tmp_dir / f"part_{self._si:04d}.pdf"
        self._writer.write(str(p))
        self._writer.close()
        self._shards.append(p)
        self._si += 1
        self._pending = 0
        self._writer = PdfWriter()

    def cleanup(self) -> None:
        for s in self._shards:
            try:
                s.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            if self.tmp_dir.exists() and not list(self.tmp_dir.iterdir()):
                self.tmp_dir.rmdir()
        except Exception:
            pass
        try:
            self._writer.close()
        except Exception:
            pass


def rebuild_pdf(
    src: str | Path,
    pages: Sequence[Page],
    out_path: str | Path,
    *,
    bilingual: bool = False,
    mask: bool = True,
    log=None,
) -> str:
    """一次性回填（小文件友好）。大文件请用 PDFRebuildWriter 逐页 add_page。"""
    w = PDFRebuildWriter(src, bilingual=bilingual, mask=mask, log=log)
    for p in pages:
        w.add_page(p)
    return w.finalize(out_path)
