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

ROOT = Path(__file__).resolve().parent.parent

NOTO_SC_URL = (
    "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/SC/"
    "NotoSansSC-Regular.otf"
)
NOTO_LICENSE_URL = "https://raw.githubusercontent.com/notofonts/noto-cjk/main/LICENSE"

# 国内镜像兜底（GitHub 可能不通）
NOTO_SC_MIRROR = "https://mirrors.tuna.tsinghua.edu.cn/Adoptium/NotoSansSC-Regular.otf"


def http_get(url: str, dest: Path, timeout: int = 60) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LinguaForge/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"   [失败] {type(exc).__name__}: {exc}")
        return False


def prepare_fonts(out: Path, skip: bool) -> None:
    fonts = out / "fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    target = fonts / "NotoSansSC-Regular.otf"

    if target.exists():
        print(f"[字体] 已存在，跳过：{target.name}")
    elif skip:
        print("[字体] 按参数跳过下载")
        return
    else:
        print(f"[字体] 下载 Noto Sans SC …")
        if not http_get(NOTO_SC_URL, target):
            print("[字体] 主源失败，尝试镜像 …")
            if not http_get(NOTO_SC_MIRROR, target):
                print("[字体] ⚠️ 下载失败。构建可继续，但 CJK 输出需手动放入字体。")
                return
        print(f"   已保存 {target}  ({target.stat().st_size/1e6:.1f} MB)")

    lic = fonts / "LICENSE_Noto_Sans_SC.txt"
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


def dump_licenses(out: Path) -> None:
    """导出第三方许可清单（随安装包分发）。"""
    import subprocess

    dest = out / "THIRD_PARTY_LICENSES.txt"
    try:
        subprocess.run(
            [sys.executable, "-m", "piplicenses", "--format=plain", "--output-file", str(dest)],
            check=False,
            capture_output=True,
        )
    except Exception:  # noqa: BLE001
        pass
    print(f"[许可] 第三方清单 → {dest if dest.exists() else '未生成（需 pip install pip-licenses）'}")


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
