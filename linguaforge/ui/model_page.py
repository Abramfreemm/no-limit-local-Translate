"""模型页：检测 Ollama 连通性、列出本地模型、选择主模型、拉取模型（带进度）。

所有 HTTP 都在 :class:`~linguaforge.ui.worker.OllamaProbeWorker` /
:class:`~linguaforge.ui.worker.ModelPullWorker` 中进行，主线程不发起网络请求。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr
from .worker import ModelPullWorker, OllamaProbeWorker

#: 常见候选模型，方便直接下拉拉取（也可手输）
PULL_CANDIDATES = (
    "translategemma:12b",
    "translategemma:4b",
    "qwen3:8b",
    "qwen3:14b",
    "gemma3:12b",
    "llama3.1:8b",
)


class ModelPage(QWidget):
    """模型管理页。"""

    def __init__(self, cfg, main_window=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.main_window = main_window
        self.lang = getattr(cfg, "ui_lang", "zh-CN") or "zh-CN"
        self._probed = False
        self._probe: OllamaProbeWorker | None = None
        self._pull: ModelPullWorker | None = None
        self._loading = False
        self._local_models: list[str] = []
        self._build_ui()
        self.retranslateUi()

    @property
    def lang_code(self) -> str:
        """当前界面语言（跟随主窗口，保证切语言后同步）。"""
        if self.main_window is not None:
            return self.main_window.lang
        return self.lang

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.lbl_host = QLabel()
        self.edt_host = QLineEdit(self.cfg.ollama.host)
        self.btn_refresh = QPushButton()
        top.addWidget(self.lbl_host)
        top.addWidget(self.edt_host, 1)
        top.addWidget(self.btn_refresh)
        root.addLayout(top)

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        self.table = QTableWidget(0, 5)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3, 4):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.table, 1)

        sel = QHBoxLayout()
        self.lbl_primary = QLabel()
        self.cmb_primary = QComboBox()
        self.cmb_primary.setEditable(True)
        self.cmb_primary.setMinimumWidth(280)
        self.lbl_pull_name = QLabel()
        self.cmb_pull = QComboBox()
        self.cmb_pull.setEditable(True)
        self.cmb_pull.addItems(list(PULL_CANDIDATES))
        self.btn_pull = QPushButton()
        self.btn_pull_cancel = QPushButton()
        sel.addWidget(self.lbl_primary)
        sel.addWidget(self.cmb_primary, 1)
        sel.addWidget(self.lbl_pull_name)
        sel.addWidget(self.cmb_pull, 1)
        sel.addWidget(self.btn_pull)
        sel.addWidget(self.btn_pull_cancel)
        root.addLayout(sel)

        self.bar_pull = QProgressBar()
        self.bar_pull.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bar_pull.setRange(0, 100)
        self.bar_pull.setValue(0)
        root.addWidget(self.bar_pull)

        self.btn_refresh.clicked.connect(self.refresh)
        self.edt_host.editingFinished.connect(self._on_host_changed)
        self.cmb_primary.currentTextChanged.connect(self._on_primary_changed)
        self.btn_pull.clicked.connect(self._on_pull)
        self.btn_pull_cancel.clicked.connect(self._on_pull_cancel)
        self.btn_pull_cancel.setEnabled(False)

    # ---------------------------------------------------------------- 生命周期
    def on_shown(self) -> None:
        """页面首次可见时才做网络探测，避免启动即打网络。"""
        if not self._probed:
            self.refresh()

    # ---------------------------------------------------------------- 探测
    def refresh(self) -> None:
        """异步探测 Ollama 并刷新模型列表。"""
        if self._probe is not None and self._probe.isRunning():
            return
        lang = self.lang_code
        self.lbl_status.setText(tr("model.probing", lang))
        self.btn_refresh.setEnabled(False)
        worker = OllamaProbeWorker(self.edt_host.text().strip() or self.cfg.ollama.host,
                                   timeout=10.0, parent=self)
        worker.sig_done.connect(self._on_probe_done)
        worker.finished.connect(worker.deleteLater)
        self._probe = worker
        worker.start()

    def _on_probe_done(self, info: object) -> None:
        lang = self.lang_code
        ok = bool(getattr(info, "get", lambda _k, _d=None: False)("ok", False))
        self.btn_refresh.setEnabled(True)
        self._probed = True
        if ok:
            version = str(info.get("version", ""))  # type: ignore[union-attr]
            self.lbl_status.setText(tr("model.online", lang, version=version))
            self.lbl_status.setStyleSheet("color:#2E7D32;")
        else:
            error = str(info.get("error", ""))  # type: ignore[union-attr]
            self.lbl_status.setText(tr("model.offline", lang, error=error))
            self.lbl_status.setStyleSheet("color:#C62828;")
        models = list(info.get("models") or [])  # type: ignore[union-attr]
        self._fill_table(models)
        names = [str(m.get("name", "")) for m in models if m.get("name")]
        self._local_models = names
        self._fill_primary(names)

    def _fill_table(self, models: list) -> None:
        lang = self.lang_code
        self.table.setRowCount(0)
        for m in models:
            idx = self.table.rowCount()
            self.table.insertRow(idx)
            name = str(m.get("name", ""))
            details = m.get("details") or {}
            size = float(m.get("size") or 0)
            self._set(idx, 0, name)
            self._set(idx, 1, str(details.get("parameter_size") or tr("model.unknown", lang)))
            self._set(idx, 2, str(details.get("quantization_level") or tr("model.unknown", lang)))
            self._set(idx, 3, tr("model.size_gb", lang, size=size / (1024 ** 3)) if size
                      else tr("model.unknown", lang))
            self._set(idx, 4, tr("model.installed", lang))

    def _set(self, row: int, col: int, text: str) -> None:
        self.table.setItem(row, col, QTableWidgetItem(text))

    def _fill_primary(self, names: list[str]) -> None:
        self._loading = True
        current = self.cfg.ollama.model
        merged = list(names)
        if current and current not in merged:
            merged.insert(0, current)
        self.cmb_primary.clear()
        self.cmb_primary.addItems(merged)
        if current:
            self.cmb_primary.setCurrentText(current)
        self._loading = False

    # ---------------------------------------------------------------- 动作
    def _on_host_changed(self) -> None:
        host = self.edt_host.text().strip()
        if not host or host == self.cfg.ollama.host:
            return
        self.cfg.ollama.host = host
        self.cfg.save()
        self._status(tr("model.host_saved", self.lang_code, host=host))
        self.refresh()

    def _on_primary_changed(self, text: str) -> None:
        if self._loading or not text:
            return
        self.cfg.ollama.model = text
        self.cfg.save()
        self._status(tr("model.saved", self.lang_code, name=text))

    def _on_pull(self) -> None:
        name = self.cmb_pull.currentText().strip()
        if not name:
            return
        if self._pull is not None and self._pull.isRunning():
            return
        host = self.edt_host.text().strip() or self.cfg.ollama.host
        worker = ModelPullWorker(host, name, parent=self)
        worker.sig_progress.connect(self._on_pull_progress)
        worker.sig_done.connect(self._on_pull_done)
        worker.finished.connect(worker.deleteLater)
        self._pull = worker
        self.btn_pull.setEnabled(False)
        self.btn_pull_cancel.setEnabled(True)
        self.bar_pull.setRange(0, 100)
        self.bar_pull.setValue(0)
        self._status(tr("model.pulling", self.lang_code) + f" {name}")
        worker.start()

    def _on_pull_cancel(self) -> None:
        if self._pull is not None:
            self._pull.request_cancel()
        self.btn_pull_cancel.setEnabled(False)

    def _on_pull_progress(self, status: str, pct: float) -> None:
        if pct < 0:
            self.bar_pull.setRange(0, 0)          # 不确定进度：走忙碌动画
            self.bar_pull.setFormat(status or tr("model.pulling", self.lang_code))
        else:
            self.bar_pull.setRange(0, 100)
            self.bar_pull.setValue(int(pct))
            self.bar_pull.setFormat(f"{status} {pct:.1f}%" if status else f"{pct:.1f}%")

    def _on_pull_done(self, ok: bool, message: str) -> None:
        lang = self.lang_code
        self.btn_pull.setEnabled(True)
        self.btn_pull_cancel.setEnabled(False)
        self.bar_pull.setRange(0, 100)
        self._local_models = []
        if ok:
            self.bar_pull.setValue(100)
            self._status(tr("model.pull_done", lang, name=message))
            self.refresh()
            return
        if message.startswith("canceled:"):
            self._status(tr("model.pull_canceled", lang, name=message.split(":", 1)[1]))
            return
        self.bar_pull.setValue(0)
        self._status(tr("model.pull_failed", lang, error=message))

    # ---------------------------------------------------------------- 工具
    def _status(self, text: str) -> None:
        if self.main_window is not None:
            self.main_window.status(text)

    @property
    def local_models(self) -> list[str]:
        """最近一次探测到的本地模型名。"""
        return list(self._local_models)

    # ---------------------------------------------------------------- 语言
    def retranslateUi(self) -> None:  # noqa: N802 —— Qt 命名约定
        """切语言时重刷全部文案。"""
        lang = self.lang_code
        self.lang = lang
        self.lbl_host.setText(tr("model.host", lang))
        self.btn_refresh.setText(tr("model.refresh", lang))
        self.lbl_primary.setText(tr("model.primary", lang))
        self.lbl_pull_name.setText(tr("model.pull_name", lang))
        self.btn_pull.setText(tr("model.pull", lang))
        self.btn_pull_cancel.setText(tr("model.pull_cancel", lang))
        self.table.setHorizontalHeaderLabels([
            tr("model.col_name", lang),
            tr("model.col_params", lang),
            tr("model.col_quant", lang),
            tr("model.col_size", lang),
            tr("model.col_status", lang),
        ])
        if not self._probed:
            self.lbl_status.setText(tr("model.status", lang))
