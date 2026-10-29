"""界面双语字典。

只覆盖 UI 文案，不参与翻译业务本身（业务语言由 Config.lang_src / lang_dst 决定）。
用法：``tr("task.start", lang)``；需要插值时用关键字参数 ``tr("model.online", lang, version=v)``。
"""

from __future__ import annotations

ZH = "zh-CN"
EN = "en-US"

#: 界面可选语言（代码, 展示名）。顺序即下拉框顺序。
LANGS: tuple[tuple[str, str], ...] = ((ZH, "简体中文"), (EN, "English"))

_ZH: dict[str, str] = {
    # ---- 应用 / 导航 ----
    "app.title": "LinguaForge 译匠",
    "app.ready": "就绪",
    "nav.task": "翻译任务",
    "nav.model": "模型管理",
    "nav.glossary": "术语表",
    "nav.settings": "设置",
    # ---- 任务页 ----
    "task.files": "文件队列",
    "task.add": "添加文件…",
    "task.remove": "移除",
    "task.clear": "清空",
    "task.start": "开始翻译",
    "task.pause": "暂停",
    "task.resume": "继续",
    "task.cancel": "取消",
    "task.preview": "预览结果",
    "task.open_out": "打开输出目录",
    "task.col_file": "文件名",
    "task.col_format": "格式",
    "task.col_status": "状态",
    "task.col_progress": "进度",
    "task.outfmt": "输出格式",
    "task.bilingual": "双语对照",
    "task.outdir": "输出目录（留空 = 与源文件同目录）",
    "task.browse": "选择…",
    "task.drop": "把文件拖到这里（PDF / Office / 文本 / 图片）",
    "task.fmt_warn_pdf": "PDF 输出走原位回填，仅支持 PDF 原文；队列中的非 PDF 文件会自动改用 Markdown 输出。",
    "task.fmt_unknown": "未知的输出格式，将按 Markdown 处理。",
    "task.unsupported": "内核暂不支持（等待解析器接入）",
    "task.hint_unsupported": "已加入队列，但内核尚无该格式的解析器：{ext}",
    "task.no_selection": "请先选择一个已完成的任务行。",
    "task.not_done": "该任务尚未产出错文件，无法预览。",
    # ---- 状态 ----
    "status.pending": "等待中",
    "status.running": "进行中",
    "status.paused": "已暂停",
    "status.done": "已完成",
    "status.failed": "失败",
    "status.canceled": "已取消",
    "status.skipped": "已跳过",
    # ---- 模型页 ----
    "model.host": "Ollama 地址",
    "model.refresh": "刷新",
    "model.status": "连接状态",
    "model.probing": "检测中…",
    "model.online": "已连接（Ollama v{version}）",
    "model.offline": "未连接：{error}",
    "model.primary": "主模型",
    "model.pull": "拉取模型",
    "model.pull_name": "模型名",
    "model.pull_cancel": "取消拉取",
    "model.pulling": "拉取中…",
    "model.pull_done": "拉取完成：{name}",
    "model.pull_failed": "拉取失败：{error}",
    "model.pull_canceled": "已取消拉取：{name}",
    "model.col_name": "模型",
    "model.col_params": "参数规模",
    "model.col_quant": "量化",
    "model.col_size": "大小",
    "model.col_status": "状态",
    "model.installed": "已安装",
    "model.not_installed": "未安装",
    "model.saved": "主模型已设为 {name}",
    "model.host_saved": "Ollama 地址已更新为 {host}",
    "model.size_gb": "{size:.2f} GB",
    "model.unknown": "未知",
    # ---- 术语表 ----
    "glossary.add": "新增",
    "glossary.delete": "删除",
    "glossary.save": "保存",
    "glossary.reload": "重新载入",
    "glossary.import": "导入 CSV",
    "glossary.export": "导出 CSV",
    "glossary.col_src": "原文术语",
    "glossary.col_dst": "译文",
    "glossary.col_note": "备注",
    "glossary.pair": "当前语言对：{src} → {dst}（保存只覆盖该语言对）",
    "glossary.tm": "翻译记忆（TM）",
    "glossary.tm_stats": "TM 条目 {entries} 条 / 累计命中 {hits} 次",
    "glossary.tm_import": "从 TM 并入（去重）",
    "glossary.tm_imported": "已从 TM 并入 {n} 条，点「保存」生效",
    "glossary.saved": "已保存 {n} 条术语（{src} → {dst}）",
    "glossary.loaded": "已载入 {n} 条术语",
    "glossary.imported": "已导入 {n} 条",
    "glossary.exported": "已导出 {n} 条到 {path}",
    "glossary.need_two": "原文与译文都不能为空。",
    "glossary.confirm_save": "保存将覆盖当前语言对（{src} → {dst}）的全部术语，共 {n} 条。继续？",
    # ---- 设置页 ----
    "settings.lang": "界面语言",
    "settings.target": "默认目标语言",
    "settings.host": "Ollama 地址",
    "settings.ocr": "启用 OCR（扫描页）",
    "settings.dpi": "OCR 渲染 DPI",
    "settings.window_pages": "流式窗口页数",
    "settings.window_chars": "流式窗口字符数",
    "settings.default_fmt": "默认输出格式",
    "settings.bilingual": "默认双语对照",
    "settings.apply": "应用并保存",
    "settings.reset": "恢复默认",
    "settings.saved": "设置已保存到 {path}",
    "settings.reset_done": "已恢复默认设置（尚未保存）",
    "settings.section_ui": "界面",
    "settings.section_engine": "引擎",
    "settings.section_perf": "性能",
    "settings.section_out": "输出",
    # ---- 预览 ----
    "preview.title": "并排预览 — {name}",
    "preview.src": "原文",
    "preview.dst": "译文",
    "preview.loading": "载入中…",
    "preview.empty": "（无内容）",
    "preview.src_unsupported": "内核暂无 {ext} 的原文提取器，左侧留空。",
    "preview.truncated": "…（原文过长，已截断）",
    # ---- 提示 ----
    "msg.ollama_title": "Ollama 不可用",
    "msg.ollama_body": "无法启动翻译：\n{problems}\n\n请确认 Ollama 已启动、地址正确，且所选模型已拉取。",
    "msg.goto_model": "是否跳转到「模型管理」页处理？",
    "msg.no_file": "请先添加至少一个文件。",
    "msg.all_done": "全部结束：成功 {ok}，失败 {fail}",
    "msg.fatal": "翻译线程异常：{error}",
    "msg.error": "错误",
    "msg.warning": "警告",
    "msg.info": "提示",
    "msg.confirm_clear": "确定清空整个队列？",
    "msg.file_filter": "支持的文件 (*.pdf *.docx *.pptx *.xlsx *.txt *.md *.html *.srt *.vtt *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp);;所有文件 (*.*)",
    "msg.csv_filter": "CSV 文件 (*.csv);;所有文件 (*.*)",
    "log.start": "开始：{name}",
    "log.done": "完成：{name}（{elapsed:.1f}s，{blocks} 块 / {translated} 已译）",
    "log.fail": "失败：{name} — {error}",
    "log.canceled": "已取消：{name}",
    # ---- 健康条（旅程 E）----
    "health.title": "环境状态",
    "health.recheck": "重新检测",
    "health.checking": "检测中…",
    "health.all_ok": "一切就绪，可以开始翻译。",
    "health.not_checked": "尚未检测。点击「重新检测」查看环境状态。",
    "health.issues": "有 {n} 项需要处理：",
    "health.fix_hint": "点击带下划线的项目前往处理。",
    # 各项名称
    "health.item.ollama": "Ollama 服务",
    "health.item.model": "翻译模型",
    "health.item.disk": "磁盘空间",
    "health.item.ocr": "OCR 组件",
    # 各状态文案
    "health.ollama.ok": "已连接（{version}）",
    "health.ollama.err": "未启动或地址错误",
    "health.ollama.warn": "版本偏低，建议升级",
    "health.ollama.not_installed": "未检测到 Ollama",
    "health.model.ok": "「{model}」已就绪",
    "health.model.err": "「{model}」未下载",
    "health.model.warn": "「{model}」未下载，将尝试备用模型",
    "health.model.unknown": "服务未连接，无法确认",
    "health.disk.ok": "剩余 {gb} GB，充足",
    "health.disk.warn": "仅剩 {gb} GB，建议清理",
    "health.disk.err": "剩余 {gb} GB，空间不足",
    "health.ocr.ok": "可用",
    "health.ocr.warn": "不可用，扫描件将无法识别",
    # ---- 通用 ----
    "common.ok": "确定",
    "common.cancel": "取消",
    "common.close": "关闭",
    "common.unknown": "未知",
}

