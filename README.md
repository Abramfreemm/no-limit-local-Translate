# LinguaForge（译匠）—— 本地离线文档翻译器

> 一台电脑 · 一个 Ollama · 不限页数与大小 · 数据不出本机

## 当前阶段

**M1 内核 MVP 已完成 ✅，进入 M2 开发（PDF 排版重建）**。完整立项→开发文档见 [`docs/`](docs/)，入口是 [`docs/00-文档总览与阅读顺序.md`](docs/00-文档总览与阅读顺序.md)。

## 项目一句话

读取本地文档（PDF / DOCX / PPTX / XLSX / EPUB / 图片 …）→ 必要时离线 OCR → 调用本机 Ollama 中的开源模型翻译 → 按原格式或双语对照输出。**全程离线，无页数与体积上限。**

## 技术骨架（拟定）

| 层 | 选型 |
|---|---|
| UI | PySide6（Qt for Python，LGPL） |
| PDF | pypdfium2 渲染 + pdfplumber 提取 + pypdf 合并 + reportlab 生成（全宽松许可，规避 PyMuPDF 的 AGPL） |
| OCR | RapidOCR（ONNX，Apache-2.0）默认；可选 PaddleOCR / Ollama 视觉模型 |
| 翻译 | Ollama HTTP API，推荐 `translategemma:12b`（质量）或 `qwen3:8b`（Apache-2.0，商用友好） |
| 存储 | SQLite（进度 / 翻译记忆 / 术语表），支撑断点续翻与大文件流式 |
| 打包 | Windows：PyInstaller + Inno Setup → `.exe` 安装包；macOS：PyInstaller + create-dmg → `.dmg` |

## 交付物

1. `LinguaForge-x.y.z-Setup.exe` —— Windows x64 安装包
2. `LinguaForge-x.y.z-arm64.dmg` —— macOS Apple Silicon 拖拽安装包

> ⚠️ dmg 无法在 Windows 上交叉编译，需要 macOS 环境（推荐 GitHub Actions 免费 macOS 构建）。详见 `docs/07`。

## 目录

```
docs/        立项到开发的全套文档（00–11，共 12 份）
linguaforge/ 核心引擎与 CLI（M1 已完成，可运行）
tests/       测试用例与样本
prototypes/  M0 原型验证脚本（Ollama / OCR / PDF 三条链路）
scripts/     资源准备等辅助脚本
packaging/   PyInstaller spec + Inno Setup iss
.github/     GitHub Actions 构建流（Windows + macOS 双 job）
samples/     示例 PDF 与译文
```

## 许可证

项目拟定 **Apache-2.0**；第三方许可随包分发 `THIRD_PARTY_LICENSES.txt`。
