"""PDF -> DocIR 解析器（流式，逐页产出，不整篇入内存）。

链路：pdfplumber 取字符级坐标 -> 词 -> 行聚类 -> 段落合并 -> 块类型推断
表格单独走 pdfplumber 的 find_tables，表格区域内文本不再重复进正文块。
页眉/页脚用采样指纹法识别（只存少量字符串，内存恒定）。
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

import pdfplumber
from pypdf import PdfReader

from ..core.config import Config
from ..core.docir import Block, BlockState, BlockType, DocIR, Origin, Page, Run, Style

# 行首有序/无序列表标记
_RE_LIST = re.compile(
    r"^\s*(?:"
    r"(?:\(?\d+(?:\.\d+)*[.)、])"          # 1. / 1.2) / 3、
    r"|(?:[a-zA-Z][.)])"                    # a. / A)
    r"|(?:[ivxIVX]+[.)])"                   # i. / IV)
    r"|[•·▪◦‣*-–—]\s+"                      # 项目符号
    r"|(?:第\s*[0-9一二三四五六七八九十]+\s*[章节条])"  # 第3章
    r")"
)
# 段末标点（用于判断是否另起新段）
_RE_SENT_END = re.compile(r"[.!?。！？:：;；]\s*[\"'”’)\]]*\s*$")
_CJK = re.compile(r"[\u3000-\u303f\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")

_RE_PAGE_NO_PATTERNS = [
    re.compile(r"^[\s\-–—.]*\d{1,4}[\s\-–—./|]*\d{0,4}[\s]*$"),
    re.compile(
        r"^(?i:page|pg\.?|p\.|seite|p[aá]gina|стр\.?)\s*\d{1,4}"
        r"(?:\s*(?:/|of|von|de|из)\s*\d{1,4})?$"
    ),
    re.compile(r"^第\s*\d{1,4}\s*页(?:\s*/?\s*共\s*\d{1,4}\s*页)?$"),
    re.compile(r"^-\s*\d{1,4}\s*-$"),
]


def _is_page_number(t: str) -> bool:
    s = t.strip()
    if not s or len(s) > 24:
        return False
    return any(p.match(s) for p in _RE_PAGE_NO_PATTERNS)


def _heading_level_of(size: float, body: float) -> int:
    """按字号相对正文的倍数推出标题层级（0 表示非标题）。"""
    if body <= 0 or size <= 0:
        return 0
    r = size / body
    if r >= 1.55:
        return 1
    if r >= 1.3:
        return 2
    if r >= 1.12:
        return 3
    return 0



def chars_to_words(chars: Sequence[dict]) -> List[dict]:
    """从字符级对象聚合成词。

    不用 page.extract_words()：它在不带 extra_attrs 时返回的 size/fontname 为 None，
    会让字号推断整体退化。直接从 chars 聚类，属性完全可控。
    """
    if not chars:
        return []
    cs = sorted(chars, key=lambda c: (round(float(c.get("top", 0)), 1), float(c.get("x0", 0))))

    # 1) 按 top 分到各文本行
    rows: List[List[dict]] = []
    cur_row: List[dict] = [cs[0]]
    cur_top = float(cs[0].get("top", 0))
    for c in cs[1:]:
        top = float(c.get("top", 0))
        tol = max(2.0, float(c.get("size", 10.0)) * 0.45)
        if abs(top - cur_top) <= tol:
            cur_row.append(c)
            cur_top = min(cur_top, top)
        else:
            rows.append(cur_row)
            cur_row, cur_top = [c], top
    rows.append(cur_row)

    # 2) 行内按水平间距切词
    words: List[dict] = []
    for row in rows:
        row.sort(key=lambda c: float(c.get("x0", 0)))
        buf: List[dict] = []
        for c in row:
            t = str(c.get("text", ""))
            if t.isspace() or t == "":
                if buf:
                    words.append(_mk_word(buf))
                    buf = []
                continue
            if buf:
                prev = buf[-1]
                gap = float(c.get("x0", 0)) - float(prev.get("x1", 0))
                sz = float(c.get("size", 10.0)) or 10.0
                if gap > sz * 0.22:
                    words.append(_mk_word(buf))
                    buf = []
            buf.append(c)
        if buf:
            words.append(_mk_word(buf))
    return words


def _mk_word(chars: List[dict]) -> dict:
    size = Counter(round(float(c.get("size", 10.0)), 1) for c in chars).most_common(1)[0][0]
    font = Counter(str(c.get("fontname", "")) for c in chars).most_common(1)[0][0]
    return {
        "text": "".join(str(c.get("text", "")) for c in chars),
        "x0": min(float(c.get("x0", 0)) for c in chars),
        "x1": max(float(c.get("x1", 0)) for c in chars),
        "top": min(float(c.get("top", 0)) for c in chars),
        "bottom": max(float(c.get("bottom", 0)) for c in chars),
        "size": size,
        "fontname": font,
        "upright": all(bool(c.get("upright", True)) for c in chars),
    }


class PDFParser:
    """逐页解析 PDF。用法：

        with PDFParser(cfg) as p:
            p.open(path)
            for page in p.iter_pages():
                ...
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        self.cfg = config or Config()
        self._pdf: Optional[pdfplumber.PDF] = None
        self._reader: Optional[PdfReader] = None
        self.path: str = ""
        self.page_count: int = 0
        self._header_fp: Set[str] = set()
        self._footer_fp: Set[str] = set()
        self._body_size: float = 10.0
        self._title: str = ""

    # ---------------- 生命周期 ----------------
    def open(self, path: str | Path) -> "PDFParser":
        self.path = str(path)
        self._pdf = pdfplumber.open(self.path)
        self.page_count = len(self._pdf.pages)
        try:
            self._reader = PdfReader(self.path)
        except Exception:
            self._reader = None
        self._sample_layout()
        return self

    def close(self) -> None:
        if self._pdf is not None:
            try:
                self._pdf.close()
            except Exception:
                pass
            self._pdf = None
        self._reader = None

    def __enter__(self) -> "PDFParser":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------------- 布局采样 ----------------
    def _sample_layout(self) -> None:
        """采样少数页面确定正文字号与页眉/页脚指纹。

        只采样 <=25 页，内存占用与总页数无关，保证超大文件安全。
        """
        if not self._pdf:
            return
        n = self.page_count
        idxs = set()
        step = max(1, n // 20)
        idxs.update(range(0, min(n, 20), max(1, step)))
        idxs.update(range(max(0, n - 5), n))
        idxs = {i for i in idxs if 0 <= i < n}

        sizes: Counter = Counter()
        head: Counter = Counter()
        foot: Counter = Counter()
        for i in sorted(idxs):
            try:
                page = self._pdf.pages[i]
                words = chars_to_words(page.chars)
                for w in words:
                    sizes[round(float(w.get("size", 10.0)), 1)] += 1
                lines = self._group_lines(words)
                if lines:
                    head[lines[0].text.strip()] += 1
                    foot[lines[-1].text.strip()] += 1
                page.flush_cache()  # 立即释放，控制内存
            except Exception:
                continue

        if sizes:
            self._body_size = sizes.most_common(1)[0][0]
        thr = max(2, int(len(idxs) * 0.5))
        self._header_fp = {t for t, c in head.items() if t and c >= thr and len(t) <= 120}
        self._footer_fp = {t for t, c in foot.items() if t and c >= thr and len(t) <= 120}

        # 标题：取元数据，否则取第 1 页最大字号行
        self._title = ""
        if self._reader is not None:
            try:
                self._title = (self._reader.metadata or {}).title or ""
            except Exception:
                pass
        if not self._title and self._pdf:
            try:
                words = chars_to_words(self._pdf.pages[0].chars)
                if words:
                    top = max(words, key=lambda w: (float(w.get("size", 0)), -float(w.get("top", 1e9))))
                    self._title = str(top.get("text", ""))
            except Exception:
                pass

    # ---------------- 逐页解析 ----------------
    def parse_page(self, index: int) -> Page:
        assert self._pdf is not None, "parser not opened"
        pl = self._pdf.pages[index]
        page = Page(
            index=index,
            width=float(pl.width or 595.0),
            height=float(pl.height or 842.0),
            rotation=int(getattr(pl, "rotation", 0) or 0),
        )
        try:
            words_all = chars_to_words(pl.chars)
        except Exception:
            words_all = []

        # 表格优先
        table_zones: List[Tuple[float, float, float, float]] = []
        try:
            for ti, tbl in enumerate(pl.find_tables() or []):
                bbox = tuple(tbl.bbox)  # type: ignore[assignment]
                table_zones.append(bbox)  # type: ignore[arg-type]
                tid = f"p{index}_t{ti}"
                for r, row in enumerate(tbl.extract() or []):
                    for c, cell in enumerate(row):
                        txt = (cell or "").strip()
                        if not txt:
                            continue
                        cb = self._cell_bbox(tbl, r, c, bbox)
                        page.blocks.append(
                            Block(
                                type=BlockType.TABLE_CELL,
                                bbox=cb,
                                text=txt,
                                style=Style(size=self._body_size),
                                state=BlockState.EXTRACTED,
                                page_index=index,
                                table_id=tid,
                                row=r,
                                col=c,
                                meta={"table_index": ti},
                            )
                        )
        except Exception:
            table_zones = []

        # 正文：排除表格区域
        words = [w for w in words_all if not self._in_zones(w, table_zones)]
        nchars = sum(len(str(w.get("text", ""))) for w in words)

        for b in self._build_blocks(words, index, page.height):
            page.blocks.append(b)

        self._renumber(page)
        page.meta["text_chars"] = nchars
        page.meta["need_ocr"] = nchars < self.cfg.ocr.min_text_chars
        pl.flush_cache()
        return page

    def iter_pages(self, start: int = 0, end: Optional[int] = None) -> Iterator[Page]:
        """流式产出页面。绝不一次性构造全部 Page。"""
        end = self.page_count if end is None else min(end, self.page_count)
        for i in range(start, end):
            yield self.parse_page(i)

    # ---------------- 块构建 ----------------
    def _build_blocks(self, words: Sequence[dict], pno: int, page_h: float) -> List[Block]:
        if not words:
            return []
        lines = self._group_lines(words)
        paras = self._merge_paragraphs(lines)
        blocks: List[Block] = []
        for pi, ln_group in enumerate(paras):
            text = self._join_lines(ln_group)
            if not text.strip():
                continue
            b = Block(page_index=pno, text=text)
            b.bbox = (
                min(l.bbox[0] for l in ln_group),
                min(l.bbox[1] for l in ln_group),
                max(l.bbox[2] for l in ln_group),
                max(l.bbox[3] for l in ln_group),
            )
            size = max(l.size for l in ln_group)
            bold = any(l.bold for l in ln_group)
            italic = all(l.italic for l in ln_group)
            font = Counter(l.font for l in ln_group).most_common(1)[0][0]
            b.runs = [Run(text=text, font=font, size=size, bold=bold, italic=italic)]
            b.style = Style(font=font, size=size, bold=bold, italic=italic)
            b.style.align = self._align_of(b.bbox, page_h if False else None)
            b.type = self._classify(text, size, bold, b.bbox, page_h, pno)
            b.style.level = _heading_level_of(size, self._body_size)
            b.state = BlockState.EXTRACTED if b.is_translatable else BlockState.SKIPPED
            b.origin = Origin.TEXT_LAYER
            b.confidence = 1.0
            b.reading_order = pi
            blocks.append(b)
        return blocks

    def _classify(self, text: str, size: float, bold: bool, bbox, page_h: float, pno: int = 0) -> BlockType:
        t = text.strip()
        # 页眉/页脚指纹命中
        if t in self._header_fp:
            return BlockType.HEADER
        if t in self._footer_fp:
            return BlockType.FOOTER
        # 页码（含 Page 3 / 第 3 页 / 3 / 12 等）
        if _is_page_number(t):
            return BlockType.PAGE_NUMBER
        rel_top = bbox[1] / page_h if page_h else 0.0
        rel_bottom = bbox[3] / page_h if page_h else 1.0
        # 版面边缘的短行：页脚 / 页眉（页码每页不同，指纹法抓不到，靠位置）
        if rel_bottom > 0.935 and len(t) <= 90 and size <= self._body_size * 1.2:
            return BlockType.FOOTER
        if rel_top < 0.055 and len(t) <= 120 and size <= self._body_size * 1.15:
            return BlockType.HEADER
        if size >= self._body_size * 1.55 and rel_top < 0.45:
            # 只有首屏的超大字号才算“文档标题”，其余是按章标题处理
            return BlockType.TITLE if pno == 0 else BlockType.HEADING
        if size >= self._body_size * 1.12 or (bold and size >= self._body_size):
            return BlockType.HEADING
        if _RE_LIST.match(t):
            return BlockType.LIST_ITEM
        return BlockType.PARAGRAPH

    @staticmethod
    def _align_of(bbox, _=None) -> str:
        return "left"

    # ---------------- 行 / 段 ----------------
    def _group_lines(self, words: Sequence[dict]) -> List["_Line"]:
        if not words:
            return []
        ws = sorted(words, key=lambda w: (round(float(w.get("top", 0)), 1), float(w.get("x0", 0))))
        lines: List[_Line] = []
        cur: List[dict] = [ws[0]]
        cur_top = float(ws[0].get("top", 0))
        for w in ws[1:]:
            top = float(w.get("top", 0))
            tol = max(2.0, float(w.get("size", 10.0)) * 0.45)
            if abs(top - cur_top) <= tol:
                cur.append(w)
                cur_top = min(cur_top, top)
            else:
                lines.append(_Line.from_words(cur))
                cur, cur_top = [w], top
        if cur:
            lines.append(_Line.from_words(cur))
        # 页内按视觉顺序（上到下）排序
        lines.sort(key=lambda l: (round(l.bbox[1], 1), l.bbox[0]))
        return lines

    def _merge_paragraphs(self, lines: List["_Line"]) -> List[List["_Line"]]:
        """把行合并为段落。

        断段依据（按可靠性排序）：
          1. 字号突变 -> 标题/正文边界；
          2. 行距过大 -> 空行分段；
          3. 上一行“短行”（右边界明显不到版心右边）且句末标点 -> 段末；
          4. 明显缩进或行首列表标记。
        """
        if not lines:
            return []
        # 版心右边线：只用正文字号的行来计算。
        # 若用全页最大 x1，会被大字号标题（往往更宽）抬高，导致正文满行被误判为“短行”，
        # 于是每个句号都断成一段。
        body_lines = [l for l in lines if abs(l.size - self._body_size) <= 1.2]
        base = body_lines or lines
        left = min(l.bbox[0] for l in base)
        right = max(l.bbox[2] for l in base)
        col_w = max(1.0, right - left)
        groups: List[List[_Line]] = [[lines[0]]]
        for prev, cur in zip(lines, lines[1:]):
            gap = cur.bbox[1] - prev.bbox[3]
            lh = max(prev.size, cur.size) * 1.2
            indent_delta = cur.bbox[0] - prev.bbox[0]
            hyphen = prev.text.rstrip().endswith(("-", "‐", "‑"))
            sent_end = bool(_RE_SENT_END.search(prev.text))
            short_line = (prev.bbox[2] - left) < col_w * 0.85
            new_para = False
            if gap > lh * 1.65:
                new_para = True
            elif abs(cur.size - prev.size) > max(prev.size, cur.size) * 0.14:
                # 字号突变 = 标题与正文的边界，必须断段
                new_para = True
            elif short_line and (sent_end or gap > lh * 0.25):
                # 上一行没写满 -> 段末（PDF 里最可靠的段落信号）
                new_para = True
            elif sent_end and indent_delta < -cur.size * 0.8:
                new_para = True
            elif indent_delta > cur.size * 1.4 and gap > lh * 0.3:
                new_para = True
            elif _RE_LIST.match(cur.text.strip()) and not _RE_LIST.match(prev.text.strip()):
                new_para = True
            if hyphen:
                new_para = False
            if new_para:
                groups.append([cur])
            else:
                groups[-1].append(cur)
        return groups

    @staticmethod
    def _join_lines(lines: List["_Line"]) -> str:
        """行合并为段落文本：英文补空格，CJK 直接拼接；处理换行连字符。"""
        out: List[str] = []
        for i, l in enumerate(lines):
            t = l.text.rstrip()
            if i < len(lines) - 1 and t.endswith(("-", "‐", "‑")):
                out.append(t[:-1])
                continue
            out.append(t)
            nxt = lines[i + 1].text.lstrip() if i + 1 < len(lines) else ""
            if nxt and not _CJK.match(t[-1:]) and not _CJK.match(nxt[:1]):
                out.append(" ")
        return re.sub(r"\s{2,}", " ", "".join(out)).strip()

    # ---------------- 工具 ----------------
    @staticmethod
    def _in_zones(w: dict, zones: Sequence[Tuple[float, float, float, float]]) -> bool:
        if not zones:
            return False
        cx = (float(w.get("x0", 0)) + float(w.get("x1", 0))) / 2
        cy = (float(w.get("top", 0)) + float(w.get("bottom", 0))) / 2
        for x0, top, x1, bot in zones:
            if x0 - 1 <= cx <= x1 + 1 and top - 1 <= cy <= bot + 1:
                return True
        return False

    @staticmethod
    def _cell_bbox(tbl, r: int, c: int, fallback) -> Tuple[float, float, float, float]:
        try:
            cell = tbl.rows[r].cells[c]
            if cell:
                return (float(cell[0]), float(cell[1]), float(cell[2]), float(cell[3]))
        except Exception:
            pass
        return tuple(fallback)  # type: ignore[return-value]

    @staticmethod
    def _renumber(page: Page) -> None:
        """按视觉阅读顺序重排：表格块跟随其所在位置。"""
        def key(b: Block):
            # 有 bbox 的列优先（双栏：先左后右），再按 y
            col_split = page.width * 0.5
            col = 0 if (b.bbox[0] + b.bbox[2]) / 2 < col_split else 1
            return (col, round(b.bbox[1] / 10), round(b.bbox[0] / 10))

        ordered = sorted(page.blocks, key=key)
        for i, b in enumerate(ordered):
            b.reading_order = i
        page.blocks = ordered

    def outline(self) -> List[Dict]:
        """书签（目录）"""
        if self._reader is None:
            return []
        try:
            return self._reader.outline or []
        except Exception:
            return []

    def to_docir(self, max_pages: Optional[int] = None) -> DocIR:
        """把整份文档读成 DocIR（仅用于小文件 / 单测；生产请走 iter_pages）。"""
        doc = DocIR(
            source_path=self.path,
            source_format="pdf",
            title=self._title or Path(self.path).stem,
        )
        for p in self.iter_pages(end=max_pages):
            doc.pages.append(p)
        return doc


class _Line:
    """内部行结构。"""

    __slots__ = ("text", "bbox", "size", "bold", "italic", "font", "type")

    def __init__(self, text: str, bbox, size: float, bold: bool, italic: bool, font: str) -> None:
        self.text = text
        self.bbox = bbox
        self.size = size
        self.bold = bold
        self.italic = italic
        self.font = font
        self.type: BlockType = BlockType.UNKNOWN

    @classmethod
    def from_words(cls, words: List[dict]) -> "_Line":
        ws = sorted(words, key=lambda w: float(w.get("x0", 0)))
        parts: List[str] = []
        for i, w in enumerate(ws):
            t = str(w.get("text", ""))
            if parts:
                prev = ws[i - 1]
                gap = float(w.get("x0", 0)) - float(prev.get("x1", 0))
                sz = float(w.get("size", 10.0)) or 10.0
                need_space = gap > sz * 0.22
                if need_space and not (_CJK.match(parts[-1][-1:]) or _CJK.match(t[:1])):
                    parts.append(" ")
            parts.append(t)
        text = re.sub(r"\s{2,}", " ", "".join(parts)).strip()
        size = Counter(round(float(w.get("size", 10.0)), 1) for w in ws).most_common(1)[0][0]
        fonts = Counter(str(w.get("fontname", "")) for w in ws)
        font = fonts.most_common(1)[0][0]
        bold = sum(1 for w in ws if _is_bold(str(w.get("fontname", "")))) > len(ws) / 2
        italic = sum(1 for w in ws if _is_italic(str(w.get("fontname", "")))) > len(ws) / 2
        bbox = (
            min(float(w.get("x0", 0)) for w in ws),
            min(float(w.get("top", 0)) for w in ws),
            max(float(w.get("x1", 0)) for w in ws),
            max(float(w.get("bottom", 0)) for w in ws),
        )
        return cls(text, bbox, size, bold, italic, font)


def _is_bold(fontname: str) -> bool:
    f = fontname.lower()
    return any(k in f for k in ("bold", "black", "heavy", "semibold", "-b", ",b"))


def _is_italic(fontname: str) -> bool:
    f = fontname.lower()
    return any(k in f for k in ("italic", "oblique", "-i", ",i"))
