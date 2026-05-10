from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QPoint, QSize, QSizeF, Qt, Signal, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
    QPen,
    QPixmap,
    QPalette,
    QTextOption,
    QWheelEvent,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.icon_button import IconButton


ROLE_LABEL = {"user": "You", "assistant": "Assistant", "system": "System"}
ROLE_GLYPH = {"user": "U", "assistant": "A", "system": "S"}


class StreamingTextEdit(QTextEdit):
    """Streaming assistant body: grows with content in pixels but does not capture the wheel —
    the conversation QScrollArea is the only vertical scroller.

    Uses QTextEdit (not QPlainTextEdit) because QTextDocumentLayout.documentSize() reports
    pixel height, while QPlainTextDocumentLayout.documentSize() reports line count — that
    line-count-as-pixels confusion was clamping streamed bubbles to ~28px regardless of length.
    """

    def _apply_document_height(self, _size: Optional[QSizeF] = None) -> None:
        """Fixed height matches laid-out document (in pixels) so parent layouts grow while streaming."""
        doc = self.document()
        layout = doc.documentLayout()
        if layout is None:
            return
        pixel_h = layout.documentSize().height()
        margins = self.contentsMargins()
        pad = margins.top() + margins.bottom() + 4
        h = int(max(28, pixel_h + pad))
        if self.height() != h:
            self.setFixedHeight(h)
            self.updateGeometry()
            self._notify_bubble_container_resize()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_document_height()

    def _notify_bubble_container_resize(self) -> None:
        """Propagate size change up to the scroll area contents so the bubble row reflows."""
        msg = self.parentWidget()  # chatBubble
        if msg is None:
            return
        row = msg.parentWidget()
        if row is None:
            return
        row.updateGeometry()
        row.adjustSize()
        bucket = row.parentWidget()
        if bucket is not None:
            bucket.adjustSize()
        p = row
        while p is not None:
            if isinstance(p, QScrollArea):
                inner = p.widget()
                if inner is not None:
                    inner.adjustSize()
                break
            p = p.parentWidget()

    def wheelEvent(self, event: QWheelEvent) -> None:
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                bar = parent.verticalScrollBar()
                pixel = event.pixelDelta()
                if pixel.y() != 0:
                    delta = pixel.y()
                else:
                    delta = int(event.angleDelta().y() * 0.5)
                bar.setValue(bar.value() - delta)
                event.accept()
                return
            parent = parent.parentWidget()
        super().wheelEvent(event)


class Avatar(QWidget):
    def __init__(self, role: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._role = role
        self._color = QColor(self._color_for_role(role))
        self.setFixedSize(QSize(34, 34))

    @staticmethod
    def _color_for_role(role: str) -> str:
        return {
            "user": "#3b82f6",
            "assistant": "#22c55e",
            "system": "#f59e0b",
        }.get(role, "#6366f1")

    def set_role(self, role: str) -> None:
        self._role = role
        self._color = QColor(self._color_for_role(role))
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self._color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, self.width(), self.height())
        painter.setPen(QPen(QColor("#0b0f1a"), 1))
        # Do not use painter.font() — inherited font may have pointSize -1 with QSS.
        font = QFont()
        font.setFamilies(["Segoe UI", "Inter", "Arial"])
        font.setBold(True)
        font.setPointSize(11)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(self.rect(), Qt.AlignCenter, ROLE_GLYPH.get(self._role, "?"))


