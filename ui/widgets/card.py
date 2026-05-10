from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.icon_button import IconButton


class Card(QFrame):
    """Rounded panel with an optional header (title + leading icon + trailing
    action button) and a body layout that callers can populate."""

    def __init__(
        self,
        title: str = "",
        icon: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(10)

        self._header = QFrame()
        self._header.setObjectName("cardHeader")
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        if icon:
            icon_label = QLabel(icon)
            icon_label.setObjectName("cardTitle")
            icon_label.setFixedWidth(18)
            icon_label.setAlignment(Qt.AlignCenter)
            header_layout.addWidget(icon_label)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("cardTitle")
        header_layout.addWidget(self._title_label)
        header_layout.addStretch()

        self._trailing_widget: Optional[QWidget] = None
        self._header_layout = header_layout

        outer.addWidget(self._header)

        self._body = QFrame()
        self._body.setObjectName("cardBody")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(8)
        outer.addWidget(self._body)

        if not title and not icon:
            self._header.setVisible(False)

    def body_layout(self) -> QVBoxLayout:
        return self._body_layout

    def add_widget(self, widget: QWidget) -> None:
        self._body_layout.addWidget(widget)

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def set_trailing(self, widget: QWidget) -> None:
        if self._trailing_widget is not None:
            self._header_layout.removeWidget(self._trailing_widget)
            self._trailing_widget.deleteLater()
        self._trailing_widget = widget
        self._header_layout.addWidget(widget)

    def set_trailing_button(self, label: str, on_click=None) -> IconButton:
        button = IconButton(label, size=24, object_name="ghostButton")
        button.setText(label)
        button.setFixedSize(0, 0)
        button.adjustSize()
        button.setMinimumHeight(22)
        button.setMaximumHeight(24)
        button.setMinimumWidth(48)
        button.setMaximumWidth(120)
        button.setObjectName("ghostButton")
        if on_click is not None:
            button.clicked.connect(on_click)
        self.set_trailing(button)
        return button
