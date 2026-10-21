"""配置层。所有可调参数集中于此，可 JSON 持久化到用户数据目录。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from platformdirs import user_data_dir

APP_AUTHOR = "LinguaForge"
APP_NAME = "LinguaForge"


def default_data_dir() -> Path:
    p = Path(user_data_dir(APP_NAME, APP_AUTHOR))
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class OllamaConfig:
    """Ollama 翻译后端。"""

    host: str = "http://127.0.0.1:11434"
    model: str = "translategemma:12b"
    fallback_models: list = field(default_factory=lambda: ["translategemma:4b", "qwen3:8b"])
    temperature: float = 0.15
    num_ctx: int = 4096
    num_predict: int = 2048
    keep_alive: str = "10m"
    timeout_s: float = 300.0
    # 分批：按字符数与条数双上限，先到先切
    batch_max_chars: int = 1200
    batch_max_items: int = 12
    max_retry: int = 2
    # 并发请求数（Ollama 默认单卡串行，>1 需足够显存）
    concurrency: int = 1


@dataclass
class OCRConfig:
    """OCR 配置。"""

    enabled: bool = True
    engine: str = "rapidocr"          # rapidocr | paddleocr | vlm
    # 文本层字符数低于此阈值判定为扫描页，触发 OCR
    min_text_chars: int = 60
    dpi: int = 200
    max_dpi: int = 300
    lang: str = "ch"
    min_confidence: float = 0.45      # 低于此置信度的 OCR 结果丢弃
    vlm_model: str = ""               # 可选：Ollama 视觉模型名


@dataclass
class GlossaryConfig:
    """术语表。"""

    enabled: bool = True
    # 每批最多注入多少条术语（避免撑爆 prompt）
    max_entries_per_batch: int = 40
    case_sensitive: bool = False


@dataclass
class TMConfig:
    """翻译记忆。"""

    enabled: bool = True
    min_match_ratio: float = 0.92     # 模糊匹配阈值


@dataclass
class OutputConfig:
    """输出配置。"""

    fmt: str = "markdown"             # markdown | txt | bilingual
    bilingual: bool = False           # 双语对照
    keep_numbering: bool = True
    ocr_text_to_markdown: bool = True


@dataclass
class PerfConfig:
    """性能与资源护栏（不设页数/体积上限，只设内存护栏）。"""

    # 内存占用超过此阈值（MB）时提示降档，不中止任务
    memory_warn_mb: int = 1500
    # 每处理多少页提交一次数据库
    commit_every_pages: int = 5
    # 渲染缓存最多保留多少页位图
    image_cache_pages: int = 3
    # 流式窗口：累计这么多页就翻译并写盘一次（内存与总页数无关）
    window_pages: int = 20
    window_chars: int = 12000


@dataclass
class Config:
    """顶层配置。"""

    lang_src: str = "auto"
    lang_dst: str = "zh-Hans"
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    glossary: GlossaryConfig = field(default_factory=GlossaryConfig)
    tm: TMConfig = field(default_factory=TMConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    perf: PerfConfig = field(default_factory=PerfConfig)
    ui_lang: str = "zh-CN"

    # ---- 持久化 ----
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Config":
        c = cls()
        for key in ("lang_src", "lang_dst", "ui_lang"):
            if key in d:
                setattr(c, key, d[key])
        if "ollama" in d:
            c.ollama = _merge(c.ollama, OllamaConfig, d["ollama"])
        if "ocr" in d:
            c.ocr = _merge(c.ocr, OCRConfig, d["ocr"])
        if "glossary" in d:
            c.glossary = _merge(c.glossary, GlossaryConfig, d["glossary"])
        if "tm" in d:
            c.tm = _merge(c.tm, TMConfig, d["tm"])
        if "output" in d:
            c.output = _merge(c.output, OutputConfig, d["output"])
        if "perf" in d:
            c.perf = _merge(c.perf, PerfConfig, d["perf"])
        return c

    def save(self, path: Optional[Path] = None) -> Path:
        p = Path(path) if path else default_data_dir() / "config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        p = Path(path) if path else default_data_dir() / "config.json"
        if not p.exists():
            return cls()
        try:
            return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return cls()


def _merge(obj: Any, cls_: type, d: Dict[str, Any]) -> Any:
    """用字典更新 dataclass，忽略未知键。"""
    known = {k: v for k, v in d.items() if k in cls_.__dataclass_fields__}
    return cls_(**{**asdict(obj), **known})


# ---- 语言名称表（供 prompt 使用）----
LANG_NAMES: Dict[str, str] = {
    "auto": "the source language (auto-detect)",
    "zh-Hans": "Simplified Chinese",
    "zh-Hant": "Traditional Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "ru": "Russian",
    "pt": "Portuguese",
    "it": "Italian",
    "ar": "Arabic",
    "hi": "Hindi",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "tr": "Turkish",
    "pl": "Polish",
    "nl": "Dutch",
    "sv": "Swedish",
    "uk": "Ukrainian",
}


def lang_name(code: str) -> str:
    return LANG_NAMES.get(code, code)
