"""翻译流水线。

流式窗口设计（支撑「不限制页数与大小」）：
    解析一页 -> 需要则 OCR -> 进入窗口
    窗口达到 window_pages 页或 window_chars 字符 -> 翻译该窗口 -> 增量写盘 -> 清空窗口
因此内存占用与文档总页数无关，1000 页 / 500MB 也能跑完。

M2/M4 扩展：
    · 输入侧按扩展名自动分发到 PDF/DOCX/PPTX/XLSX/HTML/SRT/图片/TXT 解析器
    · 输出侧按 fmt 分发到 markdown/text/pdf/docx/pptx/xlsx/srt
      （PDF 输出走原位回填，逐页落盘，依然与总页数无关）
    · 接 SQLite：逐页落盘译文，中断后可续翻，已完成页不重翻

流水线层不 import 任何 Qt 模块，可无头运行。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from .core.config import Config
from .core.docir import Block, BlockState, BlockType, DocIR, Page
from .ocr import RapidOCREngine
from .parsers import PDFParser, TextParser
from .parsers.render import PDFRenderer
from .store import Store, stable_block_id
from .translate.ollama_client import OllamaClient
from .translate.translator import Glossary, TranslationMemory, TranslateStats, Translator
from .writers.markdown import render_pages as render_markdown_pages
from .writers.text import render_page_text

TEXT_EXT = {".txt", ".md", ".markdown"}

# 输出格式 -> 文件后缀
OUT_EXT = {
    "markdown": ".md",
    "text": ".txt",
    "txt": ".txt",
    "pdf": ".pdf",
    "docx": ".docx",
    "pptx": ".pptx",
    "xlsx": ".xlsx",
    "srt": ".srt",
    "vtt": ".vtt",
}

# 需要"收集完整文档再一次性落盘"的输出格式（内存随页数增长，见 _BinarySink 说明）
_BINARY_FMTS = {"docx", "pptx", "xlsx", "srt", "vtt"}


@dataclass
class PipelineResult:
    ok: bool = False
    source: str = ""
    output: str = ""
    fmt: str = "markdown"
    pages: int = 0
    blocks: int = 0
    translated: int = 0
    ocr_pages: int = 0
    reused: int = 0             # 续翻时从库里直接复用的已译块数
    elapsed_s: float = 0.0
    model: str = ""
    task_id: str = ""
    stats: Optional[TranslateStats] = None
    errors: List[str] = field(default_factory=list)

    def summary(self) -> str:
        s = self.stats
        tm = f"  TM命中={s.tm_hits}" if s and s.tm_hits else ""
        reuse = f"  续翻复用={self.reused}" if self.reused else ""
        return (
            f"完成: {self.output}\n"
            f"  页数={self.pages} 块数={self.blocks} 已译={self.translated} OCR页={self.ocr_pages}{reuse}\n"
            f"  耗时={self.elapsed_s:.1f}s 模型={self.model}{tm}\n"
            f"  错误={len(self.errors)}"
        )


ProgressCB = Optional[Callable[[str, int, int, str], None]]
CancelCB = Optional[Callable[[], bool]]


def file_sha256(path: str | Path, chunk: int = 1 << 20) -> str:
    """大文件也安全的哈希：分块读，不一次性载入内存。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def get_parser(path: str | Path, cfg: Config):
    """按扩展名挑选解析器。返回 (parser实例或None, 是否支持渲染OCR)。"""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return PDFParser(cfg), True
    if ext in TEXT_EXT:
        return TextParser(cfg), False
    if ext == ".md" or ext == ".markdown":
        # Markdown 交给 HTML 解析器能保住标题/列表/代码块结构
        try:
            from .parsers.html_parser import HtmlParser

            return HtmlParser(cfg), False
        except Exception:  # noqa: BLE001
            return TextParser(cfg), False
    try:
        if ext == ".docx":
            from .parsers.docx_parser import DocxParser

            return DocxParser(cfg), False
        if ext == ".pptx":
            from .parsers.pptx_parser import PptxParser

            return PptxParser(cfg), False
        if ext in {".xlsx", ".xlsm"}:
            from .parsers.xlsx_parser import XlsxParser

            return XlsxParser(cfg), False
        if ext in {".html", ".htm", ".xhtml"}:
            from .parsers.html_parser import HtmlParser

            return HtmlParser(cfg), False
        if ext in {".srt", ".vtt"}:
            from .parsers.srt_parser import SrtParser

            return SrtParser(cfg), False
        if ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
            from .parsers.image_parser import ImageParser

            return ImageParser(cfg), False
    except Exception:  # noqa: BLE001
        return None, False
    return None, False


