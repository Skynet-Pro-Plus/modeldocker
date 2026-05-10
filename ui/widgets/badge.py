from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget


class CapabilityBadge(QFrame):
    """Small pill used in the Model Capabilities grid.

    Renders an icon glyph, a label, and a check/X marker indicating
    whether the currently selected model supports the capability.
    """

    def __init__(
        self,
        icon: str,
        label: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("badge")
        self.setProperty("supported", "false")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self._icon = QLabel(icon)
        self._icon.setObjectName("badgeLabel")
        self._icon.setProperty("supported", "false")
        self._icon.setFixedWidth(16)
        self._icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon)

        self._label = QLabel(label)
        self._label.setObjectName("badgeLabel")
        self._label.setProperty("supported", "false")
        self._label.setMinimumWidth(0)
        self._label.setWordWrap(True)
        layout.addWidget(self._label, 1)

        self._marker = QLabel("\u2715")
        self._marker.setObjectName("badgeLabel")
        self._marker.setProperty("supported", "false")
        self._marker.setFixedWidth(14)
        self._marker.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self._marker)

    def set_supported(self, supported: bool) -> None:
        value = "true" if supported else "false"
        self.setProperty("supported", value)
        for widget in (self._icon, self._label, self._marker):
            widget.setProperty("supported", value)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self._marker.setText("\u2713" if supported else "\u2715")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
