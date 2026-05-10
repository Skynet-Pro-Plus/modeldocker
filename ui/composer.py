from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSlider,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from openrouter_client import ModelInfo
from ui.widgets.icon_button import IconButton
from ui.widgets.pill import Pill


class ChatInput(QTextEdit):
    submit_requested = Signal()

    def keyPressEvent(self, event: Any) -> None:
        is_enter = event.key() in (Qt.Key_Return, Qt.Key_Enter)
        has_shift = bool(event.modifiers() & Qt.ShiftModifier)
        if is_enter and not has_shift:
            self.submit_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class VideoOptionsPopup(QMenu):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        title = QLabel("Video Options")
        title.setObjectName("valueLabel")
        layout.addWidget(title)

        layout.addWidget(QLabel("Duration"))
        self.duration_combo = QComboBox()
        self.duration_combo.addItems(["4 sec", "6 sec", "8 sec"])
        self.duration_combo.setCurrentText("8 sec")
        layout.addWidget(self.duration_combo)

        layout.addWidget(QLabel("Resolution"))
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["480p", "720p", "1080p"])
        self.resolution_combo.setCurrentText("720p")
        layout.addWidget(self.resolution_combo)

        layout.addWidget(QLabel("Aspect Ratio"))
        self.aspect_combo = QComboBox()
        self.aspect_combo.addItems(["16:9"])
        layout.addWidget(self.aspect_combo)

        self.audio_check = QCheckBox("Generate audio")
        self.audio_check.setChecked(True)
        layout.addWidget(self.audio_check)

        action = QWidgetAction(self)
        action.setDefaultWidget(container)
        self.addAction(action)


