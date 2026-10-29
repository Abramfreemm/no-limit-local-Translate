"""SRT / VTT 字幕 -> DocIR 解析器。

用正则解析时间轴，把起止秒数写入 block.meta["start"] / ["end"]，序号写入 meta["index"]。

关键取舍：
1. 同时吃 SRT（00:00:01,000）与 VTT（00:00:01.000）两种时间戳写法；
   VTT 的 cue settings（-->\u200e 之后的一串定位参数）不影响解析，直接忽略。
2. 宽容解析：允许 1~3 位毫秒、允许省略小时、允许序号行缺失或为 VTT 的 cue id；
   序号缺失时按出现顺序补号。
3. 字幕没有版面概念，整篇为 1 个 Page，每条字幕 = 1 个 Block（type=PARAGRAPH），
   文本保留原有换行（一行字幕常被拆成两行显示）。
4. 时间统一为 float 秒，供 srt_writer 还原时格式化。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from ..core.config import Config
from ..core.docir import Block, BlockState, BlockType, DocIR, Origin, Page, Style
from ..core.problems import DocumentParseError

# 时:分:秒,毫秒 --> 时:分:秒,毫秒（小时可省略，分隔符 , 或 . 均可）
_RE_TS = re.compile(
    r"(?:(\d{1,3}):)?(\d{1,2}):(\d{1,2})[,.](\d{1,3})"
    r"\s*-->\s*"
    r"(?:(\d{1,3}):)?(\d{1,2}):(\d{1,2})[,.](\d{1,3})"
)
_RE_INT = re.compile(r"^\d+$")


class SrtParseError(DocumentParseError):
    """SRT 解析失败。

    ADR-016：原 6 个 ``*ParseError`` 除名字外完全一致却各自演化，
    现统一继承 :class:`~linguaforge.core.problems.DocumentParseError`，
    仅保留 ``fmt="srt"`` 作为格式标签，上层可一次捕获。
    """

    def __init__(self, message: str = "", **kw) -> None:
        super().__init__(message, fmt="srt", **kw)


class SrtParser:
    """解析 .srt / .vtt。用法：

    with SrtParser(cfg) as p:
        p.open(path)
        for page in p.iter_pages():
            ...
    """

    extensions: set = {".srt", ".vtt"}

    def __init__(self, cfg=None) -> None:
        self.cfg = cfg or Config()
        self.path: str = ""
        self._cues: list[dict] = []
        self._page_count: int = 1
        self._title: str = ""
        self._fmt: str = "srt"

    # ---------------- 生命周期 ----------------
    def supports(self, path) -> bool:
        return Path(path).suffix.lower() in self.extensions

    def open(self, path) -> SrtParser:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        if not self.supports(p):
            raise SrtParseError(f"SrtParser 不支持扩展名 {p.suffix or '(无)'}，仅支持 .srt / .vtt")
        try:
            raw = p.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as e:
            raise SrtParseError(f"读取失败：{p.name}: {e}") from e
        self.path = str(p)
        self._fmt = "vtt" if p.suffix.lower() == ".vtt" else "srt"
        try:
            self._cues = parse_cues(raw)
        except Exception as e:
            raise SrtParseError(f"字幕解析失败：{p.name}: {e}") from e
        if not self._cues:
            raise SrtParseError(f"未在 {p.name} 中找到任何字幕时间轴（文件为空或不是 SRT/VTT）")
        self._title = p.stem
        return self

    def close(self) -> None:
        self._cues = []
        self._page_count = 1

    def __enter__(self) -> SrtParser:
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
    def cue_count(self) -> int:
        return len(self._cues)

    @property
    def format(self) -> str:
        """srt / vtt。"""
        return self._fmt

    # ---------------- 逐页解析 ----------------
    def parse_page(self, index: int = 0) -> Page:
        if index != 0:
            raise IndexError(f"字幕只有 1 页，越界: {index}")
        page = Page(index=0, width=0.0, height=0.0)
        page.meta["source_format"] = self._fmt
        page.meta["cue_count"] = len(self._cues)
        for i, cue in enumerate(self._cues):
            text = cue["text"]
            b = Block(
                type=BlockType.PARAGRAPH,
                text=text,
                style=Style(size=14.0),
                page_index=0,
                reading_order=i,
                origin=Origin.TEXT_LAYER,
                confidence=1.0,
            )
            b.meta["index"] = cue["index"]
            b.meta["start"] = cue["start"]
            b.meta["end"] = cue["end"]
            b.meta["cue_settings"] = cue.get("settings", "")
            b.state = BlockState.EXTRACTED if b.is_translatable else BlockState.SKIPPED
            page.blocks.append(b)
        return page

    def iter_pages(self, start: int = 0, end: int | None = None) -> Iterator[Page]:
        stop = self._page_count if end is None else min(end, self._page_count)
        for i in range(max(0, start), stop):
            yield self.parse_page(i)

    def to_docir(self, max_pages: int | None = None) -> DocIR:
        doc = DocIR(source_path=self.path, source_format=self._fmt, title=self.title)
        for p in self.iter_pages(end=max_pages):
            doc.pages.append(p)
        return doc


# ---------------- 模块级工具 ----------------
def parse_cues(raw: str) -> list[dict]:
    """把 SRT/VTT 文本解析为 [{index,start,end,text,settings}]。

    容错点：序号行可缺失、可为 VTT cue id、可带 BOM；空行分隔；
    时间戳行之后到下一个空行之间的所有行都是该条字幕的正文。
    """
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues: list[dict] = []
    n = len(lines)
    i = 0
    pending_id: str | None = None
    auto_index = 0

    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        upper = line.upper()
        if upper.startswith("WEBVTT") or upper.startswith("STYLE") or upper.startswith("REGION"):
            pending_id = None
            i += 1
            continue
        if upper == "NOTE" or upper.startswith("NOTE "):
            # VTT 注释块：跳到下一个空行
            i += 1
            while i < n and lines[i].strip():
                i += 1
            continue

        m = _RE_TS.search(line)
        if m:
            start = _hhmmss(m.group(1), m.group(2), m.group(3), m.group(4))
            end = _hhmmss(m.group(5), m.group(6), m.group(7), m.group(8))
            settings = line[m.end() :].strip()
            idx: int | None = None
            if pending_id is not None and _RE_INT.match(pending_id.strip()):
                idx = int(pending_id.strip())
            pending_id = None
            i += 1
            buf: list[str] = []
            while i < n and lines[i].strip():
                buf.append(lines[i].rstrip())
                i += 1
            text = "\n".join(buf).strip()
            if not text:
                continue
            auto_index += 1
            cues.append(
                {
                    "index": idx if idx is not None else auto_index,
                    "start": start,
                    "end": end,
                    "text": text,
                    "settings": settings,
                }
            )
            continue

        # 非时间戳行：作为下一条的候选序号 / cue id
        pending_id = line
        i += 1

    return cues


def _hhmmss(h: str | None, m: str, s: str, ms: str) -> float:
    """时间分量 -> 秒（float）。毫秒位数不足 3 位时按小数位补齐。"""
    try:
        hours = int(h) if h else 0
        minutes = int(m)
        seconds = int(s)
        milli = int(ms) * (10 ** (3 - len(ms)))
    except (TypeError, ValueError):
        return 0.0
    return float(hours * 3600 + minutes * 60 + seconds) + milli / 1000.0


def split_timestamp(text: str) -> tuple[float, float] | None:
    """从单行时间戳文本解析 (start, end) 秒。供外部复用。"""
    m = _RE_TS.search(text or "")
    if not m:
        return None
    return (
        _hhmmss(m.group(1), m.group(2), m.group(3), m.group(4)),
        _hhmmss(m.group(5), m.group(6), m.group(7), m.group(8)),
    )
