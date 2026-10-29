# 20 · 工程规范、ADR 与依赖治理

版本 v2.0 ｜ 状态：已确认 ｜ 日期：2026-10-29
上游：`04-系统架构设计.md` §7、`12-翻译流水线-测试与发布策略.md`
下游：`21-现状审计与v2重开发方案.md`

---

## 0. 为什么这三件事要放在一份文档里

**编码规范**决定代码长什么样，**ADR** 决定为什么长这样，**依赖治理**决定它十年后还能不能构建。

三者共同的作用是：**让下一个人（或半年后的你）能安全地改代码。**

---

## 1. 编码规范（Python 3.13）

### 1.1 分层与依赖方向（硬约束）

```
ui/  →  pipeline.py  →  parsers/ writers/ translate/ ocr.py  →  core/
                      ↘  store/
```

| 规则 | 检查方式 |
|---|---|
| `ui/` 不得 import `parsers` / `writers` 的具体实现 | CI grep |
| `pipeline.py` 及其下层**不得 import 任何 Qt 符号** | CI grep `PySide6` |
| `core/` 不得 import 上层任何模块 | 人工 + import-linter |
| 新增格式/写出器只能通过注册表与统一契约接入 | CR 检查 |

### 1.2 路径处理（本项目事故高发区）

```python
# ✅ 唯一正确写法
p = Path(raw).expanduser().resolve()
name = p.name                    # 只取文件名，天然隔离分隔符
out = src.with_name(f"{src.stem}.{lang}{src.suffix}")

# ❌ 禁止
out = src.parent / (str(src.name).replace(".pdf", ".zh.pdf"))   # 字符串替换，遇到 .pdf.pdf 出错
open(f"{dir}/{name}")                                            # 手拼斜杠
```

**必须处理的三类文件名**：
1. Windows 保留名：`CON PRN AUX NUL COM1-9 LPT1-9`（含带扩展名的 `CON.txt`）
2. 尾随空格与点（Windows 会静默截断）
3. 长度 > 200 字符

统一实现 `core/paths.py::safe_filename(name) -> str`，全项目只用它。

### 1.3 异常与错误码

```python
# ✅
raise DocumentParseError(Problem("LF-D05", Severity.F, {"name": src.name}, detail=str(e)))

# ❌
raise DocxParseError(f"DOCX 解析失败：{p.name}: {e}")   # 6 个类各自演化，UI 只能显示原始字符串
```

- 禁止裸 `except:`；`except Exception as e` 必须带 `# noqa: BLE001` + 一行说明为什么不具体。
- 禁止把异常吞掉只打 `print`（GUI 下 `print` 不可见）。
- **面向用户的字符串只能由错误码 + 模板生成**（19 号 §3）。

### 1.4 SQL

```python
# ✅ 列名白名单 + 值参数化
_ALLOWED = frozenset({"status", "error", "updated_at"})
def update_task(self, task_id: str, **fields):
    bad = set(fields) - _ALLOWED
    if bad:
        raise ValueError(f"不允许的列: {sorted(bad)}")
    cols = ", ".join(f"{k}=?" for k in fields)
```

**规则**：SQL 中**值**永远用 `?`；**标识符**（表名/列名）只能来自模块级 `frozenset` 白名单，不得来自运行时输入。

### 1.5 时间、随机、并发

| 项 | 规则 |
|---|---|
| 时间戳 | 一律 `time.time()` 存 float（UTC epoch）；展示层格式化；**不在存储层存格式化字符串** |
| 随机 | 临时目录/文件名用 `tempfile.mkstemp`（安全随机），不用 `random` |
| 并发 | 渲染/OCR 用线程池；翻译用信号量控制并发；**任何共享可变状态必须加锁或有明确所有权** |
| 取消 | 统一 `CancellationToken`，各阶段在安全点检查；不得用 `thread.terminate()` |

### 1.6 日志

- 只记**元数据**（页码/块数/耗时/错误码），**不记文档正文**（19 号 §4.2）。
- 禁止在循环里 `log.debug` 每块一条（10 万块会写爆磁盘），按批或每 N 页汇总。

### 1.7 UI 层的规定

- **禁止** `setStyleSheet("color:#666")` 这类字面量样式（16 号 §8.1）。所有样式走 `theme/build_qss()` 与 token。
- **禁止**在 UI 线程做任何 I/O 或解析（当前已遵守：`worker.py` 用 QThread）。
- 长任务必须可取消、可关闭窗口后继续（托盘）或明确提示会中断。
- 每个控件必须有 `accessibleName`（16 号 §7）。

