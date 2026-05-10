from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import keyring


SERVICE_NAME = "ModelDocker"
KEY_NAME = "openrouter_api_key"

# Global fallback when no role/session preference applies — OpenRouter Free Models Router.
DEFAULT_MODEL_ID = "openrouter/free"

# OpenRouter text-to-speech (see /api/v1/audio/speech).
DEFAULT_TTS_MODEL_ID = "openai/gpt-4o-mini-tts-2025-12-15"
DEFAULT_TTS_VOICE = "alloy"
# Slight upward bias (15% faster) reads back at a natural conversational pace
# without sounding rushed. OpenAI / OpenRouter accept 0.25 - 4.0.
DEFAULT_TTS_SPEED = 1.15
TTS_SPEED_MIN = 0.5
TTS_SPEED_MAX = 2.0


class SettingsStore:
    def __init__(self) -> None:
        app_dir = Path.home() / ".modeldocker"
        app_dir.mkdir(parents=True, exist_ok=True)
        self._fallback_path = app_dir / "config.json"
        self._prefs_path = app_dir / "prefs.json"

    # ---- API key ---------------------------------------------------------

    def load_api_key(self) -> Optional[str]:
        key = self._load_from_keyring()
        if key:
            return key
        return self._load_from_fallback()

    def save_api_key(self, api_key: str) -> None:
        api_key = api_key.strip()
        if not api_key:
            return
        try:
            keyring.set_password(SERVICE_NAME, KEY_NAME, api_key)
            if self._fallback_path.exists():
                self._fallback_path.unlink()
            return
        except Exception:
            pass
        self._save_to_fallback(api_key)

    def clear_api_key(self) -> None:
        try:
            keyring.delete_password(SERVICE_NAME, KEY_NAME)
        except Exception:
            pass
        if self._fallback_path.exists():
            self._fallback_path.unlink()

    def _load_from_keyring(self) -> Optional[str]:
        try:
            return keyring.get_password(SERVICE_NAME, KEY_NAME)
        except Exception:
            return None

    def _save_to_fallback(self, api_key: str) -> None:
        payload = {"api_key": api_key}
        self._fallback_path.write_text(json.dumps(payload), encoding="utf-8")

    def _load_from_fallback(self) -> Optional[str]:
        if not self._fallback_path.exists():
            return None
        try:
            payload = json.loads(self._fallback_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        value = payload.get("api_key")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    # ---- General preferences --------------------------------------------

    def _read_prefs(self) -> Dict[str, Any]:
        if not self._prefs_path.exists():
            return {}
        try:
            return json.loads(self._prefs_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_prefs(self, prefs: Dict[str, Any]) -> None:
        try:
            self._prefs_path.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
        except OSError:
            pass

    def get_pref(self, name: str, default: Any = None) -> Any:
        return self._read_prefs().get(name, default)

    def set_pref(self, name: str, value: Any) -> None:
        prefs = self._read_prefs()
        prefs[name] = value
        self._write_prefs(prefs)

    def load_theme(self) -> str:
        return str(self.get_pref("theme", "dark"))

    def save_theme(self, theme: str) -> None:
        self.set_pref("theme", theme)

    def load_memory_enabled(self) -> bool:
        """When True, enabled memories are injected into chat requests."""
        raw = self.get_pref("memory_enabled", True)
        if raw is None:
            return True
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        text = str(raw).strip().lower()
        if text in {"0", "false", "no", "off"}:
            return False
        return True

    def save_memory_enabled(self, enabled: bool) -> None:
        self.set_pref("memory_enabled", bool(enabled))

    def load_last_session_id(self) -> Optional[str]:
        value = self.get_pref("last_session_id")
        return str(value) if value else None

    def save_last_session_id(self, session_id: Optional[str]) -> None:
        self.set_pref("last_session_id", session_id)

    def effective_default_model_id(self) -> str:
        """Preferred model for new sessions / sessions without a model: user override or built-in default."""
        value = self.get_pref("default_model_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return DEFAULT_MODEL_ID

    def save_default_model_id(self, model_id: str) -> None:
        mid = model_id.strip()
        if mid:
            self.set_pref("default_model_id", mid)

    def effective_max_output_tokens(self) -> int:
        """Per-request output cap so OpenRouter doesn't reserve credit for the whole context window."""
        value = self.get_pref("max_output_tokens", 4096)
        try:
            cap = int(value)
        except (TypeError, ValueError):
            cap = 4096
        return max(256, min(cap, 32768))

    def save_max_output_tokens(self, value: int) -> None:
        self.set_pref("max_output_tokens", int(value))

    def effective_tts_model_id(self) -> str:
        value = self.get_pref("tts_model_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return DEFAULT_TTS_MODEL_ID

    def save_tts_model_id(self, model_id: str) -> None:
        mid = model_id.strip()
        if mid:
            self.set_pref("tts_model_id", mid)

    def effective_tts_voice(self) -> str:
        value = self.get_pref("tts_voice")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return DEFAULT_TTS_VOICE

    def save_tts_voice(self, voice: str) -> None:
        v = voice.strip()
        if v:
            self.set_pref("tts_voice", v)

    def effective_tts_speed(self) -> float:
        """Playback speed multiplier passed to OpenRouter ``audio/speech``.

        Clamped to ``[TTS_SPEED_MIN, TTS_SPEED_MAX]`` to keep output intelligible.
        """
        raw = self.get_pref("tts_speed", DEFAULT_TTS_SPEED)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = DEFAULT_TTS_SPEED
        return max(TTS_SPEED_MIN, min(value, TTS_SPEED_MAX))

    def save_tts_speed(self, speed: float) -> None:
        try:
            value = float(speed)
        except (TypeError, ValueError):
            return
        clamped = max(TTS_SPEED_MIN, min(value, TTS_SPEED_MAX))
        self.set_pref("tts_speed", round(clamped, 2))
