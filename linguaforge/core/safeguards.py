"""输入安全护栏（17 号 §5 落地实现）。

防御对象：**一个恶意文件搞崩本地应用**。

本产品完全离线，不接收网络输入，所以攻击面只有一处 —— 用户打开的文档。
一个 42 KB 的 zip 解压出 10 GB 内容（zip 炸弹）、一张声明 100000×100000
的图片（图片炸弹）、一个嵌套 5000 层的 PDF 页面树，都足以让进程 OOM 或卡死。

所有上限都写成常量并附理由，便于按需调整。
"""

from __future__ import annotations

import time
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .problems import Code, Problem

__all__ = [
    "LIMITS",
    "check_zip_safety",
    "check_image_pixels",
    "check_page_size",
    "check_nesting_depth",
    "Deadline",
    "guard_zip",
    "guard_page",
]

# 所有上限集中在这里。修改时请同步更新 18 号性能预算文档。
LIMITS: dict[str, Any] = {
    # zip 炸弹：OOXML（docx/pptx/xlsx）本质是 zip
    "zip_max_ratio": 200,  # 压缩比上限
    "zip_max_total_bytes": 2 << 30,  # 解压后总量上限 2 GB
    "zip_max_files": 20_000,  # 条目数上限
    # 图片像素：1.5 亿像素 ≈ A0@300DPI 扫描件，覆盖全部真实场景。
    # 故意设得比 Pillow 默认的 MAX_IMAGE_PIXELS（178956970）更严：
    # 这样「150M ~ 178M」区间由本项目的检查拦截，能给出本地化文案；
    # 超过 178M 的由 Pillow 抛 DecompressionBombError，parser 侧再映射
    # 回同一个码 LF-D08。两条路径对外表现一致。
    "image_max_pixels": 150_000_000,
    # PDF 页面尺寸：14400 pt = 200 英寸，超过即异常
    "page_max_pt": 14_400,
    # 结构嵌套深度：书签树 / 页面树递归上限，防御深层嵌套导致爆栈
    "max_nesting_depth": 64,
    # 解析总超时：默认 30 分钟
    "parse_timeout_s": 1800,
}


def check_zip_safety(path: str | Path) -> Problem | None:
    """检测 zip 炸弹：压缩比 / 解压总量 / 条目数三重判定。

    对 docx / pptx / xlsx 生效（OOXML 即 zip）。返回 Problem 表示拒绝打开。
    """
    p = Path(path)
    try:
        raw = p.stat().st_size
        with zipfile.ZipFile(p) as zf:
            infos = zf.infolist()
            if len(infos) > LIMITS["zip_max_files"]:
                return Problem(
                    Code.ZIP_BOMB,
                    params={"name": p.name, "files": len(infos)},
                    detail=f"zip 条目数 {len(infos)} 超过上限",
                    source="safeguard.zip",
                )
            total = sum(i.file_size for i in infos)
            ratio = (total / raw) if raw else float("inf")

            if total > LIMITS["zip_max_total_bytes"]:
                return Problem(
                    Code.ZIP_BOMB,
                    params={
                        "name": p.name,
                        "total_mb": round(total / 1048576, 1),
                    },
                    detail=f"解压后 {round(total / 1048576, 1)} MB 超过上限",
                    source="safeguard.zip",
                )
            if ratio > LIMITS["zip_max_ratio"]:
                return Problem(
                    Code.ZIP_BOMB,
                    params={"name": p.name, "ratio": round(ratio, 1)},
                    detail=f"压缩比 {round(ratio, 1)}:1 异常",
                    source="safeguard.zip",
                )
    except zipfile.BadZipFile:
        # 不是合法 zip，交给各自的 parser 报"文件损坏"
        return None
    except OSError:
        return None
    return None


def check_image_pixels(width: int, height: int) -> Problem | None:
    """图片像素上限检查（防御图片炸弹）。"""
    px = int(width) * int(height)
    if px > LIMITS["image_max_pixels"]:
        return Problem(
            Code.IMAGE_TOO_LARGE,
            params={"w": width, "h": height},
            detail=f"图片 {width}×{height} 共 {px} 像素，超过上限",
            source="safeguard.image",
        )
    return None


