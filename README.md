# LinguaForge（译匠）—— 本地离线文档翻译器

> 一台电脑 · 一个 Ollama · 不限页数与大小 · 数据不出本机

## 当前状态

**0.1.0 开发完成**（10.0 / 10.0 人日，2026-10-29）

| 能力 | 状态 |
|---|---|
| PDF 保排回填（文本层） | ✅ |
| 扫描件 OCR 兜底（RapidOCR / ONNX） | ✅ |
| 流式窗口流水线（内存与总页数无关） | ✅ |
| 断点续翻 + 翻译记忆复用 | ✅ |
| 术语表强制生效 | ✅ |
| 图形界面 + 健康条 + 双语预览 | ✅ |
| 命令行（doctor / models / translate） | ✅ |
| Windows 安装包 | ✅ 161 MB，含第三方许可清单 |

**未包含在 0.1.0**：EPUB、实时预览滚动同步、多文件批量队列（见 [`docs/15-产品路线图与优先级框架.md`](docs/15-产品路线图与优先级框架.md)）。

## 它解决什么问题

在线翻译服务（DeepL / Google）按页数收费、有体积上限，且必须把文档传到别人的服务器。LinguaForge 把整条链路留在本机：**文档不离开你的电脑，也不受页数与体积限制**。

代价是需要一份本机能跑的模型——用你已有的 Ollama，不额外捆绑权重。

## 支持格式

**输入**：PDF · DOCX · PPTX · XLSX / XLSM · HTML / HTM / XHTML · SRT · VTT · TXT · MD · PNG / JPG / JPEG / TIF / TIFF / BMP / WEBP

**输出**：Markdown · TXT · PDF（原位回填）· DOCX · PPTX · XLSX · SRT · VTT

## 快速开始

### 1. 准备 Ollama

```bash
ollama serve                     # 保持运行
ollama pull translategemma:12b   # 默认主模型，约 8.1 GB
```

模型可换。质量优先用 `translategemma:12b`；显存/内存吃紧用 `translategemma:4b`。降级链默认是 `translategemma:12b` → `translategemma:4b` → `qwen3:8b`，主模型缺失会自动往后找。

### 2. 安装

运行 `LinguaForge-0.1.0-Setup.exe`。安装程序**不写 Program Files、不写 HKLM**，按当前用户安装，避免 UAC 与权限问题。

> 安装包未做代码签名。Windows SmartScreen 会提示"未知发布者"，选择"更多信息 → 仍要运行"。

### 3. 图形界面

双击 `LinguaForge`。任务页顶部的健康条会先检查四件事：Ollama 连通性 / 主模型是否已下载 / 磁盘剩余空间 / OCR 组件。任一项标红时点击它可直接跳到对应设置页。

### 4. 命令行

安装目录下附 `linguaforge-cli.exe`：

```bash
# 环境自检
linguaforge-cli.exe doctor

# 看本机已有模型
linguaforge-cli.exe models

# 翻译：只翻 0–9 页，输出 Markdown
linguaforge-cli.exe translate "book.pdf" -o "book.md" --pages 0-10

# 双语对照 + 术语表
linguaforge-cli.exe translate "manual.docx" -o "manual.md" --bilingual --glossary terms.csv

# 忽略断点，从头重翻
linguaforge-cli.exe translate "book.pdf" -o "book.md" --no-resume
```

常用参数：`--fmt`（输出格式）· `--src` / `--dst`（语言，默认 auto → zh-Hans）· `--model` · `--window`（流式窗口页数，默认 20）· `--no-ocr`。

## 数据落在哪

| 内容 | 位置 |
|---|---|
| 配置 | `%LOCALAPPDATA%\LinguaForge\config.json` |
| 日志 | `%LOCALAPPDATA%\LinguaForge\logs\`（10 MB 轮转，保留 14 天） |
| 任务进度 / 翻译记忆 / 术语表 | `%LOCALAPPDATA%\LinguaForge\`（SQLite） |
| 临时分片 | 系统临时目录下 `lf_*`，启动时自动清扫超过 6 小时的残留 |

日志**不记录文档正文**，路径只留文件名 + 短哈希。卸载时询问是否一并删除上述数据。

## 技术栈

| 层 | 选型 | 许可 |
|---|---|---|
| UI | PySide6 | LGPL-3.0（动态链接） |
| PDF 渲染 | pypdfium2 | Apache-2.0 / BSD |
| PDF 提取 | pdfplumber + pdfminer.six | MIT |
| PDF 合并 / 生成 | pypdf + reportlab | BSD / BSD |
| OCR | RapidOCR（ONNX Runtime） | Apache-2.0 |
| 翻译 | Ollama HTTP API | 模型各自许可，不随包分发 |
| 存储 | SQLite（标准库） | Public Domain |
| 打包 | PyInstaller + Inno Setup | GPL with exception / 自由使用 |

**刻意排除**：PyMuPDF（AGPL）、BabelDOC、PDFMathTranslate —— 均因许可证无法与本项目兼容。完整清单见 [`docs/09-风险与合规清单.md`](docs/09-风险与合规清单.md) 与随包 `THIRD_PARTY_LICENSES.txt`。

## 目录

```
linguaforge/     核心引擎
  core/            DocIR、配置、错误码、日志、护栏、预检查
  parsers/         PDF / OOXML / HTML / 文本 / 字幕 / 图片
  translate/       Ollama 客户端、批量编号化翻译、降级链
  store/           SQLite：任务、页、块、翻译记忆、术语表
  writers/         Markdown / TXT / PDF 回填 / OOXML
  ui/              PySide6 界面、健康条、i18n（中/英）
app/main.py       入口（GUI 与 CLI 共用）
docs/             立项到验收全流程文档（00–22，共 23 份）
tests/            54 项单测
scripts/          build_windows.py / verify_books.py / verify_safeguards.py
packaging/        PyInstaller spec + Inno Setup iss
```

## 开发

```bash
python -m venv .venv && . .venv/Scripts/activate
pip install -r requirements.txt

ruff check . && ruff format --check .   # 代码风格
pytest -q                               # 54 项单测
python -m linguaforge.cli doctor        # 环境自检
```

打包 Windows 安装包（门禁 → 资源 → PyInstaller → Inno → 哈希，任一步失败即中止）：

```bash
python scripts/build_windows.py
```

端到端验证脚本：

```bash
python scripts/verify_books.py --dir <真实文档目录> --pages 0-4
python scripts/verify_safeguards.py        # 恶意输入护栏（zip 炸弹 / 图片炸弹 / 超大页面 / 深嵌套）
```

## 文档

入口：[`docs/00-文档总览与阅读顺序.md`](docs/00-文档总览与阅读顺序.md)

关键几份：`13` PRD · `14` 竞品定位 · `16` UX 设计系统 · `17` 安全与威胁建模 · `19` 错误码手册 · `22` 0.1.0 任务卡与验收清单。

## 许可证

项目本体 **Apache-2.0**。第三方组件许可见 [`THIRD_PARTY_LICENSES.txt`](resources/THIRD_PARTY_LICENSES.txt)，随安装包分发。

不捆绑任何模型权重——模型由 Ollama 管理，各自遵循其原始许可。