### 1.8 类型与静态检查

- 所有公开函数必须有类型注解。
- `mypy --strict` 先覆盖 `core/` 与 `translate/`，逐步扩至全包（12 号 §2.1）。
- `ruff` 规则集：`E,F,I,UP,B,SIM,RUF`。

### 1.9 命名与目录

| 对象 | 规则 | 例 |
|---|---|---|
| 模块 | `snake_case`，语义完整 | `pdf_rebuild.py` 不叫 `pdf.py` |
| 类 | `PascalCase` | `PDFRebuildWriter` |
| 常量 | `UPPER_SNAKE`，且集中定义 | `SUPPORTED_IN` 定义在 `pipeline.py`，UI 从此派生 |
| 私有 | 前缀 `_` | `_Line` / `_default_out` |
| 测试文件 | `test_<被测模块>.py` | `test_pipeline.py` |

---

## 2. 提交、分支与版本

### 2.1 提交信息（Conventional Commits）

```
<type>(<scope>): <subject>

<body 说明为什么，不是做了什么>

<footer: Closes #12 / BREAKING CHANGE>
```

| type | 用于 |
|---|---|
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `refactor` | 不改行为的重构 |
| `perf` | 性能优化 |
| `docs` | 仅文档 |
| `test` | 仅测试 |
| `build` / `ci` | 构建与流水线 |
| `chore` | 杂项 |

**从历史提交看，本项目已基本遵守**（如 `fix(CI): 校验值步骤指向 iscc 实际输出目录`），需保持。

### 2.2 分支

单人项目不引入复杂分支模型：

| 分支 | 用途 |
|---|---|
| `main` | 永远可构建、可发版 |
| `feat/<slug>` | 单个功能，合并前 squash |
| 无 `develop` | 单人项目不需要 |

**规则**：`main` 上不直接提交功能代码（文档与 CI 修复除外）。

### 2.3 版本

- SemVer：`MAJOR.MINOR.PATCH`
- tag 与 `pyproject.toml` 的 `version` 必须一致，CI 校验
- `0.y.z` 阶段：`MINOR` 可含破坏性变更，但**必须在 Release Notes 明示**

### 2.4 Code Review 清单

单人项目也要自审，按这张表过：

- [ ] 新增/修改的逻辑有对应测试（或说明为何不可测）
- [ ] 错误路径返回 `Problem` 而不是裸字符串
- [ ] SQL 无字符串拼接的标识符
- [ ] 文件路径经 `safe_filename`
- [ ] 不记文档正文到日志
- [ ] 未新增对 `ui/` 以外的 Qt 依赖
- [ ] 大文件/长任务路径不引入全量驻留（见 18 号 §4.2）
- [ ] 用户可见文案符合 13 号 §6 三段式
- [ ] 受影响的文档已更新（00–21）

---

## 3. 架构决策记录（ADR）

### 3.1 格式

每条 ADR 包含：**背景 → 决策 → 后果（正/负）→ 替代方案**。状态为 `Accepted` / `Superseded by ADR-xxx` / `Proposed`。

**规则**：ADR 一旦 Accepted **不修改内容**，被推翻时新增一条并标注 supersedes。这样历史可追溯。

### 3.2 索引

| # | 标题 | 状态 | 日期 |
|---|---|---|---|
| 001 | 用 DocIR 统一中间表示 | Accepted | 2026-10-21 |
| 002 | 逐页流式 + SQLite 落盘 | Accepted | 2026-10-21 |
| 003 | 流水线层不依赖 Qt | Accepted | 2026-10-21 |
| 004 | 排除 PyMuPDF（AGPL） | Accepted | 2026-10-21 |
| 005 | 不捆绑大模型权重 | Accepted | 2026-10-21 |
| 006 | RapidOCR 为默认 OCR | Accepted | 2026-10-21 |
| 007 | 编号化批量 + JSON 契约 | Accepted | 2026-10-21 |
| 008 | PDF 回填采用"剥离文字操作符"而非白底遮盖 | Accepted | 2026-10-23 |
| 009 | 双语对照用序列化往返隔离页面 | Accepted | 2026-10-23 |
| 010 | 字体实例化为静态 Regular/Bold | Accepted | 2026-10-23 |
| 011 | PyInstaller 用 onedir 而非 onefile | Accepted | 2026-10-23 |
| 012 | Windows 与 macOS 统一走 GitHub Actions | Accepted | 2026-10-21 |
| 013 | UI 能力清单从 pipeline 派生 | Accepted | 2026-10-26 |
| 014 | 不做自动更新检查 | **Accepted** | 2026-10-29 |
| 015 | 引入统一错误码体系 | **Accepted** | 2026-10-29 |
| 016 | 合并 6 个 ParseError 为单一类型 | **Accepted** | 2026-10-29 |

