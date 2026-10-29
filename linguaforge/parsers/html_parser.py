"""HTML / Markdown -> DocIR 解析器。

用 BeautifulSoup 解析，按文档顺序产出 Block：
h1-h6 -> TITLE/HEADING（含层级）、p -> PARAGRAPH、li -> LIST_ITEM、
table -> TABLE_CELL（带 row/col/table_id）、pre -> CODE、caption -> CAPTION。

关键取舍：
1. 先 decompose 掉 script / style / noscript / template，避免样式与脚本混入译文。
2. 行内强调（strong/em/code）下沉为 Run 级 bold/italic，回填时能还原格式。
3. 首个 h1 视为文档标题（BlockType.TITLE），其余 h1 为 HEADING level=1，
   与 text_parser 的 Markdown 约定一致。
4. 也吃 .md / .markdown：内置一个极简 MD->HTML 转换（不引入 markdown 库，
   避免新增依赖），只覆盖翻译场景常见构造。
5. HTML 无版面概念，整篇为 1 页，bbox 置零。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from ..core.config import Config
from ..core.docir import Block, BlockState, BlockType, DocIR, Origin, Page, Run, Style
from ..core.problems import DocumentParseError

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "head"}
_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
# 表格行内只取直接单元格，避免嵌套表格被平铺
_CELL_TAGS = ("td", "th")
_ZERO_BBOX = (0.0, 0.0, 0.0, 0.0)


class HtmlParseError(DocumentParseError):
    """HTML 解析失败。

    ADR-016：原 6 个 ``*ParseError`` 除名字外完全一致却各自演化，
    现统一继承 :class:`~linguaforge.core.problems.DocumentParseError`，
    仅保留 ``fmt="html"`` 作为格式标签，上层可一次捕获。
    """

    def __init__(self, message: str = "", **kw) -> None:
        super().__init__(message, fmt="html", **kw)


class HtmlParser:
    """解析 .html / .htm / .xhtml / .md / .markdown。用法：

    with HtmlParser(cfg) as p:
        p.open(path)
        for page in p.iter_pages():
            ...
    """

    extensions: set = {".html", ".htm", ".xhtml", ".md", ".markdown"}

    def __init__(self, cfg=None) -> None:
        self.cfg = cfg or Config()
        self.path: str = ""
        self._soup: BeautifulSoup | None = None
        self._page_count: int = 1
        self._title: str = ""

    # ---------------- 生命周期 ----------------
    def supports(self, path) -> bool:
        return Path(path).suffix.lower() in self.extensions

    def open(self, path) -> HtmlParser:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        if not self.supports(p):
            raise HtmlParseError(
                f"HtmlParser 不支持扩展名 {p.suffix or '(无)'}，仅支持 {sorted(self.extensions)}"
            )
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise HtmlParseError(f"读取失败：{p.name}: {e}") from e
        if p.suffix.lower() in (".md", ".markdown"):
            raw = _md_to_html(raw)
        try:
            self._soup = _make_soup(raw)
        except Exception as e:
            raise HtmlParseError(f"HTML 解析失败：{p.name}: {e}") from e
        self.path = str(p)
        self._title = self._detect_title()
        return self

    def close(self) -> None:
        self._soup = None

    def __enter__(self) -> HtmlParser:
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

    # ---------------- 逐页解析 ----------------
    def _detect_title(self) -> str:
        assert self._soup is not None
        try:
            if self._soup.title and self._soup.title.string:
                t = self._soup.title.string.strip()
                if t:
                    return t[:200]
        except Exception:
            pass
        try:
            h1 = self._soup.find("h1")
            if h1 is not None:
                t = h1.get_text(" ", strip=True)
                if t:
                    return t[:200]
        except Exception:
            pass
        return Path(self.path).stem

    def parse_page(self, index: int = 0) -> Page:
        assert self._soup is not None, "parser not opened"
        if index != 0:
            raise IndexError(f"HTML 只有 1 页，越界: {index}")
        # 去掉噪音节点后再遍历
        for tag in list(self._soup.find_all(_SKIP_TAGS)):
            try:
                tag.decompose()
            except Exception:
                continue

        page = Page(index=0, width=595.0, height=842.0)
        page.meta["source_format"] = "html"
        root = self._soup.body if self._soup.body is not None else self._soup
        page.blocks = self._walk(root, 0)
        for i, b in enumerate(page.blocks):
            b.reading_order = i
        page.meta["block_count"] = len(page.blocks)
        return page

    def iter_pages(self, start: int = 0, end: int | None = None) -> Iterator[Page]:
        stop = self._page_count if end is None else min(end, self._page_count)
        for i in range(max(0, start), stop):
            yield self.parse_page(i)

    def to_docir(self, max_pages: int | None = None) -> DocIR:
        doc = DocIR(source_path=self.path, source_format="html", title=self.title)
        for p in self.iter_pages(end=max_pages):
            doc.pages.append(p)
        return doc

    # ---------------- 遍历 ----------------
    def _walk(self, node: Any, page_index: int) -> list[Block]:
        """深度优先按文档顺序收集块。

        容器（div/section/ul/...）若有直接文本则先出一个段落，再递归子节点；
        行内元素交给 _inline_runs 处理，不单独成块。
        """
        blocks: list[Block] = []
        title_done = False
        table_seq = 0

        def emit(btype: BlockType, text: str, runs: list[Run], level: int = 0, **meta: Any) -> None:
            nonlocal title_done
            text = text.strip()
            if not text:
                return
            style = Style(level=level)
            if runs:
                style.bold = any(r.bold for r in runs)
                style.italic = all(r.italic for r in runs) if runs else False
            b = Block(
                type=btype,
                bbox=_ZERO_BBOX,
                text=text,
                runs=runs,
                style=style,
                page_index=page_index,
                reading_order=len(blocks),
                origin=Origin.TEXT_LAYER,
                confidence=1.0,
            )
            if meta:
                b.meta.update(meta)
            if btype is BlockType.HEADING and level == 1 and not title_done:
                # 首个一级标题视为文档标题，与 Markdown 约定一致
                b.type = BlockType.TITLE
                title_done = True
            b.state = BlockState.EXTRACTED if b.is_translatable else BlockState.SKIPPED
            blocks.append(b)

        def rec(el: Any) -> None:
            for child in list(el.children):
                if isinstance(child, NavigableString):
                    continue
                if not isinstance(child, Tag):
                    continue
                name = (child.name or "").lower()
                if name in _SKIP_TAGS:
                    continue
                if name in _HEADING_TAGS:
                    level = _HEADING_TAGS[name]
                    runs = _inline_runs(child, stop={"ul", "ol", "table"})
                    emit(BlockType.HEADING, _text_of(runs), runs, level)
                    continue
                if name == "p":
                    runs = _inline_runs(child, stop={"ul", "ol", "table", "p", "div"})
                    emit(BlockType.PARAGRAPH, _text_of(runs), runs)
                    continue
                if name == "li":
                    runs = _inline_runs(child, stop={"ul", "ol", "table", "li"})
                    emit(BlockType.LIST_ITEM, _text_of(runs), runs)
                    continue
                if name == "pre":
                    text = child.get_text()
                    emit(BlockType.CODE, text, [Run(text=text.strip(), font="monospace")])
                    continue
                if name == "table":
                    nonlocal table_seq
                    tid = f"t{table_seq}"
                    table_seq += 1
                    for b in _table_blocks(child, page_index, tid):
                        b.reading_order = len(blocks)
                        blocks.append(b)
                    continue
                if name in ("caption", "figcaption"):
                    runs = _inline_runs(child)
                    emit(BlockType.CAPTION, _text_of(runs), runs)
                    continue
                if name in ("td", "th", "tr"):
                    continue  # 游离单元格/行：只可能出现在表格内，已由 _table_blocks 处理
                if name == "br":
                    continue
                # 其他容器：直接文本先成段，再递归
                direct = _direct_text(child)
                if direct:
                    emit(BlockType.PARAGRAPH, direct, [Run(text=direct)])
                rec(child)

        rec(node)
        return blocks


# ---------------- 模块级工具 ----------------
def _make_soup(raw: str) -> BeautifulSoup:
    """优先 lxml（快且容错好），不可用时回退标准库 html.parser。"""
    last: Exception | None = None
    for parser in ("lxml", "html.parser"):
        try:
            return BeautifulSoup(raw, parser)
        except Exception as e:  # FeatureNotFound 等
            last = e
    raise HtmlParseError(f"没有可用的 HTML 解析器: {last}")


def _direct_text(el: Tag) -> str:
    """容器的直接文本（不含子元素的文本）。"""
    parts: list[str] = []
    for child in el.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _inline_runs(el: Tag, stop: set | None = None) -> list[Run]:
    """把元素内的行内文本切成 Run，保留 strong/em/code 带来的 bold/italic。"""
    stop = stop or set()
    out: list[Run] = []

    def rec(node: Any, bold: bool, italic: bool, mono: bool) -> None:
        if isinstance(node, NavigableString):
            t = str(node)
            if not t:
                return
            out.append(Run(text=t, bold=bold, italic=italic, font="monospace" if mono else ""))
            return
        if not isinstance(node, Tag):
            return
        name = (node.name or "").lower()
        if name in _SKIP_TAGS or name in stop:
            return
        if name == "br":
            out.append(Run(text="\n", bold=bold, italic=italic))
            return
        nb, ni, nm = bold, italic, mono
        if name in ("b", "strong"):
            nb = True
        elif name in ("i", "em"):
            ni = True
        elif name in ("code", "kbd", "samp", "tt"):
            nm = True
        for ch in node.children:
            rec(ch, nb, ni, nm)

    for ch in el.children:
        rec(ch, False, False, False)
    return out


def _text_of(runs: list[Run]) -> str:
    """Run 序列 -> 块文本：折叠空白，保留换行。"""
    text = "".join(r.text for r in runs)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _table_blocks(table: Tag, page_index: int, table_id: str) -> list[Block]:
    """<table> -> TABLE_CELL 块列表（含 caption 与 th 标记）。"""
    out: list[Block] = []
    try:
        caption = table.find("caption")
        if caption is not None:
            text = caption.get_text(" ", strip=True)
            if text:
                b = Block(
                    type=BlockType.CAPTION,
                    text=text,
                    page_index=page_index,
                    table_id=table_id,
                    origin=Origin.TEXT_LAYER,
                    confidence=1.0,
                )
                b.state = BlockState.EXTRACTED if b.is_translatable else BlockState.SKIPPED
                out.append(b)
        rows = table.find_all("tr")
    except Exception:
        return out

    for r, tr in enumerate(rows):
        try:
            cells = tr.find_all(_CELL_TAGS, recursive=False)
        except Exception:
            continue
        for c, cell in enumerate(cells):
            runs = _inline_runs(cell, stop={"table"})
            text = _text_of(runs)
            if not text:
                continue
            is_th = (cell.name or "").lower() == "th"
            b = Block(
                type=BlockType.TABLE_CELL,
                text=text,
                runs=runs,
                style=Style(size=11.0, bold=is_th),
                page_index=page_index,
                reading_order=len(out),
                table_id=table_id,
                row=r,
                col=c,
                origin=Origin.TEXT_LAYER,
                confidence=1.0,
            )
            b.meta["header"] = is_th or r == 0
            try:
                rowspan = cell.get("rowspan")
                colspan = cell.get("colspan")
                if rowspan:
                    b.meta["rowspan"] = int(rowspan)
                if colspan:
                    b.meta["colspan"] = int(colspan)
            except (TypeError, ValueError):
                pass
            b.state = BlockState.EXTRACTED if b.is_translatable else BlockState.SKIPPED
            out.append(b)
    return out


# ---------------- Markdown -> HTML ----------------
def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline_md(s: str) -> str:
    """极简行内 Markdown：强调、行内代码、链接。先转义再还原标记，避免 XSS 式注入。"""
    s = _esc(s)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def _md_to_html(md: str) -> str:
    """Markdown -> HTML（仅覆盖常见构造）。

    支持：ATX 标题、无序/有序列表、围栏代码块、管道表格、引用、段落与行内标记。
    不做完整 CommonMark——项目不引入 markdown 依赖，且翻译场景只需块级结构。
    """
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    quote: list[str] = []
    list_tag = ""
    code_buf: list[str] = []
    in_code = False

    def flush_para() -> None:
        nonlocal para
        if para:
            out.append("<p>" + _inline_md(" ".join(para)) + "</p>")
            para = []

    def flush_quote() -> None:
        nonlocal quote
        if quote:
            out.append("<blockquote><p>" + _inline_md(" ".join(quote)) + "</p></blockquote>")
            quote = []

    def flush_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = ""

    def flush_all() -> None:
        flush_para()
        flush_quote()
        flush_list()

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].rstrip()
        s = line.strip()
        if s.startswith("```"):
            if in_code:
                out.append("<pre><code>" + _esc("\n".join(code_buf)) + "</code></pre>")
                code_buf = []
                in_code = False
            else:
                flush_all()
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(lines[i])
            i += 1
            continue
        if not s:
            flush_all()
            i += 1
            continue
        if s.startswith("|") and s.endswith("|"):
            flush_all()
            rows: list[list[str]] = []
            while i < n and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in cells if c):
                    rows.append(cells)
                i += 1
            if rows:
                out.append("<table>")
                for ri, cells in enumerate(rows):
                    out.append("<tr>")
                    for cell in cells:
                        tag = "th" if ri == 0 else "td"
                        out.append(f"<{tag}>{_inline_md(cell)}</{tag}>")
                    out.append("</tr>")
                out.append("</table>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            flush_all()
            lv = len(m.group(1))
            out.append(f"<h{lv}>{_inline_md(m.group(2).strip())}</h{lv}>")
            i += 1
            continue
        if re.match(r"^([-*_])\s*(\1\s*){2,}$", s):
            flush_all()
            out.append("<hr/>")
            i += 1
            continue
        if s.startswith(">"):
            flush_para()
            flush_list()
            quote.append(s.lstrip(">").strip())
            i += 1
            continue
        m = re.match(r"^[-*+]\s+(.*)$", s)
        if m:
            flush_para()
            flush_quote()
            if list_tag != "ul":
                flush_list()
                out.append("<ul>")
                list_tag = "ul"
            out.append(f"<li>{_inline_md(m.group(1).strip())}</li>")
            i += 1
            continue
        m = re.match(r"^\d+[.)]\s+(.*)$", s)
        if m:
            flush_para()
            flush_quote()
            if list_tag != "ol":
                flush_list()
                out.append("<ol>")
                list_tag = "ol"
            out.append(f"<li>{_inline_md(m.group(1).strip())}</li>")
            i += 1
            continue
        flush_quote()
        flush_list()
        para.append(s)
        i += 1

    if in_code and code_buf:
        out.append("<pre><code>" + _esc("\n".join(code_buf)) + "</code></pre>")
    flush_all()
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><title></title></head>'
        "<body>" + "\n".join(out) + "</body></html>"
    )
