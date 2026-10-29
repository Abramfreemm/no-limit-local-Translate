"""后台线程层。

规则（硬约束）：主线程只画界面，任何可能耗时的动作（翻译、Ollama HTTP、模型拉取、
SQLite 批量读写）一律放进 QThread，结果通过 Signal 回到主线程。

暂停的实现：流水线只提供 ``cancel() -> bool`` 钩子，没有 pause 概念。
这里用 ``threading.Event`` 在 cancel 回调里阻塞等待，把「暂停」伪装成
「暂时不返回 True 的取消检查」，从而在批次 / 分页边界上真正停住工作线程，
而主线程全程可响应。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
from PySide6.QtCore import QThread, Signal

from ..core.config import Config
from ..pipeline import OUT_EXT, SUPPORTED_IN, Pipeline, PipelineResult
from ..translate.ollama_client import OllamaClient

# ---------------------------------------------------------------- 格式常量

#: UI 接受拖入的输入扩展名（最终清单）
INPUT_EXTS: tuple[str, ...] = (
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".txt",
    ".md",
    ".html",
    ".srt",
    ".vtt",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
)

#: 输出格式（传给 Pipeline.run 的 fmt 字符串）
OUTPUT_FORMATS: tuple[str, ...] = ("markdown", "text", "pdf", "docx", "pptx", "xlsx", "srt")

#: 内核能力清单一律从 pipeline 派生，避免 UI 与内核再度漂移
#: （M2/M4 之后内核已支持 PDF/Office/HTML/字幕/图片输入与 7 种输出）
KERNEL_INPUT_EXTS: frozenset = frozenset(SUPPORTED_IN)

#: 当前内核真正实现的输出格式（pipeline.OUT_EXT 的键，含 txt 别名）
KERNEL_OUTPUT_FMTS: frozenset = frozenset(OUT_EXT)

#: 输出格式 -> 文件后缀
OUT_SUFFIX: dict[str, str] = {
    "markdown": ".md",
    "text": ".txt",
    "pdf": ".pdf",
    "docx": ".docx",
    "pptx": ".pptx",
    "xlsx": ".xlsx",
    "srt": ".srt",
}


def is_input_ext(path: str | Path) -> bool:
    """判断扩展名是否在 UI 接受清单内。"""
    return Path(path).suffix.lower() in INPUT_EXTS


def out_path_for(src: Path, fmt: str, out_dir: str | Path | None) -> Path:
    """按输出目录与格式推导输出文件路径。"""
    src = Path(src)
    suffix = OUT_SUFFIX.get(fmt, ".md")
    name = f"{src.stem}.translated{suffix}"
    if out_dir:
        return Path(out_dir) / name
    return src.with_name(name)


# ---------------------------------------------------------------- 暂停闸门


class PauseGate:
    """暂停 / 继续 / 取消三态闸门，线程安全。"""

    def __init__(self) -> None:
        self._resume = threading.Event()
        self._resume.set()
        self._cancel = threading.Event()

    # ---- 控制 ----
    def pause(self) -> None:
        """请求暂停：闸门关闭，check() 将阻塞。"""
        self._resume.clear()

    def resume(self) -> None:
        """请求继续：闸门打开。"""
        self._resume.set()

    def request_cancel(self) -> None:
        """请求取消：同时打开闸门，唤醒阻塞中的等待以免卡死。"""
        self._cancel.set()
        self._resume.set()

    @property
    def canceled(self) -> bool:
        return self._cancel.is_set()

    @property
    def paused(self) -> bool:
        return not self._resume.is_set()

    # ---- 流水线回调 ----
    def check(self) -> bool:
        """传给 Pipeline 的 cancel 回调：暂停时阻塞等待，取消时返回 True。"""
        if self._cancel.is_set():
            return True
        while not self._resume.wait(0.2):
            if self._cancel.is_set():
                return True
        return self._cancel.is_set()


# ---------------------------------------------------------------- 翻译线程


class TranslateWorker(QThread):
    """后台跑 Pipeline 的线程。

    信号：
        sig_progress(stage, cur, total, msg) —— 直接转发 Pipeline 的 on_progress
        sig_log(text)        —— 流水线日志
        sig_item_start(row)  —— 某个队列项开始
        sig_item_done(row, PipelineResult)
        sig_item_error(row, message)
        sig_fatal(message)   —— 开局自检失败（如 Ollama 未启动）
        sig_finished_all(ok, fail)
    """

    sig_progress = Signal(str, int, int, str)
    sig_log = Signal(str)
    sig_item_start = Signal(int)
    sig_item_done = Signal(int, object)
    sig_item_error = Signal(int, str)
    sig_fatal = Signal(str)
    sig_finished_all = Signal(int, int)

    def __init__(
        self,
        cfg: Config,
        items: Sequence[tuple[int, str]],
        fmt: str = "markdown",
        bilingual: bool = False,
        out_dir: str | None = None,
        parent: Any | None = None,
    ) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.items: list[tuple[int, str]] = [(int(r), str(p)) for r, p in items]
        self.fmt = fmt
        self.bilingual = bilingual
        self.out_dir = out_dir
        self.gate = PauseGate()
        self._ok = 0
        self._fail = 0

    # ---- 控制接口（主线程调用）----
    def request_cancel(self) -> None:
        """请求取消当前及后续任务。"""
        self.gate.request_cancel()

    def pause(self) -> None:
        """暂停：在下一个分页 / 批次边界生效。"""
        self.gate.pause()

    def resume(self) -> None:
        """继续。"""
        self.gate.resume()

    # ---- 线程体 ----
    def run(self) -> None:  # noqa: D102
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001 —— 兜底，避免线程静默死亡
            msg = f"{type(exc).__name__}: {exc}"
            self.sig_log.emit(f"[致命] {msg}")
            self.sig_fatal.emit(msg)
        finally:
            self.sig_finished_all.emit(self._ok, self._fail)

    def _run(self) -> None:
        self.cfg.output.bilingual = bool(self.bilingual)
        pipe = Pipeline(self.cfg, log=self._log)

        problems = pipe.precheck()
        if problems:
            self.sig_fatal.emit("\n".join(problems))
            return

        for row, src in self.items:
            if self.gate.canceled:
                break
            self.sig_item_start.emit(row)
            self._run_one(pipe, row, Path(src))

    def _run_one(self, pipe: Pipeline, row: int, src: Path) -> None:
        ext = src.suffix.lower()
        if ext not in KERNEL_INPUT_EXTS:
            self._fail += 1
            self.sig_item_error.emit(row, f"内核暂不支持的格式: {ext}")
            return
        if not src.exists():
            self._fail += 1
            self.sig_item_error.emit(row, f"文件不存在: {src}")
            return
        if self.gate.check():
            return

        out = out_path_for(src, self.fmt, self.out_dir)
        self.sig_log.emit(f"[run] {src.name} -> {out}")
        try:
            res = pipe.run(
                src,
                out=out,
                fmt=self.fmt,
                cancel=self.gate.check,
                on_progress=self._on_progress,
            )
        except Exception as exc:  # noqa: BLE001
            self._fail += 1
            self.sig_item_error.emit(row, f"{type(exc).__name__}: {exc}")
            return

        if self.gate.canceled:
            self.sig_item_error.emit(row, "用户取消")
            return
        if res.ok:
            self._ok += 1
            self.sig_item_done.emit(row, res)
        else:
            self._fail += 1
            self.sig_item_error.emit(row, "; ".join(res.errors) or "未知错误")

    # ---- 回调 ----
    def _log(self, text: str) -> None:
        self.sig_log.emit(str(text))

    def _on_progress(self, stage: str, cur: int, total: int, msg: str) -> None:
        self.sig_progress.emit(str(stage), int(cur), int(total), str(msg))


# ---------------------------------------------------------------- Ollama 探测


class OllamaProbeWorker(QThread):
    """检测 Ollama 连通性并列出本地模型（含体积 / 参数规模）。"""

    sig_done = Signal(object)

    def __init__(self, host: str, timeout: float = 10.0, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.host = host.rstrip("/")
        self.timeout = timeout

    def run(self) -> None:  # noqa: D102
        info: dict[str, Any] = {"ok": False, "version": "", "models": [], "error": ""}
        try:
            with OllamaClient(self.host, timeout=self.timeout) as client:
                info["version"] = client.version()
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(f"{self.host}/api/tags")
                resp.raise_for_status()
                info["models"] = list(resp.json().get("models") or [])
            info["ok"] = True
        except Exception as exc:  # noqa: BLE001
            info["error"] = f"{type(exc).__name__}: {exc}"
        self.sig_done.emit(info)


# ---------------------------------------------------------------- 模型拉取


class ModelPullWorker(QThread):
    """流式拉取模型（POST /api/pull），带进度与取消。"""

    sig_progress = Signal(str, float)  # (状态文本, 百分比；-1 表示不确定)
    sig_done = Signal(bool, str)  # (是否成功, 说明)

    def __init__(self, host: str, name: str, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.host = host.rstrip("/")
        self.name = name
        self._canceled = False

    def request_cancel(self) -> None:
        """取消拉取（在下一个流式分片生效）。"""
        self._canceled = True

    def run(self) -> None:  # noqa: D102
        ok = False
        msg = ""
        try:
            timeout = httpx.Timeout(30.0, read=None)
            with httpx.Client(timeout=timeout) as client:
                with client.stream(
                    "POST",
                    f"{self.host}/api/pull",
                    json={"name": self.name, "stream": True},
                ) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if self._canceled:
                            break
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        err = str(obj.get("error") or "")
                        if err:
                            self.sig_done.emit(False, err)
                            return
                        status = str(obj.get("status") or "")
                        total = float(obj.get("total") or 0)
                        done = float(obj.get("completed") or 0)
                        pct = (done / total * 100.0) if total > 0 else -1.0
                        self.sig_progress.emit(status, pct)
            ok = not self._canceled
            msg = self.name if ok else f"canceled:{self.name}"
        except Exception as exc:  # noqa: BLE001
            ok = False
            msg = f"{type(exc).__name__}: {exc}"
        self.sig_done.emit(ok, msg)


# ---------------------------------------------------------------- 通用调用


class CallWorker(QThread):
    """把任意耗时 callable 丢到后台线程，主线程不阻塞。

    常用于 SQLite 批量读写：DAO 要求「每个线程各自 connect」，因此
    Store 必须在 run() 内部创建，不能跨线程复用主线程的连接。
    """

    sig_result = Signal(object)
    sig_error = Signal(str)

    def __init__(self, fn: Callable[[], Any], parent: Any | None = None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:  # noqa: D102
        try:
            self.sig_result.emit(self._fn())
        except Exception as exc:  # noqa: BLE001
            self.sig_error.emit(f"{type(exc).__name__}: {exc}")


__all__ = [
    "INPUT_EXTS",
    "OUTPUT_FORMATS",
    "KERNEL_INPUT_EXTS",
    "KERNEL_OUTPUT_FMTS",
    "OUT_SUFFIX",
    "is_input_ext",
    "out_path_for",
    "PauseGate",
    "TranslateWorker",
    "OllamaProbeWorker",
    "ModelPullWorker",
    "CallWorker",
    "PipelineResult",
]
