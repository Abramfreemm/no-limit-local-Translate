# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec —— Windows（onedir 模式）

说明：
  * onedir 而非 onefile：启动无需解压数百 MB，增量更新方便，杀软误报率更低。
  * 资源（字体 / OCR 模型 / 图标 / 翻译文件）通过 datas 打进包。
  * 排除 QtWebEngine 等巨型未用模块，控制体积。
  * 构建：pyinstaller packaging/win/linguaforge.spec --noconfirm --clean
"""

from PyInstaller.utils.hooks import collect_all

datas = [
    ("resources/fonts", "resources/fonts"),
    ("resources/ocr_models", "resources/ocr_models"),
    ("resources/icons", "resources/icons"),
    ("resources/i18n", "resources/i18n"),
]
binaries = []
hiddenimports = [
    "pypdfium2",
    "pdfplumber",
    "pypdf",
    "reportlab",
    "rapidocr_onnxruntime",
    "onnxruntime",
    "cv2",
    "PIL",
    "numpy",
    "httpx",
    "platformdirs",
    "loguru",
    "psutil",
    "docx",
    "pptx",
    "openpyxl",
    "bs4",
    "lxml",
]

# onnxruntime 的动态库由 hook 自动收集；这里再兜一次，避免漏 DLL
for pkg in ("onnxruntime", "rapidocr_onnxruntime"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:  # noqa: BLE001
        pass

a = Analysis(
    ["app/main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=["packaging/pyinstaller_hooks"],
    excludes=[
        "torch", "tensorflow", "pandas", "matplotlib", "scipy",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml",
        "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "pytest", "ruff",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="linguaforge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                 # GUI 入口不弹控制台
    icon="resources/icons/app.ico",
    version=None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# CLI 入口单独一个 console 版可执行文件
exe_cli = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="linguaforge-cli",
    console=True,
    icon="resources/icons/app.ico",
)

coll = COLLECT(
    exe,
    exe_cli,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="linguaforge",
)
