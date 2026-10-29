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
    """兜底：崩溃信息落盘，方便用户把日志发回来。"""
    try:
        from platformdirs import user_data_dir

        d = Path(user_data_dir("LinguaForge", "LinguaForge"))
        d.mkdir(parents=True, exist_ok=True)
        (d / "logs").mkdir(exist_ok=True)
        with open(d / "logs" / "crash.log", "a", encoding="utf-8") as fh:
            fh.write(f"\n==== {_now()} ====\n")
            traceback.print_exception(exc_type, exc, tb, file=fh)
        path = d / "logs" / "crash.log"
    except Exception:  # noqa: BLE001
        path = Path("?")
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        QApplication.instance() or QApplication(sys.argv)  # 保活引用，无需变量
        QMessageBox.critical(
            None,
            "LinguaForge 遇到未处理的错误",
            f"{exc_type.__name__}: {exc}\n\n详细信息已写入：\n{path}",
        )
    except Exception:  # noqa: BLE001
        sys.__excepthook__(exc_type, exc, tb)


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


def main() -> int:
    _setup_frozen()
    sys.excepthook = _dump_crash

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
