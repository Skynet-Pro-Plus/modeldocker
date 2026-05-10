from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget


VARIANT_COLORS = {
    "success": "#22c55e",
    "danger": "#ef4444",
    "accent": "#6366f1",
    "muted": "#8b93ab",
    "warning": "#f59e0b",
}


class StatusDot(QWidget):
    """Tiny colored circle used to indicate connection status."""

    def __init__(self, color: str = "#22c55e", diameter: int = 8, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._diameter = diameter
        self.setFixedSize(diameter + 2, diameter + 2)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(1, 1, self._diameter, self._diameter)


class Pill(QFrame):
    """Rounded pill with optional leading dot and a label."""

    def __init__(
        self,
        text: str = "",
        variant: str = "muted",
        with_dot: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("pill")
        self.setProperty("variant", variant)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(6)

        self._dot: Optional[StatusDot] = None
        if with_dot:
            self._dot = StatusDot(VARIANT_COLORS.get(variant, VARIANT_COLORS["muted"]))
            layout.addWidget(self._dot)

        self._label = QLabel(text)
        self._label.setObjectName("pillLabel")
        layout.addWidget(self._label)

    def set_text(self, text: str) -> None:
        self._label.setText(text)

    def set_variant(self, variant: str) -> None:
        self.setProperty("variant", variant)
        if self._dot is not None:
            self._dot.set_color(VARIANT_COLORS.get(variant, VARIANT_COLORS["muted"]))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
