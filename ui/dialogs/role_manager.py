from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from openrouter_client import ModelInfo
from role_store import DEFAULT_ROLE_ID, Role, RoleStore
from ui.dialogs.edit_system_prompt import RoleEditDialog


class RoleManagerDialog(QDialog):
    """Library of system-prompt roles. The active role is marked ``(active)``
    in the list. Clicking a row highlights it; the footer buttons act on the
    highlighted row.
    """

    role_activated = Signal(str)

    def __init__(
        self,
        store: RoleStore,
        active_role_id: str,
        parent: Optional[QWidget] = None,
        models: Optional[List[ModelInfo]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Roles")
        self.setModal(True)
        self.resize(520, 460)

        self.store = store
        self._active_role_id = active_role_id
        self._models: List[ModelInfo] = list(models or [])

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Roles")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()

        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._update_button_state)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._on_use())

        self.use_btn = QPushButton("Use")
        self.use_btn.setObjectName("primaryButton")
        self.use_btn.clicked.connect(self._on_use)
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.clicked.connect(self._on_edit)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._on_delete)
        self.add_btn = QPushButton("Add")
        self.add_btn.setToolTip("Add a new role")
        self.add_btn.clicked.connect(self._on_add)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(self.use_btn)
        footer.addWidget(self.edit_btn)
        footer.addWidget(self.delete_btn)
        footer.addWidget(self.add_btn)
        footer.addStretch()
        footer.addWidget(self.close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(footer)

        self._reload(select_id=active_role_id)

    # ---- List management -------------------------------------------------

    def _reload(self, select_id: Optional[str] = None) -> None:
        self.list_widget.clear()
        roles = sorted(self.store.list(), key=lambda r: r.title.strip().casefold())
        for role in roles:
            label = role.title
            if role.id == self._active_role_id:
                label = f"{label}    (active)"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, role.id)
            self.list_widget.addItem(item)
        if select_id is not None:
            self._select_id(select_id)
        elif self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        self._update_button_state()

    def _select_id(self, role_id: str) -> None:
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.data(Qt.UserRole) == role_id:
                self.list_widget.setCurrentRow(index)
                return
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _highlighted_id(self) -> Optional[str]:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        value = item.data(Qt.UserRole)
        return str(value) if value else None

    def _highlighted_role(self) -> Optional[Role]:
        role_id = self._highlighted_id()
        if not role_id:
            return None
        return self.store.get(role_id)

    def _update_button_state(self) -> None:
        role_id = self._highlighted_id()
        has_selection = role_id is not None
        is_default = role_id == DEFAULT_ROLE_ID
        self.use_btn.setEnabled(has_selection)
        self.edit_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection and not is_default)
        if is_default:
            self.delete_btn.setToolTip("The AI Assistant (built-in) role cannot be deleted.")
        else:
            self.delete_btn.setToolTip("")

    # ---- Footer actions --------------------------------------------------

    def _on_use(self) -> None:
        role_id = self._highlighted_id()
        if not role_id:
            return
        self._active_role_id = role_id
        self.role_activated.emit(role_id)
        self.accept()

    def _on_edit(self) -> None:
        role = self._highlighted_role()
        if role is None:
            return
        dialog = RoleEditDialog(
            role=role,
            locked_title=(role.id == DEFAULT_ROLE_ID),
            parent=self,
            models=self._models,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        updated = dialog.get_role()
        self.store.upsert(updated)
        self._reload(select_id=updated.id)

    def _on_delete(self) -> None:
        role = self._highlighted_role()
        if role is None or role.id == DEFAULT_ROLE_ID:
            return
        confirm = QMessageBox.question(
            self,
            "Delete role",
            f"Delete the role '{role.title}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.store.delete(role.id)
        # If we deleted the active role, fall back to Default.
        if self._active_role_id == role.id:
            self._active_role_id = DEFAULT_ROLE_ID
            self.role_activated.emit(DEFAULT_ROLE_ID)
        self._reload(select_id=DEFAULT_ROLE_ID)

    def _on_add(self) -> None:
        dialog = RoleEditDialog(
            role=None,
            locked_title=False,
            parent=self,
            models=self._models,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        new_role = dialog.get_role()
        self.store.upsert(new_role)
        self._reload(select_id=new_role.id)
