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
    "task.fmt_warn": "注意：当前内核仅实现 markdown / text 写出，其它格式会降级为纯文本。",
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
    # ---- 通用 ----
    "common.ok": "确定",
    "common.cancel": "取消",
    "common.close": "关闭",
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
    "task.fmt_warn": "Note: the kernel currently implements markdown / text writers only; "
                     "other formats fall back to plain text.",
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
    # ---- 通用 ----
    "common.ok": "OK",
    "common.cancel": "Cancel",
    "common.close": "Close",
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