---

### ADR-001 · 用 DocIR 统一中间表示

**背景**：需支持 12+ 种输入格式 × 8 种输出格式。若每种格式各自对接，实现量是 N×M。

**决策**：所有格式先解析为 DocIR（文档→页→块→run），再统一翻译，最后由各 Writer 从 DocIR 输出。

**后果**
- ✅ 新增格式只需实现 1 个解析器或 1 个写出器（N+M）
- ✅ 翻译、术语、TM 只需实现一次
- ❌ DocIR 必须同时满足"PDF 需要坐标"与"Markdown 不需要坐标"，字段对某些格式冗余
- ❌ 格式特性（如 PPTX 母版、XLSX 公式）在 DocIR 里表达困难，只能降级

**替代方案**：每种格式独立流水线（实现量爆炸，否决）；用中间 HTML（会丢失坐标，否决）。

---

### ADR-004 · 排除 PyMuPDF（AGPL）

**背景**：PyMuPDF 是 PDF 处理事实标准，性能最好；但 1.24 起为 AGPL-3.0。

**决策**：使用 pypdfium2（渲染）+ pdfplumber/pdfminer（提取）+ pypdf（结构）+ reportlab（生成）。

**后果**
- ✅ 保持 Apache-2.0 分发自由，企业可闭源集成（这是 14 号 §3 的核心商业优势）
- ❌ 渲染速度低于 PyMuPDF（OCR 通道每页多 0.1–0.3 s，可接受）
- ❌ 需要自己实现版面重建（M2 的全部难点都源于此）

**替代方案**：购买 Artifex 商业许可（成本未知，否决）；接受 AGPL（放弃商业定位，否决）。

---

### ADR-008 · PDF 回填采用"剥离文字操作符"

**背景**：最初方案是在原文字上铺白色矩形再绘制译文。实测发现：白底会**连带盖掉表格框线与表头底纹**（表格区深色像素 1.99% → 0.00%），且复制出来是"原文译文字符交错"的乱码。

**决策**：过滤页面内容流中的 `Tj / TJ / ' / "` 四个文字操作符，保留线条、图片、矢量图形；再在原坐标绘制译文。剥离失败时（文字在 Form XObject 或 Type3 字体中）自动降级回白底遮盖。

**后果**
- ✅ 表格线、底纹、图片完整保留（实测 1.99% → 1.90%）
- ✅ 复制文本干净（只有译文）
- ❌ 需要解析并重写 PDF 内容流，实现复杂度高（`pdf_rebuild.py` 约 400 行）
- ❌ 对 Form XObject / Type3 字体不生效，需降级路径

**替代方案**：白底遮盖（破坏表格，否决）；重新排版整页（等于重写 PDF，超出范围，否决）。

---

### ADR-009 · 双语对照用序列化往返隔离页面

**背景**：双语输出需要"原页 + 译页交替"。直接 `copy.deepcopy(page)` 后修改，会导致原页文字被一起剥掉 —— 因为 pypdf 的页面对象共享底层内容流引用。

**决策**：把页面写入 `BytesIO` 再读回，完成一次序列化往返，得到真正独立的页面对象。

**后果**
- ✅ 原页与工作页彻底隔离
- ❌ 每页多一次序列化/反序列化（大文档有可观开销，实测未量化）

**替代方案**：`deepcopy`（实测无效，否决）；先输出单语 PDF 再用 pypdf 合并（会产生两份文件，内存翻倍，且顺序控制更复杂）。

---

### ADR-010 · 字体实例化为静态 Regular/Bold

**背景**：Noto Sans SC 是可变字体（variable font）。reportlab 对可变字体做子集化时会**丢失 ToUnicode 映射** —— 中文能画出来，但复制/检索提取不到文字。

**决策**：构建期用 fontTools `instancer` 把可变字体实例化为静态 `Regular/Bold` 两个 TTF，随包分发静态版。

