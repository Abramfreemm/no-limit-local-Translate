"""
LinguaForge (译匠) — 本地离线文档翻译器。

设计红线：
  1. 流水线层不依赖 Qt，可无头运行与单测。
  2. 不设页数 / 体积上限：逐页流式处理，绝不整篇入内存。
  3. 不捆绑模型权重，翻译能力全部委托本机 Ollama。
"""

__version__ = "0.1.0"
__app_name__ = "LinguaForge"

__all__ = ["__version__", "__app_name__"]
