from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from openrouter_client import ModelInfo
from role_store import Role, RoleStore, recommended_model_for_role


# Sentinel item-data values for the model combo — distinguishes the two non-model
# entries from real OpenRouter model ids.
_USE_DEFAULT_MODEL = "__default__"
_USE_RECOMMENDED_MODEL = "__recommended__"


class RoleEditDialog(QDialog):
    """Editor for a single role (title + prompt + preferred model). Used for
    both new and existing roles. When ``locked_title`` is True (the built-in
    AI Assistant role), the title field is disabled.

    Pass ``models`` so the dialog can offer a real list of OpenRouter models;
    if it's empty (e.g. before the API has loaded), the combo still works as
    a "use default / use recommended" picker.
    """

    def __init__(
        self,
        role: Optional[Role] = None,
        locked_title: bool = False,
        parent: Optional[QWidget] = None,
        models: Optional[List[ModelInfo]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Role" if role is not None else "Add Role")
        self.setModal(True)
        self.resize(640, 460)

        self._original = role
        self._locked_title = locked_title
        self._models: List[ModelInfo] = list(models or [])

        info = QLabel(
            "Give the role a short title, the system prompt the assistant "
            "should follow, and the model that should be used by default when "
            "this role is active. Each role can have its own preferred model."
        )
        info.setObjectName("mutedLabel")
        info.setWordWrap(True)

        title_label = QLabel("Title")
        title_label.setObjectName("mutedLabel")
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("e.g. Electrical Specialist")
        if role is not None:
            self.title_edit.setText(role.title)
        if locked_title:
            self.title_edit.setEnabled(False)
            self.title_edit.setToolTip("The AI Assistant role title cannot be changed.")

        prompt_label = QLabel("System Prompt")
        prompt_label.setObjectName("mutedLabel")
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText("You are a helpful assistant.")
        if role is not None:
            self.prompt_edit.setPlainText(role.prompt)

        model_label = QLabel("Preferred Model")
        model_label.setObjectName("mutedLabel")

        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(360)
        self._populate_model_combo()
        self._select_initial_model()

        self.use_recommended_btn = QPushButton("Reset to recommended")
        self.use_recommended_btn.setToolTip(
            "Use the model recommended for this role (Claude Opus / Sonnet / GPT)."
        )
        self.use_recommended_btn.clicked.connect(self._on_reset_recommended)
        if role is None or recommended_model_for_role(role.id) is None:
            self.use_recommended_btn.setVisible(False)

        model_row = QHBoxLayout()
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.setSpacing(8)
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(self.use_recommended_btn, 0)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addWidget(info)
        layout.addWidget(title_label)
        layout.addWidget(self.title_edit)
        layout.addWidget(prompt_label)
        layout.addWidget(self.prompt_edit, 1)
        layout.addWidget(model_label)
        layout.addLayout(model_row)
        layout.addLayout(buttons)

    # ---- Model combo helpers ---------------------------------------------

    def _populate_model_combo(self) -> None:
        self.model_combo.clear()
        recommended_id = (
            recommended_model_for_role(self._original.id) if self._original else None
        )
        if recommended_id:
            label = self._label_for_model_id(recommended_id) or recommended_id
            self.model_combo.addItem(
                f"Recommended ({label})", userData=_USE_RECOMMENDED_MODEL
            )
        self.model_combo.addItem("Use global default model", userData=_USE_DEFAULT_MODEL)
        if self._models:
            self.model_combo.insertSeparator(self.model_combo.count())
            for model in self._models:
                label = f"{model.company} - {model.name}"
                self.model_combo.addItem(label, userData=model.model_id)

    def _select_initial_model(self) -> None:
        if self._original is None:
            self.model_combo.setCurrentIndex(0)
            return
        current = self._original.model_id
        if current is None:
            recommended_id = recommended_model_for_role(self._original.id)
            target_data = _USE_RECOMMENDED_MODEL if recommended_id else _USE_DEFAULT_MODEL
        elif current == "":
            target_data = _USE_DEFAULT_MODEL
        else:
            target_data = current
        index = self.model_combo.findData(target_data)
        if index < 0 and isinstance(target_data, str) and target_data not in (
            _USE_DEFAULT_MODEL,
            _USE_RECOMMENDED_MODEL,
        ):
            # Pinned id is not in the loaded model list — keep it as a tagged item
            # so the user's choice survives a save instead of silently reverting.
            self.model_combo.addItem(f"{target_data} (not currently available)", userData=target_data)
            index = self.model_combo.count() - 1
        if index >= 0:
            self.model_combo.setCurrentIndex(index)

    def _on_reset_recommended(self) -> None:
        index = self.model_combo.findData(_USE_RECOMMENDED_MODEL)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)

    def _label_for_model_id(self, model_id: str) -> Optional[str]:
        for model in self._models:
            if model.model_id == model_id:
                return f"{model.company} - {model.name}"
        return None

    def _selected_model_id(self) -> Optional[str]:
        """Map combo selection back to the dataclass convention:
        ``None`` for "use recommended" (lets backfill stay in charge),
        ``""`` for "use global default", or a concrete OpenRouter id.
        """
        data = self.model_combo.currentData()
        if data == _USE_RECOMMENDED_MODEL:
            return None
        if data == _USE_DEFAULT_MODEL or data is None:
            return ""
        text = str(data)
        return text

    # ---- Output ----------------------------------------------------------

    def get_role(self) -> Role:
        """Return a Role for the edited contents. Reuses the original id when
        editing; otherwise generates a fresh one.
        """
        title = self.title_edit.text().strip()
        prompt = self.prompt_edit.toPlainText().strip()
        model_id = self._selected_model_id()
        if self._original is not None:
            return Role(
                id=self._original.id,
                title=title or self._original.title,
                prompt=prompt,
                model_id=model_id,
            )
        return RoleStore.new_role(title or "Untitled", prompt, model_id=model_id)


# Backwards-compatible alias for any leftover imports.
EditSystemPromptDialog = RoleEditDialog