**后果**
- ✅ 中文可复制、可检索
- ✅ 可用真实的 Bold 而非伪粗体（reportlab 5.x 移除了 `setTextRenderMode`）
- ❌ 体积增加（两份静态字体 21 MB，可变字体原件 17.8 MB 实际已无用，应在 V1.0 删除，见 18 号 §2.3）

**替代方案**：用系统字体（macOS/Windows 字体不同，输出不可控，否决）；用 reportlab 内建 CID 字体（字形覆盖不全，否决）。

---

### ADR-011 · PyInstaller 用 onedir

**背景**：onefile 单文件分发更"干净"，但每次启动要把数百 MB 解压到临时目录。

**决策**：onedir，由 Inno Setup 打包成安装程序。

**后果**
- ✅ 启动快（无解压）
- ✅ 增量更新友好
- ✅ 杀软误报率低于 onefile
- ❌ 安装后占用 436 MB（需在下载页标注，见 18 号 §1）
- ❌ 用户能看到内部结构（无实质影响）

---

### ADR-013 · UI 能力清单从 pipeline 派生

**背景**：`worker.py` 里曾硬编码 `KERNEL_INPUT_EXTS = {".pdf", ".txt", ".md"}`，而内核已支持 20 种输入。UI 提示"暂不支持"但实际能翻，属于能力漂移。

**决策**：UI 的 `KERNEL_INPUT_EXTS` / `KERNEL_OUTPUT_FMTS` 一律从 `pipeline.SUPPORTED_IN` / `pipeline.OUT_EXT` 派生，不得手写第二份。

**后果**
- ✅ 单一真相源，内核加格式 UI 自动跟上
- ❌ UI 依赖 pipeline 的常量（可接受，`pipeline` 本就是无 Qt 的公共层）

**通用规则**：**任何"能力清单"只能有一处定义。**

---

### ADR-014 · 不做自动更新检查（Accepted）

**背景**：`02` FR-7.5 原计划做"检查更新"（请求 GitHub Release API）。

**决策**：不做任何联网请求。改为「关于」页放 GitHub Releases 静态链接。

**理由**：产品第一卖点是"零外发"。一个版本检查请求会暴露 IP、版本、使用时间，并与"绝不上传"的承诺在用户认知中冲突。收益（省一次手动下载）远小于信任成本。

**后果**
- ✅ 可以对外无保留地说"零网络请求"
- ❌ 用户不会知道有新版本
- ❌ 老版本问题反馈会持续（需在 README 显眼位置放版本号与更新说明）

**替代方案**：opt-in 检查（默认关闭）—— 保留但不在 V1.0 实现。

---

### ADR-015 · 引入统一错误码体系（Accepted）

见 `19-可观测性与错误码手册.md` §1–§3。

**决策**：以 `LF-<域><序号>` 编码，配合 `Problem` 数据结构与本地化模板，取代"UI 直接显示 `str(e)`"。

**后果**
- ✅ 用户可搜索错误码、可复制诊断包、可按码统计失败率
- ✅ 文案可统一维护与国际化
- ❌ 改造面广（需覆盖 9 个异常类 + `PipelineResult.errors`）
- ❌ 短期增加样板代码

---

### ADR-016 · 合并 6 个 ParseError（Accepted）

**背景**：`DocxParseError` / `PptxParseError` / `XlsxParseError` / `HtmlParseError` / `SrtParseError` / `ImageParseError` 六个类除名字外行为完全相同。

**决策**：合并为 `DocumentParseError(format: str, problem: Problem)`。

**后果**
- ✅ 上层只需 catch 一个类型
- ✅ 新增格式不再新增异常类
- ❌ 需要改 6 个解析器与所有测试断言（改动量约 0.5 人日）

---

## 4. 依赖治理

### 4.1 现状问题

| 问题 | 证据 | 后果 |
|---|---|---|
| 无锁文件 | `requirements.txt` 全部用 `>=` | CI 与本地可能装出不同版本；同一天重装可能不一样 |
| 双装 OpenCV | `opencv-python` 与 `opencv-python-headless` 同时存在 | 体积与潜在 DLL 冲突（本次打包未受影响，但不可依赖运气） |
| 传递依赖来历不明 | `cryptography` 10 MB 但未在 requirements 中声明 | 依赖树无法解释 |
| 无漏洞扫描 | CI 只有许可门禁 | 解析库是 CVE 高发区（见 17 号 §9） |
| 字体/模型不入库 | `.gitignore` 排除 `*.ttf` 与 `*.onnx` | 构建依赖网络下载，CI 可能因网络失败（已有踩坑记录） |

