"""主窗口：左侧导航 + 右侧 QStackedWidget。

切换语言时统一调用各页的 ``retranslateUi()``，实现运行时生效（无需重启）。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from ..core.config import Config
from .glossary_page import GlossaryPage
from .i18n import normalize_lang, tr
from .model_page import ModelPage
from .settings_page import SettingsPage
from .task_page import TaskPage

#: 导航项顺序 = 页面顺序
_NAV_KEYS = ("nav.task", "nav.model", "nav.glossary", "nav.settings")


class MainWindow(QMainWindow):
    """LinguaForge 桌面主窗口。"""

    def __init__(self, cfg: Config | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg or Config.load()
        self.lang = normalize_lang(self.cfg.ui_lang)

        central = QWidget(self)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.nav = QListWidget(central)
        self.nav.setFixedWidth(176)
        self.nav.setSpacing(2)
        layout.addWidget(self.nav, 0)

        self.stack = QStackedWidget(central)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.task_page = TaskPage(self.cfg, self, self.stack)
        self.model_page = ModelPage(self.cfg, self, self.stack)
        self.glossary_page = GlossaryPage(self.cfg, self, self.stack)
        self.settings_page = SettingsPage(self.cfg, self, self.stack)
        self.pages = [self.task_page, self.model_page, self.glossary_page, self.settings_page]
        for page in self.pages:
            self.stack.addWidget(page)

        for key in _NAV_KEYS:
            self.nav.addItem(tr(key, self.lang))
        self.nav.currentRowChanged.connect(self._on_nav_changed)

        self.setStatusBar(QStatusBar(self))
        self.resize(1160, 760)
        self.retranslateUi()
        self.nav.setCurrentRow(0)

    # ---------------------------------------------------------------- 导航
    def _on_nav_changed(self, index: int) -> None:
        """切换页面；页面可自行实现 on_shown() 做懒加载。"""
        if index < 0 or index >= self.stack.count():
            return
        self.stack.setCurrentIndex(index)
        page = self.pages[index]
        on_shown = getattr(page, "on_shown", None)
        if callable(on_shown):
            on_shown()

    def goto_model_page(self) -> None:
        """跳转到模型页（Ollama 不可用时的引导入口）。"""
        self.nav.setCurrentRow(1)

    def goto_page(self, index: int) -> None:
        """按索引跳转页面。"""
        self.nav.setCurrentRow(index)

    # ---------------------------------------------------------------- 语言
    def set_lang(self, code: str) -> None:
        """运行时切换界面语言，立即重刷主窗口与所有页面。"""
        code = normalize_lang(code)
        if code == self.lang:
            return
        self.lang = code
        self.cfg.ui_lang = code
        self.retranslateUi()
        for page in self.pages:
            page.retranslateUi()
        self.status(tr("app.ready", self.lang))

    # ---------------------------------------------------------------- 工具
    def status(self, message: str, timeout_ms: int = 6000) -> None:
        """状态栏提示。"""
        self.statusBar().showMessage(str(message), timeout_ms)

    def retranslateUi(self) -> None:  # noqa: N802 —— Qt 命名约定
        """重刷主窗口自身文案（窗口标题与导航）。"""
        self.setWindowTitle(f"{tr('app.title', self.lang)}")
        labels: list[str] = [tr(k, self.lang) for k in _NAV_KEYS]
        for i, text in enumerate(labels):
            item = self.nav.item(i)
            if item is not None:
                item.setText(text)

    # ---------------------------------------------------------------- 关闭
    def closeEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """退出前持久化配置。"""
        try:
            self.cfg.save()
        except OSError as exc:
            self.status(f"配置保存失败: {exc}")
        super().closeEvent(event)
