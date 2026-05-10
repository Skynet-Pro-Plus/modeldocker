from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."
DEFAULT_TEMPERATURE = 0.7
DEFAULT_ROLE_ID = "default"


@dataclass
class Session:
    id: str
    title: str
    created_at: float
    updated_at: float
    model_id: Optional[str] = None
    role_id: str = DEFAULT_ROLE_ID
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    temperature: float = DEFAULT_TEMPERATURE
    messages: List[Dict[str, Any]] = field(default_factory=list)
    feedback: Dict[str, str] = field(default_factory=dict)
    total_cost: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0

    def touch(self) -> None:
        self.updated_at = time.time()

    def derive_title(self) -> str:
        for message in self.messages:
            if message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                text = content.strip()
            elif isinstance(content, list):
                text = " ".join(
                    str(item.get("text", "")).strip()
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ).strip()
            else:
                text = ""
            if text:
                return text[:48] + ("..." if len(text) > 48 else "")
        return "New Session"

    def summary(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "updated_at": self.updated_at,
            "created_at": self.created_at,
            "model_id": self.model_id,
        }

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        now = time.time()
        role_id = data.get("role_id")
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex),
            title=str(data.get("title") or "New Session"),
            created_at=float(data.get("created_at") or now),
            updated_at=float(data.get("updated_at") or now),
            model_id=data.get("model_id"),
            role_id=str(role_id) if role_id else DEFAULT_ROLE_ID,
            system_prompt=str(data.get("system_prompt") or DEFAULT_SYSTEM_PROMPT),
            temperature=float(data.get("temperature") or DEFAULT_TEMPERATURE),
            messages=list(data.get("messages") or []),
            feedback=dict(data.get("feedback") or {}),
            total_cost=float(data.get("total_cost") or 0.0),
            total_prompt_tokens=int(data.get("total_prompt_tokens") or 0),
            total_completion_tokens=int(data.get("total_completion_tokens") or 0),
        )


class SessionStore:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or (Path.home() / ".modeldocker" / "sessions")
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"

    def list(self) -> List[Dict[str, Any]]:
        if not self.index_path.exists():
            return []
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, list):
            return []
        data.sort(key=lambda item: item.get("updated_at") or 0, reverse=True)
        return data

    def _write_index(self, summaries: List[Dict[str, Any]]) -> None:
        try:
            self.index_path.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _session_path(self, session_id: str) -> Path:
        safe = "".join(ch for ch in session_id if ch.isalnum() or ch in {"-", "_"})
        return self.root / f"{safe}.json"

    def load(self, session_id: str) -> Optional[Session]:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return Session.from_dict(data)

    def create(self, title: str = "New Session") -> Session:
        now = time.time()
        session = Session(
            id=uuid.uuid4().hex,
            title=title,
            created_at=now,
            updated_at=now,
        )
        self.save(session)
        return session

    def save(self, session: Session) -> None:
        session.touch()
        path = self._session_path(session.id)
        try:
            path.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")
        except OSError:
            return
        self._refresh_index_for(session.summary())

    def _refresh_index_for(self, summary: Dict[str, Any]) -> None:
        items = self.list()
        items = [item for item in items if item.get("id") != summary.get("id")]
        items.append(summary)
        items.sort(key=lambda item: item.get("updated_at") or 0, reverse=True)
        self._write_index(items)

    def delete(self, session_id: str) -> None:
        path = self._session_path(session_id)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        items = [item for item in self.list() if item.get("id") != session_id]
        self._write_index(items)

    def rename(self, session_id: str, title: str) -> Optional[Session]:
        session = self.load(session_id)
        if session is None:
            return None
        session.title = title.strip() or session.title
        self.save(session)
        return session
