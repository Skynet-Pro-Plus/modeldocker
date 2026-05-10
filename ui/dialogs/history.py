from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from session_store import SessionStore


class HistoryDialog(QDialog):
    """Manage past sessions: open, rename, delete."""

    session_opened = Signal(str)

    def __init__(self, store: SessionStore, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Session History")
        self.setModal(True)
        self.resize(600, 460)
        self.store = store

        info = QLabel("Pick a previous session to reload, or manage existing ones.")
        info.setObjectName("mutedLabel")

        self.list_widget = QListWidget()
        self.list_widget.setUniformItemSizes(False)
        self.list_widget.setAlternatingRowColors(False)
        self.list_widget.itemDoubleClicked.connect(self._on_open)

        open_btn = QPushButton("Open")
        open_btn.setObjectName("primaryButton")
        open_btn.clicked.connect(self._on_open)

        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(self._on_rename)

        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._on_delete)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(rename_btn)
        buttons.addWidget(delete_btn)
        buttons.addStretch()
        buttons.addWidget(close_btn)
        buttons.addWidget(open_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(info)
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(buttons)

        self._reload()

    def _reload(self) -> None:
        self.list_widget.clear()
        sessions = self.store.list()
        if not sessions:
            placeholder = QListWidgetItem("No saved sessions yet.")
            placeholder.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(placeholder)
            return
        for summary in sessions:
            updated = float(summary.get("updated_at") or 0)
            ts = datetime.fromtimestamp(updated).strftime("%Y-%m-%d %H:%M") if updated else "-"
            title = summary.get("title") or "Untitled session"
            model = summary.get("model_id") or "no model"
            item = QListWidgetItem(f"{title}\n{ts}  -  {model}")
            item.setData(Qt.UserRole, summary.get("id"))
            self.list_widget.addItem(item)

    def _selected_id(self) -> Optional[str]:
        item = self.list_widget.currentItem()
        if not item:
            return None
        value = item.data(Qt.UserRole)
        return str(value) if value else None

    def _on_open(self) -> None:
        session_id = self._selected_id()
        if not session_id:
            return
        self.session_opened.emit(session_id)
        self.accept()

    def _on_rename(self) -> None:
        session_id = self._selected_id()
        if not session_id:
            return
        session = self.store.load(session_id)
        if session is None:
            return
        new_title, ok = QInputDialog.getText(
            self, "Rename session", "New title:", text=session.title
        )
        if ok:
            self.store.rename(session_id, new_title)
            self._reload()

    def _on_delete(self) -> None:
        session_id = self._selected_id()
        if not session_id:
            return
        confirm = QMessageBox.question(
            self,
            "Delete session",
            "Delete this session? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.store.delete(session_id)
        self._reload()
