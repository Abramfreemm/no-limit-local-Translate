"""统一错误码与问题对象（19 号 §1–§3 落地实现）。

设计目标
--------
1. **UI 不再拼接中文错误字符串**：只做 ``tr(problem.code, **problem.params)``。
2. **日志可按码检索**：每个失败都有稳定编号，码永不复用。
3. **解析异常收敛为一个类**：原先 6 个 ``*ParseError`` 各自演化，改为
   ``DocumentParseError(format=...)`` 携带格式标签。

错误码格式
----------
``LF-<域><两位序号>``，域：

======  ==================================  ==========================
域      含义                                典型场景
======  ==================================  ==========================
E       Environment 环境与依赖              Ollama、模型、OCR 组件、磁盘
D       Document 文档输入                   格式、损坏、加密、结构异常
T       Translation 翻译过程                模型输出、超时、降级耗尽
O       Output 输出与文件系统                写出、字体、路径
S       System 系统内部                     未捕获异常、数据库、内存
U       Usage 用户操作                      队列为空、未选模型
======  ==================================  ==========================

使用示例
--------
>>> from linguaforge.core.problems import Problem, Code, Severity
>>> p = Problem(Code.MODEL_MISSING, params={"model": "qwen3:8b", "size": "5.2 GB"})
>>> p.code
'LF-E04'
>>> p.render("{model} 未下载，约 {size}")
'qwen3:8b 未下载，约 5.2 GB'
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "Severity",
    "Code",
    "Problem",
    "LinguaForgeError",
    "DocumentParseError",
    "TranslationError",
    "OutputError",
    "CODE_SEVERITY",
    "code_exists",
    "all_codes",
]


class Severity(StrEnum):
    """严重级。决定 UI 表现与是否中止任务。"""

    BLOCKER = "B"  # 无法开始（开始前拦截）
    FAILURE = "F"  # 当前任务失败
    DEGRADED = "D"  # 降级继续，结果有损
    WARNING = "W"  # 可继续，但需注意
    INFO = "I"  # 仅记录

    @property
    def label(self) -> str:
        return {
            "B": "阻断",
            "F": "失败",
            "D": "降级",
            "W": "警告",
            "I": "提示",
        }[str(self)]

    @property
    def aborts(self) -> bool:
        """是否中止任务。"""
        return self in (Severity.BLOCKER, Severity.FAILURE)


class Code(StrEnum):
    """错误码全表（19 号 §2）。

    规则：
      - 码一旦分配永不复用，即使场景删除
      - 新增只能追加，不得改变既有码语义
      - 每个码必须能回答：谁的错、能不能继续、用户能做什么、日志记什么
    """

    # ---------- E 域 · 环境与依赖 ----------
    OLLAMA_UNREACHABLE = "LF-E01"  # 连接被拒/超时
    OLLAMA_NOT_INSTALLED = "LF-E02"  # 端口无监听且未找到安装
    OLLAMA_OLD_VERSION = "LF-E03"  # 版本低于最低支持
    MODEL_MISSING = "LF-E04"  # /api/tags 不含目标模型
    MODEL_LOAD_FAILED = "LF-E05"  # 加载时 OOM / 进程退出
    MODEL_PULL_FAILED = "LF-E06"  # 下载中断或校验失败
    OCR_IMPORT_FAILED = "LF-E07"  # import rapidocr 失败
    OCR_MODEL_BROKEN = "LF-E08"  # 模型文件缺失或损坏
    DISK_INSUFFICIENT = "LF-E09"  # 剩余空间不足
    DIR_NOT_WRITABLE = "LF-E10"  # 输出目录不可写
    PROXY_DETECTED = "LF-E11"  # 探测到代理影响回环地址
    OLLAMA_EXPOSED = "LF-E12"  # Ollama 监听非回环地址

    # ---------- D 域 · 文档输入 ----------
    FILE_NOT_FOUND = "LF-D01"
    FILE_EMPTY = "LF-D02"
    FILE_ENCRYPTED = "LF-D03"
    EXT_UNSUPPORTED = "LF-D04"
    PARSE_FAILED = "LF-D05"
    PAGE_SIZE_EXCEEDED = "LF-D06"
    ZIP_BOMB = "LF-D07"
    IMAGE_TOO_LARGE = "LF-D08"
    STRUCT_TOO_DEEP = "LF-D09"
    FILE_LOCKED = "LF-D10"
    PARSE_TIMEOUT = "LF-D11"

    # ---------- T 域 · 翻译过程 ----------
    TRANSLATE_JSON_FAILED = "LF-T01"  # 内部降级，用户不可见
    TRANSLATE_COUNT_MISMATCH = "LF-T02"  # 内部降级，用户不可见
    TRANSLATE_TIMEOUT = "LF-T03"
    TRANSLATE_EMPTY = "LF-T04"
    TRANSLATE_CTX_OVERFLOW = "LF-T05"
    TRANSLATE_ALL_FALLBACK_FAILED = "LF-T06"
    GLOSSARY_CONFLICT = "LF-T07"
    TRANSLATE_PARTIAL_FAILED = "LF-T08"
    TRANSLATE_NO_FALLBACK = "LF-T09"

    # ---------- O 域 · 输出 ----------
    WRITE_FAILED = "LF-O01"
    FONT_EMBED_FAILED = "LF-O02"
    DISK_FULL_DURING_WRITE = "LF-O03"
    FILENAME_SANITIZED = "LF-O04"
    OUTPUT_LOCKED = "LF-O05"

    # ---------- S 域 · 系统内部 ----------
    UNCAUGHT_EXCEPTION = "LF-S01"
    DB_ERROR = "LF-S02"
    MEMORY_ABORT = "LF-S03"
    CONFIG_CORRUPTED = "LF-S04"

    # ---------- U 域 · 用户操作 ----------
    QUEUE_EMPTY = "LF-U01"
    NO_MODEL_SELECTED = "LF-U02"
    FORMAT_MISMATCH = "LF-U03"
    CANCELLED = "LF-U04"

    # ---------- 通用兜底 ----------
    UNKNOWN = "LF-S99"


CODE_SEVERITY: dict[str, Severity] = {
    Code.OLLAMA_UNREACHABLE: Severity.BLOCKER,
    Code.OLLAMA_NOT_INSTALLED: Severity.BLOCKER,
    Code.OLLAMA_OLD_VERSION: Severity.WARNING,
    Code.MODEL_MISSING: Severity.BLOCKER,
    Code.MODEL_LOAD_FAILED: Severity.FAILURE,
    Code.MODEL_PULL_FAILED: Severity.FAILURE,
    Code.OCR_IMPORT_FAILED: Severity.DEGRADED,
    Code.OCR_MODEL_BROKEN: Severity.DEGRADED,
    Code.DISK_INSUFFICIENT: Severity.BLOCKER,
    Code.DIR_NOT_WRITABLE: Severity.BLOCKER,
    Code.PROXY_DETECTED: Severity.WARNING,
    Code.OLLAMA_EXPOSED: Severity.WARNING,
    Code.FILE_NOT_FOUND: Severity.FAILURE,
    Code.FILE_EMPTY: Severity.FAILURE,
    Code.FILE_ENCRYPTED: Severity.FAILURE,
    Code.EXT_UNSUPPORTED: Severity.FAILURE,
    Code.PARSE_FAILED: Severity.FAILURE,
    Code.PAGE_SIZE_EXCEEDED: Severity.DEGRADED,
    Code.ZIP_BOMB: Severity.FAILURE,
    Code.IMAGE_TOO_LARGE: Severity.FAILURE,
    Code.STRUCT_TOO_DEEP: Severity.FAILURE,
    Code.FILE_LOCKED: Severity.FAILURE,
    Code.PARSE_TIMEOUT: Severity.FAILURE,
    Code.TRANSLATE_JSON_FAILED: Severity.INFO,
    Code.TRANSLATE_COUNT_MISMATCH: Severity.INFO,
    Code.TRANSLATE_TIMEOUT: Severity.DEGRADED,
    Code.TRANSLATE_EMPTY: Severity.INFO,
    Code.TRANSLATE_CTX_OVERFLOW: Severity.DEGRADED,
    Code.TRANSLATE_ALL_FALLBACK_FAILED: Severity.FAILURE,
    Code.GLOSSARY_CONFLICT: Severity.WARNING,
    Code.TRANSLATE_PARTIAL_FAILED: Severity.DEGRADED,
    Code.TRANSLATE_NO_FALLBACK: Severity.DEGRADED,
    Code.WRITE_FAILED: Severity.FAILURE,
    Code.FONT_EMBED_FAILED: Severity.DEGRADED,
    Code.DISK_FULL_DURING_WRITE: Severity.FAILURE,
    Code.FILENAME_SANITIZED: Severity.WARNING,
    Code.OUTPUT_LOCKED: Severity.FAILURE,
    Code.UNCAUGHT_EXCEPTION: Severity.FAILURE,
    Code.DB_ERROR: Severity.FAILURE,
    Code.MEMORY_ABORT: Severity.FAILURE,
    Code.CONFIG_CORRUPTED: Severity.WARNING,
    Code.QUEUE_EMPTY: Severity.INFO,
    Code.NO_MODEL_SELECTED: Severity.BLOCKER,
    Code.FORMAT_MISMATCH: Severity.WARNING,
    Code.CANCELLED: Severity.INFO,
}


def code_exists(code: str) -> bool:
    """校验错误码是否在码表中（防止手滑拼错码导致日志检索失效）。"""
    return code in CODE_SEVERITY


def all_codes() -> list[str]:
    return list(CODE_SEVERITY)


@dataclass(frozen=True)
class Problem:
    """一个可上报、可本地化、可检索的问题。

    Attributes:
        code: 错误码，如 ``LF-E04``。必须是 :class:`Code` 中的值。
        severity: 严重级。缺省时按 :data:`CODE_SEVERITY` 取默认值。
        params: 文案模板变量，UI 用它插值，不直接展示。
        detail: 仅进日志的技术细节（原始异常文本等），**绝不展示给用户**。
        page: 关联的页码（1-based），无则 None。
        block_ids: 关联的块 ID 列表。
        source: 出错来源标识（如 ``parser:pdf``、``writer:docx``）。
    """

    code: str
    severity: Severity | None = None
    params: dict[str, Any] = field(default_factory=dict)
    detail: str = ""
    page: int | None = None
    block_ids: list[str] = field(default_factory=list)
    source: str = ""

    def __post_init__(self) -> None:
        if not code_exists(self.code):
            # 不放过拼错的码：否则日志里会出现检索不到的孤儿码
            raise ValueError(f"未登记的错误码: {self.code!r}")
        if self.severity is None:
            # frozen dataclass 里只能通过 object.__setattr__ 写
            object.__setattr__(self, "severity", CODE_SEVERITY[self.code])

    @property
    def is_fatal(self) -> bool:
        return Severity(self.severity).aborts

    def render(self, template: str) -> str:
        """按模板插值出用户文案；缺参数时保留占位符，便于发现文案漏洞。"""
        try:
            return template.format(**self.params)
        except (KeyError, IndexError):
            return template

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": str(self.severity),
            "params": dict(self.params),
            "detail": self.detail,
            "page": self.page,
            "block_ids": list(self.block_ids),
            "source": self.source,
        }

    def __str__(self) -> str:
        loc = f" p{self.page}" if self.page else ""
        return f"[{self.code}{loc}] {self.detail or self.params}"


class LinguaForgeError(RuntimeError):
    """所有 LinguaForge 业务异常的基类。

    统一携带 :class:`Problem`，使上层只需
    ``except LinguaForgeError as e: e.problem`` 即可拿到结构化错误。
    """

    default_code = Code.UNKNOWN

    def __init__(
        self,
        message: str = "",
        *,
        code: str | None = None,
        params: dict[str, Any] | None = None,
        page: int | None = None,
        source: str = "",
    ) -> None:
        super().__init__(message)
        self.problem = Problem(
            code=code or self.default_code,
            params=params or {},
            detail=message,
            page=page,
            source=source,
        )


class DocumentParseError(LinguaForgeError):
    """文档解析失败（合并原 6 个 ``*ParseError``）。

    原实现里 ``DocxParseError`` / ``PptxParseError`` / ``XlsxParseError`` /
    ``HtmlParseError`` / ``SrtParseError`` / ``ImageParseError`` 六个类
    除了名字完全一致，却各自演化、UI 也要各自判断。现统一为一个类，
    用 ``fmt`` 区分具体格式。
    """

    default_code = Code.PARSE_FAILED

    def __init__(
        self,
        message: str = "",
        *,
        fmt: str = "",
        code: str | None = None,
        params: dict[str, Any] | None = None,
        page: int | None = None,
    ) -> None:
        p = dict(params or {})
        if fmt:
            p.setdefault("fmt", fmt)
        super().__init__(message, code=code, params=p, page=page, source=f"parser:{fmt or '?'}")
        self.fmt = fmt


class TranslationError(LinguaForgeError):
    """翻译过程失败。"""

    default_code = Code.TRANSLATE_ALL_FALLBACK_FAILED


class OutputError(LinguaForgeError):
    """输出 / 写出失败。"""

    default_code = Code.WRITE_FAILED


def from_exception(
    exc: BaseException,
    *,
    code: str | None = None,
    params: dict[str, Any] | None = None,
    page: int | None = None,
    source: str = "",
) -> Problem:
    """把任意异常转成 :class:`Problem`（流水线统一收口入口）。

    业务异常（:class:`LinguaForgeError` 子类）直接复用其自带的 problem；
    其余按类型映射到最接近的码，未识别的落到 ``LF-S99``。

    >>> from linguaforge.core.problems import from_exception
    >>> from linguaforge.core.problems import DocumentParseError
    >>> from_exception(DocumentParseError("坏了", fmt="pdf")).code
    'LF-D05'
    >>> from_exception(RuntimeError("boom")).code
    'LF-S99'
    """
    if isinstance(exc, LinguaForgeError):
        p = exc.problem
        # 允许调用方覆盖定位信息（如补上页码 / 来源）
        return Problem(
            code=p.code,
            severity=p.severity,
            params={**p.params, **(params or {})},
            detail=p.detail,
            page=page if page is not None else p.page,
            block_ids=list(p.block_ids),
            source=source or p.source,
        )

    inferred = code
    p = dict(params or {})

    if inferred is None:
        if isinstance(exc, FileNotFoundError):
            inferred = Code.FILE_NOT_FOUND
        elif isinstance(exc, PermissionError):
            inferred = Code.DIR_NOT_WRITABLE
        elif isinstance(exc, TimeoutError):
            inferred = Code.PARSE_TIMEOUT
        elif isinstance(exc, MemoryError):
            inferred = Code.MEMORY_ABORT
        else:
            inferred = Code.UNKNOWN

    return Problem(
        code=inferred,
        params=p,
        detail=f"{type(exc).__name__}: {exc}",
        page=page,
        source=source,
    )


def problems_to_text(problems: list[Problem]) -> list[str]:
    """把 Problem 列表渲染为可读文本（CLI / 诊断包用）。

    输出格式 ``[LF-E04 p3] <detail>``，带定位信息，便于用户直接粘贴反馈。
    """
    out = []
    for prob in problems:
        loc = f" p{prob.page}" if prob.page is not None else ""
        sev = Severity(prob.severity).label
        out.append(f"[{prob.code}{loc}][{sev}] {prob.detail or prob.params}")
    return out