_EN: dict[str, str] = {
    # ---- 应用 / 导航 ----
    "app.title": "LinguaForge",
    "app.ready": "Ready",
    "nav.task": "Tasks",
    "nav.model": "Models",
    "nav.glossary": "Glossary",
    "nav.settings": "Settings",
    # ---- 任务页 ----
    "task.files": "File queue",
    "task.add": "Add files…",
    "task.remove": "Remove",
    "task.clear": "Clear",
    "task.start": "Start",
    "task.pause": "Pause",
    "task.resume": "Resume",
    "task.cancel": "Cancel",
    "task.preview": "Preview",
    "task.open_out": "Open output folder",
    "task.col_file": "File",
    "task.col_format": "Format",
    "task.col_status": "Status",
    "task.col_progress": "Progress",
    "task.outfmt": "Output format",
    "task.bilingual": "Bilingual",
    "task.outdir": "Output folder (empty = same as source)",
    "task.browse": "Browse…",
    "task.drop": "Drop files here (PDF / Office / text / image)",
    "task.fmt_warn_pdf": "PDF output rewrites the source in place and only accepts PDF input; "
    "non-PDF files in the queue fall back to Markdown.",
    "task.fmt_unknown": "Unknown output format; falling back to Markdown.",
    "task.unsupported": "Not supported by kernel yet",
    "task.hint_unsupported": "Queued, but the kernel has no parser for this format yet: {ext}",
    "task.no_selection": "Please select a finished row first.",
    "task.not_done": "No output file has been produced for this task yet.",
    # ---- 状态 ----
    "status.pending": "Pending",
    "status.running": "Running",
    "status.paused": "Paused",
    "status.done": "Done",
    "status.failed": "Failed",
    "status.canceled": "Canceled",
    "status.skipped": "Skipped",
    # ---- 模型页 ----
    "model.host": "Ollama host",
    "model.refresh": "Refresh",
    "model.status": "Connection",
    "model.probing": "Checking…",
    "model.online": "Connected (Ollama v{version})",
    "model.offline": "Not connected: {error}",
    "model.primary": "Primary model",
    "model.pull": "Pull model",
    "model.pull_name": "Model name",
    "model.pull_cancel": "Cancel pull",
    "model.pulling": "Pulling…",
    "model.pull_done": "Pull finished: {name}",
    "model.pull_failed": "Pull failed: {error}",
    "model.pull_canceled": "Pull canceled: {name}",
    "model.col_name": "Model",
    "model.col_params": "Params",
    "model.col_quant": "Quant",
    "model.col_size": "Size",
    "model.col_status": "Status",
    "model.installed": "Installed",
    "model.not_installed": "Missing",
    "model.saved": "Primary model set to {name}",
    "model.host_saved": "Ollama host updated to {host}",
    "model.size_gb": "{size:.2f} GB",
    "model.unknown": "Unknown",
    # ---- 术语表 ----
    "glossary.add": "Add",
    "glossary.delete": "Delete",
    "glossary.save": "Save",
    "glossary.reload": "Reload",
    "glossary.import": "Import CSV",
    "glossary.export": "Export CSV",
    "glossary.col_src": "Term",
    "glossary.col_dst": "Translation",
    "glossary.col_note": "Note",
    "glossary.pair": "Language pair: {src} → {dst} (saving overwrites this pair only)",
    "glossary.tm": "Translation memory (TM)",
    "glossary.tm_stats": "TM entries: {entries} / total hits: {hits}",
    "glossary.tm_import": "Merge from TM (dedup)",
    "glossary.tm_imported": "Merged {n} entries from TM — click Save to apply",
    "glossary.saved": "Saved {n} terms ({src} → {dst})",
    "glossary.loaded": "Loaded {n} terms",
    "glossary.imported": "Imported {n} entries",
    "glossary.exported": "Exported {n} entries to {path}",
    "glossary.need_two": "Term and translation must not be empty.",
    "glossary.confirm_save": "Saving overwrites all terms for {src} → {dst} ({n} rows). Continue?",
    # ---- 设置页 ----
    "settings.lang": "UI language",
    "settings.target": "Default target language",
    "settings.host": "Ollama host",
    "settings.ocr": "Enable OCR (scanned pages)",
    "settings.dpi": "OCR render DPI",
    "settings.window_pages": "Streaming window (pages)",
    "settings.window_chars": "Streaming window (chars)",
    "settings.default_fmt": "Default output format",
    "settings.bilingual": "Default bilingual output",
    "settings.apply": "Apply & save",
    "settings.reset": "Reset to defaults",
    "settings.saved": "Settings saved to {path}",
    "settings.reset_done": "Defaults restored (not saved yet)",
    "settings.section_ui": "Interface",
    "settings.section_engine": "Engine",
    "settings.section_perf": "Performance",
    "settings.section_out": "Output",
    # ---- 预览 ----
    "preview.title": "Side-by-side preview — {name}",
    "preview.src": "Source",
    "preview.dst": "Translation",
    "preview.loading": "Loading…",
    "preview.empty": "(empty)",
    "preview.src_unsupported": "No source extractor for {ext} yet; left pane is empty.",
    "preview.truncated": "… (source too long, truncated)",
    # ---- 提示 ----
    "msg.ollama_title": "Ollama unavailable",
    "msg.ollama_body": "Cannot start translation:\n{problems}\n\n"
    "Make sure Ollama is running, the host is correct, "
    "and the selected model has been pulled.",
    "msg.goto_model": "Jump to the Models page to fix it?",
    "msg.no_file": "Please add at least one file first.",
    "msg.all_done": "All finished: {ok} succeeded, {fail} failed",
    "msg.fatal": "Translation thread error: {error}",
    "msg.error": "Error",
    "msg.warning": "Warning",
    "msg.info": "Information",
    "msg.confirm_clear": "Clear the whole queue?",
    "msg.file_filter": "Supported files (*.pdf *.docx *.pptx *.xlsx *.txt *.md *.html *.srt *.vtt "
    "*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp);;All files (*.*)",
    "msg.csv_filter": "CSV files (*.csv);;All files (*.*)",
    "log.start": "Start: {name}",
    "log.done": "Done: {name} ({elapsed:.1f}s, {blocks} blocks / {translated} translated)",
    "log.fail": "Failed: {name} — {error}",
    "log.canceled": "Canceled: {name}",
    # ---- 健康条（旅程 E）----
    "health.title": "Environment",
    "health.recheck": "Re-check",
    "health.checking": "Checking…",
    "health.all_ok": "All set. Ready to translate.",
    "health.not_checked": "Not checked yet. Click “Re-check” to inspect the environment.",
    "health.issues": "{n} item(s) need attention:",
    "health.fix_hint": "Click an underlined item to go fix it.",
    "health.item.ollama": "Ollama service",
    "health.item.model": "Translation model",
    "health.item.disk": "Disk space",
    "health.item.ocr": "OCR component",
    "health.ollama.ok": "Connected ({version})",
    "health.ollama.err": "Not running or wrong address",
    "health.ollama.warn": "Version is old; consider upgrading",
    "health.ollama.not_installed": "Ollama not found",
    "health.model.ok": "“{model}” is ready",
    "health.model.err": "“{model}” is not downloaded",
    "health.model.warn": "“{model}” missing; a fallback will be tried",
    "health.model.unknown": "Service unreachable; cannot verify",
    "health.disk.ok": "{gb} GB free — plenty",
    "health.disk.warn": "Only {gb} GB free; consider cleaning up",
    "health.disk.err": "Only {gb} GB free — not enough",
    "health.ocr.ok": "Available",
    "health.ocr.warn": "Unavailable — scanned pages cannot be recognized",
    "common.ok": "OK",
    "common.cancel": "Cancel",
    "common.close": "Close",
    "common.unknown": "Unknown",
}

