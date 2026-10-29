"""开工前预检查（13 号 §2 旅程 E + §5.2 落地实现）。

设计原则
--------
**能在开始前发现的错误，绝不留到跑到一半。**

对照：翻译到 400 页才报「模型没装」，用户已经等了 40 分钟。
预检查用 < 1.5 s 的成本换掉这种体验灾难。

检查项与对应错误码
------------------
===================================  ==========
检查                                 错误码
===================================  ==========
输出目录可写                         LF-E10
磁盘空间充足                         LF-E09
Ollama 服务可达                      LF-E01
Ollama 已安装（不可达时的细分）      LF-E02
Ollama 版本                          LF-E03
主模型已安装                         LF-E04
降级链可用性                         LF-T09
OCR 组件可用（仅开启 OCR 时）        LF-E07
输入文件存在 / 非空 / 扩展名支持    LF-D01/02/04
===================================  ==========

用法
----
>>> result = run_preflight(cfg, [Path("a.pdf")])
>>> if not result.ok:
...     for p in result.problems:
...         print(p.code, p.severity.label)
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .problems import Code, Problem, Severity

__all__ = ["PreflightResult", "run_preflight", "check_ollama", "check_disk"]

# 最低支持的 Ollama 版本（低于此版本 /api/chat 的 format 参数行为不一致）
MIN_OLLAMA = "0.5.0"

# 预估：每页翻译耗时（秒）。用于大文件提前告知，避免用户以为卡死
_EST_S_PER_PAGE = 2.6
# 磁盘安全系数：需求 × 1.5 仍不足则阻断（19 号 LF-E09）
_DISK_SAFETY = 1.5
# 触发耗时提示的页数阈值
_BIG_DOC_PAGES = 500


@dataclass
class PreflightResult:
    """预检查结果。

    Attributes:
        ok: 是否存在 ``BLOCKER`` 级问题
        problems: 全部问题，按严重级从高到低排序
        models_available: 本机实际可用的模型名列表（探测成功时有值）
        estimated_s: 预估总耗时（秒），仅作提示
    """

    ok: bool = True
    problems: list[Problem] = field(default_factory=list)
    models_available: list[str] = field(default_factory=list)
    estimated_s: float = 0.0

    @property
    def blockers(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == Severity.BLOCKER]

    @property
    def fatal(self) -> list[Problem]:
        """阻断级 + 失败级。

        ``ok`` 以这个为准：文件不存在、格式不支持这类问题对该文件就是
        致命的，让它跑下去只会得到一堆空输出。**只有警告 / 降级 / 提示
        级问题才允许继续。**
        """
        return [p for p in self.problems if Severity(p.severity).aborts]

    def text(self) -> list[str]:
        """渲染为可直接展示的字符串列表。"""
        from .problems import problems_to_text

        return problems_to_text(self.problems)


def _probe_ollama(host: str, timeout: float = 3.0):
    """探测 Ollama 服务。返回 (version, models) 或抛出 httpx 异常。"""
    import httpx

    with httpx.Client(timeout=timeout, trust_env=False) as c:
        r = c.get(f"{host.rstrip('/')}/api/version")
        r.raise_for_status()
        ver = str(r.json().get("version", ""))
        m = c.get(f"{host.rstrip('/')}/api/tags")
        models = [x.get("name", "") for x in m.json().get("models", []) if x.get("name")]
        return ver, models


def _ollama_installed() -> bool:
    """判断本机是否装了 Ollama 可执行文件（用于区分"没装"和"没启动"）。"""
    exe = shutil.which("ollama")
    if exe:
        return True
    for cand in (
        Path.home() / "AppData/Local/Programs/Ollama/ollama.exe",
        Path("/usr/local/bin/ollama"),
        Path("/opt/homebrew/bin/ollama"),
        Path("/Applications/Ollama.app/Contents/Resources/ollama"),
    ):
        if cand.exists():
            return True
    return False


def check_ollama(cfg) -> tuple[list[Problem], list[str]]:
    """检查 Ollama 服务与模型可用性。

    同时返回本机实际可用的模型列表，供 UI 渲染模型选择 ——
    这样即使主模型缺失，UI 也能直接列出「你可以改用这几个」。
    """
    out: list[Problem] = []

    try:
        ver, models = _probe_ollama(cfg.ollama.host)
    except Exception as e:  # noqa: BLE001
        # 区分"没启动"与"没安装"：装了但没起 → E01，压根没装 → E02
        code = Code.OLLAMA_UNREACHABLE if _ollama_installed() else Code.OLLAMA_NOT_INSTALLED
        out.append(
            Problem(
                code,
                params={"host": cfg.ollama.host, "exc_type": type(e).__name__},
                detail=str(e),
                source="preflight.ollama",
            )
        )
        return out, []

    if ver and _version_tuple(ver) < _version_tuple(MIN_OLLAMA):
        out.append(
            Problem(
                Code.OLLAMA_OLD_VERSION,
                params={"version": ver, "min_required": MIN_OLLAMA},
                source="preflight.ollama",
            )
        )

    if cfg.ollama.model not in models:
        out.append(
            Problem(
                Code.MODEL_MISSING,
                params={
                    "model": cfg.ollama.model,
                    "available": ", ".join(models[:6]) or "(空)",
                },
                source="preflight.ollama",
            )
        )

    # 降级链：主模型挂了还有谁可用
    usable = [m for m in (cfg.ollama.fallback_models or []) if m in models]
    if not usable:
        out.append(
            Problem(
                Code.TRANSLATE_NO_FALLBACK,
                params={
                    "primary": cfg.ollama.model,
                    "fallbacks": ", ".join(cfg.ollama.fallback_models or []) or "(无)",
                },
                source="preflight.ollama",
            )
        )

    return out, models


def check_disk(out_dir: Path, sources: list[Path]) -> list[Problem]:
    """检查磁盘空间与输出目录可写性。"""
    out: list[Problem] = []

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        probe = out_dir / ".lf_write_probe"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
    except Exception as e:  # noqa: BLE001
        out.append(
            Problem(
                Code.DIR_NOT_WRITABLE,
                params={"dir": str(out_dir), "errno": getattr(e, "errno", 0)},
                detail=str(e),
                source="preflight.disk",
            )
        )
        return out

    need = 0
    for s in sources:
        try:
            need += s.stat().st_size
        except OSError:
            continue
    need = int(need * _DISK_SAFETY) + (64 << 20)  # 预留 64 MB 余量

    try:
        free = shutil.disk_usage(str(out_dir)).free
    except Exception as e:  # noqa: BLE001
        out.append(
            Problem(
                Code.DISK_INSUFFICIENT,
                params={"dir": str(out_dir)},
                detail=str(e),
                source="preflight.disk",
            )
        )
        return out

    if free < need:
        out.append(
            Problem(
                Code.DISK_INSUFFICIENT,
                params={
                    "need_mb": round(need / 1048576, 1),
                    "free_mb": round(free / 1048576, 1),
                    "drive": out_dir.drive or str(out_dir.anchor),
                },
                source="preflight.disk",
            )
        )

    return out


def check_sources(sources: list[Path], supported: set[str]) -> list[Problem]:
    """检查输入文件：存在性、非空、扩展名支持、可读性。"""
    out: list[Problem] = []
    for s in sources:
        if not s.exists():
            out.append(
                Problem(
                    Code.FILE_NOT_FOUND,
                    params={"name": s.name},
                    source="preflight.source",
                )
            )
            continue

        try:
            size = s.stat().st_size
        except OSError as e:
            out.append(
                Problem(
                    Code.FILE_NOT_FOUND,
                    params={"name": s.name},
                    detail=str(e),
                    source="preflight.source",
                )
            )
            continue

        if size == 0:
            out.append(
                Problem(
                    Code.FILE_EMPTY,
                    params={"name": s.name},
                    source="preflight.source",
                )
            )
            continue

        if s.suffix.lower() not in supported:
            out.append(
                Problem(
                    Code.EXT_UNSUPPORTED,
                    params={"ext": s.suffix or "(无)", "list": ", ".join(sorted(supported))},
                    source="preflight.source",
                )
            )
            continue

        if not os.access(s, os.R_OK):
            out.append(
                Problem(
                    Code.FILE_LOCKED,
                    params={"name": s.name},
                    source="preflight.source",
                )
            )

    return out


def check_ocr(cfg) -> list[Problem]:
    """检查 OCR 组件可用性。仅在开启 OCR 时调用。"""
    if not cfg.ocr.enabled:
        return []

    engine = (cfg.ocr.engine or "rapidocr").lower()
    mod = {
        "rapidocr": "rapidocr_onnxruntime",
        "paddleocr": "paddleocr",
    }.get(engine)

    if mod is None:
        # vlm 引擎走 Ollama，不在此检查
        return []

    if importlib.util.find_spec(mod) is None:
        return [
            Problem(
                Code.OCR_IMPORT_FAILED,
                params={"engine": engine, "module": mod},
                detail=f"未安装 {mod}",
                source="preflight.ocr",
            )
        ]
    return []


def run_preflight(cfg, sources, *, out_dir: Path | None = None) -> PreflightResult:
    """跑全部预检查。

    :param cfg: :class:`~linguaforge.core.config.Config`
    :param sources: 待翻译文件路径列表
    :param out_dir: 输出目录，缺省时取各源文件所在目录
    """
    srcs = [Path(s) for s in sources]
    res = PreflightResult()

    # 1) 文件级检查
    try:
        from ..pipeline import SUPPORTED_IN

        supported = set(SUPPORTED_IN)
    except Exception:  # noqa: BLE001
        supported = set()

    if supported:
        res.problems += _check_sources(srcs, supported)

    # 2) 输出目录 + 磁盘
    dirs = [Path(out_dir)] if out_dir else [s.parent for s in srcs]
    for d in dirs:
        res.problems += check_disk(d, srcs)

    # 3) Ollama 与模型
    probs, models = check_ollama(cfg)
    res.problems += probs
    res.models_available = models

    # 4) OCR 组件
    res.problems += check_ocr(cfg)

    # 汇总
    _severity_rank = {
        Severity.BLOCKER: 0,
        Severity.FAILURE: 1,
        Severity.DEGRADED: 2,
        Severity.WARNING: 3,
        Severity.INFO: 4,
    }
    res.problems.sort(key=lambda p: _severity_rank.get(Severity(p.severity), 9))
    res.ok = not res.fatal

    pages, seconds = _estimate_seconds(srcs, cfg)
    res.estimated_s = seconds
    if pages > _BIG_DOC_PAGES:
        res.problems.append(
            Problem(
                Code.BIG_DOC_ETA,
                params={"pages": pages, "minutes": round(seconds / 60, 1)},
                detail=f"大文档共 {pages} 页，预估 {round(seconds / 60, 1)} 分钟",
                source="preflight.estimate",
            )
        )
        res.problems.sort(key=lambda p: _severity_rank.get(Severity(p.severity), 9))

    return res


def _check_sources(sources: list[Path], supported: set[str]) -> list[Problem]:
    return check_sources(sources, supported)


def _version_tuple(v: str) -> tuple:
    parts = []
    for chunk in str(v).split(".")[:3]:
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _estimate_seconds(sources: list[Path], cfg) -> tuple[int, float]:
    """粗略预估总耗时：页数 × 单页耗时 + OCR 页额外开销。

    返回 ``(页数, 预估秒数)``。页数探测只在 PDF 上做，成本极低。
    """
    pages = 0
    for s in sources:
        try:
            if s.suffix.lower() == ".pdf":
                from pypdf import PdfReader

                with open(s, "rb") as fh:
                    pages += len(PdfReader(fh).pages)
            else:
                pages += 1
        except Exception:  # noqa: BLE001, S110
            pages += 1
    extra = pages * 0.9 if cfg.ocr.enabled else 0.0
    return pages, round(pages * _EST_S_PER_PAGE + extra, 1)
