"""翻译层：Ollama 客户端 + 翻译器 + 术语表 + 翻译记忆。"""

from .ollama_client import OllamaClient, OllamaError, OllamaUnavailable
from .translator import (
    Glossary,
    TranslateStats,
    TranslationMemory,
    Translator,
    build_payload,
    parse_translations,
)

__all__ = [
    "OllamaClient",
    "OllamaError",
    "OllamaUnavailable",
    "Glossary",
    "TranslationMemory",
    "TranslateStats",
    "Translator",
    "build_payload",
    "parse_translations",
]
