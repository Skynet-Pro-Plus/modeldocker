from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QPushButton


class IconButton(QPushButton):
    """A flat icon-style button that uses a single glyph (text or emoji)
    and a fixed square footprint. Used in the title bar, sidebar headers,
    composer, and message action rows.
    """

    def __init__(
        self,
        glyph: str = "",
        tooltip: str = "",
        size: int = 32,
        parent=None,
        object_name: str = "iconButton",
    ) -> None:
        super().__init__(glyph, parent)
        self.setObjectName(object_name)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(QSize(size, size))
        self.setFocusPolicy(Qt.NoFocus)
        if tooltip:
            self.setToolTip(tooltip)

    def set_glyph(self, glyph: str) -> None:
        self.setText(glyph)
