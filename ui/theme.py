from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict

from PySide6.QtCore import QObject, Signal


class Theme(str, Enum):
    DARK = "dark"
    LIGHT = "light"


@dataclass(frozen=True)
class Palette:
    bg: str
    panel: str
    panel_2: str
    panel_3: str
    border: str
    border_strong: str
    text: str
    text_strong: str
    muted: str
    accent: str
    accent_hover: str
    accent_pressed: str
    success: str
    warning: str
    danger: str
    user_avatar: str
    assistant_avatar: str
    system_avatar: str


DARK_PALETTE = Palette(
    bg="#0b0f1a",
    panel="#121726",
    panel_2="#161c2e",
    panel_3="#1c2438",
    border="#252c44",
    border_strong="#33405e",
    text="#e6e8ef",
    text_strong="#ffffff",
    muted="#8b93ab",
    accent="#6366f1",
    accent_hover="#7376ff",
    accent_pressed="#5052d6",
    success="#22c55e",
    warning="#f59e0b",
    danger="#ef4444",
    user_avatar="#3b82f6",
    assistant_avatar="#22c55e",
    system_avatar="#f59e0b",
)


LIGHT_PALETTE = Palette(
    bg="#f5f7fb",
    panel="#ffffff",
    panel_2="#f0f3fa",
    panel_3="#e6ebf6",
    border="#d8dde9",
    border_strong="#b9c2d6",
    text="#1f2330",
    text_strong="#0b0f1a",
    muted="#5e667d",
    accent="#6366f1",
    accent_hover="#5052d6",
    accent_pressed="#4042b8",
    success="#16a34a",
    warning="#d97706",
    danger="#dc2626",
    user_avatar="#3b82f6",
    assistant_avatar="#16a34a",
    system_avatar="#d97706",
)


def palette_for(theme: Theme) -> Palette:
    return DARK_PALETTE if theme == Theme.DARK else LIGHT_PALETTE


class ThemeManager(QObject):
    """Application-wide theme controller. Holds the active theme and
    notifies listeners on change so dynamic colors (avatars, role headers)
    can repaint."""

    changed = Signal(object)

    def __init__(self, theme: Theme = Theme.DARK) -> None:
        super().__init__()
        self._theme = theme

    @property
    def theme(self) -> Theme:
        return self._theme

    @property
    def palette(self) -> Palette:
        return palette_for(self._theme)

    def set_theme(self, theme: Theme) -> None:
        if theme == self._theme:
            return
        self._theme = theme
        self.changed.emit(theme)

    def toggle(self) -> Theme:
        self.set_theme(Theme.LIGHT if self._theme == Theme.DARK else Theme.DARK)
        return self._theme


