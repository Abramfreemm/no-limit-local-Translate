"""设置页：界面语言、Ollama 地址、OCR、性能窗口、默认输出。

改动写回 Config 并落盘（Config.save -> 用户数据目录 config.json）；
界面语言切换立即生效（通过主窗口 set_lang 触发各页 retranslateUi）。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.config import LANG_NAMES
from .i18n import LANGS, tr
from .worker import OUTPUT_FORMATS

#: 可选目标语言（排除 auto）
TARGET_LANGS = [k for k in LANG_NAMES if k != "auto"]


class SettingsPage(QWidget):
    """设置页。"""

    def __init__(self, cfg, main_window=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.main_window = main_window
        self.lang = getattr(cfg, "ui_lang", "zh-CN") or "zh-CN"
        self._loading = True
        self._build_ui()
        self._load_from_cfg()
        self._loading = False
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

        # ---- 界面 ----
        self.box_ui = QGroupBox()
        form_ui = QFormLayout(self.box_ui)
        self.cmb_lang = QComboBox()
        for code, name in LANGS:
            self.cmb_lang.addItem(name, code)
        self.cmb_target = QComboBox()
        self.cmb_target.addItems(TARGET_LANGS)
        self.lbl_lang = QLabel()
        self.lbl_target = QLabel()
        form_ui.addRow(self.lbl_lang, self.cmb_lang)
        form_ui.addRow(self.lbl_target, self.cmb_target)
        root.addWidget(self.box_ui)

        # ---- 引擎 ----
        self.box_engine = QGroupBox()
        form_eng = QFormLayout(self.box_engine)
        self.edt_host = QLineEdit()
        self.chk_ocr = QCheckBox()
        self.spn_dpi = QSpinBox()
        self.spn_dpi.setRange(72, 600)
        self.spn_dpi.setSingleStep(10)
        self.lbl_host = QLabel()
        self.lbl_dpi = QLabel()
        form_eng.addRow(self.lbl_host, self.edt_host)
        form_eng.addRow(self.chk_ocr, QWidget())
        form_eng.addRow(self.lbl_dpi, self.spn_dpi)
        root.addWidget(self.box_engine)

        # ---- 性能 ----
        self.box_perf = QGroupBox()
        form_perf = QFormLayout(self.box_perf)
        self.spn_pages = QSpinBox()
        self.spn_pages.setRange(1, 500)
        self.spn_chars = QSpinBox()
        self.spn_chars.setRange(1000, 200000)
        self.spn_chars.setSingleStep(1000)
        self.lbl_pages = QLabel()
        self.lbl_chars = QLabel()
        form_perf.addRow(self.lbl_pages, self.spn_pages)
        form_perf.addRow(self.lbl_chars, self.spn_chars)
        root.addWidget(self.box_perf)

        # ---- 输出 ----
        self.box_out = QGroupBox()
        form_out = QFormLayout(self.box_out)
        self.cmb_fmt = QComboBox()
        self.cmb_fmt.addItems(list(OUTPUT_FORMATS))
        self.chk_bilingual = QCheckBox()
        self.lbl_fmt = QLabel()
        form_out.addRow(self.lbl_fmt, self.cmb_fmt)
        form_out.addRow(self.chk_bilingual, QWidget())
        root.addWidget(self.box_out)

        bar = QHBoxLayout()
        self.btn_apply = QPushButton()
        self.btn_reset = QPushButton()
        bar.addWidget(self.btn_apply)
        bar.addWidget(self.btn_reset)
        bar.addStretch(1)
        root.addLayout(bar)
        root.addStretch(1)

        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_reset.clicked.connect(self._on_reset)
        self.cmb_lang.currentIndexChanged.connect(self._on_lang_changed)

    # ---------------------------------------------------------------- 读写
    def _load_from_cfg(self) -> None:
        self._loading = True
        idx = self.cmb_lang.findData(self.cfg.ui_lang)
        if idx >= 0:
            self.cmb_lang.setCurrentIndex(idx)
        self.cmb_target.setCurrentText(self.cfg.lang_dst)
        self.edt_host.setText(self.cfg.ollama.host)
        self.chk_ocr.setChecked(bool(self.cfg.ocr.enabled))
        self.spn_dpi.setValue(int(self.cfg.ocr.dpi))
        self.spn_pages.setValue(int(self.cfg.perf.window_pages))
        self.spn_chars.setValue(int(self.cfg.perf.window_chars))
        self.cmb_fmt.setCurrentText(self.cfg.output.fmt)
        self.chk_bilingual.setChecked(bool(self.cfg.output.bilingual))
        self._loading = False

    def _on_apply(self) -> None:
        cfg = self.cfg
        cfg.lang_dst = self.cmb_target.currentText()
        cfg.ollama.host = self.edt_host.text().strip() or cfg.ollama.host
        cfg.ocr.enabled = self.chk_ocr.isChecked()
        cfg.ocr.dpi = int(self.spn_dpi.value())
        cfg.perf.window_pages = int(self.spn_pages.value())
        cfg.perf.window_chars = int(self.spn_chars.value())
        cfg.output.fmt = self.cmb_fmt.currentText()
        cfg.output.bilingual = self.chk_bilingual.isChecked()
        cfg.ui_lang = str(self.cmb_lang.currentData() or cfg.ui_lang)
        path = cfg.save()
        self._status(tr("settings.saved", self.lang_code, path=str(path)))
        if self.main_window is not None:
            self.main_window.set_lang(cfg.ui_lang)

    def _on_reset(self) -> None:
        from ..core.config import Config

        fresh = Config()
        fresh.ui_lang = self.cfg.ui_lang
        self.cfg.ollama.host = fresh.ollama.host
        self.cfg.ocr.enabled = fresh.ocr.enabled
        self.cfg.ocr.dpi = fresh.ocr.dpi
        self.cfg.perf.window_pages = fresh.perf.window_pages
        self.cfg.perf.window_chars = fresh.perf.window_chars
        self.cfg.output.fmt = fresh.output.fmt
        self.cfg.output.bilingual = fresh.output.bilingual
        self.cfg.lang_dst = fresh.lang_dst
        self._load_from_cfg()
        self._status(tr("settings.reset_done", self.lang_code))

    def _on_lang_changed(self, _index: int) -> None:
        """语言下拉一变就立即切换界面语言（不落盘，等「应用并保存」）。"""
        if self._loading:
            return
        code = str(self.cmb_lang.currentData() or "zh-CN")
        if self.main_window is not None:
            self.main_window.set_lang(code)

    # ---------------------------------------------------------------- 工具
    def _status(self, text: str) -> None:
        if self.main_window is not None:
            self.main_window.status(text)

    # ---------------------------------------------------------------- 语言
    def retranslateUi(self) -> None:  # noqa: N802 —— Qt 命名约定
        """切语言时重刷全部文案。"""
        lang = self.lang_code
        self.lang = lang
        self.box_ui.setTitle(tr("settings.section_ui", lang))
        self.box_engine.setTitle(tr("settings.section_engine", lang))
        self.box_perf.setTitle(tr("settings.section_perf", lang))
        self.box_out.setTitle(tr("settings.section_out", lang))
        self.lbl_lang.setText(tr("settings.lang", lang))
        self.lbl_target.setText(tr("settings.target", lang))
        self.lbl_host.setText(tr("settings.host", lang))
        self.lbl_dpi.setText(tr("settings.dpi", lang))
        self.lbl_pages.setText(tr("settings.window_pages", lang))
        self.lbl_chars.setText(tr("settings.window_chars", lang))
        self.lbl_fmt.setText(tr("settings.default_fmt", lang))
        self.chk_ocr.setText(tr("settings.ocr", lang))
        self.chk_bilingual.setText(tr("settings.bilingual", lang))
        self.btn_apply.setText(tr("settings.apply", lang))
        self.btn_reset.setText(tr("settings.reset", lang))
        for i, (_code, name) in enumerate(LANGS):
            self.cmb_lang.setItemText(i, name)
