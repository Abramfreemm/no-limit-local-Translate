"""路径与临时目录治理（17 号 §4 / §7 落地实现）。

解决了三个真实缺陷：

1. **固定临时目录**（原 ``writers/pdf_rebuild.py:258``）
   用 ``%TEMP%/lf_parts``：多实例并发翻译会互相覆盖分片；
   进程被杀后译文分片永久残留在系统临时目录。
   现改为「每任务一个唯一目录」+「启动时清扫孤儿」。

2. **文件名穿越 / 保留名**（原无防护）
   输出文件名直接来自输入文件名，可能含 ``../`` 或 Windows
   保留名（``CON``、``NUL``、``AUX`` 等），导致写穿目录或创建失败。

3. **临时目录位置零散**
   统一收敛到本文件，便于排查与清理。
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

__all__ = [
    "app_data_dir",
    "app_log_dir",
    "app_tmp_root",
    "new_task_tmpdir",
    "sweep_orphan_tmpdirs",
    "safe_filename",
    "short_hash",
]

# 孤儿判定阈值：超过这个时长仍未更新的任务目录视为残留
ORPHAN_MAX_AGE_S = 6 * 3600

# Windows 保留设备名（作为文件名会创建失败）
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# 非法字符：路径分隔符、通配符、控制字符等
_ILLEGAL = r'[<>:"/\\|?*\x00-\x1f]'

# 目录穿越片段
_TRAVERSAL = re.compile(r"^\.\.?$")


def _app_dirs():
    from platformdirs import user_data_dir

    return Path(user_data_dir("LinguaForge", "LinguaForge"))


def app_data_dir() -> Path:
    """应用数据目录（配置 / 数据库 / 日志根）。不存在则创建。"""
    d = _app_dirs()
    d.mkdir(parents=True, exist_ok=True)
    return d


def app_log_dir() -> Path:
    """日志目录：<data>/logs。"""
    d = app_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def app_tmp_root() -> Path:
    """临时文件根目录：<data>/tmp。不再使用系统 %TEMP%，便于统一清扫。"""
    d = app_data_dir() / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_task_tmpdir(prefix: str = "task") -> Path:
    """为一个翻译任务创建唯一临时目录。

    名字含时间戳与 pid，保证多实例并发不冲突；调用方用完即删。
    """
    d = app_tmp_root() / f"{prefix}_{int(time.time() * 1000)}_{os.getpid()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sweep_orphan_tmpdirs(max_age_s: int = ORPHAN_MAX_AGE_S) -> int:
    """清扫残留的任务临时目录，返回清理掉的目录数。

    用途：应用启动时调用一次。进程被杀留下的分片在这里被回收。
    清理失败不影响启动（吞异常）。
    """
    import shutil

    root = app_tmp_root()
    now = time.time()
    removed = 0
    try:
        for child in root.iterdir():
            if not child.is_dir():
                continue
            try:
                if now - child.stat().st_mtime > max_age_s:
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
            except Exception:  # noqa: BLE001, S112
                continue
    except Exception:  # noqa: BLE001
        return removed
    return removed


def short_hash(text: str, n: int = 8) -> str:
    """短哈希，用于日志里指代路径而不泄露完整路径。"""
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:n]


def safe_filename(name: str, *, max_len: int = 120, default: str = "output") -> str:
    """净化文件名，防御目录穿越与 Windows 保留名。

    处理顺序：
      1. 去掉路径分隔符与控制字符（含 ``\\x00``）
      2. 丢弃 ``.`` / ``..`` 等穿越片段
      3. 去掉首尾空白与结尾的点（Windows 不允许）
      4. 保留名加 ``_`` 后缀
      5. 超长截断（保留扩展名）
      6. 结果为空则回退 default

    >>> safe_filename("../../etc/passwd")
    'etcpasswd'
    >>> safe_filename("CON")
    'CON_'
    >>> safe_filename("   ")
    'output'
    """
    raw = str(name or "")
    # 1) 去掉非法字符
    cleaned = re.sub(_ILLEGAL, "", raw)
    # 2) 只取最后一段真正的名字，丢掉 ../ 之类
    parts = [p for p in cleaned.split(os.sep) if p and not _TRAVERSAL.match(p)]
    if not parts:
        # 兼容有人传了带 / 的路径
        parts = [p for p in re.split(r"[/\\]", cleaned) if p and not _TRAVERSAL.match(p)]
    stem = parts[-1] if parts else ""
    # 3) 去首尾空白与结尾的点
    stem = stem.strip().strip(".")
    if not stem:
        return default

    # 4) Windows 保留名（比较时忽略大小写与扩展名）
    base = stem.split(".")[0].upper()
    if base in _RESERVED:
        stem = f"{stem}_"

    # 5) 超长截断，尽量保住扩展名
    if len(stem) > max_len:
        p = Path(stem)
        suffix = p.suffix
        keep = max_len - len(suffix)
        stem = (p.stem[: max(1, keep)] if keep > 1 else p.stem[:1]) + suffix

    return stem or default