class MessageBubble(QFrame):
    """A single chat message with avatar, role label, timestamp, body
    and (for assistant messages) action buttons."""

    feedback_changed = Signal(str, str)
    speak_requested = Signal(object)

    def __init__(
        self,
        role: str,
        message_id: str,
        timestamp: Optional[float] = None,
        parent: Optional[QWidget] = None,
        display_name: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("messageRow")
        self.role = role
        self.message_id = message_id
        self._copy_provider: Callable[[], str] = lambda: ""
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)

        self._avatar = Avatar(role)
        layout.addWidget(self._avatar, 0, Qt.AlignTop)

        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(4)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        if role == "assistant" and display_name:
            header_label = display_name.strip()
        else:
            header_label = ROLE_LABEL.get(role, role.title())
        self._role_label = QLabel(header_label)
        self._role_label.setObjectName("valueLabel")
        self._timestamp_label = QLabel(self._format_timestamp(timestamp))
        self._timestamp_label.setObjectName("mutedLabel")
        self._timestamp_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header_row.addWidget(self._role_label)
        header_row.addStretch()
        header_row.addWidget(self._timestamp_label)
        right_col.addLayout(header_row)

        self._bubble = QFrame()
        self._bubble.setObjectName("chatBubble")
        self._bubble.setProperty("role", role)
        self._bubble.setMinimumWidth(0)
        self._bubble.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._bubble_layout = QVBoxLayout(self._bubble)
        self._bubble_layout.setContentsMargins(12, 10, 12, 10)
        self._bubble_layout.setSpacing(8)
        right_col.addWidget(self._bubble)

        self._actions_widget = QWidget()
        actions_layout = QHBoxLayout(self._actions_widget)
        actions_layout.setContentsMargins(2, 0, 2, 0)
        actions_layout.setSpacing(4)

        self._speak_btn = QPushButton("Speak Aloud")
        self._speak_btn.setObjectName("speakAloudButton")
        self._speak_btn.setCursor(Qt.PointingHandCursor)
        self._speak_btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._speak_btn.setToolTip("Speak aloud")
        self._speak_btn.clicked.connect(self._on_speak_clicked)

        self._copy_btn = IconButton("\u29C9", tooltip="Copy", size=26)
        self._copy_btn.clicked.connect(self._on_copy)
        self._thumbs_up_btn = IconButton("\U0001F44D", tooltip="Helpful", size=26)
        self._thumbs_up_btn.setCheckable(True)
        self._thumbs_up_btn.clicked.connect(lambda: self._on_feedback("up"))
        self._thumbs_down_btn = IconButton("\U0001F44E", tooltip="Not helpful", size=26)
        self._thumbs_down_btn.setCheckable(True)
        self._thumbs_down_btn.clicked.connect(lambda: self._on_feedback("down"))
        self._more_btn = IconButton("\u22EF", tooltip="More", size=26)
        self._more_btn.clicked.connect(self._on_more)
        actions_layout.addStretch()
        actions_layout.addWidget(self._speak_btn)
        actions_layout.addWidget(self._copy_btn)
        actions_layout.addWidget(self._thumbs_up_btn)
        actions_layout.addWidget(self._thumbs_down_btn)
        actions_layout.addWidget(self._more_btn)
        right_col.addWidget(self._actions_widget)
        if role != "assistant":
            self._actions_widget.setVisible(False)
            self._speak_btn.setVisible(False)

        layout.addLayout(right_col, 1)

    @staticmethod
    def _format_timestamp(timestamp: Optional[float]) -> str:
        if not timestamp:
            timestamp = time.time()
        return datetime.fromtimestamp(timestamp).strftime("%I:%M %p").lstrip("0")

    def set_role(self, role: str) -> None:
        self.role = role
        self._avatar.set_role(role)
        self._bubble.setProperty("role", role)
        self._bubble.style().unpolish(self._bubble)
        self._bubble.style().polish(self._bubble)
        self._role_label.setText(ROLE_LABEL.get(role, role.title()))
        self._actions_widget.setVisible(role == "assistant")
        self._speak_btn.setVisible(role == "assistant")

    def set_copy_provider(self, provider: Callable[[], str]) -> None:
        self._copy_provider = provider

    def set_feedback(self, feedback: Optional[str]) -> None:
        self._thumbs_up_btn.setChecked(feedback == "up")
        self._thumbs_down_btn.setChecked(feedback == "down")

    def text_for_tts(self) -> str:
        """Plain text of the bubble body for read-aloud."""
        return ConversationView._collect_text(self)

    def set_speaking(self, active: bool) -> None:
        """While loading or playing TTS, show stop label; otherwise the read prompt."""
        if active:
            self._speak_btn.setText("Stop")
            self._speak_btn.setToolTip("Stop")
            self._speak_btn.setProperty("speaking", True)
        else:
            self._speak_btn.setText("Speak Aloud")
            self._speak_btn.setToolTip("Speak aloud")
            self._speak_btn.setProperty("speaking", False)
        self._speak_btn.style().unpolish(self._speak_btn)
        self._speak_btn.style().polish(self._speak_btn)

    def set_speak_enabled(self, enabled: bool) -> None:
        self._speak_btn.setEnabled(enabled)

    def _on_speak_clicked(self) -> None:
        if self.role == "assistant":
            self.speak_requested.emit(self)

    def add_text(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._bubble_layout.addWidget(label)
        return label

    def add_widget(self, widget: QWidget) -> None:
        self._bubble_layout.addWidget(widget)

    def add_streaming_editor(self) -> QTextEdit:
        """Read-only editor for token streaming: incremental inserts avoid
        full-document QLabel relayout flicker. Height tracks document size in pixels."""
        edit = StreamingTextEdit()
        edit.setObjectName("streamBody")
        edit.setReadOnly(True)
        edit.setFrameShape(QFrame.NoFrame)
        edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        edit.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        edit.setPlaceholderText("Thinking...")
        edit.setLineWrapMode(QTextEdit.WidgetWidth)
        doc = edit.document()
        doc.setDocumentMargin(0)
        edit.setContentsMargins(0, 0, 0, 0)
        edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        edit.setMinimumHeight(28)

        doc.setDefaultTextOption(QTextOption(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop))
        # documentSizeChanged fires after layout with pixel-accurate sizes — unlike
        # contentsChanged, which fires before layout has computed wrapped heights.
        doc.documentLayout().documentSizeChanged.connect(edit._apply_document_height)
        pal = edit.palette()
        base = self.palette().color(QPalette.ColorRole.WindowText)
        ph = QColor(base)
        ph.setAlphaF(0.45)
        pal.setColor(QPalette.ColorRole.PlaceholderText, ph)
        edit.setPalette(pal)

        self._bubble_layout.addWidget(edit)
        QTimer.singleShot(0, edit._apply_document_height)
        return edit

    def _on_copy(self) -> None:
        text = self._copy_provider() or ""
        if not text:
            for index in range(self._bubble_layout.count()):
                widget = self._bubble_layout.itemAt(index).widget()
                if isinstance(widget, QLabel):
                    text += widget.text() + "\n"
                elif isinstance(widget, (QPlainTextEdit, QTextEdit)):
                    text += widget.toPlainText() + "\n"
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text.strip())

    def _on_feedback(self, kind: str) -> None:
        if kind == "up" and self._thumbs_up_btn.isChecked():
            self._thumbs_down_btn.setChecked(False)
            self.feedback_changed.emit(self.message_id, "up")
        elif kind == "down" and self._thumbs_down_btn.isChecked():
            self._thumbs_up_btn.setChecked(False)
            self.feedback_changed.emit(self.message_id, "down")
        else:
            self.feedback_changed.emit(self.message_id, "")

    def _on_more(self) -> None:
        menu = QMenu(self)
        copy_action = menu.addAction("Copy text")
        action = menu.exec(self._more_btn.mapToGlobal(QPoint(0, self._more_btn.height())))
        if action == copy_action:
            self._on_copy()