def build_stylesheet(theme: Theme) -> str:
    p = palette_for(theme)
    return f"""
    QWidget {{
        color: {p.text};
        font-family: "Segoe UI", "Inter", Arial, sans-serif;
        font-size: 10pt;
        background: transparent;
    }}

    QFrame#rootShell {{
        background: {p.bg};
        border: 1px solid {p.border};
        border-radius: 12px;
    }}
    QFrame#rootShell[maximized="true"] {{
        border-radius: 0px;
    }}

    QFrame#titleBar {{
        background: {p.panel};
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
        border-bottom: 1px solid {p.border};
    }}
    QFrame#rootShell[maximized="true"] QFrame#titleBar {{
        border-top-left-radius: 0px;
        border-top-right-radius: 0px;
    }}

    QFrame#card {{
        background: {p.panel};
        border: 1px solid {p.border};
        border-radius: 12px;
    }}
    QFrame#cardHeader {{
        background: transparent;
        border: none;
    }}
    QLabel#cardTitle {{
        color: {p.text_strong};
        font-size: 10pt;
        font-weight: 600;
    }}
    QLabel#cardSubtitle {{
        color: {p.muted};
        font-size: 8pt;
    }}

    QLabel#sectionTitle {{
        color: {p.text_strong};
        font-size: 11pt;
        font-weight: 600;
    }}

    QLabel#mutedLabel {{
        color: {p.muted};
    }}

    QLabel#valueLabel {{
        color: {p.text_strong};
        font-weight: 600;
    }}

    QLabel#balanceValue {{
        color: {p.success};
        font-weight: 600;
    }}

    QLabel#brandTitle {{
        color: {p.text_strong};
        font-size: 11pt;
        font-weight: 700;
        letter-spacing: 0.3px;
    }}
    QLabel#brandSubtitle {{
        color: {p.muted};
        font-size: 8pt;
    }}

    QFrame#pill {{
        background: {p.panel_3};
        border: 1px solid {p.border};
        border-radius: 10px;
    }}
    QFrame#pill[variant="success"] {{
        background: rgba(34, 197, 94, 0.12);
        border-color: rgba(34, 197, 94, 0.45);
    }}
    QFrame#pill[variant="danger"] {{
        background: rgba(239, 68, 68, 0.12);
        border-color: rgba(239, 68, 68, 0.45);
    }}
    QFrame#pill[variant="accent"] {{
        background: rgba(99, 102, 241, 0.14);
        border-color: rgba(99, 102, 241, 0.5);
    }}
    QFrame#pill[variant="muted"] {{
        background: {p.panel_3};
        border-color: {p.border};
    }}
    QLabel#pillLabel {{
        color: {p.text};
        font-size: 8pt;
        font-weight: 500;
    }}

    QPushButton#speakAloudButton {{
        background: {p.panel_3};
        border: 1px solid {p.border};
        border-radius: 10px;
        color: {p.muted};
        font-size: 8pt;
        font-weight: 500;
        padding: 4px 10px;
    }}
    QPushButton#speakAloudButton:hover {{
        background: {p.panel_2};
        color: {p.text};
        border-color: {p.border_strong};
    }}
    QPushButton#speakAloudButton:pressed {{
        background: {p.panel};
        color: {p.text_strong};
    }}
    QPushButton#speakAloudButton:disabled {{
        color: {p.muted};
        background: {p.panel_3};
        border-color: {p.border};
    }}
    QPushButton#speakAloudButton[speaking="true"] {{
        background: {p.accent};
        color: {p.text_strong};
        border-color: {p.accent_pressed};
    }}
    QPushButton#speakAloudButton[speaking="true"]:hover {{
        background: {p.accent_hover};
    }}

    QFrame#badge {{
        background: {p.panel_2};
        border: 1px solid {p.border};
        border-radius: 8px;
    }}
    QFrame#badge[supported="true"] {{
        background: {p.panel_3};
        border-color: {p.border_strong};
    }}
    QFrame#badge[supported="false"] {{
        background: {p.panel_2};
        border-color: {p.border};
    }}
    QLabel#badgeLabel {{
        color: {p.text};
        font-size: 8pt;
    }}
    QLabel#badgeLabel[supported="false"] {{
        color: {p.muted};
    }}

    QPushButton {{
        background: {p.panel_2};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 8px 14px;
    }}
    QPushButton:hover {{
        background: {p.panel_3};
        border-color: {p.border_strong};
    }}
    QPushButton:disabled {{
        color: {p.muted};
        background: {p.panel};
    }}

    QPushButton#primaryButton {{
        background: {p.accent};
        color: #ffffff;
        border: 1px solid {p.accent};
    }}
    QPushButton#primaryButton:hover {{
        background: {p.accent_hover};
        border-color: {p.accent_hover};
    }}
    QPushButton#primaryButton:pressed {{
        background: {p.accent_pressed};
    }}
    QPushButton#primaryButton:disabled {{
        background: {p.panel_2};
        color: {p.muted};
        border-color: {p.border};
    }}

    QPushButton#linkButton {{
        background: transparent;
        border: none;
        color: {p.danger};
        padding: 4px 6px;
    }}
    QPushButton#linkButton:hover {{
        color: {p.accent};
    }}

    QPushButton#ghostButton {{
        background: transparent;
        color: {p.muted};
        border: 1px solid transparent;
        padding: 6px 10px;
    }}
    QPushButton#ghostButton:hover {{
        background: {p.panel_2};
        color: {p.text};
        border-color: {p.border};
    }}

    QPushButton#iconButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 6px;
    }}
    QPushButton#iconButton:hover {{
        background: {p.panel_2};
        border-color: {p.border};
    }}
    QPushButton#iconButton:checked {{
        background: {p.panel_3};
        border-color: {p.border_strong};
    }}

    QPushButton#winControl {{
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 6px 10px;
        color: {p.muted};
        font-size: 10pt;
    }}
    QPushButton#winControl:hover {{
        background: {p.panel_3};
        color: {p.text};
    }}
    QPushButton#winClose {{
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 6px 10px;
        color: {p.muted};
    }}
    QPushButton#winClose:hover {{
        background: {p.danger};
        color: #ffffff;
    }}

    QLineEdit, QTextEdit, QPlainTextEdit {{
        background: {p.panel_2};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 6px 8px;
        selection-background-color: {p.accent};
        selection-color: #ffffff;
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border-color: {p.accent};
    }}

    QPlainTextEdit#streamBody {{
        background: transparent;
        border: none;
        padding: 0px;
        color: {p.text};
        selection-background-color: {p.accent};
        selection-color: #ffffff;
    }}
    QPlainTextEdit#streamBody:focus {{
        border: none;
    }}

    QComboBox {{
        background: {p.panel_2};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 6px 10px;
        min-height: 22px;
    }}
    QComboBox:hover {{
        border-color: {p.border_strong};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background: {p.panel};
        color: {p.text};
        border: 1px solid {p.border};
        selection-background-color: {p.accent};
        selection-color: #ffffff;
        outline: none;
        padding: 4px;
    }}

    QCheckBox {{
        color: {p.text};
        spacing: 6px;
    }}
    QCheckBox::indicator {{
        width: 14px;
        height: 14px;
        border-radius: 3px;
        border: 1px solid {p.border_strong};
        background: {p.panel_2};
    }}
    QCheckBox::indicator:checked {{
        background: {p.accent};
        border-color: {p.accent};
    }}

    QSlider::groove:horizontal {{
        height: 4px;
        background: {p.panel_3};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        width: 14px;
        height: 14px;
        margin: -6px 0;
        background: {p.accent};
        border-radius: 7px;
        border: 1px solid {p.accent};
    }}
    QSlider::sub-page:horizontal {{
        background: {p.accent};
        border-radius: 2px;
    }}

    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 4px 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {p.border_strong};
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {p.muted};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {p.border_strong};
        border-radius: 4px;
        min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {p.muted};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}

    QFrame#chatBubble {{
        background: {p.panel_2};
        border: 1px solid {p.border};
        border-radius: 12px;
    }}
    QFrame#chatBubble[role="user"] {{
        background: {p.panel_3};
    }}
    QFrame#chatBubble[role="system"] {{
        background: {p.panel_2};
        border-color: {p.warning};
    }}

    QFrame#composer {{
        background: {p.panel};
        border: 1px solid {p.border};
        border-radius: 12px;
    }}

    QFrame#conversationFrame {{
        background: {p.panel};
        border: 1px solid {p.border};
        border-radius: 12px;
    }}

    QMenu {{
        background: {p.panel};
        border: 1px solid {p.border};
        color: {p.text};
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 14px;
        border-radius: 4px;
    }}
    QMenu::item:selected {{
        background: {p.accent};
        color: #ffffff;
    }}

    QToolTip {{
        background: {p.panel_3};
        color: {p.text};
        border: 1px solid {p.border};
        padding: 4px 6px;
    }}
    """


_palette_token_map: Dict[str, str] = {
    "bg": "bg",
    "panel": "panel",
    "panel_2": "panel_2",
    "panel_3": "panel_3",
    "border": "border",
    "border_strong": "border_strong",
    "text": "text",
    "text_strong": "text_strong",
    "muted": "muted",
    "accent": "accent",
    "success": "success",
    "warning": "warning",
    "danger": "danger",
}


def palette_token(theme: Theme, name: str) -> str:
    p = palette_for(theme)
    attr = _palette_token_map.get(name, name)
    return getattr(p, attr)
