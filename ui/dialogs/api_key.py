from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

OPENROUTER_SIGNUP_URL = "https://openrouter.ai/"


class ApiKeyDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OpenRouter API Key")
        self.setModal(True)
        self.resize(520, 210)

        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setPlaceholderText("sk-or-v1-...")

        info = QLabel(
            "Enter your OpenRouter API key. It will be saved to Windows "
            "Credential Manager and reused on next launch."
        )
        info.setWordWrap(True)
        info.setObjectName("mutedLabel")

        link_hint = QLabel(
            f'Need a key? Get one at <a href="{OPENROUTER_SIGNUP_URL}">{OPENROUTER_SIGNUP_URL}</a>'
        )
        link_hint.setWordWrap(True)
        link_hint.setTextFormat(Qt.TextFormat.RichText)
        link_hint.setOpenExternalLinks(True)
        link_hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link_hint.setObjectName("mutedLabel")

        ok_btn = QPushButton("Save")
        ok_btn.setObjectName("primaryButton")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel_btn)
        buttons.addWidget(ok_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(info)
        layout.addWidget(link_hint)
        layout.addWidget(self.key_input)
        layout.addLayout(buttons)

    def get_key(self) -> str:
        return self.key_input.text().strip()
