from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from memory_store import MAX_MEMORY_TEXT_CHARS, Memory, MemoryStore
from role_store import RoleStore


class MemoryManagerDialog(QDialog):
    """Create and edit saved memories (global or per-role)."""

    def __init__(
        self,
        memory_store: MemoryStore,
        role_store: RoleStore,
        current_role_id: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Saved memory")
        self.resize(560, 420)
        self._memory_store = memory_store
        self._role_store = role_store
        self._current_role_id = current_role_id

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_row_changed)

        self._text = QPlainTextEdit()
        self._text.setPlaceholderText(
            "Short facts or preferences the assistant should remember "
            f"(max {MAX_MEMORY_TEXT_CHARS} characters)."
        )

        self._role_combo = QComboBox()
        self._populate_role_combo()

        self._enabled = QCheckBox("Enabled")
        self._enabled.setChecked(True)

        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_memory)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._save_current)
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._delete_current)

        row_btns = QHBoxLayout()
        row_btns.addWidget(add_btn)
        row_btns.addWidget(save_btn)
        row_btns.addWidget(delete_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Saved items"))
        layout.addWidget(self._list, 1)
        layout.addWidget(QLabel("Memory text"))
        layout.addWidget(self._text, 1)
        layout.addWidget(QLabel("Applies to"))
        layout.addWidget(self._role_combo)
        layout.addWidget(self._enabled)
        layout.addLayout(row_btns)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._reload_list(select_id=None)

    def _populate_role_combo(self) -> None:
        self._role_combo.clear()
        self._role_combo.addItem("All roles", None)
        for role in self._role_store.list():
            self._role_combo.addItem(role.title, role.id)

    def _reload_list(self, select_id: Optional[str]) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for mem in self._memory_store.list(include_disabled=True):
            scope = "All roles"
            if mem.role_id:
                role = self._role_store.get(mem.role_id)
                scope = role.title if role else mem.role_id
            flag = "" if mem.enabled else " (off)"
            preview = mem.text.strip().replace("\n", " ")
            if len(preview) > 72:
                preview = preview[:72] + "..."
            label = f"{preview or '(empty)'}{flag} — {scope}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, mem.id)
            self._list.addItem(item)
        self._list.blockSignals(False)

        if select_id:
            for row in range(self._list.count()):
                item = self._list.item(row)
                if item and item.data(Qt.UserRole) == select_id:
                    self._list.setCurrentRow(row)
                    break
        elif self._list.count():
            self._list.setCurrentRow(0)

    def _selected_id(self) -> Optional[str]:
        item = self._list.currentItem()
        if item is None:
            return None
        raw = item.data(Qt.UserRole)
        return str(raw) if raw else None

    def _on_row_changed(self, current: QListWidgetItem, _previous: QListWidgetItem) -> None:
        self._load_into_form(self._selected_id())

    def _load_into_form(self, memory_id: Optional[str]) -> None:
        if not memory_id:
            self._text.clear()
            self._enabled.setChecked(True)
            self._pick_role_in_combo(None)
            return
        mem = self._memory_store.get(memory_id)
        if mem is None:
            self._text.clear()
            return
        self._text.setPlainText(mem.text)
        self._enabled.setChecked(mem.enabled)
        self._pick_role_in_combo(mem.role_id)

    def _pick_role_in_combo(self, role_id: Optional[str]) -> None:
        for index in range(self._role_combo.count()):
            if self._role_combo.itemData(index) == role_id:
                self._role_combo.setCurrentIndex(index)
                return
        self._role_combo.setCurrentIndex(0)

    def _role_from_combo(self) -> Optional[str]:
        data = self._role_combo.currentData()
        if data is None:
            return None
        return str(data)

    def _add_memory(self) -> None:
        mem = Memory(
            id="",
            text="",
            role_id=self._current_role_id,
            enabled=True,
            created_at=0.0,
            updated_at=0.0,
        )
        self._memory_store.upsert(mem)
        self._reload_list(select_id=mem.id)

    def _save_current(self) -> None:
        mid = self._selected_id()
        if not mid:
            QMessageBox.information(self, "Nothing selected", "Select a memory or click Add.")
            return
        text = self._text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Empty memory", "Enter some text before saving.")
            return
        existing = self._memory_store.get(mid)
        if existing is None:
            return
        updated = Memory(
            id=existing.id,
            text=text[:MAX_MEMORY_TEXT_CHARS],
            role_id=self._role_from_combo(),
            enabled=self._enabled.isChecked(),
            created_at=existing.created_at,
            updated_at=existing.updated_at,
        )
        self._memory_store.upsert(updated)
        self._reload_list(select_id=mid)

    def _delete_current(self) -> None:
        mid = self._selected_id()
        if not mid:
            return
        confirm = QMessageBox.question(
            self,
            "Delete memory",
            "Remove this saved memory?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self._memory_store.delete(mid)
        self._reload_list(select_id=None)
