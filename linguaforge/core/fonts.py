"""CJK 字体解析与注册。

许可红线：
  - 随包分发只能用 **Noto Sans SC（OFL-1.1）**，绝不能打包微软雅黑 / 苹方
    （不可再分发）；
  - 检测不到随包字体时，允许 **引用本机已安装的系统字体**（不复制、不分发），
    保证任何机器都能出 PDF，只是该文件里的字体未嵌子集、换机可能走 fallback。
  - reportlab 的 TTFont 默认开启子集化，1000 页也只嵌入用过的字形，不会把
    10 MB 字体塞进产物。
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

_REGISTERED: dict = {}


def app_base_dir() -> Path:
    """运行时根目录：开发态是仓库根，打包态是 PyInstaller 的 _MEIPASS。"""
    if getattr(sys, "frozen", False):  # PyInstaller
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2]


def bundled_fonts_dir() -> Path:
    return app_base_dir() / "resources" / "fonts"


def _system_candidates() -> list[tuple[Path, int]]:
    """本机字体候选（path, subfontIndex）。只在未随包时兜底使用。"""
    home = Path.home()
    sysname = platform.system()
    if sysname == "Windows":
        fonts = Path.home().drive + "\\Windows\\Fonts"  # 通常是 C:\\Windows\\Fonts
        base = Path(fonts)
        return [
            (base / "msyh.ttc", 0),
            (base / "msyhbd.ttc", 0),
            (base / "simhei.ttf", 0),
            (base / "deng.ttf", 0),
            (base / "simsun.ttc", 0),
        ]
    if sysname == "Darwin":
        return [
            (Path("/System/Library/Fonts/PingFang.ttc"), 0),
            (Path("/System/Library/Fonts/STHeiti Medium.ttc"), 0),
            (Path("/Library/Fonts/Arial Unicode.ttf"), 0),
        ]
    return [
        (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"), 0),
        (Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"), 0),
        (Path("/usr/share/fonts/truetype/arphic/uming.ttc"), 0),
        (home / ".fonts" / "NotoSansSC-Regular.ttf", 0),
    ]


def _bundled_candidates() -> list[tuple[Path, int]]:
    d = bundled_fonts_dir()
    return [
        (d / "NotoSansSC-Regular.ttf", 0),
        (d / "NotoSansSC.ttf", 0),
        (d / "NotoSansSC-Bold.ttf", 0),
        (d / "SourceHanSansSC-Regular.otf", 0),
    ]


def ensure_body_font(prefer_bundled: bool = True) -> str | None:
    """注册正文用中文字体，返回 reportlab 字体名；全部失败返回 None。"""
    if "body" in _REGISTERED:
        return _REGISTERED["body"]

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    order = (_bundled_candidates() if prefer_bundled else []) + _system_candidates()
    seen = set()
    for path, idx in order:
        try:
            if not path.exists():
                continue
            key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            name = "LFCJK"
            pdfmetrics.registerFont(TTFont(name, str(path), subfontIndex=idx))
            _REGISTERED["body"] = name
            return name
        except Exception:
            continue
    return None


def ensure_bold_font(prefer_bundled: bool = True) -> str | None:
    """注册粗体中文字体。失败返回 None —— 调用方改用加描边的伪粗体。"""
    if "bold" in _REGISTERED:
        return _REGISTERED["bold"]

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    order: list[tuple[Path, int]] = []
    d = bundled_fonts_dir()
    order += [(d / "NotoSansSC-Bold.ttf", 0)]
    if platform.system() == "Windows":
        base = Path(Path.home().drive + "\\Windows\\Fonts")
        order += [(base / "msyhbd.ttc", 0), (base / "simhei.ttf", 0)]
    for path, idx in order:
        try:
            if not path.exists():
                continue
            name = "LFCJKBold"
            pdfmetrics.registerFont(TTFont(name, str(path), subfontIndex=idx))
            _REGISTERED["bold"] = name
            return name
        except Exception:
            continue
    return None


def font_status() -> dict:
    """给 doctor / 自检用。"""
    return {
        "bundled": str(bundled_fonts_dir()),
        "bundled_exists": (bundled_fonts_dir() / "NotoSansSC.ttf").exists()
        or (bundled_fonts_dir() / "NotoSansSC-Regular.ttf").exists(),
        "body": ensure_body_font(),
        "bold": ensure_bold_font(),
    }
