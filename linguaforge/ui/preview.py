"""并排预览：左原文、右译文。

不做 PDF 渲染（红线要求），只做文本 / Markdown 呈现：
  - 右栏直接读流水线已产出的文件（markdown 走 setMarkdown，其余走纯文本）；
  - 左栏对 .txt/.md/.html/.srt/.vtt 直接读盘，对 .pdf 用 PDFParser 抽取文本层，
    其余格式留空并给出说明。抽取放在 QThread 里，避免大文件卡住主线程。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..parsers import PDFParser
from .i18n import tr
from .worker import CallWorker

#: 左栏抽取的字符上限，避免超大文档把预览卡死
_SRC_CHAR_LIMIT = 200_000

_TEXTUAL_EXTS = {".txt", ".md", ".markdown", ".html", ".htm", ".srt", ".vtt"}


def extract_source_text(path: str | Path) -> str:
    """抽取源文件纯文本；返回空串表示无法提取（调用方据此提示不支持）。"""
    p = Path(path)
    ext = p.suffix.lower()
    try:
        if ext in _TEXTUAL_EXTS:
            return p.read_text(encoding="utf-8", errors="replace")[:_SRC_CHAR_LIMIT]
        if ext == ".pdf":
            return _extract_pdf(p)
    except (OSError, ValueError) as exc:
        return f"[读取失败] {type(exc).__name__}: {exc}"
    return ""


def _extract_pdf(pdf: Path) -> str:
    """用 PDFParser 抽取 PDF 文本层（不渲染位图）。"""
    parts: list[str] = []
    parser = PDFParser().open(pdf)
    try:
        for page in parser.iter_pages():
            text = "\n".join(b.text for b in page.blocks if b.text.strip())
            if text:
                parts.append(text)
            if sum(len(x) for x in parts) > _SRC_CHAR_LIMIT:
                parts.append("…")
                break
    finally:
        parser.close()
    return "\n\n".join(parts)[:_SRC_CHAR_LIMIT]


class PreviewDialog(QDialog):
    """并排预览对话框。构造后调用 :meth:`load` 触发载入。"""

    def __init__(
        self,
        source: str,
        output: str,
        fmt: str = "markdown",
        lang: str = "zh-CN",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.source = str(source)
        self.output = str(output)
        self.fmt = fmt
        self.lang = lang
        self._worker: CallWorker | None = None

        self.setWindowTitle(tr("preview.title", lang, name=Path(source).name))
        self.resize(1100, 720)

        root = QVBoxLayout(self)
        split = QSplitter(Qt.Orientation.Horizontal, self)
        root.addWidget(split, 1)

        self.lbl_src = QLabel(tr("preview.src", lang))
        self.lbl_dst = QLabel(tr("preview.dst", lang))
        self.left = QTextBrowser()
        self.right = QTextBrowser()
        self.left.setReadOnly(True)
        self.right.setReadOnly(True)

        for label, browser in ((self.lbl_src, self.left), (self.lbl_dst, self.right)):
            box = QWidget(self)
            vbox = QVBoxLayout(box)
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.addWidget(label)
            vbox.addWidget(browser, 1)
            split.addWidget(box)
        split.setSizes([520, 520])

    # ---- 载入 ----
    def load(self) -> None:
        """载入两侧内容：右栏同步读盘（已产出文件），左栏异步抽取。"""
        self.left.setPlainText(tr("preview.loading", self.lang))
        self._load_output()
        self._start_source_worker()

    def _load_output(self) -> None:
        path = Path(self.output)
        if not path.exists():
            self.right.setPlainText(tr("preview.empty", self.lang))
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError) as exc:
            self.right.setPlainText(f"[读取失败] {type(exc).__name__}: {exc}")
            return
        if self.fmt == "markdown":
            self.right.setMarkdown(text)
        else:
            self.right.setPlainText(text or tr("preview.empty", self.lang))

    def _start_source_worker(self) -> None:
        ext = Path(self.source).suffix.lower()
        if ext not in _TEXTUAL_EXTS and ext != ".pdf":
            self.left.setPlainText(tr("preview.src_unsupported", self.lang, ext=ext))
            return
        self._worker = CallWorker(lambda: extract_source_text(self.source), parent=self)
        self._worker.sig_result.connect(self._on_source_text)
        self._worker.sig_error.connect(self._on_source_error)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_source_text(self, text: object) -> None:
        self.left.setPlainText(str(text) or tr("preview.empty", self.lang))

    def _on_source_error(self, message: str) -> None:
        self.left.setPlainText(f"[抽取失败] {message}")

    # ---- 语言 ----
    def retranslateUi(self) -> None:
        """切换界面语言后重刷文案。"""
        self.setWindowTitle(tr("preview.title", self.lang, name=Path(self.source).name))
        self.lbl_src.setText(tr("preview.src", self.lang))
        self.lbl_dst.setText(tr("preview.dst", self.lang))

    def closeEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """关闭时确保后台抽取线程已结束，避免悬挂线程。"""
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            worker.wait(3000)
        super().closeEvent(event)