_TABLES: dict[str, dict[str, str]] = {ZH: _ZH, EN: _EN}


def normalize_lang(value: str | None) -> str:
    """把任意语言输入归一到受支持的语言代码，未知输入回落到中文。"""
    v = (value or "").strip().lower()
    if v.startswith("en"):
        return EN
    if v.startswith("zh"):
        return ZH
    return ZH


def tr(key: str, lang: str | None = None, **kwargs: object) -> str:
    """取一条界面文案；``kwargs`` 用于 ``str.format`` 插值。"""
    table = _TABLES.get(normalize_lang(lang), _ZH)
    text = table.get(key) or _ZH.get(key) or _EN.get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


# ---------------------------------------------------------------------------
# 错误码 -> 用户文案（19 号 §2 全表）
#
# UI 唯一的职责就是把 Problem 渲染成人类可读文案，不再自己拼字符串。
# 三段式：发生了什么 / 为什么 / 你能做什么。
# ---------------------------------------------------------------------------

PROBLEM_TEXT: dict[str, dict[str, str]] = {
    # ---------------- E 域 · 环境与依赖 ----------------
    "LF-E01": {
        "zh": "没连上 Ollama（本机翻译引擎）。它可能没有启动。请先打开 Ollama，再点「重新检测」。",
        "en": "Cannot reach Ollama (the local translation engine). It may not be running. Start Ollama, then click Re-detect.",
    },
    "LF-E02": {
        "zh": "这台电脑上没找到 Ollama。它是本软件依赖的翻译引擎，需要单独安装（免费）。",
        "en": "Ollama was not found on this computer. It is the translation engine this app relies on and must be installed separately (free).",
    },
    "LF-E03": {
        "zh": "你的 Ollama 版本较旧（当前 {version}，建议 ≥ {min_required}），部分功能可能异常。建议升级。",
        "en": "Your Ollama version is old (current {version}, recommended ≥ {min_required}). Some features may misbehave. Consider upgrading.",
    },
    "LF-E04": {
        "zh": "模型「{model}」还没有下载。下载后即可使用。本机已有：{available}",
        "en": "Model “{model}” has not been downloaded yet. Download it to continue. Already available: {available}",
    },
    "LF-E05": {
        "zh": "模型「{model}」加载失败，可能是内存不足。换一个小一点的模型通常可以解决。",
        "en": "Failed to load model “{model}”, possibly due to insufficient memory. A smaller model usually works.",
    },
    "LF-E06": {
        "zh": "模型下载没有完成，可能是网络中断。可以重新下载，已下载的部分会保留。",
        "en": "The model download did not finish, possibly due to a network interruption. Retrying keeps the downloaded part.",
    },
    "LF-E07": {
        "zh": "文字识别组件缺失，扫描页将被跳过（其余页正常翻译）。",
        "en": "The OCR component is missing. Scanned pages will be skipped (other pages translate normally).",
    },
    "LF-E08": {
        "zh": "文字识别模型文件异常，扫描页无法识别。",
        "en": "The OCR model files are invalid. Scanned pages cannot be recognised.",
    },
    "LF-E09": {
        "zh": "磁盘空间不够。这次大约需要 {need_mb} MB，{drive} 盘还剩 {free_mb} MB。",
        "en": "Not enough disk space. This run needs about {need_mb} MB; {drive} has {free_mb} MB free.",
    },
    "LF-E10": {
        "zh": "无法写入输出目录「{dir}」。它可能是只读的，或被其他程序占用。",
        "en": "Cannot write to the output directory “{dir}”. It may be read-only or in use by another program.",
    },
    "LF-E11": {
        "zh": "检测到系统代理，可能影响本机服务连接。已自动绕过 127.0.0.1。",
        "en": "A system proxy was detected and could affect local connections. 127.0.0.1 is bypassed automatically.",
    },
    "LF-E12": {
        "zh": "Ollama 正在监听「{host}」，可能被局域网内其他设备访问。建议改回 127.0.0.1。",
        "en": "Ollama is listening on “{host}”, which may be reachable from your network. Bind it back to 127.0.0.1.",
    },
    # ---------------- D 域 · 文档输入 ----------------
    "LF-D01": {
        "zh": "找不到文件「{name}」。它可能被移动或删除了。",
        "en": "Cannot find file “{name}”. It may have been moved or deleted.",
    },
    "LF-D02": {
        "zh": "「{name}」是空文件（0 字节），没有可翻译的内容。",
        "en": "“{name}” is an empty file (0 bytes); there is nothing to translate.",
    },
    "LF-D03": {
        "zh": "「{name}」设置了打开密码，暂不支持。请先在原软件里取消密码。",
        "en": "“{name}” is password-protected, which is not supported. Remove the password first.",
    },
    "LF-D04": {
        "zh": "暂不支持「{ext}」格式。目前支持：{list}",
        "en": "“{ext}” format is not supported. Supported: {list}",
    },
    "LF-D05": {
        "zh": "「{name}」文件结构损坏，无法读取。",
        "en": "“{name}” is structurally damaged and cannot be read.",
    },
    "LF-D06": {
        "zh": "第 {page} 页尺寸异常（{w}×{h}），已跳过。",
        "en": "Page {page} has an abnormal size ({w}×{h}) and was skipped.",
    },
    "LF-D07": {
        "zh": "「{name}」内部结构异常（疑似压缩炸弹），出于安全已拒绝打开。",
        "en": "“{name}” has an abnormal internal structure (possible compression bomb). Refused to open for safety.",
    },
    "LF-D08": {
        "zh": "图片尺寸过大（{w}×{h}），无法处理。",
        "en": "Image is too large ({w}×{h}) to process.",
    },
    "LF-D09": {
        "zh": "文档结构异常（嵌套过深），已停止解析以避免卡死。",
        "en": "Abnormal document structure (too deeply nested). Parsing stopped to avoid a hang.",
    },
    "LF-D10": {
        "zh": "「{name}」正被其他程序占用。关闭占用它的程序后重试。",
        "en": "“{name}” is locked by another program. Close it and retry.",
    },
    "LF-D11": {
        "zh": "「{name}」处理超时（超过 {n} 分钟），已停止。这个文件可能结构异常复杂。",
        "en": "“{name}” timed out after {n} minutes and was stopped. The file may be unusually complex.",
    },
    # ---------------- T 域 · 翻译过程 ----------------
    "LF-T01": {
        "zh": "模型输出格式异常，已自动改用备用解析方式。",
        "en": "Unexpected model output format; fell back to an alternative parser.",
    },
    "LF-T02": {
        "zh": "模型返回的条目数与请求不符，已自动改用备用解析方式。",
        "en": "Model returned a different number of items; fell back to an alternative parser.",
    },
    "LF-T03": {
        "zh": "模型响应超时。已自动重试并拆分批次；若仍失败，相关段落保留原文。",
        "en": "Model response timed out. Retried with smaller batches; if it still fails, the affected passages keep the original text.",
    },
    "LF-T04": {
        "zh": "模型返回内容为空，相关段落保留原文。",
        "en": "Model returned empty content; the affected passages keep the original text.",
    },
    "LF-T05": {
        "zh": "部分长段落超出模型上下文，已自动拆分重译。",
        "en": "Some long passages exceeded the model context and were split and retranslated.",
    },
    "LF-T06": {
        "zh": "第 {pages} 页的 {n} 段翻译失败。原文已保留，可直接阅读。",
        "en": "Translation failed for {n} passages on page {pages}. The original text is preserved.",
    },
    "LF-T07": {
        "zh": "术语表里「{term}」有 {n} 种译法，已按最后一条生效。",
        "en": "The glossary has {n} translations for “{term}”; the last one is used.",
    },
    "LF-T08": {
        "zh": "{n} 段翻译失败，已保留原文。",
        "en": "{n} passages failed to translate; the original text is preserved.",
    },
    "LF-T09": {
        "zh": "主模型「{primary}」不可用，且没有可用的备用模型。建议再装一个较小的模型作为备用。",
        "en": "Primary model “{primary}” is unavailable and no fallback model works. Install a smaller model as a backup.",
    },
    # ---------------- O 域 · 输出 ----------------
    "LF-O01": {
        "zh": "生成「{fmt}」文件失败。{detail}",
        "en": "Failed to generate “{fmt}” output. {detail}",
    },
    "LF-O02": {
        "zh": "中文字体嵌入失败，译文可能显示为方框。已回退到系统字体。",
        "en": "Failed to embed the CJK font; translated text may render as boxes. Fell back to a system font.",
    },
    "LF-O03": {
        "zh": "写入过程中磁盘满了。请清理空间后重试（已译内容已保存，可续跑）。",
        "en": "Disk became full while writing. Free space and retry (translated pages are saved and resumable).",
    },
    "LF-O04": {
        "zh": "输出文件名已自动调整为「{name}」。",
        "en": "The output filename was adjusted to “{name}”.",
    },
    "LF-O05": {
        "zh": "输出文件「{name}」正被打开。关闭它后重试。",
        "en": "Output file “{name}” is open elsewhere. Close it and retry.",
    },
    # ---------------- S 域 · 系统内部 ----------------
    "LF-S01": {
        "zh": "程序遇到一个未预期的错误。已自动记录日志，可复制诊断信息反馈给我们。",
        "en": "An unexpected error occurred. It has been logged; you can copy diagnostics for support.",
    },
    "LF-S02": {
        "zh": "本地进度数据库异常，本次无法续跑，将从头开始。",
        "en": "The local progress database is broken; this run cannot resume and will start over.",
    },
    "LF-S03": {
        "zh": "内存不足，任务已中止（已译内容已保存，可续跑）。",
        "en": "Out of memory. The task was stopped (translated pages are saved and resumable).",
    },
    "LF-S04": {
        "zh": "设置文件损坏，已重置为默认值。",
        "en": "The settings file was corrupted and has been reset to defaults.",
    },
    # ---------------- U 域 · 用户操作 ----------------
    "LF-U01": {"zh": "先拖入要翻译的文件。", "en": "Add files to translate first."},
    "LF-U02": {
        "zh": "还没有选翻译模型。去「模型」页选一个。",
        "en": "No translation model selected. Pick one on the Models page.",
    },
    "LF-U03": {
        "zh": "「{name}」不是 PDF，无法生成保排 PDF，将改用 Markdown 输出。",
        "en": "“{name}” is not a PDF, so layout-preserving PDF output is unavailable; Markdown will be used.",
    },
    "LF-U04": {"zh": "已取消。", "en": "Cancelled."},
    "LF-U05": {
        "zh": "这份文档共 {pages} 页，预计需要约 {minutes} 分钟。翻译过程中可以随时暂停，已译内容会自动保存。",
        "en": "This document has {pages} pages; expect about {minutes} minutes. You can pause anytime — translated pages are saved automatically.",
    },
    "LF-S99": {"zh": "发生了一个未知错误。", "en": "An unknown error occurred."},
}


def problem_text(problem, lang: str | None = None) -> str:
    """把一个 :class:`Problem` 渲染成用户可见文案。

    优先用该码在目标语言下的文案；缺失时退回 ``detail``，再退回码本身。
    文案里的 ``{param}`` 用 ``problem.params`` 插值。

    :param problem: 待渲染的问题对象
    :param lang: 目标语言，缺省按当前界面语言
    """
    entry = PROBLEM_TEXT.get(problem.code)
    if not entry:
        return problem.detail or str(problem.code)

    which = "zh" if normalize_lang(lang) == ZH else "en"
    template = entry.get(which) or entry.get("zh") or entry.get("en")
    if not template:
        return problem.detail or str(problem.code)

    try:
        return template.format(**problem.params)
    except (KeyError, IndexError, ValueError):
        # 文案与 params 不匹配时保留占位符，便于发现，而不是静默输出半截话
        return template
