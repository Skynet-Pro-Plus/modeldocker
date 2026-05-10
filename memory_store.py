from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Limits keep prompts small and predictable.
MAX_MEMORY_TEXT_CHARS = 300
MAX_MEMORIES_IN_PROMPT = 12


@dataclass
class Memory:
    id: str
    text: str
    # ``None`` means the memory applies to every role.
    role_id: Optional[str]
    enabled: bool
    created_at: float
    updated_at: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Memory":
        raw_role = data.get("role_id")
        if raw_role is None or raw_role == "":
            role_id: Optional[str] = None
        else:
            role_id = str(raw_role)
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex),
            text=str(data.get("text") or ""),
            role_id=role_id,
            enabled=bool(data.get("enabled", True)),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
        )


class MemoryStore:
    """Persists user-managed memories at ``~/.modeldocker/memories.json``."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or (Path.home() / ".modeldocker" / "memories.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._memories: List[Memory] = self._load_all()

    def _load_all(self) -> List[Memory]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, list):
            return []
        out: List[Memory] = []
        for item in data:
            if isinstance(item, dict) and item.get("id"):
                out.append(Memory.from_dict(item))
        return out

    def _write_all(self, memories: List[Memory]) -> None:
        try:
            self.path.write_text(
                json.dumps([m.to_dict() for m in memories], indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def list(
        self,
        role_id: Optional[str] = None,
        *,
        include_disabled: bool = False,
    ) -> List[Memory]:
        """List memories, optionally filtered to those visible for a role.

        When ``role_id`` is set, returns global memories (``role_id is None``)
        plus memories pinned to that role. When ``role_id`` is ``None``, returns
        all memories.
        """
        items = list(self._memories)
        if not include_disabled:
            items = [m for m in items if m.enabled]
        if role_id is not None:
            items = [
                m for m in items if m.role_id is None or m.role_id == role_id
            ]
        items.sort(key=lambda m: (-m.updated_at, m.id))
        return items

    def active_for_role(self, role_id: str) -> List[Memory]:
        """Enabled memories applicable to ``role_id``, newest first."""
        result: List[Memory] = []
        for m in self._memories:
            if not m.enabled:
                continue
            if m.role_id is None or m.role_id == role_id:
                result.append(m)
        result.sort(key=lambda m: (-m.updated_at, m.id))
        return result

    def count_active_for_role(self, role_id: str) -> int:
        return len(self.active_for_role(role_id))

    def get(self, memory_id: str) -> Optional[Memory]:
        for m in self._memories:
            if m.id == memory_id:
                return m
        return None

    def upsert(self, memory: Memory) -> None:
        text = memory.text.strip()
        if len(text) > MAX_MEMORY_TEXT_CHARS:
            text = text[:MAX_MEMORY_TEXT_CHARS]
        memory.text = text
        now = time.time()
        if not memory.id or not str(memory.id).strip():
            memory.id = uuid.uuid4().hex
        if memory.created_at <= 0:
            memory.created_at = now
        memory.updated_at = now

        replaced = False
        new_list: List[Memory] = []
        for existing in self._memories:
            if existing.id == memory.id:
                new_list.append(memory)
                replaced = True
            else:
                new_list.append(existing)
        if not replaced:
            new_list.append(memory)
        self._memories = new_list
        self._write_all(self._memories)

    def delete(self, memory_id: str) -> None:
        self._memories = [m for m in self._memories if m.id != memory_id]
        self._write_all(self._memories)

    def format_for_prompt(self, role_id: str, limit: int = MAX_MEMORIES_IN_PROMPT) -> str:
        """Return extra system text for the model, or empty string if none."""
        memories = self.active_for_role(role_id)[: max(0, limit)]
        lines: List[str] = []
        for m in memories:
            line = m.text.strip()
            if line:
                lines.append(line)
        if not lines:
            return ""
        body = "\n".join(f"- {line}" for line in lines)
        return (
            "Relevant saved memory:\n"
            f"{body}\n\n"
            "Use these memories only when relevant. "
            "Do not mention saved memory unless helpful."
        )