class Composer(QFrame):
    """Bottom area: model picker, input, action row, footer."""

    send_requested = Signal()
    model_changed = Signal(str)
    save_default_model_requested = Signal()
    save_role_model_requested = Signal()
    model_filter_changed = Signal()
    pick_image_requested = Signal()
    pick_pdf_requested = Signal()
    clear_attachments_requested = Signal()
    clear_chat_requested = Signal()
    temperature_changed = Signal(float)
    tts_speed_changed = Signal(float)
    image_output_toggled = Signal(bool)
    video_output_toggled = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("composer")
        self._models: List[ModelInfo] = []
        self._filter_actions: Dict[str, QAction] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)

        outer.addLayout(self._build_model_row())
        outer.addLayout(self._build_input_row())
        outer.addLayout(self._build_controls_row())
        outer.addLayout(self._build_footer_row())

    # ---- UI rows ---------------------------------------------------------

    def _build_model_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        label = QLabel("Model")
        label.setObjectName("mutedLabel")
        label.setMinimumWidth(44)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search models...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setToolTip(
            "Type to filter the model list by company, name, id, or capability.\n"
            "Press Enter to open the filtered dropdown."
        )
        # textChanged passes str; model_filter_changed is Signal() — cannot connect
        # directly to .emit (PySide6: "only accepts 0 argument(s), 1 given!").
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        self.search_edit.returnPressed.connect(self._on_search_activated)

        self.match_count_pill = Pill("", variant="muted")
        self.match_count_pill.setToolTip("Number of models matching the current search and filters")
        self.match_count_pill.setVisible(False)

        self.gear_btn = QToolButton()
        self.gear_btn.setText("\u2699")
        self.gear_btn.setToolTip("Filters, temperature & speech speed")
        self.gear_btn.setPopupMode(QToolButton.InstantPopup)
        self._gear_menu = QMenu(self.gear_btn)
        self._build_gear_menu(self._gear_menu)
        self.gear_btn.setMenu(self._gear_menu)
        self.gear_btn.setFixedSize(34, 32)

        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(220)
        self.model_combo.currentIndexChanged.connect(self._on_model_index_changed)
        self.model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.set_default_model_btn = QPushButton("Set as default")
        self.set_default_model_btn.setObjectName("ghostButton")
        self.set_default_model_btn.setMinimumHeight(32)
        self.set_default_model_btn.setToolTip(
            "Remember the selected model for new sessions and chats that have no model saved."
        )
        self.set_default_model_btn.clicked.connect(self.save_default_model_requested.emit)

        self.save_role_model_btn = QPushButton("Save for role")
        self.save_role_model_btn.setObjectName("ghostButton")
        self.save_role_model_btn.setMinimumHeight(32)
        # Hidden by default; main_window flips it on whenever a non-Default
        # role is active and updates the tooltip with the role title.
        self.save_role_model_btn.setVisible(False)
        self.save_role_model_btn.clicked.connect(self.save_role_model_requested.emit)

        # Combo + button share one stretch slot so they never paint over each other when space is tight.
        model_pick_shell = QWidget()
        model_pick_shell.setMinimumWidth(0)
        model_pick_shell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        mpc = QHBoxLayout(model_pick_shell)
        mpc.setContentsMargins(0, 0, 0, 0)
        mpc.setSpacing(8)
        mpc.addWidget(self.model_combo, 1)
        mpc.addWidget(self.set_default_model_btn, 0)
        mpc.addWidget(self.save_role_model_btn, 0)

        self.in_price_pill = Pill("In: -", variant="muted")
        self.out_price_pill = Pill("Out: -", variant="muted")

        row.addWidget(label)
        row.addWidget(self.search_edit, 0)
        row.addWidget(self.match_count_pill)
        row.addWidget(self.gear_btn)
        row.addWidget(model_pick_shell, 1)
        row.addWidget(self.in_price_pill)
        row.addWidget(self.out_price_pill)
        return row

    def _build_gear_menu(self, menu: QMenu) -> None:
        for key, label in [
            ("text", "\U0001F4DD Text"),
            ("image", "\U0001F5BC Image"),
            ("file", "\U0001F4C4 Files / PDFs"),
            ("audio", "\U0001F50A Audio"),
            ("video", "\U0001F39E Video"),
        ]:
            action = QAction(label, menu)
            action.setCheckable(True)
            action.toggled.connect(lambda _checked: self.model_filter_changed.emit())
            menu.addAction(action)
            self._filter_actions[key] = action

        clear_filters = QAction("Clear filters", menu)
        clear_filters.triggered.connect(self._clear_filters)
        menu.addSeparator()
        menu.addAction(clear_filters)

        menu.addSeparator()

        temp_widget = QWidget()
        temp_layout = QVBoxLayout(temp_widget)
        temp_layout.setContentsMargins(10, 6, 10, 6)
        temp_layout.setSpacing(4)
        header = QHBoxLayout()
        title = QLabel("Temperature")
        title.setObjectName("valueLabel")
        self.temp_value_label = QLabel("0.7")
        self.temp_value_label.setObjectName("mutedLabel")
        self.temp_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.temp_value_label)
        temp_layout.addLayout(header)

        self.temp_slider = QSlider(Qt.Horizontal)
        self.temp_slider.setMinimum(0)
        self.temp_slider.setMaximum(20)
        self.temp_slider.setSingleStep(1)
        self.temp_slider.setValue(7)
        self.temp_slider.valueChanged.connect(self._on_temperature_changed)
        temp_layout.addWidget(self.temp_slider)

        action = QWidgetAction(menu)
        action.setDefaultWidget(temp_widget)
        menu.addAction(action)

        # ----- Speech (TTS) speed --------------------------------------
        # Slider stores integer percent of normal speed (50% .. 200%) so it
        # plays nicely with QSlider; the public API uses a float multiplier.
        speech_widget = QWidget()
        speech_layout = QVBoxLayout(speech_widget)
        speech_layout.setContentsMargins(10, 6, 10, 6)
        speech_layout.setSpacing(4)
        speech_header = QHBoxLayout()
        speech_title = QLabel("Speech speed")
        speech_title.setObjectName("valueLabel")
        self.speech_value_label = QLabel("1.15x")
        self.speech_value_label.setObjectName("mutedLabel")
        self.speech_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        speech_header.addWidget(speech_title)
        speech_header.addStretch()
        speech_header.addWidget(self.speech_value_label)
        speech_layout.addLayout(speech_header)

        self.speech_slider = QSlider(Qt.Horizontal)
        self.speech_slider.setMinimum(50)
        self.speech_slider.setMaximum(200)
        self.speech_slider.setSingleStep(5)
        self.speech_slider.setPageStep(10)
        self.speech_slider.setValue(115)
        self.speech_slider.setToolTip(
            "Playback speed for the assistant's Speak Aloud audio. 1.00x is normal."
        )
        self.speech_slider.valueChanged.connect(self._on_tts_speed_changed)
        speech_layout.addWidget(self.speech_slider)

        speech_action = QWidgetAction(menu)
        speech_action.setDefaultWidget(speech_widget)
        menu.addAction(speech_action)

    def _on_search_text_changed(self, _text: str) -> None:
        self.model_filter_changed.emit()

    def _on_search_activated(self) -> None:
        """Expand the model dropdown when the user explicitly asks (Enter / Down)."""
        if self._models:
            self.model_combo.showPopup()

    def _filters_active(self) -> bool:
        if self.search_text():
            return True
        return any(action.isChecked() for action in self._filter_actions.values())

    def _update_match_count_pill(self, matched: int, total: int) -> None:
        if total <= 0 or not self._filters_active():
            self.match_count_pill.set_text("")
            self.match_count_pill.setVisible(False)
            return
        self.match_count_pill.set_text(f"{matched} of {total}")
        self.match_count_pill.setVisible(True)

    def _clear_filters(self) -> None:
        self.search_edit.clear()
        for action in self._filter_actions.values():
            action.setChecked(False)
        self.model_filter_changed.emit()

    def _on_temperature_changed(self, value: int) -> None:
        temp = round(value / 10.0, 1)
        self.temp_value_label.setText(f"{temp:.1f}")
        self.footer_temp_label.setText(f"Temperature: {temp:.1f}")
        self.temperature_changed.emit(float(temp))

    def _on_tts_speed_changed(self, value: int) -> None:
        speed = round(value / 100.0, 2)
        self.speech_value_label.setText(f"{speed:.2f}x")
        self.tts_speed_changed.emit(float(speed))

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.input_edit = ChatInput()
        self.input_edit.setAcceptDrops(False)
        self.input_edit.setPlaceholderText(
            "Type your message... (Shift + Enter for new line)"
        )
        self.input_edit.setFixedHeight(96)
        self.input_edit.submit_requested.connect(self.send_requested.emit)
        row.addWidget(self.input_edit)
        return row

    def _build_controls_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.attach_pdf_btn = QPushButton("\U0001F4CE  Attach")
        self.attach_pdf_btn.clicked.connect(self.pick_pdf_requested.emit)

        self.attach_image_btn = QPushButton("\U0001F5BC  Upload Image")
        self.attach_image_btn.clicked.connect(self.pick_image_requested.emit)

        self.generate_image_btn = QPushButton("\u2728  Generate Image")
        self.generate_image_btn.setCheckable(True)
        self.generate_image_btn.toggled.connect(self.image_output_toggled.emit)

        self.video_options_btn = QPushButton("\U0001F39E  Video")
        self.video_options_btn.setCheckable(True)
        self.video_options_btn.toggled.connect(self.video_output_toggled.emit)
        self.video_options_menu = VideoOptionsPopup(self)
        self.video_options_btn.setMenu(self.video_options_menu)

        self.clear_uploads_btn = QPushButton("Clear Uploads")
        self.clear_uploads_btn.setObjectName("ghostButton")
        self.clear_uploads_btn.clicked.connect(self.clear_attachments_requested.emit)

        info_btn = IconButton("\u24D8", tooltip="Tip: Drag images or PDFs into the window to attach.", size=30)

        self.send_btn = QPushButton("\u2708  Send")
        self.send_btn.setObjectName("primaryButton")
        self.send_btn.setMinimumWidth(110)
        self.send_btn.clicked.connect(self.send_requested.emit)

        row.addWidget(self.attach_pdf_btn)
        row.addWidget(self.attach_image_btn)
        row.addWidget(self.generate_image_btn)
        row.addWidget(self.video_options_btn)
        row.addWidget(self.clear_uploads_btn)
        row.addWidget(info_btn)
        row.addStretch()
        row.addWidget(self.send_btn)
        return row

    def _build_footer_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(10)

        self.footer_context_label = QLabel("Context Window: -")
        self.footer_context_label.setObjectName("mutedLabel")
        self.footer_total_tokens_label = QLabel("Total Tokens: 0")
        self.footer_total_tokens_label.setObjectName("mutedLabel")
        self.footer_temp_label = QLabel("Temperature: 0.7")
        self.footer_temp_label.setObjectName("mutedLabel")

        sep1 = QLabel("\u2022")
        sep1.setObjectName("mutedLabel")
        sep2 = QLabel("\u2022")
        sep2.setObjectName("mutedLabel")

        self.clear_chat_btn = QPushButton("New chat")
        self.clear_chat_btn.setObjectName("linkButton")
        self.clear_chat_btn.setCursor(Qt.PointingHandCursor)
        self.clear_chat_btn.clicked.connect(self.clear_chat_requested.emit)

        row.addWidget(self.footer_context_label)
        row.addWidget(sep1)
        row.addWidget(self.footer_total_tokens_label)
        row.addWidget(sep2)
        row.addWidget(self.footer_temp_label)
        row.addStretch()
        row.addWidget(self.clear_chat_btn)
        return row

    # ---- Public update API ----------------------------------------------

    def set_models(self, models: List[ModelInfo]) -> None:
        self._models = models
        self.refresh_combo()

    def update_role_save_target(self, role_title: Optional[str]) -> None:
        """Show/hide the 'Save for role' button based on the active role.
        Pass ``None`` for the Default role; the button stays hidden in that
        case (saving Default is what the global "Set as default" button does).
        """
        if role_title:
            self.save_role_model_btn.setVisible(True)
            self.save_role_model_btn.setToolTip(
                f"Save the selected model as the preferred model for the role: {role_title}"
            )
        else:
            self.save_role_model_btn.setVisible(False)
            self.save_role_model_btn.setToolTip("")

    def filter_actions(self) -> Dict[str, QAction]:
        return self._filter_actions

    def search_text(self) -> str:
        return self.search_edit.text().strip().lower()

    def selected_model_id(self) -> Optional[str]:
        data = self.model_combo.currentData()
        return str(data) if data else None

    def select_model_by_id(self, model_id: Optional[str]) -> None:
        if not model_id:
            return
        index = self.model_combo.findData(model_id)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)

    def refresh_combo(self) -> None:
        previous_id = self.selected_model_id()
        filtered = self._filter_models()
        filtered_ids = {m.model_id for m in filtered}
        self._update_match_count_pill(matched=len(filtered), total=len(self._models))

        # Keep the previously-selected model visible at the top even when the
        # current filter would hide it, so typing in the search box never
        # silently swaps the active model out from under the user.
        pinned: List[ModelInfo] = []
        if previous_id and previous_id not in filtered_ids:
            pinned_model = self.get_model(previous_id)
            if pinned_model is not None:
                pinned.append(pinned_model)

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for model in pinned:
            label = f"{model.company} - {model.name} | {model.release_date_label}  \u2014 current"
            self.model_combo.addItem(label, userData=model.model_id)
        for model in filtered:
            label = f"{model.company} - {model.name} | {model.release_date_label}"
            self.model_combo.addItem(label, userData=model.model_id)
        if previous_id:
            index = self.model_combo.findData(previous_id)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
        self.model_combo.blockSignals(False)

        # Only emit ``model_changed`` when the resolved selection actually
        # differs from before; a pure filter rebuild that preserves the same
        # selection should not retrigger downstream session updates.
        new_id = self.selected_model_id()
        if new_id != previous_id:
            self._on_model_index_changed(self.model_combo.currentIndex())

    def _filter_models(self) -> List[ModelInfo]:
        query = self.search_text()
        # Every non-empty word must appear somewhere in the model's search text
        # (case-insensitive). Example: "openai gpt" matches rows containing both.
        tokens = [t for t in query.split() if t]
        required = [k for k, action in self._filter_actions.items() if action.isChecked()]
        results: List[ModelInfo] = []
        for model in self._models:
            haystack = model.search_haystack
            if tokens and not all(tok in haystack for tok in tokens):
                continue
            if required and not all(self._model_matches_filter(model, key) for key in required):
                continue
            results.append(model)
        return results

    @staticmethod
    def _model_matches_filter(model: ModelInfo, key: str) -> bool:
        if key == "file":
            return model.supports_pdf_input
        if key == "image":
            return model.supports_image_input or model.supports_image_output
        if key == "video":
            return model.supports_video_output
        values = set(model.input_modalities) | set(model.output_modalities)
        return key in values

    def get_model(self, model_id: Optional[str]) -> Optional[ModelInfo]:
        if not model_id:
            return None
        for model in self._models:
            if model.model_id == model_id:
                return model
        return None

    def update_for_model(self, model: Optional[ModelInfo]) -> None:
        if model is None:
            self.attach_image_btn.setVisible(False)
            self.attach_pdf_btn.setVisible(False)
            self.generate_image_btn.setVisible(False)
            self.video_options_btn.setVisible(False)
            self.in_price_pill.set_text("In: -")
            self.out_price_pill.set_text("Out: -")
            self.footer_context_label.setText("Context Window: -")
            return

        self.attach_image_btn.setVisible(model.supports_image_input)
        self.attach_pdf_btn.setVisible(model.supports_pdf_input)
        self.generate_image_btn.setVisible(True)
        self.video_options_btn.setVisible(model.supports_video_output)
        if not model.supports_video_output:
            self.video_options_btn.setChecked(False)

        self._populate_video_controls(model)

        in_per_m = model.pricing.prompt * 1_000_000
        out_per_m = model.pricing.completion * 1_000_000
        self.in_price_pill.set_text(f"In: ${in_per_m:.4f} /M")
        self.out_price_pill.set_text(f"Out: ${out_per_m:.4f} /M")

        ctx = model.context_length
        if ctx:
            if ctx >= 1000:
                ctx_text = f"{ctx // 1000}K"
            else:
                ctx_text = str(ctx)
            self.footer_context_label.setText(f"Context Window: {ctx_text} tokens")
        else:
            self.footer_context_label.setText("Context Window: unknown")

        if not model.supports_image_output:
            self.generate_image_btn.setToolTip(
                "Uses OpenRouter's image-generation tool fallback for this model."
            )
        else:
            self.generate_image_btn.setToolTip("Native image output supported.")

        self.search_edit.setToolTip(model.friendly_capability_label)

    def _populate_video_controls(self, model: ModelInfo) -> None:
        if not model.supports_video_output:
            return
        popup = self.video_options_menu
        durations = [f"{value} sec" for value in model.supported_video_durations]
        current_d = popup.duration_combo.currentText()
        popup.duration_combo.clear()
        popup.duration_combo.addItems(durations)
        if current_d in durations:
            popup.duration_combo.setCurrentText(current_d)

        resolutions = list(model.supported_video_resolutions)
        current_r = popup.resolution_combo.currentText()
        popup.resolution_combo.clear()
        popup.resolution_combo.addItems(resolutions)
        if current_r in resolutions:
            popup.resolution_combo.setCurrentText(current_r)

        aspects = list(model.supported_video_aspect_ratios)
        current_a = popup.aspect_combo.currentText()
        popup.aspect_combo.clear()
        popup.aspect_combo.addItems(aspects)
        if current_a in aspects:
            popup.aspect_combo.setCurrentText(current_a)

        popup.audio_check.setEnabled(model.supports_video_audio)
        if not model.supports_video_audio:
            popup.audio_check.setChecked(False)

    def video_options(self) -> Dict[str, Any]:
        popup = self.video_options_menu
        try:
            duration = int(popup.duration_combo.currentText().split()[0])
        except (ValueError, IndexError):
            duration = 8
        return {
            "duration": duration,
            "resolution": popup.resolution_combo.currentText(),
            "aspect_ratio": popup.aspect_combo.currentText(),
            "audio": popup.audio_check.isChecked(),
        }

    def temperature(self) -> float:
        return round(self.temp_slider.value() / 10.0, 1)

    def set_temperature(self, value: float) -> None:
        self.temp_slider.blockSignals(True)
        self.temp_slider.setValue(int(round(value * 10)))
        self.temp_slider.blockSignals(False)
        self.temp_value_label.setText(f"{value:.1f}")
        self.footer_temp_label.setText(f"Temperature: {value:.1f}")

    def tts_speed(self) -> float:
        return round(self.speech_slider.value() / 100.0, 2)

    def set_tts_speed(self, value: float) -> None:
        clamped = max(0.5, min(float(value), 2.0))
        self.speech_slider.blockSignals(True)
        self.speech_slider.setValue(int(round(clamped * 100)))
        self.speech_slider.blockSignals(False)
        self.speech_value_label.setText(f"{clamped:.2f}x")

    def set_total_tokens(self, count: int) -> None:
        self.footer_total_tokens_label.setText(f"Total Tokens: {count:,}")

    def set_send_enabled(self, enabled: bool) -> None:
        self.send_btn.setEnabled(enabled)

    def get_input_text(self) -> str:
        return self.input_edit.toPlainText().strip()

    def clear_input(self) -> None:
        self.input_edit.clear()

    def is_image_output_requested(self) -> bool:
        return self.generate_image_btn.isChecked() and self.generate_image_btn.isVisible()

    def is_video_output_requested(self) -> bool:
        return self.video_options_btn.isChecked() and self.video_options_btn.isVisible()

    def reset_output_toggles(self) -> None:
        self.generate_image_btn.setChecked(False)
        self.video_options_btn.setChecked(False)

    def _on_model_index_changed(self, _index: int) -> None:
        model_id = self.selected_model_id()
        self.model_changed.emit(model_id or "")