class ConversationView(QFrame):
    """Scrolling list of MessageBubbles plus a header label and a
    floating scroll-to-bottom button."""

    feedback_changed = Signal(str, str)
    speak_requested = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("conversationFrame")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        title = QLabel("\U0001F4AC  Conversation")
        title.setObjectName("sectionTitle")
        header_row.addWidget(title)
        header_row.addStretch()
        outer.addLayout(header_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._messages_container = QWidget()
        self._messages_container.setMinimumWidth(0)
        self._messages_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._messages_layout = QVBoxLayout(self._messages_container)
        self._messages_layout.setContentsMargins(4, 4, 4, 4)
        self._messages_layout.setSpacing(14)
        # No trailing stretch: a bottom stretch made "scroll to bottom" land on
        # empty space below the last bubble.
        self._scroll.setWidget(self._messages_container)
        outer.addWidget(self._scroll, 1)

        self._scroll_bottom_btn = IconButton("\u2304", tooltip="Scroll to latest", size=30, parent=self)
        self._scroll_bottom_btn.setObjectName("ghostButton")
        self._scroll_bottom_btn.raise_()
        self._scroll_bottom_btn.clicked.connect(self.scroll_to_bottom)

        self._scroll_programmatic = False
        self._scroll_coalesce = QTimer(self)
        self._scroll_coalesce.setSingleShot(True)
        self._scroll_coalesce.setInterval(24)
        self._scroll_coalesce.timeout.connect(self._perform_scroll_to_bottom)

        self._scroll.verticalScrollBar().valueChanged.connect(self._update_scroll_button_visibility)
        self._update_scroll_button_visibility()

        self._media_players: List = []

    # ---- Layout / scroll -------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_scroll_button()

    def _reposition_scroll_button(self) -> None:
        margin = 18
        size = self._scroll_bottom_btn.size()
        x = self.width() - size.width() - margin
        y = self.height() - size.height() - margin
        self._scroll_bottom_btn.move(x, y)

    def _update_scroll_button_visibility(self) -> None:
        if self._scroll_programmatic:
            return
        bar = self._scroll.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 8
        self._scroll_bottom_btn.setVisible(not at_bottom and bar.maximum() > 0)
        self._reposition_scroll_button()

    def schedule_scroll_to_bottom(self) -> None:
        """Coalesce rapid scroll requests during streaming (one repaint per ~24ms)."""
        self._scroll_coalesce.start()

    def _perform_scroll_to_bottom(self) -> None:
        if self._messages_layout.count() == 0:
            return
        self._messages_container.adjustSize()
        bar = self._scroll.verticalScrollBar()
        self._scroll_programmatic = True
        try:
            bar.setValue(bar.maximum())
        finally:
            self._scroll_programmatic = False
        self._reposition_scroll_button()

    def scroll_to_bottom(self) -> None:
        """Scroll after layout; retry once so growing content is fully measured."""
        QTimer.singleShot(0, self._perform_scroll_to_bottom)
        QTimer.singleShot(40, self._perform_scroll_to_bottom)

    def scroll_to_bottom_settled(self) -> None:
        """After stream ends / images attach, catch delayed layout."""
        QTimer.singleShot(0, self._perform_scroll_to_bottom)
        QTimer.singleShot(80, self._perform_scroll_to_bottom)
        QTimer.singleShot(160, self._perform_scroll_to_bottom)

    # ---- Public message API ---------------------------------------------

    def clear(self) -> None:
        while self._messages_layout.count() > 0:
            item = self._messages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for player, audio in self._media_players:
            try:
                player.stop()
                player.deleteLater()
                audio.deleteLater()
            except Exception:
                pass
        self._media_players.clear()
        self._update_scroll_button_visibility()

    def add_bubble(
        self,
        role: str,
        message_id: str,
        timestamp: Optional[float] = None,
        display_name: Optional[str] = None,
    ) -> MessageBubble:
        bubble = MessageBubble(role, message_id, timestamp, display_name=display_name)
        bubble.feedback_changed.connect(self.feedback_changed.emit)
        bubble.speak_requested.connect(self.speak_requested.emit)
        self._messages_layout.addWidget(bubble)
        self.scroll_to_bottom()
        return bubble

    def add_text_message(
        self,
        role: str,
        message_id: str,
        text: str,
        timestamp: Optional[float] = None,
        display_name: Optional[str] = None,
    ) -> MessageBubble:
        bubble = self.add_bubble(role, message_id, timestamp, display_name=display_name)
        bubble.add_text(text)
        bubble.set_copy_provider(lambda b=bubble: self._collect_text(b))
        return bubble

    @staticmethod
    def _collect_text(bubble: MessageBubble) -> str:
        parts: List[str] = []
        layout = bubble._bubble_layout  # noqa: SLF001
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if isinstance(widget, QLabel):
                parts.append(widget.text())
            elif isinstance(widget, (QPlainTextEdit, QTextEdit)):
                parts.append(widget.toPlainText())
        return "\n".join(parts).strip()

    def add_image(
        self,
        role: str,
        message_id: str,
        image_path: Path,
        label: str = "image",
        display_name: Optional[str] = None,
    ) -> MessageBubble:
        bubble = self.add_bubble(role, message_id, display_name=display_name)
        bubble.add_text(f"{label.title()}: {image_path.name}")
        if image_path.exists():
            image_label = QLabel()
            image_label.setAlignment(Qt.AlignLeft)
            image_label.setMinimumSize(QSize(120, 80))
            pixmap = QPixmap(str(image_path))
            if not pixmap.isNull():
                image_label.setPixmap(pixmap.scaledToWidth(384, Qt.SmoothTransformation))
            else:
                image_label.setText(str(image_path))
            image_label.setContextMenuPolicy(Qt.CustomContextMenu)
            image_label.customContextMenuRequested.connect(
                lambda pos, path=image_path, widget=image_label: self._show_media_context_menu(
                    widget, pos, path, "image"
                )
            )
            bubble.add_widget(image_label)
        return bubble

    def add_video(
        self,
        role: str,
        message_id: str,
        video_path: Path,
        job_id: str,
        display_name: Optional[str] = None,
    ) -> MessageBubble:
        bubble = self.add_bubble(role, message_id, display_name=display_name)
        bubble.add_text(f"Video: {video_path.name} | Job {job_id}")
        if not video_path.exists():
            return bubble

        video_card = QWidget()
        layout = QVBoxLayout(video_card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        video_widget = QVideoWidget()
        video_widget.setMinimumSize(QSize(480, 270))
        video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        video_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        video_widget.customContextMenuRequested.connect(
            lambda pos, path=video_path, widget=video_widget: self._show_media_context_menu(
                widget, pos, path, "video"
            )
        )
        layout.addWidget(video_widget)

        controls = QHBoxLayout()
        play_btn = QPushButton("Play")
        save_btn = QPushButton("Save As")
        controls.addWidget(play_btn)
        controls.addWidget(save_btn)
        controls.addStretch()
        layout.addLayout(controls)

        from PySide6.QtCore import QUrl

        player = QMediaPlayer(self)
        audio_output = QAudioOutput(self)
        player.setAudioOutput(audio_output)
        player.setVideoOutput(video_widget)
        player.setSource(QUrl.fromLocalFile(str(video_path)))
        self._media_players.append((player, audio_output))

        def toggle() -> None:
            if player.playbackState() == QMediaPlayer.PlayingState:
                player.pause()
            else:
                player.play()

        play_btn.clicked.connect(toggle)
        save_btn.clicked.connect(lambda _checked=False, path=video_path: self._save_media_as(path, "video"))
        player.playbackStateChanged.connect(
            lambda state, button=play_btn: button.setText(
                "Pause" if state == QMediaPlayer.PlayingState else "Play"
            )
        )
        bubble.add_widget(video_card)
        return bubble

    # ---- Internals -------------------------------------------------------

    def _show_media_context_menu(self, widget: QWidget, pos, path: Path, media_type: str) -> None:
        menu = QMenu(widget)
        save_action = menu.addAction(f"Save {media_type} as...")
        open_folder_action = menu.addAction("Open containing folder")
        action = menu.exec(widget.mapToGlobal(pos))
        if action == save_action:
            self._save_media_as(path, media_type)
        elif action == open_folder_action:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _save_media_as(self, source: Path, media_type: str) -> None:
        if not source.exists():
            QMessageBox.warning(self, "Save failed", f"The {media_type} file no longer exists.")
            return
        filter_text = (
            "Images (*.png *.jpg *.jpeg *.webp *.gif);;All files (*.*)"
            if media_type == "image"
            else "Videos (*.mp4 *.mov *.webm *.mpeg);;All files (*.*)"
        )
        target, _ = QFileDialog.getSaveFileName(
            self,
            f"Save {media_type} as",
            source.name,
            filter_text,
        )
        if not target:
            return
        try:
            shutil.copyfile(source, target)
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
