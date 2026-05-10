"""First-turn session title extraction from assistant streaming responses.

The model is instructed (via a one-shot system suffix, not stored in session
messages) to emit a delimiter-wrapped title block before the answer body.
See FIRST_TURN_SESSION_TITLE_EXTRA_SYSTEM for the contract.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

SESSION_TITLE_BEGIN = "<<<SESSION_TITLE>>>"
SESSION_TITLE_END = "<<<END_SESSION_TITLE>>>"
MAX_SESSION_TITLE_LEN = 48

# Appended to the real system prompt only for the first plain-text chat request.
FIRST_TURN_SESSION_TITLE_EXTRA_SYSTEM = (
    "Before your visible reply to the user, output a machine-readable session "
    "title block exactly in this format (nothing before the opening line):\n\n"
    f"{SESSION_TITLE_BEGIN}\n"
    "<Single-line short subject title in Title Case, max "
    f"{MAX_SESSION_TITLE_LEN} characters, no quotes or newlines>\n"
    f"{SESSION_TITLE_END}\n\n"
    "Then output one blank line, then your full answer to the user as usual. "
    "The front-end strips the title block from what the user sees; only your "
    "answer after the blank line appears in the chat bubble."
)


def sanitize_session_title(raw: str) -> str:
    line = raw.replace("\n", " ").replace("\r", " ").strip()
    line = re.sub(r"\s+", " ", line)
    if len(line) > MAX_SESSION_TITLE_LEN:
        return line[: MAX_SESSION_TITLE_LEN - 3] + "..."
    return line


def split_first_turn_response(raw: str) -> Tuple[Optional[str], str]:
    """Split full assistant output into (title, answer). If markers are missing
    or malformed, returns (None, raw) so callers can fall back on derive_title.
    """
    text = raw
    i = text.find(SESSION_TITLE_BEGIN)
    if i == -1:
        return None, raw
    j = text.find(SESSION_TITLE_END, i + len(SESSION_TITLE_BEGIN))
    if j == -1:
        return None, raw
    inner = text[i + len(SESSION_TITLE_BEGIN) : j].strip()
    answer = text[j + len(SESSION_TITLE_END) :].lstrip("\r\n")
    if not inner:
        return None, raw
    return sanitize_session_title(inner), answer


class StreamingSessionTitleParser:
    """Incremental parser: suppresses text until <<<END_SESSION_TITLE>>> has been seen."""

    __slots__ = ("_pending", "_phase", "title")

    def __init__(self) -> None:
        self._pending = ""
        self._phase = "seek_begin"  # seek_begin | seek_end | done
        self.title: Optional[str] = None

    def feed(self, chunk: str) -> str:
        """Return the substring of ``chunk`` (combined with carry-over state) that
        should be shown in the assistant bubble. Prefix before the title block
        end marker yields empty string.
        """
        if self._phase == "done":
            return chunk

        self._pending += chunk
        visible_buf: list[str] = []

        while True:
            if self._phase == "seek_begin":
                idx = self._pending.find(SESSION_TITLE_BEGIN)
                if idx == -1:
                    max_keep = len(SESSION_TITLE_BEGIN) - 1
                    if len(self._pending) > max_keep:
                        self._pending = self._pending[-max_keep:]
                    return "".join(visible_buf)
                self._pending = self._pending[idx + len(SESSION_TITLE_BEGIN) :]
                self._phase = "seek_end"
                continue

            if self._phase == "seek_end":
                j = self._pending.find(SESSION_TITLE_END)
                if j == -1:
                    max_keep = len(SESSION_TITLE_END) - 1
                    if len(self._pending) > max_keep:
                        self._pending = self._pending[-max_keep:]
                    return "".join(visible_buf)
                raw_title = self._pending[:j].strip()
                self.title = sanitize_session_title(raw_title) if raw_title else None
                self._pending = self._pending[j + len(SESSION_TITLE_END) :].lstrip("\r\n")
                self._phase = "done"
                if self._pending:
                    visible_buf.append(self._pending)
                    self._pending = ""
                return "".join(visible_buf)
