"""LinguaForge 桌面端 GUI 入口。

这是 PyInstaller 打包的入口脚本：它只负责把 UI 拉起来，
业务逻辑一律在 linguaforge 包里，保证打包前后行为一致。

设计要点：
    · 冻结运行（PyInstaller）时 sys.argv[0] 是 exe 路径，工作目录不可靠，
      因此所有资源路径都必须基于 sys._MEIPASS / 可执行文件目录解析。
    · 未捕获异常先写日志再提示，避免"双击没反应"这种最难排查的故障。
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _setup_frozen() -> None:
    """冻结运行时把包根目录塞进 sys.path。

    注意：**不要**在这里切换工作目录。GUI 模式下工作目录可能是 Program Files
    （只读），确有切走的需要，但那会把 CLI 的相对路径语义也改掉——用户在命令行里
    敲的相对路径会突然找不到文件。因此切目录只发生在 GUI 分支（见 main）。
    """
    if not getattr(sys, "frozen", False):
        return
    meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    if str(meipass) not in sys.path:
        sys.path.insert(0, str(meipass))


def _dump_crash(exc_type, exc, tb) -> None:
    """兜底：崩溃落盘 + 提示，绝不"双击没反应"。

    落盘走 :func:`linguaforge.core.logging.log_crash`，与常规日志同目录
    （``<data>/logs/crash.log``），用户一次打包即可把现场发回来。

    KeyboardInterrupt 不拦截：Ctrl-C 是正常的退出信号，不应该弹窗。
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return

    path = Path("?")
    try:
        from linguaforge.core.logging import log_crash

        path = log_crash(exc_type, exc, tb)
    except Exception:  # noqa: BLE001
        path = _fallback_crash(exc_type, exc, tb)

    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        QApplication.instance() or QApplication(sys.argv)  # 保活引用，无需变量
        QMessageBox.critical(
            None,
            "LinguaForge 遇到未处理的错误",
            f"{exc_type.__name__}: {exc}\n\n详细信息已写入：\n{path}",
        )
    except Exception:  # noqa: BLE001 —— 无 GUI / 离屏时退回默认钩子
        sys.__excepthook__(exc_type, exc, tb)


def _fallback_crash(exc_type, exc, tb) -> Path:
    """统一日志模块也挂了时的最后手段：直接写到用户数据目录。"""
    try:
        from platformdirs import user_data_dir

        d = Path(user_data_dir("LinguaForge", "LinguaForge")) / "logs"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "crash.log"
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(f"\n==== {_now()} ====\n")
            traceback.print_exception(exc_type, exc, tb, file=fh)
        return p
    except Exception:  # noqa: BLE001
        return Path("?")


def _now() -> str:
    import datetime

    return datetime.datetime.now().isoformat(timespec="seconds")


def _force_utf8_console() -> None:
    """Windows 控制台默认按 GBK 解码 UTF-8 输出，中文进度会变乱码。

    仅在输出被重定向（管道/文件）时还不够——交互时同样要处理，
    所以直接把 stdin/stdout/stderr 重新配置为 UTF-8。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def _is_cli() -> bool:
    """判断当前应该走命令行还是图形界面。

    GUI 与 CLI 在 PyInstaller 里共用一个 Analysis（避免重复静态分析、
    体积翻倍），靠可执行文件名分流：linguaforge-cli.exe -> 命令行。
    """
    name = Path(sys.executable).stem.lower()
    return "cli" in name


def _bootstrap() -> None:
    """启动时的一次性初始化：日志落盘 + 残留分片清扫。

    两者都吞异常——它们属于"锦上添花"，绝不能挡住主流程启动。
    """
    sys.excepthook = _dump_crash  # 越早装越好，下面的初始化出错也能被兜住
    try:
        from linguaforge.core.logging import setup_logging

        # GUI（console=False）下 stderr 为 None，这里显式关掉控制台 sink
        setup_logging(console=_is_cli())
    except Exception:  # noqa: BLE001
        pass
    try:
        from linguaforge.core.paths import sweep_orphan_tmpdirs

        sweep_orphan_tmpdirs()
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    _setup_frozen()
    _bootstrap()

    if _is_cli():
        # 命令行：保持调用者的工作目录，相对路径才符合用户预期
        _force_utf8_console()  # 否则 Windows 控制台按 GBK 解码，中文进度全是乱码
        from linguaforge.cli import main as cli_main

        return cli_main(sys.argv[1:])

    # GUI：安装目录往往只读，切到用户目录，避免相对路径写文件失败
    try:
        os.chdir(Path.home())
    except Exception:  # noqa: BLE001
        pass
    from linguaforge.ui import main as ui_main

    return ui_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
