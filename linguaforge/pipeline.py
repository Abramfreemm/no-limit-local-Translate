"""翻译流水线。

流式窗口设计（支撑「不限制页数与大小」）：
    解析一页 -> 需要则 OCR -> 进入窗口
    窗口达到 window_pages 页或 window_chars 字符 -> 翻译该窗口 -> 增量写盘 -> 清空窗口
因此内存占用与文档总页数无关，1000 页 / 500MB 也能跑完。

流水线层不 import 任何 Qt 模块，可无头运行。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from .core.config import Config
from .core.docir import Block, BlockType, DocIR, Page
from .ocr import RapidOCREngine
from .parsers import PDFParser, TextParser
from .parsers.render import PDFRenderer
from .translate.ollama_client import OllamaClient
from .translate.translator import Glossary, TranslationMemory, TranslateStats, Translator
from .writers.markdown import render_pages
from .writers.text import render_page_text

TEXT_EXT = {".txt", ".md", ".markdown"}


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
    elapsed_s: float = 0.0
    model: str = ""
    stats: Optional[TranslateStats] = None
    errors: List[str] = field(default_factory=list)

    def summary(self) -> str:
        s = self.stats
        tm = f"  TM命中={s.tm_hits}" if s and s.tm_hits else ""
        return (
            f"完成: {self.output}\n"
            f"  页数={self.pages} 块数={self.blocks} 已译={self.translated} OCR页={self.ocr_pages}\n"
            f"  耗时={self.elapsed_s:.1f}s 模型={self.model}{tm}\n"
            f"  错误={len(self.errors)}"
        )


ProgressCB = Optional[Callable[[str, int, int, str], None]]
CancelCB = Optional[Callable[[], bool]]


class Pipeline:
    """一次翻译任务。"""

    def __init__(
        self,
        cfg: Optional[Config] = None,
        ocr=None,
        translator: Optional[Translator] = None,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.cfg = cfg or Config()
        self.log = log or (lambda _m: None)
        self._ocr = ocr
        self.translator = translator or Translator(self.cfg, log=self.log)
        self.glossary = self.translator.glossary
        self.tm = self.translator.tm

    # ---------------- OCR ----------------
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

    # ---------------- 主流程 ----------------
    def run(
        self,
        src: str | Path,
        out: Optional[str | Path] = None,
        fmt: Optional[str] = None,
        cancel: CancelCB = None,
        on_progress: ProgressCB = None,
    ) -> PipelineResult:
        t0 = time.time()
        src = Path(src)
        if not src.exists():
            return PipelineResult(ok=False, source=str(src), errors=[f"文件不存在: {src}"])

        ext = src.suffix.lower()
        fmt = fmt or self.cfg.output.fmt
        bilingual = self.cfg.output.bilingual
        if ext in TEXT_EXT and fmt == "markdown":
            fmt = "markdown"

        out_path = Path(out) if out else self._default_out(src, fmt)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        res = PipelineResult(source=str(src), output=str(out_path), fmt=fmt, model=self.cfg.ollama.model)
        parser = None
        renderer = None
        try:
            if ext == ".pdf":
                parser = PDFParser(self.cfg).open(src)
                total = parser.page_count
                title = parser._title or src.stem
                if self.cfg.ocr.enabled:
                    try:
                        renderer = PDFRenderer(src, self.cfg.ocr.dpi)
                    except Exception as e:  # noqa: BLE001
                        self.log(f"[render] 初始化失败：{e}")
            elif ext in TEXT_EXT:
                parser = TextParser(self.cfg).open(src)
                total = 1
                title = src.stem
            else:
                return PipelineResult(
                    ok=False, source=str(src), errors=[f"暂不支持的格式: {ext}（后续版本支持）"]
                )
        except Exception as e:  # noqa: BLE001
            return PipelineResult(ok=False, source=str(src), errors=[f"打开失败: {e}"])

        try:
            state = {"header_done": False}
            with open(out_path, "w", encoding="utf-8") as fh:
                window: List[Page] = []
                window_chars = 0
                pages_done = 0

                for page in parser.iter_pages():
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

                    if (
                        len(window) >= self.cfg.perf.window_pages
                        or window_chars >= self.cfg.perf.window_chars
                    ):
                        self._flush(
                            window, fh, fmt, bilingual, res, cancel, on_progress,
                            pages_done, total, title, state,
                        )
                        window, window_chars = [], 0
                        if cancel and cancel():
                            res.errors.append("用户取消")
                            break

                if window:
                    self._flush(
                        window, fh, fmt, bilingual, res, cancel, on_progress,
                        pages_done, total, title, state,
                    )

            res.pages = pages_done
            res.elapsed_s = time.time() - t0
            res.ok = not res.errors or res.translated > 0
            if on_progress:
                on_progress("done", pages_done, total, "完成")
        finally:
            if renderer:
                renderer.close()
            if parser:
                parser.close()
        return res

    # ---------------- 窗口处理 ----------------
    def _flush(
        self,
        window: List[Page],
        fh,
        fmt: str,
        bilingual: bool,
        res: PipelineResult,
        cancel: CancelCB,
        on_progress: ProgressCB,
        pages_done: int,
        total: int,
        title: str = "",
        state: Optional[dict] = None,
    ) -> None:
        # 首次 flush 时补文档标题（正文自带标题块就不重复写，也不重复翻译）
        if state is not None and not state.get("header_done"):
            state["header_done"] = True
            first_blocks = window[0].blocks if window and window[0].blocks else []
            # 页首常是页眉，不能只看第一个块；前几个块里有 TITLE 就认为正文自带标题
            has_title_block = any(b.type is BlockType.TITLE for b in first_blocks[:4])
            if title and not has_title_block:
                zh = self._translate_text(title)
                if fmt == "markdown":
                    fh.write(f"# {zh}\n\n")
                else:
                    fh.write(f"{zh}\n{'=' * min(60, max(8, len(zh)))}\n\n")

        blocks: List = []
        for p in window:
            blocks.extend(p.translatable_blocks)

        if blocks:
            stats = self.translator.translate_blocks(
                blocks,
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

        if fmt == "markdown":
            frag = render_pages("", window, total, bilingual)
        else:
            frag = "\n".join(
                line for p in window for line in render_page_text(p, bilingual)
            )
        if frag.strip():
            fh.write(frag)
            if not frag.endswith("\n"):
                fh.write("\n")
            fh.write("\n")
        fh.flush()
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
        ext = ".md" if fmt == "markdown" else ".txt"
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
