# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec —— Windows（onedir 模式）

说明：
  * onedir 而非 onefile：启动无需每次解压数百 MB，增量更新方便，杀软误报率更低。
  * 资源目录按"存在才收集"处理，缺哪个都不至于让构建直接失败。
  * OCR 模型随 rapidocr_onnxruntime 包一起分发，不需要额外 resources/ocr_models。
  * 排除 QtWebEngine 等巨型未用模块，控制体积。
  * 构建：pyinstaller packaging/win/linguaforge.spec --noconfirm --clean
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# SPECPATH 是 spec 文件所在目录（packaging/win），项目根在它上面两级
ROOT = (Path(SPECPATH).parent.parent if "SPECPATH" in globals() else Path.cwd()).resolve()  # noqa: F821

datas = []
for rel in ("resources/fonts", "resources/icons", "resources/i18n", "resources/ocr_models"):
    p = ROOT / rel
    if p.exists():
        datas.append((str(p), rel))

binaries = []
hiddenimports = [
    # PDF 内核
    "pypdfium2", "pdfplumber", "pypdf", "reportlab",
    # OCR
    "rapidocr_onnxruntime", "onnxruntime", "cv2",
    # 图像与数值
    "PIL", "numpy",
    # 网络与基础设施
    "httpx", "platformdirs", "loguru", "psutil",
    # 办公格式
    "docx", "pptx", "openpyxl", "bs4", "lxml",
    # 本项目子模块（动态 import 的解析器/写出器，静态分析扫不到）
    "linguaforge.parsers.docx_parser", "linguaforge.parsers.pptx_parser",
    "linguaforge.parsers.xlsx_parser", "linguaforge.parsers.html_parser",
    "linguaforge.parsers.srt_parser", "linguaforge.parsers.image_parser",
    "linguaforge.writers.docx_writer", "linguaforge.writers.pptx_writer",
    "linguaforge.writers.xlsx_writer", "linguaforge.writers.srt_writer",
    "linguaforge.writers.pdf_rebuild",
]

# onnxruntime / rapidocr 的动态库与数据文件由 hook 自动收集；这里再兜一次防漏 DLL
for pkg in ("onnxruntime", "rapidocr_onnxruntime"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:  # noqa: BLE001
        pass

icon = str(ROOT / "resources" / "icons" / "app.ico")
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
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                 # GUI 入口不弹控制台
    icon=icon,
    version=None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# CLI 入口单独一个 console 版可执行文件，便于命令行批量翻译与排障
exe_cli = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="linguaforge-cli",
    console=True,
    icon=icon,
)

coll = COLLECT(
    exe,
    exe_cli,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LinguaForge",
)
