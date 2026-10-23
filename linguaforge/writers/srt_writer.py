"""DocIR -> SRT / VTT 字幕输出。

时间轴取自 block.meta["start"] / ["end"]（单位：秒，float，由 srt_parser 写入）。

接口：
    render_pages(state, pages, total, bilingual) -> str
        真正的流式输出：直接返回本窗口的字幕文本片段，可逐窗口追加写盘。
    write_all(pages, out_path, *, bilingual, title) -> str

关键取舍：
1. SRT 毫秒分隔符是逗号，VTT 是点号（HH:MM:SS.mmm），格式由输出扩展名自动判定
   （.vtt -> VTT，其余 -> SRT）。
2. 时间缺失或非法时（块不是字幕来源）不丢弃内容：按上一条结束时间顺延，
   时长 = max(2.0s, 字数 * 0.04s)，保证产出仍然是可播放的字幕。
3. 序号优先用 meta["index"]，缺失时用 state 里的自增序号跨窗口连续。
4. 双语模式：第一行译文、第二行原文（字幕两行显示是通行做法，不额外造时间轴）。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from ..core.docir import Page

_RE_SINGLE_TS = re.compile(r"^(?:(\d{1,3}):)?(\d{1,2}):(\d{1,2})[,.](\d{1,3})$")
_DEFAULT_DURATION = 2.0
_CHAR_SEC = 0.04


def render_pages(
    state: dict,
    pages: Sequence[Page],
    total: int = 0,
    bilingual: bool = False,
) -> str:
    """渲染一个窗口的字幕文本片段。

    state 约定：
        state["fmt"]         : "srt" | "vtt"
        state["index"]       : 下一条字幕序号（跨窗口连续）
        state["cursor"]      : 上一条的结束时间（秒），用于补缺失时间轴
        state["header_done"] : VTT 头是否已输出
        state["title"]       : 可选标题（写入 VTT 头）
    """
    fmt = "vtt" if str(state.get("fmt", "srt")).lower() == "vtt" else "srt"
    state["fmt"] = fmt
    state["total"] = total
    index = int(state.get("index", 1) or 1)
    cursor = float(state.get("cursor", 0.0) or 0.0)

    out: list[str] = []
    if fmt == "vtt" and not state.get("header_done"):
        title = str(state.get("title", "") or "").strip()
        out.append(f"WEBVTT - {title}" if title else "WEBVTT")
        out.append("")
        state["header_done"] = True

    for page in pages:
        for b in page.blocks_sorted:
            text = (b.out_text or "").strip()
            if not text:
                continue
            if bilingual and b.translated.strip() and b.text.strip():
                text = f"{b.translated.strip()}\n{b.text.strip()}"

            start = _to_seconds(b.meta.get("start"))
            end = _to_seconds(b.meta.get("end"))
            if start is None:
                start = cursor
            if end is None or end <= start:
                end = start + max(_DEFAULT_DURATION, len(text) * _CHAR_SEC)
            cursor = max(cursor, end)

            idx = b.meta.get("index")
            try:
                num = int(idx) if idx is not None else index
            except (TypeError, ValueError):
                num = index
            if num <= 0:
                num = index

            out.append(str(num))
            out.append(f"{fmt_ts(start, fmt)} --> {fmt_ts(end, fmt)}")
            out.append(text)
            out.append("")
            index = num + 1

    state["index"] = index
    state["cursor"] = cursor
    text = "\n".join(out)
    # 调用方预先放入 state["buffer"]="" 即启用累积，之后可用 finalize() 一次落盘
    if "buffer" in state:
        state["buffer"] = f"{state['buffer']}{text}"
    return text


def finalize(state: dict, out_path) -> str:
    """字幕没有需要收尾的对象，此函数与其他 Writer 保持接口一致。

    两种用法：
      1) 流式：直接把 render_pages 的返回值追加写盘（推荐，不占额外内存）；
      2) 累积：调用前 state["buffer"] = ""，render_pages 会累积片段，最后 finalize 落盘。
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = str(state.get("buffer", "") or "")
    fmt = "vtt" if out.suffix.lower() == ".vtt" else "srt"
    if fmt == "vtt" and not text.startswith("WEBVTT"):
        text = "WEBVTT\n\n" + text
    out.write_text(text.rstrip() + "\n", encoding="utf-8")
    return str(out)


def write_all(
    pages: Sequence[Page],
    out_path,
    *,
    bilingual: bool = False,
    title: str = "",
) -> str:
    """一次性写出完整 SRT / VTT，返回输出路径字符串。"""
    p = Path(out_path)
    fmt = "vtt" if p.suffix.lower() == ".vtt" else "srt"
    state = {
        "fmt": fmt,
        "index": 1,
        "cursor": 0.0,
        "header_done": False,
        "title": title,
    }
    text = render_pages(state, pages, len(pages), bilingual)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.rstrip() + "\n", encoding="utf-8")
    return str(p)


# ---------------- 内部实现 ----------------
def fmt_ts(seconds: float, fmt: str = "srt") -> str:
    """秒 -> 时间戳文本。SRT 用逗号毫秒，VTT 用点号毫秒。"""
    try:
        sec = float(seconds)
    except (TypeError, ValueError):
        sec = 0.0
    if sec < 0:
        sec = 0.0
    total_ms = int(round(sec * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    sep = "," if fmt == "srt" else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{ms:03d}"


def _to_seconds(value: object) -> float | None:
    """把 meta 里的时间转成秒。支持 float/int、数字字符串与 HH:MM:SS[,mmm]。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if v >= 0 else None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            v = float(s)
            return v if v >= 0 else None
        except ValueError:
            pass
        m = _RE_SINGLE_TS.match(s)
        if not m:
            return None
        try:
            hours = int(m.group(1)) if m.group(1) else 0
            minutes = int(m.group(2))
            secs = int(m.group(3))
            milli = int(m.group(4)) * (10 ** (3 - len(m.group(4))))
        except (TypeError, ValueError):
            return None
        return float(hours * 3600 + minutes * 60 + secs) + milli / 1000.0
    return None