### 4.2 目标状态

```
requirements.txt       （手写，只写直接依赖 + 版本约束；现状保留）
requirements.lock      （pip freeze 精度，含全部传递依赖的确定版本）
```

- **CI 与发版**用 `requirements.lock` 安装；本地开发可用 `requirements.txt`。
- **不强制 `--require-hashes`**：hash 模式要求每条依赖都带 sha256，当前有 4 个包来自 wheel-only 渠道，维护成本大于收益。若后续要发布 SBOM 或过审计，再升级到 hash 模式。
- **不引入 pip-compile / uv**（D14）：这两个工具会多一层工具链与 lock 语义迁移，而 `pip freeze` 已经能解决「同一天重装装出不同版本」这个真实问题。V1.1 若要更好的依赖图，再评估 uv。
- **漏洞扫描**：`pip-audit -r requirements.lock` 进 CI（P0-2），高危项必须清零或在 09 号风险表登记缓解措施。

### 4.3 新增依赖的准入四问

任何新依赖必须在 PR 描述里回答：

1. **许可**是什么？是否 AGPL/GPL/NC？（不满足直接否决，无例外）
2. **体积**增加多少？（>20 MB 需要理由）
3. **能否被现有依赖替代**？（避免引入第 3 个 PDF 库这类事）
4. **维护状态**？最近一次提交、是否有已知高危 CVE、是否有轮子（wheel）覆盖三平台？

### 4.4 升级节奏

| 类型 | 频率 | 方式 |
|---|---|---|
| 安全补丁（CVE） | 立即 | 单独 PR，走完整门禁 |
| 补丁版本 | 每月 | 一次批量升级 + 回归 |
| 次版本（minor） | 每季 | 单独评估，重点看 PDF/Qt/onnx 三类 |
| 主版本（major） | 按需 | 单独开 issue，评估迁移成本 |
| Python 版本 | 跟随依赖支持范围 | 当前 3.13，若某依赖不支持需评估回退 |

### 4.5 SBOM（软件物料清单）

发布时生成 CycloneDX 格式：

```bash
pip install cyclonedx-bom
cyclonedx-py requirements -i requirements.lock -o sbom.json
```

随 Release 附 `sbom.json`。价值：
- 用户（尤其企业）可自行审计
- 出现新 CVE 时可快速判断"我们是否受影响"
- 与 `THIRD_PARTY_LICENSES.txt` 互补（一个管许可，一个管清单）

### 4.6 许可门禁（已有，需强化）

```bash
pip-licenses --fail-on "GPL;AGPL;CC-BY-NC" --format=csv -o licenses.csv
```

**必须加的一条**：门禁不仅检查直接依赖，还要检查**传递依赖**与**打包进产物的文件**（如 OCR 的 ONNX 模型权重有自己的许可）。

---

## 5. 文档治理

| 规则 | 说明 |
|---|---|
| 编号唯一 | `docs/NN-标题.md`，编号不复用 |
| 状态行 | 每份文档末尾必须有 `**状态**：待评审 / 已确认 / 已废弃` |
| 上游/下游 | 文档头部标注依赖关系，便于变更传播 |
| 变更同步 | 代码改动若影响文档，同一 PR 内更新 |
| 不做"二份真相" | 任何数据（如支持格式数）只能在一处定义，其他地方引用 |

**已知的一处"二份真相"**：`00` 号文档说支持 12 种输入，`02` 号 FR-1 列了 14 种，代码 `SUPPORTED_IN` 是 20 个扩展名（约 12 种格式）。**必须以代码与 `02` 为准，`00` 号修订。**

---
**状态**：已确认（2026-10-29）

| 待确认项 | 结论 | 决策号 |
|---|---|---|
| ADR-014 不做自动更新检查 | **Accepted** | D8 |
| ADR-015 引入统一错误码体系 | **Accepted**，0.1.0 P1 | D11 |
| ADR-016 合并 6 个 ParseError | **Accepted**，0.1.0 P1-2 | — |
| §4.2 锁文件方案 | **Accepted**，但**降级为 `pip freeze` 精度**、不引 pip-compile/uv、不强制 hash | D14 |

> 本文档的规则不是「建议」，是 Code Review 的检查表。规则与现实冲突时，改规则要写 ADR，不能口头豁免。
