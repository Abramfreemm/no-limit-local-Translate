"""应用启动层：QApplication 生命周期、单实例、全局异常兜底、日志落盘。

不 import 任何页面模块以外的内核逻辑；业务全部交给 pipeline。
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from ..core.config import Config
from ..core.logging import get_logger, log_crash, setup_logging

try:  # QtNetwork 可能随发行版裁剪，缺失时优雅降级为「不做单实例」
    from PySide6.QtNetwork import QLocalServer, QLocalSocket

    _HAS_QTNETWORK = True
except ImportError:  # pragma: no cover —— 正常安装不会走到
    QLocalServer = None  # type: ignore[assignment]
    QLocalSocket = None  # type: ignore[assignment]
    _HAS_QTNETWORK = False

LOGGER_NAME = "linguaforge.ui"
_SERVER_NAME = "LinguaForge-UI-SingleInstance"

#: 全局只弹一次的崩溃提示，避免异常风暴刷屏
_crash_dialog_shown = False

#: 持有长生命周期对象，防止被 GC（QLocalServer 被回收后监听即失效）
_STATE: dict = {}


# ---------------------------------------------------------------- 日志
def init_logging() -> Path:
    """把日志落到统一目录，返回日志**目录**。

    实现委托给 :func:`linguaforge.core.logging.setup_logging`（loguru，
    10 MB 轮转 / 14 天保留 / gz 压缩 / 多进程安全 / diagnose=False）。

    GUI 以 ``console=False`` 打包时 stderr 为 None，因此这里显式关掉
    控制台 sink —— 既避免 loguru 往空句柄写，也避免污染 CLI 输出。
    """
    return setup_logging(console=False)


# ---------------------------------------------------------------- 异常兜底
def _show_crash_dialog(text: str) -> None:
    """弹一次崩溃提示；无 GUI / 离屏 / 非主线程时只写日志，不弹窗。"""
    global _crash_dialog_shown
    if _crash_dialog_shown:
        return
    app = QApplication.instance()
    if app is None:
        return
    from PySide6.QtCore import QThread
    from PySide6.QtGui import QGuiApplication

    if QThread.currentThread() is not app.thread():
        return
    if QGuiApplication.platformName() == "offscreen":
        return
    _crash_dialog_shown = True
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("LinguaForge — 未捕获异常")
    box.setText("程序遇到未处理的异常，详情已写入日志。\n\n" + text[-1200:])
    box.exec()


def install_excepthook() -> None:
    """接管 sys.excepthook：写崩溃日志 + 弹一次提示，绝不静默崩溃。"""

    def _hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            log_crash(exc_type, exc, tb)
        except Exception as diag_exc:  # noqa: BLE001 —— 兜底不能再抛
            get_logger(LOGGER_NAME).error("崩溃落盘失败: {}", diag_exc)
        try:
            _show_crash_dialog(text)
        except Exception as diag_exc:  # noqa: BLE001 —— 兜底不能再抛
            get_logger(LOGGER_NAME).error("崩溃弹窗失败: {}", diag_exc)

    sys.excepthook = _hook


# ---------------------------------------------------------------- 单实例
def _acquire_single_instance(name: str = _SERVER_NAME) -> tuple[bool, object | None]:
    """尝试成为唯一实例。

    返回 ``(是否拥有, server)``。已有实例在跑时返回 ``(False, None)``；
    QtNetwork 不可用时返回 ``(True, None)``（降级为不做单实例）。
    """
    if not _HAS_QTNETWORK:
        return True, None

    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(300):
        try:
            sock.write(b"raise")
            sock.flush()
            sock.waitForBytesWritten(300)
            sock.disconnectFromServer()
        except OSError as exc:
            get_logger(LOGGER_NAME).warning("通知已有实例失败: {}", exc)
        return False, None

    QLocalServer.removeServer(name)
    server = QLocalServer()
    if not server.listen(name):
        get_logger(LOGGER_NAME).warning("单实例监听失败: {}", server.errorString())
        return True, None
    return True, server


def _raise_window(win) -> None:
    """被第二个实例唤醒时把窗口提到前台。"""
    win.show()
    win.raise_()
    win.activateWindow()


# ---------------------------------------------------------------- 参数
def _parse_args(argv: list | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="linguaforge-ui", add_help=True)
    ap.add_argument("--lang", default="", help="界面语言：zh-CN / en-US")
    ap.add_argument("--no-single-instance", action="store_true", help="禁用单实例检查")
    args, _unknown = ap.parse_known_args(list(sys.argv[1:] if argv is None else argv))
    return args


# ---------------------------------------------------------------- 入口
def main(argv=None) -> int:
    """GUI 入口，返回进程退出码。"""
    args = _parse_args(argv)
    log_dir = init_logging()
    log = get_logger(LOGGER_NAME)
    install_excepthook()
    log.info("启动 LinguaForge UI，日志目录: {}", log_dir)

    argv_list = list(sys.argv if argv is None else ["linguaforge-ui", *argv])
    app = QApplication.instance() or QApplication(argv_list)
    app.setApplicationName("LinguaForge")
    app.setOrganizationName("LinguaForge")

    owned = True
    server = None
    if not args.no_single_instance:
        owned, server = _acquire_single_instance()
    if not owned:
        log.info("检测到已有实例在运行，本次退出")
        return 0
    if server is not None:
        _STATE["server"] = server

    cfg = Config.load()
    if args.lang:
        cfg.ui_lang = args.lang

    from .main_window import MainWindow  # 延迟导入：QApplication 已就绪

    win = MainWindow(cfg)
    _STATE["window"] = win
    if server is not None:
        server.newConnection.connect(lambda: _raise_window(win))
    win.show()

    code = app.exec()
    try:
        cfg.save()
    except OSError as exc:
        log.error("配置保存失败: {}", exc)
    log.info("退出，code={}", code)
    return int(code)
