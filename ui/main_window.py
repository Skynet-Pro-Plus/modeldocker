from __future__ import annotations

import base64
import os
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from openrouter_client import (
    ModelInfo,
    OpenRouterClient,
    OpenRouterError,
    build_request_messages,
    calculate_interaction_cost,
    encode_file_as_data_url,
    extract_image_urls,
)
from session_title_parse import (
    FIRST_TURN_SESSION_TITLE_EXTRA_SYSTEM,
    StreamingSessionTitleParser,
    split_first_turn_response,
)
from role_store import DEFAULT_ROLE_ID, Role, RoleStore
from session_store import (
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TEMPERATURE,
    Session,
    SessionStore,
)
from settings_store import DEFAULT_MODEL_ID, SettingsStore
from shiboken6 import isValid
from ui.composer import Composer
from ui.conversation_view import ConversationView, MessageBubble
from ui.dialogs import ApiKeyDialog, HistoryDialog, RoleManagerDialog
from ui.sidebar import Sidebar
from ui.theme import Theme, ThemeManager, build_stylesheet
from ui.title_bar import TitleBar


RESIZE_MARGIN = 8


@dataclass
class PendingAttachment:
    path: str
    kind: str  # image | pdf


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)


class Worker(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.result.emit(result)
        except Exception:
            self.signals.error.emit(traceback.format_exc())


class StreamWorkerSignals(QObject):
    event = Signal(object)
    finished = Signal()
    error = Signal(str)


class StreamWorker(QRunnable):
    def __init__(
        self,
        client: OpenRouterClient,
        model_id: str,
        messages: List[Dict[str, Any]],
        modalities: Optional[List[str]],
        temperature: Optional[float],
        max_tokens: Optional[int] = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.model_id = model_id
        self.messages = messages
        self.modalities = modalities
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.signals = StreamWorkerSignals()

    def run(self) -> None:
        try:
            for event in self.client.chat_stream(
                self.model_id,
                self.messages,
                self.modalities,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            ):
                if event.get("type") == "error":
                    raise OpenRouterError(event.get("message", "OpenRouter stream error"))
                self.signals.event.emit(event)
            self.signals.finished.emit()
        except Exception:
            self.signals.error.emit(traceback.format_exc())


class VideoWorkerSignals(QObject):
    progress = Signal(object)
    result = Signal(object)
    error = Signal(str)


class VideoWorker(QRunnable):
    def __init__(
        self,
        client: OpenRouterClient,
        model_id: str,
        prompt: str,
        output_dir: str,
        duration: int,
        resolution: str,
        aspect_ratio: str,
        generate_audio: bool,
        frame_images: Optional[List[Dict[str, Any]]],
    ) -> None:
        super().__init__()
        self.client = client
        self.model_id = model_id
        self.prompt = prompt
        self.output_dir = output_dir
        self.duration = duration
        self.resolution = resolution
        self.aspect_ratio = aspect_ratio
        self.generate_audio = generate_audio
        self.frame_images = frame_images
        self.signals = VideoWorkerSignals()

    def run(self) -> None:
        try:
            result = self.client.generate_video(
                self.model_id,
                self.prompt,
                self.output_dir,
                self.duration,
                self.resolution,
                self.aspect_ratio,
                self.generate_audio,
                None,
                self.frame_images,
                self.signals.progress.emit,
            )
            self.signals.result.emit(result)
        except Exception:
            self.signals.error.emit(traceback.format_exc())


class TtsWorkerSignals(QObject):
    ready = Signal(bytes, object, int)
    cost_resolved = Signal(object, int, float)
    error = Signal(str, object, int)


class TtsWorker(QRunnable):
    def __init__(
        self,
        client: OpenRouterClient,
        text: str,
        model_id: str,
        voice: str,
        bubble: MessageBubble,
        gen: int,
        speed: float = 1.0,
    ) -> None:
        super().__init__()
        self.client = client
        self.text = text
        self.model_id = model_id
        self.voice = voice
        self.bubble = bubble
        self.gen = gen
        self.speed = float(speed)
        self.signals = TtsWorkerSignals()

    def run(self) -> None:
        try:
            speech = self.client.create_speech(
                self.text,
                model=self.model_id,
                voice=self.voice,
                response_format="mp3",
                speed=self.speed,
            )
        except OpenRouterError as exc:
            self.signals.error.emit(str(exc), self.bubble, self.gen)
            return
        except Exception:
            self.signals.error.emit(traceback.format_exc(), self.bubble, self.gen)
            return
        # Hand the audio back to the UI immediately; the cost lookup is async
        # and must not block playback (it can take ~1s for the metadata row to
        # show up on OpenRouter's side).
        self.signals.ready.emit(speech.audio, self.bubble, self.gen)
        if speech.generation_id:
            try:
                cost = self.client.fetch_generation_total_cost(speech.generation_id)
            except Exception:
                cost = 0.0
            if cost > 0:
                self.signals.cost_resolved.emit(self.bubble, self.gen, cost)


class ModelDockerMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ModelDocker")
        self.setMinimumSize(1100, 720)
        self.resize(1280, 820)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

        # ---- State -------------------------------------------------------
        self.thread_pool = QThreadPool.globalInstance()
        self.settings = SettingsStore()
        self.session_store = SessionStore()
        self.role_store = RoleStore()
        self.client: Optional[OpenRouterClient] = None
        self.models: List[ModelInfo] = []
        self.pending_attachments: List[PendingAttachment] = []
        self.active_workers: List[Any] = []
        self.validating_key = False
        # On the very first model sync after launch, force the OpenRouter
        # Free Models Router (``openrouter/free``) to be selected, regardless
        # of the resumed session's saved model. After the first successful
        # sync this flag is cleared and the normal resolution chain resumes.
        self._launch_force_free_router = True

        self.theme_manager = ThemeManager(
            Theme.LIGHT if self.settings.load_theme() == "light" else Theme.DARK
        )

        self.session: Session = self._initial_session()

        self.stream_text = ""
        self.stream_usage: Dict[str, Any] = {}
        self.stream_images: List[str] = []
        self.stream_model: Optional[ModelInfo] = None
        self.stream_started_at = 0.0
        self.stream_bubble: Optional[MessageBubble] = None
        self.stream_edit: Optional[QTextEdit] = None
        self._stream_progress_last_ui = 0.0
        self._stream_assistant_label = ""
        self._stream_title_parser: Optional[StreamingSessionTitleParser] = None
        self._stream_first_turn_ai_title = False

        self.generated_image_dir = Path.home() / ".modeldocker" / "generated_images"
        self.generated_image_dir.mkdir(parents=True, exist_ok=True)
        self.generated_video_dir = Path.home() / ".modeldocker" / "generated_videos"
        self.generated_video_dir.mkdir(parents=True, exist_ok=True)

        self._tts_gen = 0
        self._tts_pending_bubble: Optional[MessageBubble] = None
        self._tts_active_bubble: Optional[MessageBubble] = None
        self._tts_temp_path: Optional[Path] = None
        self._tts_player = QMediaPlayer(self)
        self._tts_audio_output = QAudioOutput(self)
        self._tts_player.setAudioOutput(self._tts_audio_output)
        self._tts_player.mediaStatusChanged.connect(self._on_tts_media_status)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._flush_session)

        # ---- UI ---------------------------------------------------------
        self._build_ui()
        self._wire_signals()
        self._apply_theme()
        self._populate_session_dropdown()
        self._render_session_into_ui()

        QTimer.singleShot(0, self._startup_auth_and_load)

    # ------------------------------------------------------------------
    # Window chrome / frameless
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.root_shell = QFrame()
        self.root_shell.setObjectName("rootShell")
        self.root_shell.setMouseTracking(True)
        self.root_shell.setProperty("maximized", "false")
        # Layered translucent windows need this so QSS backgrounds actually paint.
        self.root_shell.setAttribute(Qt.WA_StyledBackground, True)

        shell_layout = QVBoxLayout(self.root_shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.title_bar = TitleBar()
        self.title_bar.setAttribute(Qt.WA_StyledBackground, True)
        shell_layout.addWidget(self.title_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(14, 12, 14, 14)
        body_layout.setSpacing(12)

        self.sidebar = Sidebar()
        body_layout.addWidget(self.sidebar, 0)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        self.conversation = ConversationView()
        self.conversation.setAttribute(Qt.WA_StyledBackground, True)
        self.conversation.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.composer = Composer()
        self.composer.setAttribute(Qt.WA_StyledBackground, True)
        self.composer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.composer.set_tts_speed(self.settings.effective_tts_speed())

        right_layout.addWidget(self.conversation, 1)
        right_layout.addWidget(self.composer, 0)
        body_layout.addWidget(right, 1)

        shell_layout.addWidget(body, 1)

        outer_layout.addWidget(self.root_shell)

        central = QWidget()
        central.setLayout(outer_layout)
        central.setMouseTracking(True)
        self.setCentralWidget(central)

    def _wire_signals(self) -> None:
        # Title bar
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_toggle_requested.connect(self._toggle_maximized)
        self.title_bar.close_requested.connect(self.close)
        self.title_bar.theme_toggle_requested.connect(self._on_theme_toggle)
        self.title_bar.history_requested.connect(self._open_history_dialog)
        self.title_bar.new_session_requested.connect(self._on_new_session)
        self.title_bar.session_selected.connect(self._on_session_selected)

        # Sidebar
        self.sidebar.connect_clicked.connect(self._prompt_for_api_key)
        self.sidebar.manage_role_clicked.connect(self._open_role_manager)

        # Composer
        self.composer.send_requested.connect(self._send_message)
        self.composer.model_changed.connect(self._on_model_changed)
        self.composer.save_default_model_requested.connect(self._on_save_default_model)
        self.composer.save_role_model_requested.connect(self._on_save_model_for_role)
        self.composer.model_filter_changed.connect(self._refresh_composer_models)
        self.composer.pick_image_requested.connect(self._pick_image)
        self.composer.pick_pdf_requested.connect(self._pick_pdf)
        self.composer.clear_attachments_requested.connect(self._clear_attachments)
        self.composer.clear_chat_requested.connect(self._clear_chat)
        self.composer.temperature_changed.connect(self._on_temperature_changed)
        self.composer.tts_speed_changed.connect(self._on_tts_speed_changed)
        self.composer.image_output_toggled.connect(
            lambda checked: self.composer.video_options_btn.setChecked(False) if checked else None
        )
        self.composer.video_output_toggled.connect(
            lambda checked: self.composer.generate_image_btn.setChecked(False) if checked else None
        )

        # Conversation
        self.conversation.feedback_changed.connect(self._on_feedback_changed)
        self.conversation.speak_requested.connect(self._on_speak_requested)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        app.setStyleSheet(build_stylesheet(self.theme_manager.theme))
        is_dark = self.theme_manager.theme == Theme.DARK
        self.title_bar.set_theme_glyph(is_dark)

    def _on_theme_toggle(self) -> None:
        new_theme = self.theme_manager.toggle()
        self.settings.save_theme(new_theme.value)
        self._apply_theme()

    # ------------------------------------------------------------------
    # Frameless window: maximize state, edge resize
    # ------------------------------------------------------------------

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.WindowStateChange:
            maximized = bool(self.windowState() & Qt.WindowMaximized)
            self.title_bar.set_maximized_glyph(maximized)
            self.root_shell.setProperty("maximized", "true" if maximized else "false")
            self.root_shell.style().unpolish(self.root_shell)
            self.root_shell.style().polish(self.root_shell)
            margin = 0 if maximized else 0
            self.centralWidget().layout().setContentsMargins(margin, margin, margin, margin)
        super().changeEvent(event)

    def _edge_for_pos(self, pos: QPoint) -> Qt.Edges:
        edges = Qt.Edges()
        rect = self.rect()
        if pos.x() <= RESIZE_MARGIN:
            edges |= Qt.LeftEdge
        elif pos.x() >= rect.width() - RESIZE_MARGIN:
            edges |= Qt.RightEdge
        if pos.y() <= RESIZE_MARGIN:
            edges |= Qt.TopEdge
        elif pos.y() >= rect.height() - RESIZE_MARGIN:
            edges |= Qt.BottomEdge
        return edges

    def _cursor_for_edge(self, edges: Qt.Edges) -> Qt.CursorShape:
        if edges == (Qt.LeftEdge | Qt.TopEdge) or edges == (Qt.RightEdge | Qt.BottomEdge):
            return Qt.SizeFDiagCursor
        if edges == (Qt.RightEdge | Qt.TopEdge) or edges == (Qt.LeftEdge | Qt.BottomEdge):
            return Qt.SizeBDiagCursor
        if edges & (Qt.LeftEdge | Qt.RightEdge):
            return Qt.SizeHorCursor
        if edges & (Qt.TopEdge | Qt.BottomEdge):
            return Qt.SizeVerCursor
        return Qt.ArrowCursor

    def mouseMoveEvent(self, event) -> None:
        if not self.isMaximized():
            edges = self._edge_for_pos(event.position().toPoint())
            self.setCursor(self._cursor_for_edge(edges))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and not self.isMaximized():
            edges = self._edge_for_pos(event.position().toPoint())
            if edges:
                handle = self.windowHandle()
                if handle is not None:
                    handle.startSystemResize(edges)
                    event.accept()
                    return
        super().mousePressEvent(event)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _initial_session(self) -> Session:
        last_id = self.settings.load_last_session_id()
        if last_id:
            existing = self.session_store.load(last_id)
            if existing is not None:
                return existing
        return self.session_store.create("New Session")

    def _populate_session_dropdown(self) -> None:
        sessions = self.session_store.list()
        self.title_bar.set_sessions(sessions, self.session.id)

    def _assistant_display_for_message(self, message: Dict[str, Any], role: str) -> Optional[str]:
        """Header label for assistant bubbles when replaying saved messages."""
        if role != "assistant":
            return None
        raw = message.get("assistant_label")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return "Assistant"

    def _assistant_display_for_new_reply(self) -> str:
        """Header label for new assistant messages — reflects the active role title."""
        return self._active_role().title.strip() or "Assistant"

    def _render_session_into_ui(self) -> None:
        self.composer.set_temperature(self.session.temperature)
        self._sync_session_prompt_from_role()
        self.sidebar.set_active_role_title(self._active_role().title)
        self._refresh_role_save_button()
        self.sidebar.set_session_total(self.session.total_cost)
        self.sidebar.set_usage(self.session.total_prompt_tokens, self.session.total_completion_tokens)
        total_tokens = self.session.total_prompt_tokens + self.session.total_completion_tokens
        self.composer.set_total_tokens(total_tokens)
        self.conversation.clear()
        for message in self.session.messages:
            self._render_message_into_ui(message, save=False)

    def _render_message_into_ui(self, message: Dict[str, Any], save: bool = False) -> None:
        role = message.get("role", "user")
        message_id = message.get("id") or uuid.uuid4().hex
        message["id"] = message_id
        timestamp = message.get("timestamp")
        content = message.get("content")
        local_image = message.get("_local_image")
        video_paths = message.get("_video_paths") or []
        display_name = self._assistant_display_for_message(message, role)

        if isinstance(content, str):
            bubble = self.conversation.add_text_message(
                role, message_id, content, timestamp, display_name=display_name
            )
        elif isinstance(content, list):
            bubble = self.conversation.add_bubble(role, message_id, timestamp, display_name=display_name)
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    bubble.add_text(str(item.get("text") or ""))
                elif item.get("type") == "image_url":
                    if not local_image:
                        bubble.add_text("(image attached)")
                elif item.get("type") == "file":
                    file_info = item.get("file") or {}
                    bubble.add_text(f"Attached file: {file_info.get('filename', 'document')}")
        else:
            bubble = self.conversation.add_text_message(
                role, message_id, "", timestamp, display_name=display_name
            )

        if local_image:
            path = Path(str(local_image))
            if path.exists():
                self._add_image_to_bubble(bubble, path)

        for video_path_str in video_paths:
            path = Path(str(video_path_str))
            if path.exists():
                self.conversation.add_video(
                    role, message_id, path, message_id[:8], display_name=display_name
                )

        bubble.set_feedback(self.session.feedback.get(message_id))
        if save:
            self._schedule_save()

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _flush_session(self) -> None:
        try:
            self.session_store.save(self.session)
            self.settings.save_last_session_id(self.session.id)
        except Exception:
            pass
        self._populate_session_dropdown()

    def _on_new_session(self) -> None:
        self.session = self.session_store.create("New Session")
        self.pending_attachments = []
        self._render_session_into_ui()
        self._sync_composer_model_selection()
        self._populate_session_dropdown()
        self.settings.save_last_session_id(self.session.id)

    def _on_session_selected(self, session_id: str) -> None:
        if session_id == self.session.id:
            return
        existing = self.session_store.load(session_id)
        if existing is None:
            return
        self.session = existing
        self.pending_attachments = []
        self._render_session_into_ui()
        self._sync_composer_model_selection()
        self.settings.save_last_session_id(self.session.id)

    def _open_history_dialog(self) -> None:
        dialog = HistoryDialog(self.session_store, self)
        dialog.session_opened.connect(self._on_session_selected)
        dialog.exec()
        self._populate_session_dropdown()

    def _clear_chat(self) -> None:
        confirm = QMessageBox.question(
            self,
            "New chat",
            "Start a new chat session? Your current conversation stays in history.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self._flush_session()
        self._on_new_session()

    def _open_role_manager(self) -> None:
        dialog = RoleManagerDialog(
            self.role_store,
            self.session.role_id,
            self,
            models=self.models,
        )
        dialog.role_activated.connect(self._activate_role)
        dialog.exec()
        # An edit may have changed the active role's prompt or preferred model
        # without a re-activate; also a delete may have nudged us back to
        # Default. Re-sync prompt + composer model either way.
        self._sync_session_prompt_from_role()
        self.sidebar.set_active_role_title(self._active_role().title)
        self._sync_composer_model_selection()
        self._refresh_role_save_button()
        self._schedule_save()

    def _activate_role(self, role_id: str) -> None:
        self.session.role_id = role_id
        # When the user activates a different role, clear the session-level
        # model pin so the role's preferred model wins over a stale per-session
        # choice from the previous role.
        self.session.model_id = None
        self._sync_session_prompt_from_role()
        self.sidebar.set_active_role_title(self._active_role().title)
        self._sync_composer_model_selection()
        self._refresh_role_save_button()
        self._schedule_save()

    def _active_role(self) -> Role:
        role = self.role_store.get(self.session.role_id)
        if role is None:
            self.session.role_id = DEFAULT_ROLE_ID
            return self.role_store.ensure_default()
        return role

    def _sync_session_prompt_from_role(self) -> None:
        self.session.system_prompt = self._active_role().prompt or DEFAULT_SYSTEM_PROMPT

    def _on_temperature_changed(self, value: float) -> None:
        self.session.temperature = float(value)
        self._schedule_save()

    def _on_tts_speed_changed(self, value: float) -> None:
        # Speech speed is a global preference (applies to all assistant
        # bubbles), not per-session — persist it via the settings store.
        self.settings.save_tts_speed(float(value))

    def _on_feedback_changed(self, message_id: str, value: str) -> None:
        if not message_id:
            return
        if value:
            self.session.feedback[message_id] = value
        else:
            self.session.feedback.pop(message_id, None)
        self._schedule_save()

    # ------------------------------------------------------------------
    # Text-to-speech (OpenRouter)
    # ------------------------------------------------------------------

    def _remove_tts_temp_file(self) -> None:
        path = self._tts_temp_path
        self._tts_temp_path = None
        if path is None:
            return
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    def _on_speak_requested(self, bubble: MessageBubble) -> None:
        if not isValid(bubble):
            return

        if (
            self._tts_active_bubble is bubble
            and self._tts_player.playbackState() == QMediaPlayer.PlayingState
        ):
            self._tts_player.stop()
            self._tts_active_bubble = None
            bubble.set_speaking(False)
            self._remove_tts_temp_file()
            return

        if self._tts_pending_bubble is bubble:
            self._tts_gen += 1
            self._tts_pending_bubble = None
            bubble.set_speaking(False)
            return

        if self._tts_active_bubble is not None and self._tts_active_bubble is not bubble:
            prev = self._tts_active_bubble
            self._tts_active_bubble = None
            if isValid(prev):
                prev.set_speaking(False)
            self._remove_tts_temp_file()
        if self._tts_player.playbackState() == QMediaPlayer.PlayingState:
            self._tts_player.stop()

        if self._tts_pending_bubble is not None and self._tts_pending_bubble is not bubble:
            prev_p = self._tts_pending_bubble
            self._tts_pending_bubble = None
            self._tts_gen += 1
            if isValid(prev_p):
                prev_p.set_speaking(False)

        if not self.client:
            self.sidebar.set_status("Text-to-speech", "Connect with an API key first.", level="warn")
            return

        text = bubble.text_for_tts().strip()
        if not text:
            self.sidebar.set_status("Text-to-speech", "No text to read in this message.", level="warn")
            return

        self._tts_gen += 1
        gen = self._tts_gen
        self._tts_pending_bubble = bubble
        bubble.set_speaking(True)

        worker = TtsWorker(
            self.client,
            text,
            self.settings.effective_tts_model_id(),
            self.settings.effective_tts_voice(),
            bubble,
            gen,
            speed=self.settings.effective_tts_speed(),
        )
        worker.signals.ready.connect(self._on_tts_ready)
        worker.signals.cost_resolved.connect(self._on_tts_cost_resolved)
        worker.signals.error.connect(self._on_tts_error)
        self.thread_pool.start(worker)

    def _on_tts_ready(self, data: bytes, bubble: MessageBubble, gen: int) -> None:
        if gen != self._tts_gen or self._tts_pending_bubble is not bubble:
            return
        if not isValid(bubble):
            self._tts_pending_bubble = None
            return
        self._tts_pending_bubble = None
        self._remove_tts_temp_file()
        try:
            fd, raw_path = tempfile.mkstemp(suffix=".mp3", prefix="md_tts_")
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            path = Path(raw_path)
        except OSError as exc:
            bubble.set_speaking(False)
            self.sidebar.set_status("TTS failed", str(exc), level="warn")
            return
        self._tts_temp_path = path
        self._tts_active_bubble = bubble
        self._tts_player.setSource(QUrl.fromLocalFile(str(path)))
        self._tts_player.play()

    def _on_tts_cost_resolved(self, _bubble: MessageBubble, gen: int, cost: float) -> None:
        # Late-arriving cost: still record it even if playback has ended or the
        # user already started another bubble, as long as it belongs to the
        # current TTS generation. Stale generations are ignored.
        if gen != self._tts_gen or cost <= 0:
            return
        self._record_usage(0, 0, cost)
        self._schedule_save()
        self._refresh_balance_async()

    def _on_tts_error(self, err: str, bubble: MessageBubble, gen: int) -> None:
        if gen != self._tts_gen or self._tts_pending_bubble is not bubble:
            return
        self._tts_pending_bubble = None
        if isValid(bubble):
            bubble.set_speaking(False)
        message = self._pretty_error(err)
        self.sidebar.set_status("TTS failed", message, level="error")

    def _on_tts_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status not in (
            QMediaPlayer.MediaStatus.EndOfMedia,
            QMediaPlayer.MediaStatus.InvalidMedia,
        ):
            return
        bubble = self._tts_active_bubble
        self._tts_active_bubble = None
        if bubble is not None and isValid(bubble):
            bubble.set_speaking(False)
        self._remove_tts_temp_file()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _startup_auth_and_load(self) -> None:
        saved_key = self.settings.load_api_key()
        if saved_key:
            self.client = OpenRouterClient(saved_key)
            self._set_auth_busy(True, "Validating saved API key...")
            self._run_worker(
                self.client.validate_key,
                on_result=self._on_key_validated,
                on_error=self._handle_key_error,
            )
            return
        self._prompt_for_api_key()

    def _prompt_for_api_key(self) -> None:
        dialog = ApiKeyDialog(self)
        if dialog.exec() != QDialog.Accepted:
            self.sidebar.set_status("Not connected", "API key required", level="warn")
            self.sidebar.set_connection(False, "API key required")
            return
        api_key = dialog.get_key()
        if not api_key:
            QMessageBox.warning(self, "Missing key", "Please enter a valid API key.")
            self._prompt_for_api_key()
            return
        self.client = OpenRouterClient(api_key)
        self._set_auth_busy(True, "Validating API key...")
        self._run_worker(
            self.client.validate_key,
            on_result=lambda result: self._on_new_key_validated(api_key, result),
            on_error=self._handle_key_error,
        )

    def _on_new_key_validated(self, api_key: str, key_info: Dict[str, Any]) -> None:
        self.settings.save_api_key(api_key)
        self._on_key_validated(key_info)

    def _on_key_validated(self, key_info: Dict[str, Any]) -> None:
        self._set_auth_busy(False)
        self.title_bar.set_connected(True, "Connected")
        self.sidebar.set_connection(True, "Connected")
        self.sidebar.set_status("Connected", "Loading models...", level="info")
        self._render_balance(key_info)
        self._run_worker(
            self.client.get_models if self.client else (lambda: []),
            on_result=self._on_models_loaded,
            on_error=self._handle_api_error,
        )

    def _handle_key_error(self, error_text: str) -> None:
        message = self._pretty_error(error_text)
        self._set_auth_busy(False)
        self.title_bar.set_connected(False, "Disconnected")
        self.sidebar.set_connection(False, "Validation failed")
        self.sidebar.set_status("Key validation failed", message, level="error")
        self.settings.clear_api_key()
        QMessageBox.critical(self, "Key validation failed", message)
        self._prompt_for_api_key()

    def _set_auth_busy(self, busy: bool, status: Optional[str] = None) -> None:
        self.validating_key = busy
        self.sidebar.connect_btn.setEnabled(not busy)
        if status:
            self.sidebar.set_status(status, "", level="info")
        if busy:
            QTimer.singleShot(35_000, self._handle_validation_timeout)

    def _handle_validation_timeout(self) -> None:
        if not self.validating_key:
            return
        self._set_auth_busy(False)
        self.sidebar.set_status(
            "Validation timed out",
            "Check your network and try Connect API Key again.",
            level="error",
        )
        self.title_bar.set_connected(False, "Timed out")

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    def _resolve_preferred_model_id(self) -> Optional[str]:
        """Pick the model id for the composer.

        With messages in the session, the per-session model wins if it is still
        in the catalog, then role preference, saved global default, built-in
        ``openrouter/free``, then the first API model.

        With an **empty** session, role and global defaults (including the
        built-in free router) are applied **before** the stored session model so
        a stale combo selection does not override the default OpenRouter free
        model on startup.
        """
        if not self.models:
            return None
        valid = {m.model_id for m in self.models}

        # First model sync after launch: prefer OpenRouter Free Models Router
        # if available so the app always opens on the free router regardless of
        # what the resumed session / active role had pinned previously.
        if self._launch_force_free_router and DEFAULT_MODEL_ID in valid:
            return DEFAULT_MODEL_ID

        def from_role_and_global() -> Optional[str]:
            role = self.role_store.get(self.session.role_id)
            if role is not None and role.model_id and role.model_id in valid:
                return role.model_id
            preferred = self.settings.effective_default_model_id()
            if preferred in valid:
                return preferred
            if DEFAULT_MODEL_ID in valid:
                return DEFAULT_MODEL_ID
            return None

        if self.session.messages:
            if self.session.model_id and self.session.model_id in valid:
                return self.session.model_id
            resolved = from_role_and_global()
            if resolved is not None:
                return resolved
        else:
            resolved = from_role_and_global()
            if resolved is not None:
                return resolved
            if self.session.model_id and self.session.model_id in valid:
                return self.session.model_id

        return self.models[0].model_id

    def _sync_composer_model_selection(self) -> None:
        """Apply session + default-model preference to the model combo (clears search if the pick is hidden)."""
        if not self.models:
            return
        resolved = self._resolve_preferred_model_id()
        if not resolved:
            return
        if self.composer.model_combo.findData(resolved) < 0:
            self.composer.search_edit.blockSignals(True)
            self.composer.search_edit.clear()
            self.composer.search_edit.blockSignals(False)
            self.composer.refresh_combo()
        if self.composer.model_combo.findData(resolved) < 0:
            if self.composer.model_combo.count() == 0:
                return
            data = self.composer.model_combo.itemData(0)
            resolved = str(data) if data else resolved
        self.composer.select_model_by_id(resolved)
        # Once the launch-time selection has happened, future syncs (role
        # change, session switch, etc.) follow the normal preference order.
        if self._launch_force_free_router:
            self._launch_force_free_router = False
            # Reflect the launch override in the active session so the saved
            # session opens on the free router on subsequent sends.
            if self.session.model_id != resolved:
                self.session.model_id = resolved
                self._schedule_save()

    def _on_save_default_model(self) -> None:
        model_id = self.composer.selected_model_id()
        if not model_id:
            QMessageBox.information(self, "Default model", "Select a model in the list first.")
            return
        self.settings.save_default_model_id(model_id)
        label = self.composer.model_combo.currentText()
        QMessageBox.information(
            self,
            "Default model saved",
            f"New sessions and chats without a saved model will start with:\n{label}",
        )

    def _on_save_model_for_role(self) -> None:
        """Pin the currently selected model to the active role so future
        sessions opened with that role start there.
        """
        model_id = self.composer.selected_model_id()
        if not model_id:
            QMessageBox.information(self, "Save for role", "Select a model in the list first.")
            return
        role = self._active_role()
        updated = self.role_store.set_model_id(role.id, model_id)
        if updated is None:
            return
        # Clear any per-session pin so the freshly saved role default takes
        # effect in this session too.
        self.session.model_id = None
        self._schedule_save()
        label = self.composer.model_combo.currentText()
        QMessageBox.information(
            self,
            "Model saved for role",
            f"The role '{role.title}' will now open with:\n{label}",
        )

    def _refresh_role_save_button(self) -> None:
        role = self._active_role()
        is_default = role.id == DEFAULT_ROLE_ID
        title = None if is_default else role.title
        self.composer.update_role_save_target(title)

    def _on_models_loaded(self, models: List[ModelInfo]) -> None:
        self.models = models
        self.composer.set_models(models)
        self._sync_composer_model_selection()
        self._refresh_role_save_button()
        self.sidebar.set_status("Ready", f"{len(models)} models loaded", level="ok")

    def _refresh_composer_models(self) -> None:
        self.composer.refresh_combo()

    def _on_model_changed(self, model_id: str) -> None:
        model = self.composer.get_model(model_id) if model_id else None
        self.session.model_id = model_id or None
        self.composer.update_for_model(model)
        self.sidebar.update_capabilities(model)
        self._refresh_attachment_compatibility()
        self._schedule_save()

    def _active_model(self) -> Optional[ModelInfo]:
        """Resolve the currently active model from the composer (the source of
        truth) and keep `session.model_id` in sync. Falls back to the session's
        stored id if the composer has no selection (e.g. before models load).
        """
        selected_id = self.composer.selected_model_id()
        if selected_id:
            if self.session.model_id != selected_id:
                self.session.model_id = selected_id
            return self.composer.get_model(selected_id)
        return self.composer.get_model(self.session.model_id)

    def _refresh_attachment_compatibility(self) -> None:
        model = self._active_model()
        if model is None:
            return
        kept: List[PendingAttachment] = []
        for att in self.pending_attachments:
            if att.kind == "image" and not model.supports_image_input:
                continue
            if att.kind == "pdf" and not model.supports_pdf_input:
                continue
            kept.append(att)
        if len(kept) != len(self.pending_attachments):
            self.pending_attachments = kept

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------

    def _pick_image(self) -> None:
        model = self._active_model()
        if model is None or not model.supports_image_input:
            QMessageBox.information(
                self,
                "Picture upload unavailable",
                "Choose a model that accepts image input.",
            )
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select image", "", "Images (*.png *.jpg *.jpeg *.webp *.gif)"
        )
        if path:
            self._add_attachment(path)

    def _pick_pdf(self) -> None:
        model = self._active_model()
        if model is None or not model.supports_pdf_input:
            QMessageBox.information(
                self,
                "PDF upload unavailable",
                "Choose a model that accepts file/PDF input.",
            )
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select PDF", "", "PDF (*.pdf)")
        if path:
            self._add_attachment(path)

    def _add_attachment(self, path: str) -> bool:
        model = self._active_model()
        file_path = Path(path)
        suffix = file_path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            if model is None or not model.supports_image_input:
                self.sidebar.set_status(
                    "Picture not attached", "Choose a model with image input.", level="warn"
                )
                return False
            self.pending_attachments.append(PendingAttachment(path=str(file_path), kind="image"))
            self.sidebar.set_status(
                "Attachment added", f"{len(self.pending_attachments)} pending", level="info"
            )
            return True
        if suffix == ".pdf":
            if model is None or not model.supports_pdf_input:
                self.sidebar.set_status(
                    "PDF not attached", "Choose a model with file input.", level="warn"
                )
                return False
            self.pending_attachments.append(PendingAttachment(path=str(file_path), kind="pdf"))
            self.sidebar.set_status(
                "Attachment added", f"{len(self.pending_attachments)} pending", level="info"
            )
            return True
        self.sidebar.set_status("Unsupported file type", file_path.name, level="warn")
        return False

    def _clear_attachments(self) -> None:
        self.pending_attachments = []
        self.sidebar.set_status("Attachments cleared", "", level="muted")

    # ------------------------------------------------------------------
    # Drag & drop
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        if self._has_supported_drop(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        # Qt warns about "drag in possibly invalid state" when a drop-accepting
        # widget omits dragMoveEvent. Mirror dragEnterEvent's decision.
        if self._has_supported_drop(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def _has_supported_drop(self, event) -> bool:
        mime = event.mimeData()
        if not mime.hasUrls():
            return False
        for url in mime.urls():
            local = url.toLocalFile()
            if local and self._is_supported_drop_path(local):
                return True
        return False

    def dropEvent(self, event) -> None:
        added = False
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and self._add_attachment(path):
                added = True
        if added:
            event.acceptProposedAction()
        else:
            event.ignore()

    @staticmethod
    def _is_supported_drop_path(path: str) -> bool:
        suffix = Path(path).suffix.lower()
        return suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf"}

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def _send_message(self) -> None:
        if not self.client:
            QMessageBox.warning(self, "Not connected", "Client is not initialized yet.")
            return
        model = self._active_model()
        if model is None:
            QMessageBox.warning(self, "No model", "Please choose a model.")
            return

        text = self.composer.get_input_text()
        if not text and not self.pending_attachments:
            return
        if self.composer.is_video_output_requested() and not text:
            QMessageBox.information(self, "Prompt required", "Enter a text prompt to generate a video.")
            return

        content_parts: List[Dict[str, Any]] = []
        video_frame_images: List[Dict[str, Any]] = []
        if text:
            content_parts.append({"type": "text", "text": text})
        for att in self.pending_attachments:
            filename, data_url = encode_file_as_data_url(att.path)
            if att.kind == "image":
                content_parts.append({"type": "image_url", "image_url": {"url": data_url}})
                video_frame_images.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                        "frame_type": "first_frame",
                    }
                )
            elif att.kind == "pdf":
                content_parts.append(
                    {
                        "type": "file",
                        "file": {"filename": filename, "file_data": data_url},
                    }
                )

        message_id = uuid.uuid4().hex
        if len(content_parts) == 1 and content_parts[0].get("type") == "text":
            user_payload: Dict[str, Any] = {
                "id": message_id,
                "role": "user",
                "content": content_parts[0]["text"],
                "timestamp": time.time(),
            }
        else:
            user_payload = {
                "id": message_id,
                "role": "user",
                "content": content_parts,
                "timestamp": time.time(),
            }

        self.session.messages.append(user_payload)

        is_first_turn = len(self.session.messages) == 1
        is_plain_text_only = isinstance(user_payload.get("content"), str)
        use_ai_session_title = (
            is_first_turn
            and is_plain_text_only
            and not self.composer.is_video_output_requested()
            and not self.composer.is_image_output_requested()
        )
        if use_ai_session_title:
            self.session.title = "New Session"
        else:
            self.session.title = self.session.derive_title()

        self._render_message_into_ui(user_payload)
        sent_attachments = list(self.pending_attachments)
        for att in sent_attachments:
            if att.kind == "image":
                self._append_local_image_to_session("user", Path(att.path))
            else:
                self._append_text_to_session("system", f"Attached file: {Path(att.path).name}")
        self.composer.clear_input()
        self.pending_attachments = []
        self._schedule_save()

        self.composer.set_send_enabled(False)
        request_messages = build_request_messages(
            self._messages_for_request(),
            self.session.system_prompt,
            extra_system=FIRST_TURN_SESSION_TITLE_EXTRA_SYSTEM if use_ai_session_title else "",
        )
        temperature = self.session.temperature if model.supports_temperature else None

        if self.composer.is_video_output_requested():
            options = self.composer.video_options()
            self.sidebar.set_status(
                "Generating video...",
                "This can take a few minutes.",
                level="info",
            )
            self._run_video_worker(
                model,
                text,
                video_frame_images or None,
                options,
            )
            self.composer.reset_output_toggles()
            return

        if self.composer.is_image_output_requested():
            self.sidebar.set_status("Generating image...", "Waiting for model response.", level="info")
            max_tokens = self.settings.effective_max_output_tokens() if model.supports_max_tokens else None
            self._run_worker(
                self.client.generate_image,
                model.model_id,
                request_messages,
                model.supports_image_output,
                temperature,
                max_tokens,
                on_result=lambda data: self._on_image_generation_response(model, data),
                on_error=self._on_chat_error,
            )
            self.composer.reset_output_toggles()
            return

        self.sidebar.set_status("Streaming response...", "Receiving tokens.", level="info")
        self._stream_first_turn_ai_title = use_ai_session_title
        self._begin_streaming_response(model)
        self._run_stream_worker(model, request_messages, None, temperature)

    def _messages_for_request(self) -> List[Dict[str, Any]]:
        cleaned: List[Dict[str, Any]] = []
        for msg in self.session.messages:
            if msg.get("role") == "system":
                continue
            cleaned.append({k: v for k, v in msg.items() if k in {"role", "content"}})
        return cleaned

    def _append_text_to_session(self, role: str, text: str) -> None:
        message = {
            "id": uuid.uuid4().hex,
            "role": role,
            "content": text,
            "timestamp": time.time(),
        }
        self.session.messages.append(message)
        self._render_message_into_ui(message)
        self._schedule_save()

    def _append_local_image_to_session(self, role: str, image_path: Path) -> None:
        message_id = uuid.uuid4().hex
        message = {
            "id": message_id,
            "role": role,
            "content": [
                {"type": "image_url", "image_url": {"url": f"file://{image_path}"}},
            ],
            "timestamp": time.time(),
            "_local_image": str(image_path),
        }
        self.session.messages.append(message)
        self.conversation.add_image(role, message_id, image_path, label="picture")
        self._schedule_save()

    # ------------------------------------------------------------------
    # Response handlers
    # ------------------------------------------------------------------

    def _begin_streaming_response(self, model: ModelInfo) -> None:
        self.stream_model = model
        self.stream_text = ""
        self.stream_usage = {}
        self.stream_images = []
        self.stream_started_at = time.monotonic()
        if self._stream_first_turn_ai_title:
            self._stream_title_parser = StreamingSessionTitleParser()
        else:
            self._stream_title_parser = None
        message_id = uuid.uuid4().hex
        self._stream_message_id = message_id
        self._stream_assistant_label = self._assistant_display_for_new_reply()
        self.stream_bubble = self.conversation.add_bubble(
            "assistant",
            message_id,
            display_name=self._stream_assistant_label,
        )
        self.stream_edit = self.stream_bubble.add_streaming_editor()
        self.stream_bubble.set_copy_provider(
            lambda b=self.stream_bubble: ConversationView._collect_text(b)
        )
        self.stream_bubble.set_speak_enabled(False)
        self._stream_progress_last_ui = time.monotonic()

    def _on_stream_event(self, event: Dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "text":
            content = str(event.get("content", ""))
            self.stream_text += content
            if self._stream_title_parser is not None:
                visible = self._stream_title_parser.feed(content)
                if visible and self.stream_edit is not None:
                    self.stream_edit.insertPlainText(visible)
            elif self.stream_edit is not None:
                self.stream_edit.insertPlainText(content)
            self.conversation.schedule_scroll_to_bottom()
            now = time.monotonic()
            if now - self._stream_progress_last_ui >= 0.25:
                self._stream_progress_last_ui = now
                self._update_stream_progress()
        elif event_type == "usage":
            usage = event.get("usage")
            if isinstance(usage, dict):
                self.stream_usage = usage
        elif event_type == "images":
            for image in event.get("images") or []:
                image_url = image.get("image_url") or image.get("imageUrl") or {}
                if isinstance(image_url, dict) and image_url.get("url"):
                    self.stream_images.append(str(image_url["url"]))

    def _on_stream_finished(self, model: ModelInfo) -> None:
        self.composer.set_send_enabled(True)
        used_title_parse = self._stream_first_turn_ai_title
        self._stream_first_turn_ai_title = False
        self._stream_title_parser = None

        if used_title_parse:
            t, ans = split_first_turn_response(self.stream_text)
            if t:
                self.session.title = t
            else:
                self.session.title = self.session.derive_title()
            assistant = ans.strip() if ans.strip() else "(empty response)"
            if self.stream_edit is not None:
                self.stream_edit.setPlainText(assistant)
            self._populate_session_dropdown()
        else:
            assistant = self.stream_text.strip() or "(empty response)"
            if self.stream_edit is not None:
                self.stream_edit.setPlainText(assistant)

        message = {
            "id": self._stream_message_id,
            "role": "assistant",
            "content": assistant,
            "timestamp": time.time(),
            "assistant_label": self._stream_assistant_label or self._assistant_display_for_new_reply(),
        }
        self.session.messages.append(message)

        for image_url in self.stream_images:
            local_path = self._materialize_image_url(image_url)
            if local_path is not None:
                if self.stream_bubble is not None:
                    self._add_image_to_bubble(self.stream_bubble, local_path)

        self.conversation.scroll_to_bottom_settled()

        prompt_tokens = int(self.stream_usage.get("prompt_tokens") or 0)
        completion_tokens = int(self.stream_usage.get("completion_tokens") or 0)
        cost = calculate_interaction_cost(prompt_tokens, completion_tokens, model.pricing)
        self._record_usage(prompt_tokens, completion_tokens, cost)
        self.sidebar.set_status("Response received", "All systems operational", level="ok")

        if self.stream_bubble is not None and isValid(self.stream_bubble):
            self.stream_bubble.set_speak_enabled(True)

        self.stream_text = ""
        self.stream_started_at = 0.0
        self.stream_edit = None
        self.stream_bubble = None
        self.stream_model = None
        self._stream_assistant_label = ""

        self._refresh_balance_async()
        self._schedule_save()

    def _on_image_generation_response(self, model: ModelInfo, response: Dict[str, Any]) -> None:
        self.composer.set_send_enabled(True)
        image_urls = extract_image_urls(response)
        message = response.get("choices", [{}])[0].get("message", {})
        assistant = self._message_text(message)

        message_id = uuid.uuid4().hex
        assistant_header = self._assistant_display_for_new_reply()
        bubble = self.conversation.add_bubble(
            "assistant", message_id, display_name=assistant_header
        )
        if assistant:
            bubble.add_text(assistant)

        if image_urls:
            for image_url in image_urls:
                local_path = self._materialize_image_url(image_url)
                if local_path is not None:
                    self._add_image_to_bubble(bubble, local_path)
            self.sidebar.set_status("Image generated", "All systems operational", level="ok")
        else:
            mode = "native image output" if model.supports_image_output else "OpenRouter image-generation tool"
            bubble.add_text(
                f"No image was returned. Tried {mode}; try a more direct prompt like 'Generate an image of ...'."
            )
            self.sidebar.set_status("No image returned", "Try a more direct prompt.", level="warn")

        if assistant or image_urls:
            self.session.messages.append(
                {
                    "id": message_id,
                    "role": "assistant",
                    "content": assistant or "(image response)",
                    "timestamp": time.time(),
                    "assistant_label": assistant_header,
                }
            )

        usage = response.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        cost = calculate_interaction_cost(prompt_tokens, completion_tokens, model.pricing)
        self._record_usage(prompt_tokens, completion_tokens, cost)
        self._refresh_balance_async()
        self._schedule_save()

    def _on_video_generation_response(self, model: ModelInfo, response: Dict[str, Any]) -> None:
        self.composer.set_send_enabled(True)
        saved_paths = [Path(path) for path in response.get("saved_paths") or []]
        job_id = str(response.get("id") or "unknown")

        message_id = uuid.uuid4().hex
        assistant_header = self._assistant_display_for_new_reply()
        if saved_paths:
            for video_path in saved_paths:
                self.conversation.add_video(
                    "assistant", message_id, video_path, job_id, display_name=assistant_header
                )
            self.session.messages.append(
                {
                    "id": message_id,
                    "role": "assistant",
                    "content": f"Generated video: {job_id}",
                    "timestamp": time.time(),
                    "_video_paths": [str(p) for p in saved_paths],
                    "assistant_label": assistant_header,
                }
            )
            self.sidebar.set_status("Video generated", "All systems operational", level="ok")
        else:
            bubble = self.conversation.add_bubble("system", message_id)
            bubble.add_text("Video generation finished, but no downloaded video file was returned.")
            self.sidebar.set_status("No video returned", "Generation finished without output.", level="warn")

        usage = response.get("usage") or {}
        cost = float(usage.get("cost") or 0)
        self._record_usage(0, 0, cost)
        self._refresh_balance_async()
        self._schedule_save()

    def _add_image_to_bubble(self, bubble: MessageBubble, image_path: Path) -> None:
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QLabel

        label = QLabel(f"Image: {image_path.name}")
        bubble.add_widget(label)
        if not image_path.exists():
            return
        image_label = QLabel()
        image_label.setMinimumSize(QSize(120, 80))
        pixmap = QPixmap(str(image_path))
        if not pixmap.isNull():
            image_label.setPixmap(pixmap.scaledToWidth(384, Qt.SmoothTransformation))
        else:
            image_label.setText(str(image_path))
        bubble.add_widget(image_label)

    def _record_usage(self, prompt_tokens: int, completion_tokens: int, cost: float) -> None:
        self.session.total_prompt_tokens += prompt_tokens
        self.session.total_completion_tokens += completion_tokens
        self.session.total_cost += cost
        self.sidebar.set_session_total(self.session.total_cost)
        self.sidebar.set_last_interaction(cost)
        self.sidebar.set_usage(
            self.session.total_prompt_tokens, self.session.total_completion_tokens
        )
        self.composer.set_total_tokens(
            self.session.total_prompt_tokens + self.session.total_completion_tokens
        )

    def _update_stream_progress(self) -> None:
        elapsed = int(time.monotonic() - self.stream_started_at) if self.stream_started_at else 0
        self.sidebar.set_status(
            "Streaming response...",
            f"{len(self.stream_text):,} chars | {elapsed}s elapsed",
            level="info",
        )

    def _on_video_progress(self, progress: Dict[str, Any]) -> None:
        status = str(progress.get("status") or "generating").replace("_", " ")
        elapsed = int(progress.get("elapsed_seconds") or 0)
        percent = progress.get("progress")
        percent_text = ""
        if isinstance(percent, (int, float)):
            value = percent * 100 if percent <= 1 else percent
            percent_text = f" | {value:.0f}%"
        self.sidebar.set_status(
            f"Video {status}",
            f"{elapsed}s elapsed{percent_text}",
            level="info",
        )

    def _on_chat_error(self, error_text: str) -> None:
        self.composer.set_send_enabled(True)
        message = self._pretty_error(error_text)
        failed_bubble = self.stream_bubble
        if self.stream_edit is not None and not self.stream_text.strip():
            self.stream_edit.setPlainText("(request failed)")
        self.stream_text = ""
        self.stream_started_at = 0.0
        self.stream_edit = None
        self.stream_bubble = None
        self.stream_model = None
        self._stream_assistant_label = ""
        self._stream_title_parser = None
        self._stream_first_turn_ai_title = False
        if failed_bubble is not None and isValid(failed_bubble):
            failed_bubble.set_speak_enabled(True)
        self.sidebar.set_status("Request failed", message, level="error")
        bubble = self.conversation.add_bubble("system", uuid.uuid4().hex)
        bubble.add_text(f"Error: {message}")
        QMessageBox.critical(self, "Request failed", message)

    def _refresh_balance_async(self) -> None:
        if not self.client:
            return
        self._run_worker(
            self.client.get_key_info,
            on_result=self._render_balance,
            on_error=lambda err: self.sidebar.set_status(
                "Balance refresh failed",
                self._pretty_error(err),
                level="warn",
            ),
        )

    def _render_balance(self, key_data: Dict[str, Any]) -> None:
        remaining = key_data.get("limit_remaining")
        if remaining is None:
            text = "Unlimited"
        else:
            text = f"${float(remaining):.4f}"
        self.sidebar.set_balance(text)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _materialize_image_url(self, image_url: str) -> Optional[Path]:
        if not image_url.startswith("data:image/"):
            return None
        header, _, payload = image_url.partition(",")
        if not payload:
            return None
        mime = header.split(";", 1)[0].replace("data:", "")
        ext = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }.get(mime, ".png")
        count = len(list(self.generated_image_dir.glob("modeldocker_image_*"))) + 1
        file_path = self.generated_image_dir / f"modeldocker_image_{count}{ext}"
        try:
            file_path.write_bytes(base64.b64decode(payload))
        except (OSError, ValueError):
            return None
        return file_path

    def _message_text(self, message: Dict[str, Any]) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            return "\n".join(part for part in parts if part).strip()
        return ""

    def _run_worker(
        self,
        fn: Callable[..., Any],
        *args: Any,
        on_result: Callable[[Any], None],
        on_error: Callable[[str], None],
    ) -> None:
        worker = Worker(fn, *args)
        self.active_workers.append(worker)

        def handle_result(result: Any, completed_worker: Worker = worker) -> None:
            self._release_worker(completed_worker)
            on_result(result)

        def handle_error(error_text: str, completed_worker: Worker = worker) -> None:
            self._release_worker(completed_worker)
            on_error(error_text)

        worker.signals.result.connect(handle_result)
        worker.signals.error.connect(handle_error)
        self.thread_pool.start(worker)

    def _run_stream_worker(
        self,
        model: ModelInfo,
        messages: List[Dict[str, Any]],
        modalities: Optional[List[str]],
        temperature: Optional[float],
    ) -> None:
        if not self.client:
            return
        max_tokens = self.settings.effective_max_output_tokens() if model.supports_max_tokens else None
        worker = StreamWorker(
            self.client,
            model.model_id,
            messages,
            modalities,
            temperature,
            max_tokens=max_tokens,
        )
        self.active_workers.append(worker)

        def handle_finished(completed_worker: StreamWorker = worker) -> None:
            self._release_worker(completed_worker)
            self._on_stream_finished(model)

        def handle_error(error_text: str, completed_worker: StreamWorker = worker) -> None:
            self._release_worker(completed_worker)
            self._on_chat_error(error_text)

        worker.signals.event.connect(self._on_stream_event)
        worker.signals.finished.connect(handle_finished)
        worker.signals.error.connect(handle_error)
        self.thread_pool.start(worker)

    def _run_video_worker(
        self,
        model: ModelInfo,
        prompt: str,
        frame_images: Optional[List[Dict[str, Any]]],
        options: Dict[str, Any],
    ) -> None:
        if not self.client:
            return
        worker = VideoWorker(
            self.client,
            model.model_id,
            prompt,
            str(self.generated_video_dir),
            int(options.get("duration", 8)),
            str(options.get("resolution", "720p")),
            str(options.get("aspect_ratio", "16:9")),
            bool(options.get("audio", True)),
            frame_images,
        )
        self.active_workers.append(worker)

        def handle_result(result: Any, completed_worker: VideoWorker = worker) -> None:
            self._release_worker(completed_worker)
            self._on_video_generation_response(model, result)

        def handle_error(error_text: str, completed_worker: VideoWorker = worker) -> None:
            self._release_worker(completed_worker)
            self._on_chat_error(error_text)

        worker.signals.progress.connect(self._on_video_progress)
        worker.signals.result.connect(handle_result)
        worker.signals.error.connect(handle_error)
        self.thread_pool.start(worker)

    def _release_worker(self, worker: Any) -> None:
        if worker in self.active_workers:
            self.active_workers.remove(worker)

    def _handle_api_error(self, error_text: str) -> None:
        self.sidebar.set_status("API error", self._pretty_error(error_text), level="error")
        QMessageBox.critical(self, "OpenRouter error", self._pretty_error(error_text))

    @staticmethod
    def _pretty_error(error_text: str) -> str:
        if "OpenRouterError" in error_text:
            lines = [line.strip() for line in error_text.splitlines() if line.strip()]
            message = lines[-1]
        else:
            message = error_text.splitlines()[-1] if error_text.strip() else "Unknown error"
        if "requires more credits" in message or "fewer max_tokens" in message:
            message = (
                f"{message}\n\nHint: lower the per-reply output cap. The default is "
                "4096 tokens; you can change it by setting 'max_output_tokens' in "
                "~/.modeldocker/prefs.json."
            )
        elif "internal server error" in message.lower():
            message = (
                f"{message}\n\nOpenRouter accepted the request but the selected model/provider failed. "
                "Try a different model, or retry this one after a moment."
            )
        return message

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._save_timer.stop()
        self._flush_session()
        if self._tts_player.playbackState() == QMediaPlayer.PlayingState:
            self._tts_player.stop()
        self._remove_tts_temp_file()
        super().closeEvent(event)