def check_page_size(width: float, height: float) -> Problem | None:
    """PDF 页面尺寸异常检查。超大尺寸会让渲染分配巨额内存。"""
    if max(width, height) > LIMITS["page_max_pt"]:
        return Problem(
            Code.PAGE_SIZE_EXCEEDED,
            params={"w": round(width, 1), "h": round(height, 1)},
            detail=f"页面 {round(width, 1)}×{round(height, 1)} pt 异常",
            source="safeguard.page",
        )
    return None


def check_nesting_depth(depth: int, what: str = "结构") -> Problem | None:
    """嵌套深度上限检查（防御深层书签树 / 页面树导致递归爆栈）。"""
    if depth > LIMITS["max_nesting_depth"]:
        return Problem(
            Code.STRUCT_TOO_DEEP,
            params={"depth": depth, "max": LIMITS["max_nesting_depth"], "what": what},
            detail=f"{what}嵌套深度 {depth} 超过上限 {LIMITS['max_nesting_depth']}",
            source="safeguard.depth",
        )
    return None


def guard_page(width: float, height: float, page_no: int | None = None) -> None:
    """页面级防护：尺寸异常即拒绝解析。

    :raises DocumentParseError: 携带 LF-D06
    """
    from .problems import DocumentParseError

    prob = check_page_size(width, height)
    if prob is not None:
        prob = replace(prob, page=page_no)
        raise DocumentParseError(
            prob.detail,
            code=prob.code,
            fmt="pdf",
            params=prob.params,
            page=prob.page,
        )


def guard_zip(path: str | Path) -> Problem | None:
    """对 OOXML 文件做 zip 安全检测。非 zip 格式返回 None。"""
    if Path(path).suffix.lower() not in {".docx", ".pptx", ".xlsx", ".xlsm"}:
        return None
    return check_zip_safety(path)


def guard_input(path: str | Path, fmt: str = "") -> None:
    """解析入口的统一前置检查，失败抛 :class:`DocumentParseError`。

    依次检查：存在 -> 非空 -> zip 炸弹（仅 OOXML）。

    :raises DocumentParseError: 携带结构化 Problem（LF-D01 / D02 / D07）
    """
    from .problems import DocumentParseError

    p = Path(path)
    ext = p.suffix.lower()

    if not p.exists():
        raise DocumentParseError(
            f"文件不存在: {p}",
            code=Code.FILE_NOT_FOUND,
            fmt=fmt or ext,
            params={"name": p.name},
        )

    try:
        size = p.stat().st_size
    except OSError as e:
        raise DocumentParseError(
            f"无法读取文件信息: {p}: {e}",
            code=Code.FILE_LOCKED,
            fmt=fmt or ext,
            params={"name": p.name, "errno": getattr(e, "errno", 0)},
        ) from e

    if size == 0:
        raise DocumentParseError(
            f"空文件（0 字节）: {p.name}",
            code=Code.FILE_EMPTY,
            fmt=fmt or ext,
            params={"name": p.name},
        )

    prob = guard_zip(p)
    if prob is not None:
        raise DocumentParseError(
            prob.detail,
            code=prob.code,
            fmt=fmt or ext,
            params=prob.params,
        )


@dataclass
class Deadline:
    """总超时守卫：跨页累计，超时即中止（19 号 LF-D11）。

    用法：
        dl = Deadline(1800)
        for page in pages:
            if dl.expired():
                raise TimeoutError(...)
    """

    timeout_s: float = float(LIMITS["parse_timeout_s"])
    _t0: float = 0.0

    def __post_init__(self) -> None:
        self._t0 = time.time()

    @property
    def elapsed_s(self) -> float:
        return time.time() - self._t0

    def expired(self) -> bool:
        return self.elapsed_s > self.timeout_s

    def problem(self, last_page: int | None = None) -> Problem:
        return Problem(
            Code.PARSE_TIMEOUT,
            params={
                "n": round(self.timeout_s / 60, 1),
                "elapsed_s": round(self.elapsed_s, 1),
                "last_page": last_page,
            },
            detail=f"解析超过 {round(self.timeout_s / 60, 1)} 分钟",
            page=last_page,
            source="safeguard.timeout",
        )
