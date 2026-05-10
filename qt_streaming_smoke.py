"""Headless Qt smoke test: validates that the streaming chat bubble grows in pixels
as tokens are appended.

The previous implementation used QPlainTextEdit, whose document layout reports
documentSize().height() in *line counts* rather than pixels — that caused the
streaming bubble to clamp to ~28px regardless of how much text streamed in.
This test simulates a stream of four token chunks and asserts:

  1. Editor height grows monotonically across inserts.
  2. The final height is at least 6x the initial (placeholder) height.
  3. Editor height matches documentLayout().documentSize().height() within a
     small tolerance, proving we're reading pixel-accurate layout sizes.

Run:
    python qt_streaming_smoke.py
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

    from ui.conversation_view import MessageBubble

    app = QApplication.instance() or QApplication(sys.argv)

    host = QWidget()
    host.resize(700, 800)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)

    bubble = MessageBubble("assistant", "smoke-1")
    layout.addWidget(bubble)
    host.show()
    app.processEvents()

    edit = bubble.add_streaming_editor()
    app.processEvents()

    heights: list[int] = [edit.height()]
    chunks = [
        "Hello\n",
        "Line two with a bit more text\n",
        ("wrap " * 60) + "\n",
        ("more text " * 200),
    ]
    for chunk in chunks:
        edit.insertPlainText(chunk)
        app.processEvents()
        heights.append(edit.height())

    print("heights:", heights)

    assert heights == sorted(heights), (
        f"editor height did not grow monotonically while streaming: {heights}"
    )
    assert heights[-1] >= 6 * max(1, heights[0]), (
        f"final streamed height too small relative to initial: {heights}"
    )

    doc_h = edit.document().documentLayout().documentSize().height()
    margins = edit.contentsMargins()
    expected = int(doc_h) + margins.top() + margins.bottom() + 4
    delta = abs(edit.height() - expected)
    assert delta <= 30, (
        f"widget height {edit.height()} does not match documentLayout pixel "
        f"height {doc_h} (expected ~{expected}, delta {delta})"
    )

    print("OK streaming bubble grows in pixels with content")
    return 0


if __name__ == "__main__":
    sys.exit(main())
