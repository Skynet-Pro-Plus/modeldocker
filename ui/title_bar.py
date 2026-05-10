from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.icon_button import IconButton
from ui.widgets.pill import Pill


class LogoWidget(QWidget):
    """QPainter-drawn brand mark: a rounded square with a gradient fill
    and an `O` glyph. Cheaper than shipping a PNG asset."""

    def __init__(self, size: int = 32, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(size, size))
        self._size = size

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        gradient = QLinearGradient(0, 0, self._size, self._size)
        gradient.setColorAt(0.0, QColor("#7c3aed"))
        gradient.setColorAt(1.0, QColor("#3b82f6"))
        painter.setBrush(gradient)
        painter.setPen(Qt.NoPen)
        radius = self._size / 4
        painter.drawRoundedRect(0, 0, self._size, self._size, radius, radius)

        pen = QPen(QColor("#ffffff"))
        pen.setWidthF(self._size * 0.12)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        inset = self._size * 0.28
        painter.drawEllipse(inset, inset, self._size - 2 * inset, self._size - 2 * inset)


class TitleBar(QFrame):
    """Custom frameless-window title bar.

    Emits high-level signals so the main window can react to the
    composite controls (theme toggle, new session, history, session
    selection, window controls).
    """

    new_session_requested = Signal()
    history_requested = Signal()
    theme_toggle_requested = Signal()
    session_selected = Signal(str)
    minimize_requested = Signal()
    maximize_toggle_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(56)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._drag_active = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 10, 8)
        layout.setSpacing(12)

        layout.addLayout(self._build_brand(), 0)
        layout.addStretch(1)
        layout.addLayout(self._build_session_picker(), 0)
        layout.addStretch(1)
        layout.addLayout(self._build_trailing_actions(), 0)
        layout.addLayout(self._build_window_controls(), 0)

    def _build_brand(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(LogoWidget(size=34))

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)
        title = QLabel("ModelDocker")
        title.setObjectName("brandTitle")
        subtitle_row = QHBoxLayout()
        subtitle_row.setContentsMargins(0, 0, 0, 0)
        subtitle_row.setSpacing(6)
        subtitle = QLabel("LLM Workstation")
        subtitle.setObjectName("brandSubtitle")
        version_pill = Pill(text="v2.0.0", variant="muted")
        subtitle_row.addWidget(subtitle)
        subtitle_row.addWidget(version_pill)
        subtitle_row.addStretch()
        text_col.addWidget(title)
        text_col.addLayout(subtitle_row)
        row.addLayout(text_col)
        return row

    def _build_session_picker(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.session_combo = QComboBox()
        self.session_combo.setMinimumWidth(220)
        self.session_combo.setMaximumWidth(320)
        self.session_combo.currentIndexChanged.connect(self._on_session_index_changed)
        self.session_combo.setToolTip("Switch sessions")

        self.new_session_btn = IconButton("+", tooltip="New session", size=32)
        self.new_session_btn.clicked.connect(self.new_session_requested.emit)

        row.addWidget(self.session_combo)
        row.addWidget(self.new_session_btn)
        return row

    def _build_trailing_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.theme_btn = IconButton("\u2600", tooltip="Toggle theme", size=32)
        self.theme_btn.clicked.connect(self.theme_toggle_requested.emit)

        self.history_btn = IconButton("\u23F1", tooltip="Session history", size=32)
        self.history_btn.setText("History")
        self.history_btn.setObjectName("ghostButton")
        self.history_btn.setFixedSize(QSize(82, 32))
        self.history_btn.clicked.connect(self.history_requested.emit)

        self.connected_pill = Pill(text="Disconnected", variant="danger", with_dot=True)

        row.addWidget(self.theme_btn)
        row.addWidget(self.history_btn)
        row.addWidget(self.connected_pill)
        return row

    def _build_window_controls(self) -> QHBoxLayout:
        """Minimize / maximize / close — flush right, standard title-bar icons."""
        row = QHBoxLayout()
        row.setContentsMargins(8, 0, 4, 0)
        row.setSpacing(0)

        style = self.style()
        icon_sz = QSize(16, 16)

        self.minimize_btn = QPushButton(self)
        self.minimize_btn.setObjectName("winControl")
        self.minimize_btn.setFlat(True)
        self.minimize_btn.setFocusPolicy(Qt.NoFocus)
        self.minimize_btn.setCursor(Qt.PointingHandCursor)
        self.minimize_btn.setToolTip("Minimize")
        self.minimize_btn.setIcon(style.standardIcon(QStyle.SP_TitleBarMinButton))
        self.minimize_btn.setIconSize(icon_sz)
        self.minimize_btn.setFixedSize(40, 32)
        self.minimize_btn.clicked.connect(self.minimize_requested.emit)

        self.maximize_btn = QPushButton(self)
        self.maximize_btn.setObjectName("winControl")
        self.maximize_btn.setFlat(True)
        self.maximize_btn.setFocusPolicy(Qt.NoFocus)
        self.maximize_btn.setCursor(Qt.PointingHandCursor)
        self.maximize_btn.setToolTip("Maximize")
        self.maximize_btn.setIcon(style.standardIcon(QStyle.SP_TitleBarMaxButton))
        self.maximize_btn.setIconSize(icon_sz)
        self.maximize_btn.setFixedSize(40, 32)
        self.maximize_btn.clicked.connect(self.maximize_toggle_requested.emit)

        self.close_btn = QPushButton(self)
        self.close_btn.setObjectName("winClose")
        self.close_btn.setFlat(True)
        self.close_btn.setFocusPolicy(Qt.NoFocus)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip("Close")
        self.close_btn.setIcon(style.standardIcon(QStyle.SP_TitleBarCloseButton))
        self.close_btn.setIconSize(icon_sz)
        self.close_btn.setFixedSize(40, 32)
        self.close_btn.clicked.connect(self.close_requested.emit)

        row.addWidget(self.minimize_btn)
        row.addWidget(self.maximize_btn)
        row.addWidget(self.close_btn)
        return row

    def set_connected(self, connected: bool, label: Optional[str] = None) -> None:
        text = label or ("Connected" if connected else "Disconnected")
        self.connected_pill.set_text(text)
        self.connected_pill.set_variant("success" if connected else "danger")

    def set_theme_glyph(self, theme_is_dark: bool) -> None:
        self.theme_btn.set_glyph("\u263D" if theme_is_dark else "\u2600")
        self.theme_btn.setToolTip("Switch to light theme" if theme_is_dark else "Switch to dark theme")

    def set_maximized_glyph(self, maximized: bool) -> None:
        style = self.style()
        if maximized:
            self.maximize_btn.setIcon(style.standardIcon(QStyle.SP_TitleBarNormalButton))
            self.maximize_btn.setToolTip("Restore down")
        else:
            self.maximize_btn.setIcon(style.standardIcon(QStyle.SP_TitleBarMaxButton))
            self.maximize_btn.setToolTip("Maximize")

    def set_sessions(self, sessions, current_id: Optional[str]) -> None:
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        for session_summary in sessions:
            label = session_summary.get("title") or "Untitled session"
            self.session_combo.addItem(label, userData=session_summary.get("id"))
        if current_id:
            index = self.session_combo.findData(current_id)
            if index >= 0:
                self.session_combo.setCurrentIndex(index)
        self.session_combo.blockSignals(False)

    def _on_session_index_changed(self, _index: int) -> None:
        session_id = self.session_combo.currentData()
        if session_id:
            self.session_selected.emit(str(session_id))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            window = self.window().windowHandle()
            if window is not None:
                self._drag_active = True
                window.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.maximize_toggle_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
