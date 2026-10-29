"""环境健康条（旅程 E 落地）。

解决的问题
----------
用户点了「开始翻译」，30 秒后红字报错说 Ollama 没启动。这个反馈来得太晚——
文件已经解析了一半，时间已经花了。旅程 E 要求把失败**前移**到用户还没投入
成本之前，用一条常驻的健康条把环境状态摊开。

设计取舍
--------
1. **红黄绿三档，不弹窗**。健康条是「背景状态」而非「紧急事件」，弹窗会
   打断操作，与"常驻可查"的诉求相悖。
2. **点击可跳转**。发现问题的价值在于能一键去解决，所以每一项都带动作：
   Ollama / 模型问题 -> 跳模型页；磁盘问题 -> 提示清理。只报不治等于没报。
3. **检测放后台线程**。Ollama 探测是 HTTP 请求，网络不通时可能卡数秒，
   放主线程会让界面假死，比"不检测"更糟。
4. **失败时降级为"未知"而非"错误"**。检测过程本身崩了（比如缺 psutil）
   不代表环境有问题，标红是误报。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr


#: 健康档位。值与样式表一一对应，改样式只需改 _STYLE 一处。
class Level(StrEnum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"
    UNKNOWN = "unknown"
    CHECKING = "checking"


_STYLE = {
    Level.OK: ("#0F7B3F", "#E8F6EC"),
    Level.WARN: ("#B26A00", "#FFF6E5"),
    Level.ERROR: ("#B42318", "#FDECEA"),
    Level.UNKNOWN: ("#667085", "#F2F4F7"),
    Level.CHECKING: ("#175CD3", "#EFF4FF"),
}

#: 档位 -> 圆点字符。用文本而非图片，避免打包资源与高分屏模糊问题。
_DOT = {
    Level.OK: "●",
    Level.WARN: "●",
    Level.ERROR: "●",
    Level.UNKNOWN: "○",
    Level.CHECKING: "◐",
}

#: 磁盘剩余空间低于此值即黄灯提示（GB）
_DISK_WARN_GB = 5.0


@dataclass
class CheckItem:
    """一项检查结果。

    存的是 i18n **键 + 参数**而不是渲染后的文本：这样运行时切语言
    （MainWindow.set_lang -> retranslateUi）能立刻把状态文案也一起刷掉，
    而不是只刷了项目名、状态还停留在旧语言。

    Attributes:
        key: 稳定标识，用于点击回调分发与测试断言
        level: 健康档位
        text_key: 状态文案的 i18n 键
        params: 文案模板变量
        action: 该项可跳转的目标标识，None 表示不可点
    """

    key: str
    level: Level = Level.UNKNOWN
    text_key: str = ""
    params: dict = field(default_factory=dict)
    action: str | None = None

    def text(self, lang: str) -> str:
        """按目标语言渲染状态文案。"""
        if not self.text_key:
            return ""
        try:
            return tr(self.text_key, lang, **self.params)
        except (KeyError, IndexError, ValueError):
            return tr(self.text_key, lang)


def run_checks(cfg, out_dir: Path | str | None = None) -> list[CheckItem]:
    """跑全部环境检查。

    纯函数式（无 Qt 依赖），便于在 CLI 与单测里直接调用。

    :param cfg: :class:`~linguaforge.core.config.Config`
    :param out_dir: 输出目录，缺省时取用户数据目录所在盘
    """
    from ..core.preflight import check_disk, check_ocr, check_ollama, probe_ollama_version
    from ..core.problems import Code

    items: list[CheckItem] = []

    # ---- 1) Ollama 服务 ----
    probs, models = check_ollama(cfg)
    codes = {p.code for p in probs}
    if Code.OLLAMA_UNREACHABLE in codes or Code.OLLAMA_NOT_INSTALLED in codes:
        lvl = Level.ERROR
        key = (
            "health.ollama.not_installed"
            if Code.OLLAMA_NOT_INSTALLED in codes
            else "health.ollama.err"
        )
        params = {}
    elif Code.OLLAMA_OLD_VERSION in codes:
        lvl, key, params = Level.WARN, "health.ollama.warn", {}
    else:
        # 连接正常：再取一次版本用于展示（不可达时不会走到这里）
        host = str(getattr(getattr(cfg, "ollama", None), "host", "") or "")
        ver = probe_ollama_version(host) if host else ""
        lvl, key = Level.OK, "health.ollama.ok"
        params = {"version": ver or "-"}
    items.append(CheckItem("ollama", lvl, key, params, action="model"))
    reachable = lvl != Level.ERROR

    # ---- 2) 翻译模型 ----
    # 连不上 Ollama 时模型列表为空，此时**不能**判定为"已就绪"——
    # 拿不到名单不代表模型在，标绿是纯粹的误报。
    primary = str(getattr(getattr(cfg, "ollama", None), "model", "") or "")
    missing = Code.MODEL_MISSING in codes
    if not reachable:
        lvl, key, params = Level.UNKNOWN, "health.model.unknown", {}
    elif not primary:
        lvl, key, params = Level.UNKNOWN, "common.unknown", {}
    elif missing:
        has_fallback = bool(models)
        lvl = Level.WARN if has_fallback else Level.ERROR
        key = "health.model.warn" if has_fallback else "health.model.err"
        params = {"model": primary}
    else:
        lvl, key = Level.OK, "health.model.ok"
        params = {"model": primary}
    items.append(CheckItem("model", lvl, key, params, action="model"))

    # ---- 3) 磁盘空间 / 目录可写 ----
    try:
        target = Path(out_dir) if out_dir else _default_out_dir(cfg)
        dprobs = check_disk(target, [])
        free = _free_gb(target)
        gb = f"{free:.1f}"
        if any(p.code == Code.DIR_NOT_WRITABLE for p in dprobs) or (
            any(p.code == Code.DISK_INSUFFICIENT for p in dprobs)
        ):
            lvl = Level.ERROR
        elif free < _DISK_WARN_GB:
            lvl = Level.WARN
        else:
            lvl = Level.OK
        key, params = f"health.disk.{lvl}", {"gb": gb}
    except Exception:  # noqa: BLE001 —— 检测失败降级为未知，不误报
        lvl, key, params = Level.UNKNOWN, "common.unknown", {}
    items.append(CheckItem("disk", lvl, key, params, action="settings"))

    # ---- 4) OCR 组件 ----
    try:
        oprobs = check_ocr(cfg)
        lvl = Level.WARN if oprobs else Level.OK
        key, params = f"health.ocr.{lvl}", {}
    except Exception:  # noqa: BLE001
        lvl, key, params = Level.UNKNOWN, "common.unknown", {}
    items.append(CheckItem("ocr", lvl, key, params, action="settings"))

    return items


def _default_out_dir(cfg) -> Path:
    from ..core.config import default_data_dir

    return Path(default_data_dir())


def _free_gb(path: Path) -> float:
    import shutil

    usage = shutil.disk_usage(str(path))
    return usage.free / (1 << 30)


class HealthChip(QLabel):
    """一个可点击的状态胶囊。带下划线表示可跳转。"""

    sig_clicked = Signal(str)

    def __init__(self, item: CheckItem, lang: str = "zh-CN", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item: CheckItem = item
        self.action: str | None = item.action
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if item.action else Qt.CursorShape.ArrowCursor
        )
        self.set_item(item, lang)

    def set_item(self, item: CheckItem, lang: str = "zh-CN") -> None:
        """按 CheckItem 与目标语言重绘。"""
        self.item = item
        self.action = item.action
        fg, bg = _STYLE[item.level]
        name = tr(f"health.item.{item.key}", lang)
        body = item.text(lang) or tr("common.unknown", lang)
        detail = f"<span style='color:{fg}'>{body}</span>"
        if item.action:
            detail = f"<u>{detail}</u>"
        self.setText(
            f"<span style='color:#344054'>{name}</span> "
            f"<span style='color:{fg}'>{_DOT[item.level]}</span> {detail}"
        )
        self.setStyleSheet(
            f"QLabel{{background:{bg};border:1px solid {bg};border-radius:10px;padding:4px 10px;}}"
        )
        self.setToolTip(body)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """点击时把 action 发回去；无动作则忽略。"""
        if self.action:
            self.sig_clicked.emit(self.action)
        super().mouseReleaseEvent(event)


class HealthBar(QFrame):
    """环境健康条：三个状态胶囊 + 重新检测按钮 + 问题摘要。

    信号：
        sig_action(name) —— 用户点击了某项，name ∈ {model, settings}
    """

    sig_action = Signal(str)

    def __init__(self, cfg=None, main_window=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.main_window = main_window
        self._items: list[CheckItem] = []
        self._worker = None
        #: 是否跑过一次检测。未检测时不能显示"一切就绪"——没有数据不等于健康
        self._checked = False
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._build_ui()
        self.retranslateUi()

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet("font-weight:600;color:#344054;")
        top.addWidget(self.lbl_title)

        lang = self._lang()
        self._chips: dict[str, HealthChip] = {}
        for key in ("ollama", "model", "disk", "ocr"):
            chip = HealthChip(CheckItem(key, Level.CHECKING, tr("health.checking", lang)), lang)
            chip.sig_clicked.connect(self.sig_action)
            self._chips[key] = chip
            top.addWidget(chip)

        top.addStretch(1)

        self.btn_recheck = QPushButton()
        self.btn_recheck.setFixedWidth(96)
        self.btn_recheck.clicked.connect(self.refresh)
        top.addWidget(self.btn_recheck)
        root.addLayout(top)

        self.lbl_summary = QLabel()
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_summary.setStyleSheet("color:#475467;")
        root.addWidget(self.lbl_summary)

    # ---------------------------------------------------------------- 检测
    def refresh(self) -> None:
        """后台重跑检查。Ollama 探测是网络请求，必须避开主线程。"""
        from .worker import CallWorker

        lang = self._lang()
        self.btn_recheck.setEnabled(False)
        for key, chip in self._chips.items():
            chip.set_item(
                CheckItem(key, Level.CHECKING, tr("health.checking", lang), action=chip.action),
                lang,
            )
        self._worker = CallWorker(lambda: run_checks(self.cfg))
        self._worker.sig_result.connect(self._on_result)
        self._worker.sig_error.connect(self._on_error)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_result(self, items) -> None:
        self._items = list(items or [])
        self._checked = True
        for it in self._items:
            chip = self._chips.get(it.key)
            if chip is not None:
                chip.set_item(it)
        self._render_summary()

    def _on_error(self, message: str) -> None:
        self._render_summary(message)

    def _on_done(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        self._worker = None
        self.btn_recheck.setEnabled(True)

    # ---------------------------------------------------------------- 渲染
    def _lang(self) -> str:
        """当前界面语言：优先主窗口，保证切语言后同步。"""
        return getattr(self.main_window, "lang", None) or "zh-CN"

    def _render_summary(self, error: str = "") -> None:
        lang = self._lang()
        if error:
            self.lbl_summary.setText(f"<span style='color:#B42318'>{error}</span>")
            return
        if not self._checked:
            self.lbl_summary.setText(tr("health.not_checked", lang))
            return
        if not self._items:
            self.lbl_summary.setText(tr("health.all_ok", lang))
            return

        bad = [i for i in self._items if i.level in (Level.ERROR, Level.WARN)]
        if not bad:
            self.lbl_summary.setText(tr("health.all_ok", lang))
            return

        head = tr("health.issues", lang, n=len(bad))
        lines = "".join(
            f"<div>· <b>{tr(f'health.item.{i.key}', lang)}</b> — "
            f"<span style='color:{_STYLE[i.level][0]}'>{i.text(lang)}</span></div>"
            for i in bad
        )
        hint = tr("health.fix_hint", lang)
        self.lbl_summary.setText(f"<div>{head}</div>{lines}<div style='color:#98A2B3'>{hint}</div>")

    def has_blocker(self) -> bool:
        """是否存在阻断级问题（供「开始翻译」按钮做前置判断）。"""
        return any(i.level == Level.ERROR for i in self._items)

    # ---------------------------------------------------------------- 语言
    def retranslateUi(self) -> None:  # noqa: N802 —— Qt 命名约定
        """重刷文案与各项名称。"""
        lang = getattr(self.main_window, "lang", None) or "zh-CN"
        self.lbl_title.setText(tr("health.title", lang))
        self.btn_recheck.setText(tr("health.recheck", lang))
        for key, chip in self._chips.items():
            cur = next((i for i in self._items if i.key == key), None)
            chip.set_item(cur or CheckItem(key, Level.UNKNOWN, tr("common.unknown", lang)))
        self._render_summary()


__all__ = ["Level", "CheckItem", "HealthChip", "HealthBar", "run_checks"]
