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

__all__ = ["setup_logging", "get_logger", "redact_path", "log_dir", "LOG_FORMAT"]

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

ROTATION = "10 MB"
RETENTION = "14 days"
_COMPRESSION = "gz"

_initialized = False


def log_dir() -> Path:
    """日志目录。优先用 paths 模块的统一位置。"""
    from .paths import app_log_dir

    return app_log_dir()


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

    幂等：重复调用不会重复添加 sink。
    返回日志文件所在目录，便于 UI 上「打开日志目录」。

    :param console: 是否输出到 stderr。缺省时按 ``sys.stderr`` 是否可用判断
                    （GUI ``console=False`` 打包时 stderr 为 None）
    """
    global _initialized
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
        logger.add(sys.stderr, level="WARNING", format=LOG_FORMAT)

    return d


def get_logger(name: str = "linguaforge"):
    """取 logger。尚未初始化时按默认配置兜底，避免静默丢日志。"""
    from loguru import logger

    if not _initialized:
        setup_logging(console=False)
    return logger.bind(name=name)