SUPPORTED_IN = (
    {".pdf", ".docx", ".pptx", ".xlsx", ".xlsm", ".html", ".htm", ".xhtml",
     ".srt", ".vtt", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
    | TEXT_EXT
)


class _TextSink:
    """文本类输出（markdown / txt）：逐窗口追加写文件，内存恒定。"""

    def __init__(self, fh, fmt: str, bilingual: bool) -> None:
        self.fh = fh
        self.fmt = fmt
        self.bilingual = bilingual

    def add(self, window: Sequence[Page], total: int) -> None:
        if self.fmt == "markdown":
            frag = render_markdown_pages("", window, total, self.bilingual)
        else:
            frag = "\n".join(
                line for p in window for line in render_page_text(p, self.bilingual)
            )
        if frag.strip():
            self.fh.write(frag)
            if not frag.endswith("\n"):
                self.fh.write("\n")
            self.fh.write("\n")
            self.fh.flush()

    def write_raw(self, text: str) -> None:
        self.fh.write(text)
        self.fh.flush()

    def finalize(self, out_path) -> str:
        return str(out_path)


class _BinarySink:
    """办公/字幕类输出（docx / pptx / xlsx / srt）。

    这类格式的文件结构决定了必须"整体保存一次"，无法像文本那样增量追加，
    所以窗口内容会累积在内存里的 Document/Presentation/Workbook 上。
    代价：内存随正文量增长（与 PDF 的逐页流式不同）。
    对常见几十到几百页的办公文档完全够用；超大文件请优先选 markdown 输出。
    """

    def __init__(self, fmt: str, bilingual: bool, log: Callable[[str], None]) -> None:
        self.fmt = fmt
        self.bilingual = bilingual
        self.log = log
        # 字幕类 Writer 靠 state["buffer"] 判断是否启用累积模式，
        # 不预置的话 render_pages 的返回片段会全部丢掉，finalize 写出空文件。
        self.state: Dict[str, Any] = {
            "fmt": fmt,
            "index": 1,
            "cursor": 0.0,
            "header_done": False,
            "buffer": "",
        }
        self._mod = None
        import importlib

        name = "srt_writer" if fmt in {"srt", "vtt"} else f"{fmt}_writer"
        try:
            self._mod = importlib.import_module(f".writers.{name}", __package__)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"输出格式 {fmt} 不可用：{e}") from e

    def add(self, window: Sequence[Page], total: int) -> None:
        self._mod.render_pages(self.state, window, total, self.bilingual)

    def write_raw(self, text: str) -> None:
        # 二进制 sink 无法塞入裸文本，标题块由 render_pages 自行处理
        if text.strip():
            self.state.setdefault("_header", text)

    def finalize(self, out_path) -> str:
        return self._mod.finalize(self.state, out_path)


class _PDFSink:
    """PDF 输出：走原位回填，逐页落盘 + 分片合并，内存与总页数无关。"""

    def __init__(self, src: str | Path, bilingual: bool, log: Callable[[str], None]) -> None:
        from .writers.pdf_rebuild import PDFRebuildWriter

        self.w = PDFRebuildWriter(src, bilingual=bilingual, log=log)
        self.log = log

    def add(self, window: Sequence[Page], total: int) -> None:
        for p in window:
            self.w.add_page(p)

    def write_raw(self, text: str) -> None:
        pass

    def finalize(self, out_path) -> str:
        return self.w.finalize(out_path)


