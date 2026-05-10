from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from openrouter_client import ModelInfo
from ui.widgets.badge import CapabilityBadge
from ui.widgets.card import Card
from ui.widgets.pill import Pill, StatusDot


class _LabeledRow(QWidget):
    def __init__(self, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._label = QLabel(label)
        self._label.setObjectName("mutedLabel")
        self._value = QLabel("-")
        self._value.setObjectName("valueLabel")
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self._label)
        layout.addWidget(self._value, 1)

    def set_value(self, text: str) -> None:
        self._value.setText(text)

    def set_value_object_name(self, name: str) -> None:
        self._value.setObjectName(name)
        self._value.style().unpolish(self._value)
        self._value.style().polish(self._value)


class Sidebar(QScrollArea):
    """Card-based left sidebar shown next to the conversation."""

    connect_clicked = Signal()
    manage_role_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumWidth(310)
        self.setMaximumWidth(360)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._build_api_card())
        layout.addWidget(self._build_system_prompt_card())
        layout.addWidget(self._build_usage_card())
        layout.addWidget(self._build_capabilities_card())
        layout.addWidget(self._build_status_card())
        layout.addStretch()

        self.setWidget(container)

    # ---- Cards -----------------------------------------------------------

    def _build_api_card(self) -> Card:
        card = Card("API Connection", icon="\U0001F511")

        self.connect_btn = QPushButton("Connect API Key")
        self.connect_btn.setObjectName("primaryButton")
        self.connect_btn.clicked.connect(self.connect_clicked.emit)
        card.add_widget(self.connect_btn)

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.api_status_dot = StatusDot("#ef4444", diameter=8)
        self.api_status_label = QLabel("Not connected")
        self.api_status_label.setObjectName("mutedLabel")
        self.api_status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.api_compat_pill = Pill("OpenAI Compatible", variant="accent")
        status_row.addWidget(self.api_status_dot)
        status_row.addWidget(self.api_status_label, 1)
        status_row.addWidget(self.api_compat_pill)
        wrapper = QWidget()
        wrapper.setLayout(status_row)
        card.add_widget(wrapper)
        return card

    def _build_system_prompt_card(self) -> Card:
        card = Card("System Prompt", icon="\U0001F4DD")
        self.role_button = QPushButton("Role: AI Assistant    \u203A")
        self.role_button.setObjectName("ghostButton")
        self.role_button.setMinimumHeight(36)
        self.role_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.role_button.setCursor(Qt.PointingHandCursor)
        self.role_button.setToolTip("Manage roles (system prompts)")
        self.role_button.clicked.connect(self.manage_role_clicked.emit)
        card.add_widget(self.role_button)
        return card

    def _build_usage_card(self) -> Card:
        card = Card("Usage & Cost", icon="\U0001F4CA")
        self.balance_row = _LabeledRow("Balance")
        self.balance_row.set_value_object_name("balanceValue")
        self.session_total_row = _LabeledRow("Session Total")
        self.last_interaction_row = _LabeledRow("Last Interaction")
        self.usage_prompt_row = _LabeledRow("Usage (prompt)")
        self.completion_tokens_row = _LabeledRow("Completion Tokens")

        for row in (
            self.balance_row,
            self.session_total_row,
            self.last_interaction_row,
            self.usage_prompt_row,
            self.completion_tokens_row,
        ):
            card.add_widget(row)
        return card

    def _build_capabilities_card(self) -> Card:
        card = Card("Model Capabilities", icon="\U0001F9E9")
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        self.badge_image_in = CapabilityBadge("\U0001F5BC", "Analyze Images")
        self.badge_image_out = CapabilityBadge("\u2728", "Generate Images")
        self.badge_tools = CapabilityBadge("\U0001F527", "Tool Use")
        self.badge_function = CapabilityBadge("\U0001F9EE", "Function Calling")
        self.badge_web = CapabilityBadge("\U0001F310", "Web Search")
        self.badge_code = CapabilityBadge("\U0001F4BB", "Code Interpreter")

        grid.addWidget(self.badge_image_in, 0, 0)
        grid.addWidget(self.badge_image_out, 1, 0)
        grid.addWidget(self.badge_tools, 2, 0)
        grid.addWidget(self.badge_function, 3, 0)
        grid.addWidget(self.badge_web, 4, 0)
        grid.addWidget(self.badge_code, 5, 0)
        card.add_widget(grid_widget)
        return card

    def _build_status_card(self) -> Card:
        card = Card("Status", icon="\u26A1")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.status_dot = StatusDot("#8b93ab", diameter=10)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.status_title = QLabel("Initializing...")
        self.status_title.setObjectName("valueLabel")
        self.status_title.setWordWrap(True)
        self.status_subtitle = QLabel("Please wait")
        self.status_subtitle.setObjectName("mutedLabel")
        self.status_subtitle.setWordWrap(True)
        text_col.addWidget(self.status_title)
        text_col.addWidget(self.status_subtitle)
        row.addWidget(self.status_dot)
        row.addLayout(text_col, 1)
        wrapper = QWidget()
        wrapper.setLayout(row)
        card.add_widget(wrapper)
        return card

    # ---- Public update API ----------------------------------------------

    def set_connection(self, connected: bool, message: Optional[str] = None) -> None:
        self.api_status_dot.set_color("#22c55e" if connected else "#ef4444")
        self.api_status_label.setText(message or ("Connected" if connected else "Not connected"))

    def set_active_role_title(self, title: str) -> None:
        cleaned = title.strip() or "AI Assistant"
        if len(cleaned) > 32:
            cleaned = cleaned[:32] + "..."
        self.role_button.setText(f"Role: {cleaned}    \u203A")

    def set_balance(self, remaining_text: str) -> None:
        self.balance_row.set_value(remaining_text)

    def set_session_total(self, value: float) -> None:
        self.session_total_row.set_value(f"${value:.6f}")

    def set_last_interaction(self, value: float) -> None:
        self.last_interaction_row.set_value(f"${value:.6f}")

    def set_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.usage_prompt_row.set_value(f"{prompt_tokens:,}")
        self.completion_tokens_row.set_value(f"{completion_tokens:,}")

    def set_status(self, title: str, subtitle: str = "", level: str = "info") -> None:
        color = {
            "ok": "#22c55e",
            "warn": "#f59e0b",
            "error": "#ef4444",
            "info": "#6366f1",
            "muted": "#8b93ab",
        }.get(level, "#8b93ab")
        self.status_dot.set_color(color)
        self.status_title.setText(title)
        self.status_subtitle.setText(subtitle)

    def update_capabilities(self, model: Optional[ModelInfo]) -> None:
        if model is None:
            for badge in (
                self.badge_image_in,
                self.badge_image_out,
                self.badge_tools,
                self.badge_function,
                self.badge_web,
                self.badge_code,
            ):
                badge.set_supported(False)
            return
        self.badge_image_in.set_supported(model.supports_image_input)
        self.badge_image_out.set_supported(model.supports_image_output)
        self.badge_tools.set_supported(model.supports_tools)
        self.badge_function.set_supported(model.supports_function_calling)
        self.badge_web.set_supported(model.supports_web_search)
        self.badge_code.set_supported(model.supports_code_interpreter)
