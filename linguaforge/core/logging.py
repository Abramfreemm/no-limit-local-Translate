"""日志落盘与脱敏（19 号 §4 落地实现）。

解决的问题
----------
GUI 以 ``console=False`` 打包，未捕获异常的 traceback 直接消失，
用户只看到闪退，无法反馈。此前 loguru 在依赖清单里，但全代码库
**没有任何一处** ``logger.add(...)`` —— 等于没装。

隐私红线（硬约束，违反视为缺陷）
------------------------------
- **绝不记录正文内容**（原文或译文）
- 路径只记 ``文件名 + 短哈希``，不记完整路径
- 不记录术语表的术语与译法（可能含商业敏感信息）
- Ollama 请求只记模型名、耗时、条数、状态码，不记 payload

使用
----
>>> from linguaforge.core.logging import setup_logging, get_logger
>>> setup_logging()            # 应用启动时调一次
>>> log = get_logger(__name__)
>>> log.info("hello")
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = [
    "setup_logging",
    "get_logger",
    "redact_path",
    "log_dir",
    "crash_file",
    "diagnostics",
    "LOG_FORMAT",
]

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

ROTATION = "10 MB"
RETENTION = "14 days"
_COMPRESSION = "gz"

_initialized = False
_console_sink_id: int | None = None


def log_dir() -> Path:
    """日志目录。优先用 paths 模块的统一位置。"""
    from .paths import app_log_dir

    return app_log_dir()


def crash_file() -> Path:
    """崩溃日志文件路径（与常规日志同目录，便于用户一次打包发回）。"""
    return log_dir() / "crash.log"


def diagnostics() -> dict[str, str]:
    """收集诊断信息：版本、平台、Python、内存、CPU、frozen 状态。

    只含环境元数据，**绝不含**文档路径与正文。供崩溃日志与「关于」面板复用。
    """
    import os
    import platform
    import sys

    info: dict[str, str] = {
        "app": "LinguaForge",
        "version": _app_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "frozen": str(bool(getattr(sys, "frozen", False))),
        "cwd": os.getcwd(),
        "pid": str(os.getpid()),
        "cpu_count": str(os.cpu_count() or 0),
        "memory_total_gb": "",
        "memory_available_gb": "",
    }
    try:
        import psutil

        vm = psutil.virtual_memory()
        info["memory_total_gb"] = f"{vm.total / (1 << 30):.1f}"
        info["memory_available_gb"] = f"{vm.available / (1 << 30):.1f}"
    except Exception:  # noqa: BLE001 —— psutil 可选，缺失不影响诊断
        pass
    return info


def diagnostics_text() -> str:
    """诊断信息的可读文本形式。"""
    return "\n".join(f"{k:>20}: {v}" for k, v in diagnostics().items())


def _app_version() -> str:
    """读取应用版本；取不到时回退 dev。"""
    try:
        from importlib.metadata import version

        return version("linguaforge")
    except Exception:  # noqa: BLE001
        return "dev"


def redact_path(path: str | Path) -> str:
    """把路径脱敏为 ``<文件名>#<hash8>``。

    既保留"哪个文件"的可读性，又不泄露用户的目录结构
    （用户目录名常含姓名、公司名等）。

    >>> redact_path("/Users/alice/secret/report.pdf")
    'report.pdf#1a2b3c4d'
    """
    from .paths import short_hash

    p = Path(str(path))
    return f"{p.name}#{short_hash(str(p))}"


def _detect_level() -> str:
    """从环境变量取日志级别，缺省 INFO。"""
    import os

    return os.environ.get("LINGUAFORGE_LOG_LEVEL", "INFO").upper()


def setup_logging(*, console: bool | None = None, level: str | None = None) -> Path:
    """初始化日志：文件（轮转 + 压缩）+ 可选控制台。

    幂等：重复调用不会重复添加 sink（控制台 sink 也只加一次）。
    返回日志文件所在目录，便于 UI 上「打开日志目录」。

    :param console: 是否输出到 stderr。缺省时按 ``sys.stderr`` 是否可用判断
                    （GUI ``console=False`` 打包时 stderr 为 None）
    """
    global _initialized, _console_sink_id
    from loguru import logger

    d = log_dir()
    if not _initialized:
        logger.remove()  # 去掉默认 stderr sink，改为显式控制
        logger.add(
            d / "linguaforge_{time:YYYY-MM-DD}.log",
            level=level or _detect_level(),
            format=LOG_FORMAT,
            rotation=ROTATION,
            retention=RETENTION,
            compression=_COMPRESSION,
            encoding="utf-8",
            enqueue=True,  # 多进程/多线程安全
            backtrace=True,
            diagnose=False,  # 不打印局部变量，避免泄露正文
        )
        _initialized = True

    if console is None:
        console = sys.stderr is not None
    if console:
        if _console_sink_id is None:
            _console_sink_id = logger.add(sys.stderr, level="WARNING", format=LOG_FORMAT)
    elif _console_sink_id is not None:
        # 显式要求关闭控制台输出时，把之前加的 sink 摘掉
        try:
            logger.remove(_console_sink_id)
        except Exception:  # noqa: BLE001
            pass
        _console_sink_id = None

    return d


def log_crash(exc_type, exc, tb) -> Path:
    """把未捕获异常写入统一崩溃日志，返回文件路径；写失败返回 ``Path("?")``。

    与常规日志分开成 ``crash.log``：崩溃现场需要**完整的 traceback**（含
    局部变量上下文），而常规日志受 ``diagnose=False`` 约束。
    崩溃场景是用户主动排查，优先级高于脱敏。
    """
    import datetime
    import traceback

    path = Path("?")
    try:
        path = crash_file()
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"\n==== {stamp} ====\n")
            fh.write(f"{diagnostics_text()}\n")
            fh.write("-" * 60 + "\n")
            traceback.print_exception(exc_type, exc, tb, file=fh)
    except Exception:  # noqa: BLE001 —— 兜底不能再抛
        pass

    try:
        from loguru import logger

        logger.error(
            "未捕获异常: {}: {}",
            getattr(exc_type, "__name__", exc_type),
            exc,
        )
    except Exception:  # noqa: BLE001
        pass
    return path


def get_logger(name: str = "linguaforge"):
    """取 logger。尚未初始化时按默认配置兜底，避免静默丢日志。"""
    from loguru import logger

    if not _initialized:
        setup_logging(console=False)
    return logger.bind(name=name)
