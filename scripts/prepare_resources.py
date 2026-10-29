"""构建前资源准备：字体 + OCR 模型 + 第三方许可清单。

用法：
    python scripts/prepare_resources.py                # 准备到 resources/
    python scripts/prepare_resources.py --out D:/tmp   # 指定输出目录（沙箱受限时可用）
    python scripts/prepare_resources.py --skip-font    # 跳过字体下载

产出：
    <out>/fonts/NotoSansSC-Regular.otf  + LICENSE_OFL.txt
    <out>/ocr_models/*.onnx             + README.md（模型来源与许可）
    THIRD_PARTY_LICENSES.txt

说明：字体与 ONNX 模型体积较大（约 15 MB + 10 MB），已在 .gitignore 中排除，
      由本脚本在构建时获取，不入库。
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
from pathlib import Path

# CI 上 Windows 控制台默认是 cp1252，打印中文会直接 UnicodeEncodeError 崩掉整个构建。
# 这里统一把输出流改成 UTF-8，比依赖外部设 PYTHONIOENCODING 更可靠。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parent.parent

# 必须是 **glyf 轮廓的 TTF**：reportlab 的 TTFont 不支持 CFF（.otf），
# 拿 OTF 去注册会直接失败、导致回填出的 PDF 没有中文。
# google/fonts 里的 NotoSansSC[wght].ttf 是可变 TTF，下面再实例化成静态字重。
NOTO_SC_URL = (
    "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"
)
NOTO_SC_URL_GITHUB = (
    "https://github.com/google/fonts/raw/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"
)
NOTO_LICENSE_URL = "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/notosanssc/OFL.txt"


def http_get(url: str, dest: Path, timeout: int = 60) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LinguaForge/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"   [失败] {type(exc).__name__}: {exc}")
        return False


def instantiate_static(src: Path, out_dir: Path) -> int:
    """把可变字体实例化成 Regular / Bold 两个静态 TTF。

    为什么必须做这一步：reportlab 对**可变字体**做子集化时会丢 ToUnicode
    映射，中文能画出来但 pdfplumber / 复制粘贴取不到文本（等于"看得见、
    搜不到"）。实例化成静态字体后映射正常，所以这里不能省。
    """
    try:
        from fontTools.ttLib import TTFont
        from fontTools.varLib import instancer
    except ImportError:
        print("[字体] ⚠️ 未装 fontTools，跳过静态实例化（pip install fonttools）")
        return 0
    n = 0
    for weight, name in ((400, "NotoSansSC-Regular.ttf"), (700, "NotoSansSC-Bold.ttf")):
        dest = out_dir / name
        if dest.exists():
            n += 1
            continue
        try:
            f = TTFont(str(src))
            inst = instancer.instantiateVariableFont(
                f, {"wght": weight}, inplace=False, updateFontNames=True
            )
            inst.save(str(dest))
            n += 1
            print(f"   实例化 {name} ({dest.stat().st_size / 1e6:.1f} MB)")
        except Exception as exc:  # noqa: BLE001
            print(f"   [失败] {name}: {type(exc).__name__}: {exc}")
    return n


def prepare_fonts(out: Path, skip: bool) -> None:
    fonts = out / "fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    variable = fonts / "NotoSansSC.ttf"

    if not variable.exists() and not skip:
        print("[字体] 下载 Noto Sans SC（可变 TTF）…")
        if not http_get(NOTO_SC_URL, variable):
            print("[字体] 主源失败，尝试 GitHub 直连 …")
            if not http_get(NOTO_SC_URL_GITHUB, variable):
                print("[字体] ⚠️ 下载失败。构建可继续，但 CJK 输出需手动放入字体。")
                return
        print(f"   已保存 {variable.name}  ({variable.stat().st_size / 1e6:.1f} MB)")
    elif skip:
        print("[字体] 按参数跳过下载")

    if variable.exists():
        instantiate_static(variable, fonts)

    lic = fonts / "OFL.txt"
    if not lic.exists():
        print("[字体] 下载 OFL-1.1 许可声明（随包分发是强制要求）…")
        http_get(NOTO_LICENSE_URL, lic)


def prepare_ocr_models(out: Path) -> None:
    """从已安装的 rapidocr_onnxruntime 包内复制 ONNX 模型到 resources。"""
    models_dir = out / "ocr_models"
    models_dir.mkdir(parents=True, exist_ok=True)
    try:
        import rapidocr_onnxruntime as pkg

        src = Path(pkg.__file__).parent / "models"
    except ImportError:
        print("[OCR] ⚠️ rapidocr_onnxruntime 未安装，跳过模型复制")
        (models_dir / "README.md").write_text(
            "# OCR 模型\n\n由 `rapidocr-onnxruntime` 包提供（Apache-2.0）。\n"
            "构建前请先 `pip install rapidocr-onnxruntime`，再运行本脚本。\n",
            encoding="utf-8",
        )
        return
    if not src.exists():
        print(f"[OCR] ⚠️ 未找到模型目录：{src}")
        return
    n = 0
    for f in src.rglob("*"):
        if f.is_file():
            dst = models_dir / f.relative_to(src)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                shutil.copy2(f, dst)
            n += 1
    print(f"[OCR] 已复制 {n} 个模型文件 → {models_dir}")
    (models_dir / "README.md").write_text(
        "# OCR 模型\n\n来源：`rapidocr-onnxruntime`（Apache-2.0）\n"
        "PP-OCRv4 检测 / 方向分类 / 识别模型，纯 CPU 可跑，无需联网。\n",
        encoding="utf-8",
    )


# 只出现在构建环境、不会打进安装包的工具。
# 其中 PyInstaller 是 GPLv2，但对它产出的程序有明确例外条款：
# 使用它打包的应用程序不受 GPL 传染（见 PyInstaller  LICENSE 中的
# "we will not ... claim that you ... must be licensed under the GPL"）。
# 因此必须把它们与"随包分发的运行时依赖"分开列，避免用户误解。
BUILD_ONLY = {
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "altgraph",
    "pefile",
    "setuptools",
    "pip",
    "wheel",
    "ruff",
    "pytest",
    "pytest-timeout",
    "pip-licenses",
    "fonttools",
}


def dump_licenses(out: Path) -> None:
    """导出第三方许可清单（随安装包分发）。

    分两段：
      1) 运行时依赖 —— 真正打进安装包，用户机器上存在；
      2) 构建期工具 —— 只在打包机器上有，GPL 工具在此列明但不随包分发。
    """
    import subprocess

    raw = out / "_licenses_raw.txt"
    try:
        subprocess.run(
            [sys.executable, "-m", "piplicenses", "--format=plain", "--output-file", str(raw)],
            check=False,
            capture_output=True,
        )
    except Exception:  # noqa: BLE001
        pass
    if not raw.exists():
        print("[许可] 未生成（需 pip install pip-licenses）")
        return

    lines = raw.read_text(encoding="utf-8", errors="ignore").splitlines()
    header, rest = (lines[0], lines[1:]) if lines else ("", [])
    runtime, build = [], []
    for ln in rest:
        if not ln.strip():
            continue
        name = ln.split()[0].lower() if ln.split() else ""
        (build if name in BUILD_ONLY else runtime).append(ln)

    dest = out / "THIRD_PARTY_LICENSES.txt"
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write("LinguaForge（译匠）第三方许可清单\n")
        fh.write("=" * 72 + "\n\n")
        fh.write("【一】随本软件分发的运行时依赖\n")
        fh.write("-" * 72 + "\n")
        fh.write(header.rstrip() + "\n")
        fh.write("\n".join(runtime) + "\n\n")
        fh.write("【二】仅用于构建本软件的工具（不随包分发）\n")
        fh.write("-" * 72 + "\n")
        fh.write(
            "以下工具只存在于打包构建环境，不会安装到您的电脑上。\n"
            "其中 PyInstaller 为 GPLv2，但其许可证附带例外条款：用它打包的\n"
            "应用程序本身不被要求以 GPL 开源。此处列出仅为透明披露。\n\n"
        )
        fh.write(header.rstrip() + "\n")
        fh.write("\n".join(build) + "\n\n")
        fh.write("本软件自身采用 Apache-2.0 许可，详见随包的 LICENSE 文件。\n")
        fh.write(
            "中文字体 Noto Sans SC 采用 SIL Open Font License 1.1，"
            "许可全文见 resources/fonts/OFL.txt。\n"
        )
    raw.unlink(missing_ok=True)
    print(f"[许可] 第三方清单 → {dest}（运行时 {len(runtime)} / 构建期 {len(build)}）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "resources"))
    ap.add_argument("--skip-font", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"资源输出目录：{out}")
    prepare_fonts(out, args.skip_font)
    prepare_ocr_models(out)
    dump_licenses(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
