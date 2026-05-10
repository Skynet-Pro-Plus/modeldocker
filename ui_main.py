"""Backwards-compatible shim.

The main window lives in the `ui/` package. This module re-exports the entry
point so existing imports (`from ui_main import ModelDockerMainWindow`) work.
"""

from ui.main_window import ModelDockerMainWindow

__all__ = ["ModelDockerMainWindow"]