class Pipeline:
    """一次翻译任务。"""

    def __init__(
        self,
        cfg: Optional[Config] = None,
        ocr=None,
        translator: Optional[Translator] = None,
        log: Optional[Callable[[str], None]] = None,
        store: Optional[Store] = None,
    ) -> None:
        self.cfg = cfg or Config()
        self.log = log or (lambda _m: None)
        self._ocr = ocr
        self.translator = translator or Translator(self.cfg, log=self.log)
        self.glossary = self.translator.glossary
        self.tm = self.translator.tm
        self._store = store
        self._own_store = store is None

    # ---------------- 依赖 ----------------
    @property
    def ocr(self):
        if self._ocr is None and self.cfg.ocr.enabled:
            try:
                self._ocr = RapidOCREngine(self.cfg)
                if not self._ocr.available:
                    self._ocr = None
            except Exception as e:  # noqa: BLE001
                self.log(f"[ocr] 不可用：{e}")
                self._ocr = None
        return self._ocr

    @property
    def store(self) -> Optional[Store]:
        """懒开数据库连接。流水线不强制依赖存储，取不到就降级为不续翻。"""
        if self._store is None:
            try:
                self._store = Store()
            except Exception as e:  # noqa: BLE001
                self.log(f"[store] 不可用，本次不记录续翻进度：{e}")
                self._store = None
        return self._store

    def close(self) -> None:
        if self._own_store and self._store is not None:
            try:
                self._store.close()
            except Exception:  # noqa: BLE001
                pass
            self._store = None

    # ---------------- 主流程 ----------------
    def run(
        self,
        src: str | Path,
        out: Optional[str | Path] = None,
        fmt: Optional[str] = None,
        cancel: CancelCB = None,
        on_progress: ProgressCB = None,
        *,
        resume: bool = True,
        page_range: Optional[tuple] = None,
        store: Optional[Store] = None,
    ) -> PipelineResult:
        """执行翻译任务。

        :param resume: 为 True 时接 SQLite，中断后再跑同一文件可从断点继续
        :param page_range: (start, end) 页码范围（0-based，end 不含），用于抽样试翻
        :param store: 外部传入的 Store（UI 复用一个连接时用）
        """
        t0 = time.time()
        src = Path(src)
        if not src.exists():
            return PipelineResult(ok=False, source=str(src), errors=[f"文件不存在: {src}"])

        ext = src.suffix.lower()
        fmt = (fmt or self.cfg.output.fmt or "markdown").lower()
        if fmt == "txt":
            fmt = "text"
        if fmt not in OUT_EXT:
            return PipelineResult(ok=False, source=str(src), errors=[f"不支持的输出格式: {fmt}"])
        bilingual = self.cfg.output.bilingual
        if ext in TEXT_EXT and fmt == "markdown":
            fmt = "markdown"

        out_path = Path(out) if out else self._default_out(src, fmt)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        res = PipelineResult(source=str(src), output=str(out_path), fmt=fmt,
                             model=self.cfg.ollama.model)
        if store is not None:
            self._store = store
            self._own_store = False

        parser = None
        renderer = None
        try:
            parser, can_render = get_parser(src, self.cfg)
            if parser is None:
                return PipelineResult(
                    ok=False, source=str(src),
                    errors=[f"暂不支持的格式: {ext}（支持：{', '.join(sorted(SUPPORTED_IN))}）"],
                )
            parser.open(src)
            total = parser.page_count
            title = getattr(parser, "title", "") or src.stem
            if can_render and self.cfg.ocr.enabled:
                try:
                    renderer = PDFRenderer(src, self.cfg.ocr.dpi)
                except Exception as e:  # noqa: BLE001
                    self.log(f"[render] 初始化失败：{e}")
        except Exception as e:  # noqa: BLE001
            return PipelineResult(ok=False, source=str(src), errors=[f"打开失败: {e}"])

        # ---------------- 续翻准备 ----------------
        task_id = ""
        done_pages: set = set()
        st = self.store if resume else None
        if st is not None:
            try:
                sha = file_sha256(src)
                prev = st.find_task_by_source(sha, self.cfg.lang_dst)
                # 已完成（done）的任务同样可复用：同一文件再翻一次不该重新烧 token。
                # 换模型则视为"要更好的译文"，从头重翻。
                reusable = prev is not None and prev.get("status") in {
                    "running", "paused", "failed", "canceled", "done",
                }
                if reusable and prev.get("model") and prev["model"] != self.cfg.ollama.model:
                    self.log(
                        f"[resume] 模型已切换（{prev['model']} -> {self.cfg.ollama.model}），本次重新翻译"
                    )
                    reusable = False
                if reusable:
                    task_id = prev["id"]
                    done_pages = st.get_done_pages(task_id)
                    if done_pages:
                        self.log(f"[resume] 续翻任务 {task_id}，已完成 {len(done_pages)} 页")
                else:
                    task_id = st.create_task(
                        str(src), source_sha256=sha,
                        lang_dst=self.cfg.lang_dst, output_mode=fmt,
                        model=self.cfg.ollama.model,
                    )
                res.task_id = task_id
                st.set_status(task_id, "running")
            except Exception as e:  # noqa: BLE001
                self.log(f"[store] 续翻未启用：{e}")
                st = None

        sink = None
        fh = None
        try:
            # 页码范围
            p0 = int(page_range[0]) if page_range else 0
            p1 = int(page_range[1]) if page_range and page_range[1] else total

            # 输出目标
            if fmt == "pdf":
                if ext != ".pdf":
                    self.log("[out] PDF 输出仅支持 PDF 输入，已自动降级为 Markdown")
                    res.fmt = "markdown"
                    fmt = "markdown"
                    out_path = out_path.with_suffix(".md")
                    res.output = str(out_path)
                else:
                    sink = _PDFSink(src, bilingual, self.log)
            if sink is None:
                if fmt in _BINARY_FMTS:
                    sink = _BinarySink(fmt, bilingual, self.log)
                else:
                    fh = open(out_path, "w", encoding="utf-8")
                    sink = _TextSink(fh, fmt, bilingual)

            state = {"header_done": False}
            window: List[Page] = []
            window_chars = 0
            pages_done = 0

            for page in parser.iter_pages(p0, p1):
                if cancel and cancel():
                    res.errors.append("用户取消")
                    break
                try:
                    if renderer and page.meta.get("need_ocr") and self.cfg.ocr.enabled:
                        self._do_ocr(page, renderer)
                except Exception as e:  # noqa: BLE001
                    res.errors.append(f"p{page.index + 1} OCR 失败: {e}")

                window.append(page)
                window_chars += sum(len(b.text) for b in page.blocks)
                pages_done += 1
                res.blocks += len(page.blocks)
                if page.ocr_used:
                    res.ocr_pages += 1

                if on_progress:
                    on_progress("parse", pages_done, total, f"解析第 {pages_done}/{total} 页")

                if (len(window) >= self.cfg.perf.window_pages
                        or window_chars >= self.cfg.perf.window_chars):
                    self._flush(window, sink, fmt, bilingual, res, cancel, on_progress,
                                pages_done, total, title, state, st, task_id, done_pages)
                    window, window_chars = [], 0
                    if cancel and cancel():
                        res.errors.append("用户取消")
                        break

            if window:
                self._flush(window, sink, fmt, bilingual, res, cancel, on_progress,
                            pages_done, total, title, state, st, task_id, done_pages)

            if sink is not None:
                sink.finalize(out_path)

            res.pages = pages_done
            res.elapsed_s = time.time() - t0
            res.ok = not res.errors or res.translated > 0 or res.reused > 0
            if st is not None and task_id:
                try:
                    st.set_status(task_id, "done" if not res.errors else "failed")
                except Exception:  # noqa: BLE001
                    pass
            if on_progress:
                on_progress("done", pages_done, total, "完成")
        except Exception as e:  # noqa: BLE001
            res.errors.append(f"写出失败: {e}")
            res.ok = False
            if st is not None and task_id:
                try:
                    st.set_status(task_id, "failed", str(e))
                except Exception:  # noqa: BLE001
                    pass
        finally:
            if fh:
                fh.close()
            if renderer:
                renderer.close()
            if parser:
                parser.close()
        return res

    # ---------------- 窗口处理 ----------------
    def _flush(
        self,
        window: List[Page],
        sink,
        fmt: str,
        bilingual: bool,
        res: PipelineResult,
        cancel: CancelCB,
        on_progress: ProgressCB,
        pages_done: int,
        total: int,
        title: str = "",
        state: Optional[dict] = None,
        st: Optional[Store] = None,
        task_id: str = "",
        done_pages: Optional[set] = None,
    ) -> None:
        # 首次 flush 时补文档标题（正文自带标题块就不重复写，也不重复翻译）
        if state is not None and not state.get("header_done"):
            state["header_done"] = True
            first_blocks = window[0].blocks if window and window[0].blocks else []
            has_title_block = any(b.type is BlockType.TITLE for b in first_blocks[:4])
            if title and not has_title_block:
                zh = self._translate_text(title)
                if fmt == "markdown":
                    sink.write_raw(f"# {zh}\n\n")
                elif fmt == "text":
                    sink.write_raw(f"{zh}\n{'=' * min(60, max(8, len(zh)))}\n\n")

        done_pages = done_pages or set()
        need_translate: List[Block] = []

        for p in window:
            # 1) 先落盘一次，拿到稳定 block_id（ID 由 page_index+seq+原文决定）
            if st is not None and task_id:
                try:
                    st.upsert_blocks(task_id, p.blocks, p.index)
                except Exception as e:  # noqa: BLE001
                    self.log(f"[store] p{p.index + 1} 落盘失败：{e}")

            # 2) 已完成页：从库里把译文捞回来，不重翻
            if p.index in done_pages and st is not None:
                try:
                    rows = st.get_page_blocks(task_id, p.index)
                    if rows:
                        by_id = {r["block_id"]: r["translated"] or "" for r in rows}
                        reused_here = 0
                        for b in p.blocks:
                            if b.id in by_id and by_id[b.id]:
                                b.translated = by_id[b.id]
                                b.state = BlockState.TRANSLATED
                                reused_here += 1
                        res.reused += reused_here
                        if reused_here:
                            self.log(f"[resume] p{p.index + 1} 复用 {reused_here} 块")
                        continue
                except Exception as e:  # noqa: BLE001
                    self.log(f"[resume] p{p.index + 1} 读取失败，改为重翻：{e}")

            need_translate.extend(p.translatable_blocks)

        if need_translate:
            stats = self.translator.translate_blocks(
                need_translate,
                cancel=cancel,
                on_batch=lambda i, n: on_progress and on_progress(
                    "translate", i, n, f"翻译批次 {i}/{n}"
                ),
            )
            res.translated += stats.translated
            if res.stats is None:
                res.stats = stats
            else:
                res.stats.translated = res.translated
                res.stats.batches += stats.batches
                res.stats.requests += stats.requests
                res.stats.tm_hits += stats.tm_hits
                res.stats.failed += stats.failed
                res.stats.elapsed_s += stats.elapsed_s
                res.stats.degrade_events.extend(stats.degrade_events)
            res.model = stats.model_used

            # 3) 译文回写数据库 —— 断点续翻的依据
            if st is not None and task_id:
                for p in window:
                    if p.index in done_pages:
                        continue
                    try:
                        st.update_translations(task_id, p.blocks)
                        st.upsert_page(task_id, p.index, status="translated",
                                       block_count=len(p.blocks))
                    except Exception as e:  # noqa: BLE001
                        self.log(f"[store] p{p.index + 1} 回写失败：{e}")

        sink.add(window, total)
        if on_progress:
            on_progress("write", pages_done, total, f"已写出至第 {pages_done} 页")

    def _do_ocr(self, page: Page, renderer: PDFRenderer) -> None:
        ocr = self.ocr
        if ocr is None:
            return
        img = renderer.render(page.index, self.cfg.ocr.dpi)
        n = ocr.fill_page(page, img, self.cfg.ocr.dpi)
        if n:
            self.log(f"[ocr] p{page.index + 1} 识别 {n} 块")

    def _translate_text(self, text: str) -> str:
        """翻译单段文本（文档标题等）。失败回退原文。"""
        if not text.strip():
            return ""
        b = Block(text=text.strip(), type=BlockType.TITLE)
        try:
            self.translator.translate_blocks([b])
        except Exception as e:  # noqa: BLE001
            self.log(f"[title] 翻译失败：{e}")
            return text
        return b.translated or text

    # ---------------- 工具 ----------------
    @staticmethod
    def _default_out(src: Path, fmt: str) -> Path:
        ext = OUT_EXT.get(fmt, ".md")
        return src.with_name(f"{src.stem}.translated{ext}")

    # ---------------- 连通性自检 ----------------
    def precheck(self) -> List[str]:
        """返回问题列表；空列表表示就绪。"""
        problems: List[str] = []
        try:
            with OllamaClient(self.cfg.ollama.host, timeout=10) as c:
                c.version()
                if not c.has_model(self.cfg.ollama.model):
                    problems.append(
                        f"模型 {self.cfg.ollama.model} 未安装，请先执行: ollama pull {self.cfg.ollama.model}"
                    )
        except Exception as e:  # noqa: BLE001
            problems.append(f"Ollama 不可用：{e}（请先启动 Ollama）")
        return problems
