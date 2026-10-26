# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec —— macOS（onedir + .app bundle）

与 Windows 版共用入口 app/main.py。
macOS 必须用 onedir：签名与公证都要求 .app 是可浏览的目录结构，
onefile 的可执行产物在 Gatekeeper 下容易被判为损坏。

构建（**必须在 macOS 上执行**，Windows 交叉编译不出可用的 arm64 产物）：
    pyinstaller packaging/mac/linguaforge.spec --noconfirm --clean
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = (Path(SPECPATH).parent.parent if "SPECPATH" in globals() else Path.cwd()).resolve()  # noqa: F821

datas = []
for rel in ("resources/fonts", "resources/icons", "resources/i18n", "resources/ocr_models"):
    p = ROOT / rel
    if p.exists():
        datas.append((str(p), rel))

_licenses = ROOT / "resources" / "THIRD_PARTY_LICENSES.txt"
if _licenses.exists():
    datas.append((str(_licenses), "resources"))

binaries = []
hiddenimports = [
    "pypdfium2", "pdfplumber", "pypdf", "reportlab",
    "rapidocr_onnxruntime", "onnxruntime", "cv2",
    "PIL", "numpy",
    "httpx", "platformdirs", "loguru", "psutil",
    "docx", "pptx", "openpyxl", "bs4", "lxml",
    "linguaforge.parsers.docx_parser", "linguaforge.parsers.pptx_parser",
    "linguaforge.parsers.xlsx_parser", "linguaforge.parsers.html_parser",
    "linguaforge.parsers.srt_parser", "linguaforge.parsers.image_parser",
    "linguaforge.writers.docx_writer", "linguaforge.writers.pptx_writer",
    "linguaforge.writers.xlsx_writer", "linguaforge.writers.srt_writer",
    "linguaforge.writers.pdf_rebuild",
]

for pkg in ("onnxruntime", "rapidocr_onnxruntime"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:  # noqa: BLE001
        pass

icon = str(ROOT / "resources" / "icons" / "app.icns")
if not Path(icon).exists():
    icon = None

a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(ROOT / "packaging" / "pyinstaller_hooks")],
    excludes=[
        "torch", "tensorflow", "pandas", "matplotlib", "scipy",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml",
        "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "pytest", "ruff", "fontTools",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LinguaForge",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LinguaForge",
)

app = BUNDLE(
    coll,
    name="LinguaForge.app",
    icon=icon,
    bundle_identifier="cn.linguaforge.app",
    info_plist={
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "LSMinimumSystemVersion": "11.0",
        "NSAppleEventsUsageDescription": "LinguaForge 需要访问您选择的文件以完成翻译。",
        "NSDocumentsFolderUsageDescription": "LinguaForge 需要访问您选择的文件夹以保存译文。",
        "NSDownloadsFolderUsageDescription": "LinguaForge 需要访问您选择的文件夹以保存译文。",
    },
)
