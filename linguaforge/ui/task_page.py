"""任务页：拖放文件队列 + 开始 / 暂停 / 继续 / 取消 + 输出选项。

所有耗时动作都在 :class:`~linguaforge.ui.worker.TranslateWorker` 里跑，
本页面只负责「收信号 -> 改控件」。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr
from .preview import PreviewDialog
from .worker import (
    KERNEL_INPUT_EXTS,
    KERNEL_OUTPUT_FMTS,
    OUTPUT_FORMATS,
    TranslateWorker,
    is_input_ext,
)

#: 状态代码 -> i18n key 后缀
_DONE = "done"
_FAILED = "failed"
_PENDING = "pending"
_RUNNING = "running"
_PAUSED = "paused"
_CANCELED = "canceled"
_SKIPPED = "skipped"


@dataclass
class _Row:
    """队列里的一行。"""

    path: Path
    status: str = _PENDING
    progress: int = 0
    message: str = ""
    output: str = ""
    bar: QProgressBar | None = field(default=None, repr=False)


class TaskPage(QWidget):
    """翻译任务页。"""

    def __init__(self, cfg, main_window=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.main_window = main_window
        self.lang = getattr(cfg, "ui_lang", "zh-CN") or "zh-CN"
        self._rows: dict[int, _Row] = {}
        self._next_row = 0
        self._current_row = -1
        self._worker: TranslateWorker | None = None
        self._preview: PreviewDialog | None = None
        self.setAcceptDrops(True)
        self._build_ui()
        self.retranslateUi()

    # ---------------------------------------------------------------- UI
    @property
    def lang_code(self) -> str:
        """当前界面语言（优先取主窗口的，保证切语言后同步）。"""
        if self.main_window is not None:
            return self.main_window.lang
        return self.lang

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.btn_add = QPushButton()
        self.btn_remove = QPushButton()
        self.btn_clear = QPushButton()
        self.btn_preview = QPushButton()
        self.btn_open_out = QPushButton()
        for b in (self.btn_add, self.btn_remove, self.btn_clear, self.btn_preview, self.btn_open_out):
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        self.lbl_hint = QLabel()
        self.lbl_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_hint.setWordWrap(True)
        root.addWidget(self.lbl_hint)

        self.table = QTableWidget(0, 4)
        self.table.setAcceptDrops(False)
        self.table.viewport().setAcceptDrops(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.table, 1)

        opt = QHBoxLayout()
        self.lbl_fmt = QLabel()
        self.cmb_fmt = QComboBox()
        self.cmb_fmt.addItems(list(OUTPUT_FORMATS))
        self.chk_bilingual = QCheckBox()
        self.lbl_out = QLabel()
        self.edt_out = QLineEdit()
        self.btn_browse = QPushButton()
        opt.addWidget(self.lbl_fmt)
        opt.addWidget(self.cmb_fmt)
        opt.addWidget(self.chk_bilingual)
        opt.addWidget(self.lbl_out)
        opt.addWidget(self.edt_out, 1)
        opt.addWidget(self.btn_browse)
        root.addLayout(opt)

        self.lbl_fmt_warn = QLabel()
        self.lbl_fmt_warn.setWordWrap(True)
        self.lbl_fmt_warn.setStyleSheet("color:#B26A00;")
        root.addWidget(self.lbl_fmt_warn)

        run = QHBoxLayout()
        self.btn_start = QPushButton()
        self.btn_pause = QPushButton()
        self.btn_resume = QPushButton()
        self.btn_cancel = QPushButton()
        for b in (self.btn_start, self.btn_pause, self.btn_resume, self.btn_cancel):
            run.addWidget(b)
        run.addStretch(1)
        root.addLayout(run)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(96)
        root.addWidget(self.log)

        self.btn_add.clicked.connect(self._on_add)
        self.btn_remove.clicked.connect(self._on_remove)
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_preview.clicked.connect(self._on_preview)
        self.btn_open_out.clicked.connect(self._on_open_out)
        self.btn_browse.clicked.connect(self._on_browse)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_resume.clicked.connect(self._on_resume)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.cmb_fmt.currentTextChanged.connect(self._on_fmt_changed)

        self._set_running(False)

    # ---------------------------------------------------------------- 拖放
    def dragEnterEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """只接受带本地文件路径的拖入。"""
        md = event.mimeData()
        if md.hasUrls() and any(u.isLocalFile() for u in md.urls()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """落下一个或多个文件，按扩展名过滤后入队。"""
        paths: list[str] = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            p = url.toLocalFile()
            if is_input_ext(p):
                paths.append(p)
            else:
                self._warn(tr("msg.warning", self.lang_code),
                           tr("task.hint_unsupported", self.lang_code, ext=Path(p).suffix))
        if paths:
            self.add_paths(paths)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    # ---------------------------------------------------------------- 队列
    def add_paths(self, paths) -> int:
        """把一批路径加入队列，返回新增行数。"""
        added = 0
        for raw in paths:
            p = Path(raw)
            if not p.exists():
                continue
            row = self._next_row
            self._next_row += 1
            item = _Row(path=p)
            if p.suffix.lower() not in KERNEL_INPUT_EXTS:
                item.status = _SKIPPED
                item.message = tr("task.hint_unsupported", self.lang_code, ext=p.suffix)
            self._rows[row] = item
            self._insert_row(row, item)
            added += 1
        if added:
            self._on_fmt_changed(self.cmb_fmt.currentText())
        return added

    def _insert_row(self, row: int, item: _Row) -> None:
        idx = self.table.rowCount()
        self.table.insertRow(idx)
        self.table.setItem(idx, 0, QTableWidgetItem(item.path.name))
        self.table.setItem(idx, 1, QTableWidgetItem(item.path.suffix.lower().lstrip(".")))
        self.table.setItem(idx, 2, QTableWidgetItem(""))
        bar = QProgressBar()
        bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar.setRange(0, 100)
        bar.setValue(item.progress)
        self.table.setCellWidget(idx, 3, bar)
        item.bar = bar
        self.table.item(idx, 0).setData(Qt.ItemDataRole.UserRole, row)
        self._refresh_row_text(row)

    def _visual_index(self, row: int) -> int:
        """逻辑行号 -> 表格可视行号。"""
        for i in range(self.table.rowCount()):
            it = self.table.item(i, 0)
            if it is not None and it.data(Qt.ItemDataRole.UserRole) == row:
                return i
        return -1

    def _refresh_row_text(self, row: int) -> None:
        item = self._rows.get(row)
        if item is None:
            return
        idx = self._visual_index(row)
        if idx < 0:
            return
        status = tr(f"status.{item.status}", self.lang_code)
        if item.message:
            status = f"{status} · {item.message}" if item.status != _RUNNING else item.message
        cell = self.table.item(idx, 2)
        if cell is not None:
            cell.setText(status)
            cell.setToolTip(item.message or str(item.path))
        if item.bar is not None:
            item.bar.setValue(item.progress)

    # ---------------------------------------------------------------- 动作
    def _on_add(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("task.add", self.lang_code), "", tr("msg.file_filter", self.lang_code)
        )
        if files:
            self.add_paths(files)

    def _on_remove(self) -> None:
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            return
        for model_idx in sorted((m.row() for m in sel), reverse=True):
            it = self.table.item(model_idx, 0)
            if it is None:
                continue
            row = it.data(Qt.ItemDataRole.UserRole)
            self._rows.pop(row, None)
            self.table.removeRow(model_idx)
        self._on_fmt_changed(self.cmb_fmt.currentText())

    def _on_clear(self) -> None:
        if not self._rows:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("msg.info", self.lang_code))
        box.setText(tr("msg.confirm_clear", self.lang_code))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self.table.setRowCount(0)
        self._rows.clear()
        self._on_fmt_changed(self.cmb_fmt.currentText())

    def _on_browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("task.browse", self.lang_code), "")
        if d:
            self.edt_out.setText(d)

    def _on_open_out(self) -> None:
        target = self.edt_out.text().strip()
        if not target:
            for item in self._rows.values():
                if item.output:
                    target = str(Path(item.output).parent)
                    break
        if not target:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def _on_preview(self) -> None:
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            self._warn(tr("msg.info", self.lang_code), tr("task.no_selection", self.lang_code))
            return
        it = self.table.item(sel[0].row(), 0)
        if it is None:
            return
        item = self._rows.get(it.data(Qt.ItemDataRole.UserRole))
        if item is None:
            return
        if not item.output or not Path(item.output).exists():
            self._warn(tr("msg.info", self.lang_code), tr("task.not_done", self.lang_code))
            return
        dlg = PreviewDialog(str(item.path), item.output, self.cmb_fmt.currentText(),
                            self.lang_code, self)
        self._preview = dlg
        dlg.load()
        dlg.exec()

    def _on_fmt_changed(self, text: str) -> None:
        """只在真正会发生降级时提示。

        内核已支持全部 7 种输出格式；唯一会降级的情况是
        「输出选了 PDF，但输入不是 PDF」——PDF 输出走原位回填，必须以 PDF 为底稿。
        """
        warn = ""
        if text == "pdf":
            non_pdf = [it for it in self._rows.values()
                       if it.path.suffix.lower() != ".pdf"]
            if non_pdf:
                warn = tr("task.fmt_warn_pdf", self.lang_code)
        elif text not in KERNEL_OUTPUT_FMTS:
            warn = tr("task.fmt_unknown", self.lang_code)
        self.lbl_fmt_warn.setText(warn)
        self.lbl_fmt_warn.setVisible(bool(warn))

    # ---------------------------------------------------------------- 运行
    def _on_start(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        items = [(row, str(it.path)) for row, it in self._rows.items()
                 if it.status in (_PENDING, _FAILED, _CANCELED)
                 and it.path.suffix.lower() in KERNEL_INPUT_EXTS]
        if not items:
            self._warn(tr("msg.info", self.lang_code), tr("msg.no_file", self.lang_code))
            return

        for row, _p in items:
            self._rows[row].status = _PENDING
            self._rows[row].progress = 0
            self._rows[row].message = ""
            self._refresh_row_text(row)

        cfg = copy.deepcopy(self.cfg)
        fmt = self.cmb_fmt.currentText()
        worker = TranslateWorker(
            cfg, items, fmt=fmt,
            bilingual=self.chk_bilingual.isChecked(),
            out_dir=self.edt_out.text().strip() or None,
            parent=self,
        )
        worker.sig_progress.connect(self._on_progress)
        worker.sig_log.connect(self._on_log)
        worker.sig_item_start.connect(self._on_item_start)
        worker.sig_item_done.connect(self._on_item_done)
        worker.sig_item_error.connect(self._on_item_error)
        worker.sig_fatal.connect(self._on_fatal)
        worker.sig_finished_all.connect(self._on_all_finished)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        self._set_running(True)
        worker.start()

    def _on_pause(self) -> None:
        if self._worker is None:
            return
        self._worker.pause()
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(True)
        for row, item in self._rows.items():
            if item.status == _RUNNING:
                item.status = _PAUSED
                self._refresh_row_text(row)
        self._status(tr("status.paused", self.lang_code))

    def _on_resume(self) -> None:
        if self._worker is None:
            return
        self._worker.resume()
        self.btn_pause.setEnabled(True)
        self.btn_resume.setEnabled(False)
        for row, item in self._rows.items():
            if item.status == _PAUSED:
                item.status = _RUNNING
                self._refresh_row_text(row)

    def _on_cancel(self) -> None:
        if self._worker is None:
            return
        self._worker.request_cancel()
        for row, item in self._rows.items():
            if item.status in (_PENDING, _RUNNING, _PAUSED):
                item.status = _CANCELED
                self._refresh_row_text(row)

    # ---------------------------------------------------------------- 信号槽
    def _on_item_start(self, row: int) -> None:
        self._current_row = row
        item = self._rows.get(row)
        if item is None:
            return
        item.status = _RUNNING
        item.progress = 0
        self._refresh_row_text(row)
        self._log_line(tr("log.start", self.lang_code, name=item.path.name))

    def _on_progress(self, stage: str, cur: int, total: int, msg: str) -> None:
        item = self._rows.get(self._current_row)
        if item is None:
            return
        ratio = (cur / total) if total else 0.0
        if stage == "parse":
            pct = ratio * 30
        elif stage == "translate":
            pct = 30 + ratio * 60
        elif stage == "write":
            pct = 90 + ratio * 10
        else:
            pct = 100.0
        item.progress = max(item.progress, int(min(100, pct)))
        item.message = msg
        self._refresh_row_text(self._current_row)

    def _on_item_done(self, row: int, result: object) -> None:
        item = self._rows.get(row)
        if item is None:
            return
        item.status = _DONE
        item.progress = 100
        item.message = ""
        item.output = str(getattr(result, "output", "") or "")
        self._refresh_row_text(row)
        self._log_line(tr(
            "log.done", self.lang_code, name=item.path.name,
            elapsed=float(getattr(result, "elapsed_s", 0.0) or 0.0),
            blocks=int(getattr(result, "blocks", 0) or 0),
            translated=int(getattr(result, "translated", 0) or 0),
        ))
        self._log_line(str(getattr(result, "summary", lambda: "")()))

    def _on_item_error(self, row: int, message: str) -> None:
        item = self._rows.get(row)
        if item is None:
            return
        canceled = "取消" in message or "cancel" in message.lower()
        item.status = _CANCELED if canceled else _FAILED
        item.message = message
        self._refresh_row_text(row)
        key = "log.canceled" if canceled else "log.fail"
        self._log_line(tr(key, self.lang_code, name=item.path.name, error=message))

    def _on_fatal(self, message: str) -> None:
        """开局自检失败（典型：Ollama 未启动 / 模型未安装）。"""
        self._log_line(f"[FATAL] {message}")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(tr("msg.ollama_title", self.lang_code))
        box.setText(tr("msg.ollama_body", self.lang_code, problems=message))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Close)
        box.button(QMessageBox.StandardButton.Yes).setText(tr("nav.model", self.lang_code))
        box.button(QMessageBox.StandardButton.Close).setText(tr("common.close", self.lang_code))
        if box.exec() == QMessageBox.StandardButton.Yes and self.main_window is not None:
            self.main_window.goto_model_page()

    def _on_all_finished(self, ok: int, fail: int) -> None:
        self._status(tr("msg.all_done", self.lang_code, ok=ok, fail=fail))

    def _on_worker_finished(self) -> None:
        self._set_running(False)
        worker = self._worker
        if worker is not None:
            worker.deleteLater()
        self._worker = None
        self._current_row = -1

    def _on_log(self, text: str) -> None:
        self._log_line(text)

    # ---------------------------------------------------------------- 工具
    def _set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_pause.setEnabled(running)
        self.btn_resume.setEnabled(False)
        self.btn_cancel.setEnabled(running)
        self.btn_add.setEnabled(not running)
        self.btn_remove.setEnabled(not running)
        self.btn_clear.setEnabled(not running)
        self.cmb_fmt.setEnabled(not running)
        self.chk_bilingual.setEnabled(not running)
        self.edt_out.setEnabled(not running)
        self.btn_browse.setEnabled(not running)

    def _log_line(self, text: str) -> None:
        self.log.append(str(text))

    def _status(self, text: str) -> None:
        if self.main_window is not None:
            self.main_window.status(text)

    def _warn(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    # ---------------------------------------------------------------- 语言
    def retranslateUi(self) -> None:  # noqa: N802 —— Qt 命名约定
        """切语言时重刷全部文案。"""
        lang = self.lang_code
        self.lang = lang
        self.btn_add.setText(tr("task.add", lang))
        self.btn_remove.setText(tr("task.remove", lang))
        self.btn_clear.setText(tr("task.clear", lang))
        self.btn_preview.setText(tr("task.preview", lang))
        self.btn_open_out.setText(tr("task.open_out", lang))
        self.btn_start.setText(tr("task.start", lang))
        self.btn_pause.setText(tr("task.pause", lang))
        self.btn_resume.setText(tr("task.resume", lang))
        self.btn_cancel.setText(tr("task.cancel", lang))
        self.btn_browse.setText(tr("task.browse", lang))
        self.lbl_fmt.setText(tr("task.outfmt", lang))
        self.chk_bilingual.setText(tr("task.bilingual", lang))
        self.lbl_out.setText(tr("task.outdir", lang))
        self.lbl_hint.setText(tr("task.drop", lang))
        self.table.setHorizontalHeaderLabels([
            tr("task.col_file", lang),
            tr("task.col_format", lang),
            tr("task.col_status", lang),
            tr("task.col_progress", lang),
        ])
        self._on_fmt_changed(self.cmb_fmt.currentText())
        for row in self._rows:
            self._refresh_row_text(row)
