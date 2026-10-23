"""PySide6 桌面 UI 层（M5）。

对外只暴露 ``main(argv=None) -> int``：

    python -m linguaforge.ui
    python -c "from linguaforge.ui import main; raise SystemExit(main())"

约束：流水线层不依赖 Qt；本层不做任何翻译业务，只负责编排与呈现。
"""

from __future__ import annotations

from .app import main

__all__ = ["main"]
