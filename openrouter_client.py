from __future__ import annotations

import base64
import json
import mimetypes
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote

import httpx


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

MODALITY_ICONS = {
    "text": "📝",
    "image": "🖼️",
    "file": "📄",
    "files": "📄",
    "pdf": "📄",
    "audio": "🔊",
    "video": "🎞️",
}


class OpenRouterError(Exception):
    pass


@dataclass
class Pricing:
    prompt: float = 0.0
    completion: float = 0.0
    request: float = 0.0

    @staticmethod
    def from_api(data: Optional[Dict[str, Any]]) -> "Pricing":
        if not data:
            return Pricing()
        return Pricing(
            prompt=_to_float(data.get("prompt")),
            completion=_to_float(data.get("completion")),
            request=_to_float(data.get("request")),
        )


@dataclass
class ModelInfo:
    model_id: str
    name: str
    company: str
    pricing: Pricing = field(default_factory=Pricing)
    input_modalities: List[str] = field(default_factory=list)
    output_modalities: List[str] = field(default_factory=list)
    modality: Optional[str] = None
    supported_parameters: List[str] = field(default_factory=list)
    architecture: Dict[str, Any] = field(default_factory=dict)
    video_metadata: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def supports_image_input(self) -> bool:
        values = set(self.input_modalities)
        parameter_values = set(v.lower() for v in self.supported_parameters)
        return "image" in values or self.architecture.get("input_image") is True or "image_url" in parameter_values

    @property
    def supports_pdf_input(self) -> bool:
        values = set(self.input_modalities)
        parameter_values = set(v.lower() for v in self.supported_parameters)
        return "file" in values or "pdf" in values or "files" in parameter_values or "plugins" in parameter_values

    @property
    def supports_image_output(self) -> bool:
        return "image" in set(self.output_modalities)

    @property
    def supports_video_output(self) -> bool:
        return "video" in set(self.output_modalities)

    @property
    def supports_text_output(self) -> bool:
        return "text" in set(self.output_modalities)

    @property
    def capability_label(self) -> str:
        inputs = _modality_icon_label(self.input_modalities)
        outputs = _modality_icon_label(self.output_modalities)
        return f"In: {inputs} | Out: {outputs}"

    @property
    def friendly_capability_label(self) -> str:
        analyze = "yes" if self.supports_image_input else "no"
        generate_image = "yes" if self.supports_image_output else "tool"
        generate_video = "yes" if self.supports_video_output else "no"
        return (
            f"Analyze images: {analyze} | Generate images: {generate_image} | "
            f"Generate video: {generate_video} | {self.capability_label}"
        )

    @property
    def search_haystack(self) -> str:
        """Lowercased text used for substring / token search in the model picker."""
        parts: List[str] = [
            self.company,
            self.name,
            self.model_id,
            self.capability_label,
            self.friendly_capability_label,
        ]
        raw = self.raw
        if isinstance(raw, dict):
            desc = raw.get("description")
            if isinstance(desc, str) and desc.strip():
                parts.append(desc)
            tp = raw.get("top_provider")
            if isinstance(tp, dict):
                for key in ("name", "slug", "display_name"):
                    v = tp.get(key)
                    if isinstance(v, str) and v.strip():
                        parts.append(v)
        return " ".join(parts).lower()

    @property
    def label(self) -> str:
        in_per_m = self.pricing.prompt * 1_000_000
        out_per_m = self.pricing.completion * 1_000_000
        return (
            f"{self.company} - {self.name} | "
            f"{self.release_date_label} | "
            f"{self.capability_label} | "
            f"Input ${in_per_m:.4f}/M | Output ${out_per_m:.4f}/M"
        )

    @property
    def release_date_label(self) -> str:
        return f"Released {date}" if (date := _release_date(self.raw, self.video_metadata)) else "Released unknown"

    @property
    def release_timestamp(self) -> Optional[int]:
        return _release_timestamp(self.raw, self.video_metadata)

    @property
    def video_pricing_label(self) -> str:
        return _video_pricing_label(self.video_metadata)

    @property
    def supported_video_durations(self) -> List[int]:
        return _int_values(self.video_metadata.get("supported_durations")) or [4, 6, 8]

    @property
    def supported_video_resolutions(self) -> List[str]:
        return _string_values(self.video_metadata.get("supported_resolutions")) or ["720p"]

    @property
    def supported_video_aspect_ratios(self) -> List[str]:
        return _string_values(self.video_metadata.get("supported_aspect_ratios")) or ["16:9"]

    @property
    def supports_video_audio(self) -> bool:
        return self.video_metadata.get("generate_audio") is True

    @property
    def _supported_parameters_set(self) -> set[str]:
        return {p.lower() for p in self.supported_parameters}

    @property
    def supports_tools(self) -> bool:
        return "tools" in self._supported_parameters_set

    @property
    def supports_function_calling(self) -> bool:
        params = self._supported_parameters_set
        return "tool_choice" in params or "tools" in params

    @property
    def supports_web_search(self) -> bool:
        params = self._supported_parameters_set
        return (
            "web_search_options" in params
            or "web_search" in params
            or "plugins" in params
        )

    @property
    def supports_code_interpreter(self) -> bool:
        return False

    @property
    def supports_temperature(self) -> bool:
        return "temperature" in self._supported_parameters_set

    @property
    def supports_max_tokens(self) -> bool:
        params = self._supported_parameters_set
        return "max_tokens" in params or "max_completion_tokens" in params

    @property
    def context_length(self) -> Optional[int]:
        for key in ("context_length", "context_window"):
            value = self.raw.get(key)
            try:
                if value is None:
                    continue
                return int(value)
            except (TypeError, ValueError):
                continue
        top = self.raw.get("top_provider") or {}
        try:
            value = top.get("context_length")
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            pass
        return None


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_modalities(value: Any) -> List[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    normalized: List[str] = []
    for item in values:
        text = str(item).strip().lower()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _string_values(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _int_values(value: Any) -> List[int]:
    if not isinstance(value, list):
        return []
    values: List[int] = []
    for item in value:
        try:
            values.append(int(item))
        except (TypeError, ValueError):
            continue
    return values


def _release_date(*sources: Dict[str, Any]) -> str:
    timestamp = _release_timestamp(*sources)
    if timestamp is None:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")


def _release_timestamp(*sources: Dict[str, Any]) -> Optional[int]:
    for source in sources:
        value = source.get("created")
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            continue
        if timestamp <= 0:
            continue
        return timestamp
    return None


def _modality_icon_label(modalities: List[str]) -> str:
    if not modalities:
        return "?"
    icons: List[str] = []
    for modality in modalities:
        icon = MODALITY_ICONS.get(modality, modality)
        if icon not in icons:
            icons.append(icon)
    return " ".join(icons)


def _error_message(data: Dict[str, Any]) -> str:
    candidates: List[str] = []

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                visit(nested_value, str(nested_key).lower())
        elif isinstance(value, list):
            for item in value:
                visit(item, key)
        elif value is not None and key in {"message", "error", "detail", "details", "reason"}:
            text = str(value).strip()
            if text and text not in candidates:
                candidates.append(text)

    visit(data)
    return " | ".join(candidates[:4])


def _video_pricing_label(video_metadata: Dict[str, Any]) -> str:
    pricing = video_metadata.get("pricing_skus") or {}
    if not pricing:
        return "Video pricing: unavailable"

    rows: List[Tuple[float, str]] = []
    for sku, value in pricing.items():
        price = _to_float(value)
        if price > 0:
            rows.append((price, str(sku)))
    if not rows:
        return "Video pricing: unavailable"

    rows.sort(key=lambda item: item[0])
    parts = [f"${price:.4f}/{_video_price_unit(sku)}" for price, sku in rows[:4]]
    return f"Video pricing: {' | '.join(parts)}"


def _video_price_unit(sku: str) -> str:
    text = sku.replace("_", " ")
    if "duration seconds" in text:
        unit = "sec"
    elif "video tokens" in text:
        unit = "video token"
    else:
        unit = "unit"

    details: List[str] = []
    if "with audio" in text:
        details.append("audio")
    elif "without audio" in text:
        details.append("no audio")
    for resolution in ("480p", "720p", "1080p", "4k"):
        if resolution in text:
            details.append(resolution.upper() if resolution == "4k" else resolution)
    return f"{unit} ({', '.join(details)})" if details else unit


def _name_sort_key(model: ModelInfo) -> Tuple[str, str, str]:
    return (model.company.lower(), model.name.lower(), model.model_id.lower())


def sort_models(models: List[ModelInfo], mode: str = "name_az") -> List[ModelInfo]:
    if mode == "name_za":
        return sorted(models, key=_name_sort_key, reverse=True)
    if mode == "newest":
        return sorted(
            models,
            key=lambda m: (
                m.release_timestamp is None,
                -(m.release_timestamp or 0),
                *_name_sort_key(m),
            ),
        )
    if mode == "oldest":
        return sorted(
            models,
            key=lambda m: (
                m.release_timestamp is None,
                m.release_timestamp or 0,
                *_name_sort_key(m),
            ),
        )
    return sorted(models, key=_name_sort_key)


def calculate_interaction_cost(
    prompt_tokens: int,
    completion_tokens: int,
    pricing: Pricing,
) -> float:
    return (
        (prompt_tokens * pricing.prompt)
        + (completion_tokens * pricing.completion)
        + pricing.request
    )


@dataclass
class SpeechSynthesisResult:
    """Result of POST /audio/speech: audio bytes plus optional OpenRouter generation id."""

    audio: bytes
    generation_id: Optional[str] = None


def generation_total_cost(payload: Dict[str, Any]) -> float:
    """USD total from GET /generation JSON (`data.total_cost`)."""
    data = payload.get("data")
    if not isinstance(data, dict):
        return 0.0
    raw = data.get("total_cost")
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def build_request_messages(
    history: List[Dict[str, Any]],
    system_prompt: str = "",
    extra_system: str = "",
) -> List[Dict[str, Any]]:
    base = system_prompt.strip()
    extra = extra_system.strip()
    if extra:
        merged = f"{base}\n\n{extra}" if base else extra
    else:
        merged = base
    if not merged:
        return list(history)
    return [{"role": "system", "content": merged}, *history]


def parse_stream_data(data: str) -> Optional[Dict[str, Any]]:
    if data == "[DONE]":
        return {"type": "done"}
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None

    if payload.get("error"):
        error = payload["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        return {"type": "error", "message": message or "OpenRouter stream error"}

    usage = payload.get("usage")
    if usage:
        return {"type": "usage", "usage": usage}

    choice = (payload.get("choices") or [{}])[0]
    delta = choice.get("delta") or {}
    content = delta.get("content")
    if content:
        return {"type": "text", "content": content}

    images = delta.get("images") or choice.get("message", {}).get("images")
    if images:
        return {"type": "images", "images": images}

    return None


def image_generation_payload(
    model_id: str,
    messages: List[Dict[str, Any]],
    native_image_output: bool,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model_id,
        "messages": messages,
    }
    if native_image_output:
        payload["modalities"] = ["text", "image"]
    else:
        payload["tools"] = [{"type": "openrouter:image_generation"}]
    return payload


def video_generation_payload(
    model_id: str,
    prompt: str,
    duration: int = 8,
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    generate_audio: bool = True,
    input_references: Optional[List[Dict[str, Any]]] = None,
    frame_images: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model_id,
        "prompt": prompt,
        "duration": duration,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "generate_audio": generate_audio,
    }
    if frame_images:
        payload["frame_images"] = frame_images
    if input_references:
        payload["input_references"] = input_references
    return payload


def extract_image_urls(payload: Dict[str, Any]) -> List[str]:
    urls: List[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("url") and str(value.get("url")).startswith(("data:image/", "http://", "https://")):
                urls.append(str(value["url"]))
            if value.get("imageUrl") and isinstance(value["imageUrl"], str):
                urls.append(value["imageUrl"])
            if value.get("image_url") and isinstance(value["image_url"], str):
                urls.append(value["image_url"])
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and value.startswith(("data:image/", "http://", "https://")):
            urls.append(value)

    for choice in payload.get("choices") or []:
        visit(choice.get("message", {}))

    deduped: List[str] = []
    for url in urls:
        if url not in deduped:
            deduped.append(url)
    return deduped


def video_output_path(output_dir: Path, job_id: str, index: int = 0) -> Path:
    safe_job_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in job_id)
    return output_dir / f"modeldocker_video_{safe_job_id}_{index}.mp4"


def encode_file_as_data_url(file_path: str) -> Tuple[str, str]:
    path = Path(file_path)
    if not path.exists():
        raise OpenRouterError(f"Attachment not found: {file_path}")
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type:
        mime_type = "application/octet-stream"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return path.name, f"data:{mime_type};base64,{data}"


class OpenRouterClient:
    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        self.api_key = api_key.strip()
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=10.0, read=timeout, write=timeout, pool=10.0)
        )

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost/modeldocker",
            "X-Title": "ModelDocker Desktop",
        }

    def validate_key(self) -> Dict[str, Any]:
        response = self._get("/key")
        return self._handle_response(response).get("data", {})

    def get_key_info(self) -> Dict[str, Any]:
        return self.validate_key()

    def get_models(self) -> List[ModelInfo]:
        response = self._get("/models?output_modalities=all")
        payload = self._handle_response(response)
        video_models = self._get_video_models_by_id()
        models: List[ModelInfo] = []
        for item in payload.get("data", []):
            model_id = item.get("id", "")
            if not model_id:
                continue
            company = model_id.split("/", 1)[0] if "/" in model_id else "other"
            architecture = item.get("architecture") or {}
            input_modalities = _normalize_modalities(architecture.get("input_modalities"))
            output_modalities = _normalize_modalities(architecture.get("output_modalities"))
            modality = architecture.get("modality")
            models.append(
                ModelInfo(
                    model_id=model_id,
                    name=item.get("name") or model_id,
                    company=company.title(),
                    pricing=Pricing.from_api(item.get("pricing")),
                    input_modalities=input_modalities,
                    output_modalities=output_modalities,
                    modality=str(modality).lower() if modality else None,
                    supported_parameters=[str(v) for v in item.get("supported_parameters") or []],
                    architecture=architecture,
                    video_metadata=video_models.get(model_id, {}),
                    raw=item,
                )
            )
        return sort_models(models)

    def _get_video_models_by_id(self) -> Dict[str, Dict[str, Any]]:
        try:
            response = self._get("/videos/models")
            payload = self._handle_response(response)
        except OpenRouterError:
            return {}
        return {
            str(item.get("id")): item
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        }

    def chat(
        self,
        model_id: str,
        messages: List[Dict[str, Any]],
        modalities: Optional[List[str]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model_id,
            "messages": messages,
        }
        if modalities:
            payload["modalities"] = modalities
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if max_tokens is not None and max_tokens > 0:
            payload["max_tokens"] = int(max_tokens)
        response = self._post(
            "/chat/completions",
            payload,
        )
        return self._handle_response(response)

    def generate_image(
        self,
        model_id: str,
        messages: List[Dict[str, Any]],
        native_image_output: bool,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload = image_generation_payload(model_id, messages, native_image_output)
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if max_tokens is not None and max_tokens > 0:
            payload["max_tokens"] = int(max_tokens)
        response = self._post(
            "/chat/completions",
            payload,
        )
        return self._handle_response(response)

    def generate_video(
        self,
        model_id: str,
        prompt: str,
        output_dir: str,
        duration: int = 8,
        resolution: str = "720p",
        aspect_ratio: str = "16:9",
        generate_audio: bool = True,
        input_references: Optional[List[Dict[str, Any]]] = None,
        frame_images: Optional[List[Dict[str, Any]]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        poll_interval_seconds: float = 5.0,
        timeout_seconds: float = 900.0,
    ) -> Dict[str, Any]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        submit = self._post(
            "/videos",
            video_generation_payload(
                model_id=model_id,
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                generate_audio=generate_audio,
                input_references=input_references,
                frame_images=frame_images,
            ),
        )
        job = self._handle_response(submit)
        job_id = job.get("id")
        if not job_id:
            raise OpenRouterError("OpenRouter did not return a video job ID.")

        deadline = time.monotonic() + timeout_seconds
        started_at = time.monotonic()
        poll_url = job.get("polling_url") or f"{OPENROUTER_BASE_URL}/videos/{job_id}"
        last_status = job
        while time.monotonic() < deadline:
            status = str(last_status.get("status", "")).lower()
            if progress_callback:
                progress_callback(
                    {
                        "id": job_id,
                        "status": status or "submitted",
                        "progress": last_status.get("progress") or last_status.get("percent_complete"),
                        "elapsed_seconds": int(time.monotonic() - started_at),
                    }
                )
            if status == "completed":
                urls = last_status.get("unsigned_urls") or []
                if not urls:
                    raise OpenRouterError("Video job completed, but no video URL was returned.")
                saved_paths: List[str] = []
                for index, url in enumerate(urls):
                    target = video_output_path(output_path, str(job_id), index)
                    self._download(url, target)
                    saved_paths.append(str(target))
                last_status["saved_paths"] = saved_paths
                return last_status
            if status in {"failed", "cancelled", "expired"}:
                raise OpenRouterError(_error_message(last_status) or f"Video generation {status}.")
            time.sleep(poll_interval_seconds)
            poll_response = self._get_url(str(poll_url))
            last_status = self._handle_response(poll_response)

        raise OpenRouterError("Video generation timed out before completion.")

    def chat_stream(
        self,
        model_id: str,
        messages: List[Dict[str, Any]],
        modalities: Optional[List[str]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if modalities:
            payload["modalities"] = modalities
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if max_tokens is not None and max_tokens > 0:
            payload["max_tokens"] = int(max_tokens)

        buffer = ""
        try:
            with self._client.stream(
                "POST",
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=self.headers,
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    try:
                        data = json.loads(response.read().decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        data = {}
                    message = (
                        data.get("error", {}).get("message")
                        or data.get("message")
                        or f"OpenRouter stream failed with HTTP {response.status_code}"
                    )
                    raise OpenRouterError(message)
                for chunk in response.iter_text():
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line or line.startswith(":") or not line.startswith("data:"):
                            continue
                        event = parse_stream_data(line[5:].strip())
                        if event:
                            yield event
                        if event and event.get("type") == "done":
                            return
        except httpx.TimeoutException as exc:
            raise OpenRouterError("OpenRouter stream timed out. Check your network connection.") from exc
        except httpx.RequestError as exc:
            raise OpenRouterError(f"Unable to stream from OpenRouter: {exc}") from exc

    def create_speech(
        self,
        text: str,
        *,
        model: str,
        voice: str = "alloy",
        response_format: str = "mp3",
        speed: float = 1.0,
        timeout: float = 120.0,
    ) -> SpeechSynthesisResult:
        """OpenRouter TTS (OpenAI-compatible speech endpoint). Returns audio and optional generation id."""
        payload: Dict[str, Any] = {
            "input": text,
            "model": model,
            "voice": voice,
            "response_format": response_format,
            "speed": float(speed),
        }
        try:
            response = self._client.post(
                f"{OPENROUTER_BASE_URL}/audio/speech",
                headers=self.headers,
                json=payload,
                timeout=httpx.Timeout(timeout, connect=10.0, read=timeout, write=30.0, pool=10.0),
            )
        except httpx.TimeoutException as exc:
            raise OpenRouterError("OpenRouter TTS timed out. Check your network connection.") from exc
        except httpx.RequestError as exc:
            raise OpenRouterError(f"Unable to reach OpenRouter for TTS: {exc}") from exc

        if response.status_code >= 400:
            try:
                data = response.json()
            except ValueError:
                data = {}
            message = _error_message(data) if isinstance(data, dict) else ""
            if not message:
                message = response.text.strip() or f"OpenRouter TTS failed with HTTP {response.status_code}"
            raise OpenRouterError(message)
        gen_id = response.headers.get("x-generation-id") or response.headers.get("X-Generation-Id")
        if gen_id:
            gen_id = gen_id.strip() or None
        return SpeechSynthesisResult(audio=response.content, generation_id=gen_id)

    def get_generation(self, generation_id: str) -> Dict[str, Any]:
        """GET /generation?id=... — usage and billed total_cost for a generation (e.g. TTS)."""
        qid = quote(generation_id, safe="")
        response = self._get(f"/generation?id={qid}")
        return self._handle_response(response)

    def fetch_generation_total_cost(
        self,
        generation_id: str,
        *,
        attempts: int = 5,
        backoff_sec: float = 0.28,
    ) -> float:
        """Poll generation metadata until total_cost is present (metadata may lag slightly)."""
        for attempt in range(attempts):
            if attempt:
                time.sleep(backoff_sec)
            try:
                payload = self.get_generation(generation_id)
            except OpenRouterError:
                if attempt >= attempts - 1:
                    return 0.0
                continue
            data = payload.get("data")
            if isinstance(data, dict) and data.get("total_cost") is not None:
                return generation_total_cost(payload)
        return 0.0

    def _get(self, path: str) -> httpx.Response:
        try:
            return self._client.get(f"{OPENROUTER_BASE_URL}{path}", headers=self.headers)
        except httpx.TimeoutException as exc:
            raise OpenRouterError("OpenRouter request timed out. Check your network connection.") from exc
        except httpx.RequestError as exc:
            raise OpenRouterError(f"Unable to reach OpenRouter: {exc}") from exc

    def _get_url(self, url: str) -> httpx.Response:
        try:
            return self._client.get(url, headers=self.headers)
        except httpx.TimeoutException as exc:
            raise OpenRouterError("OpenRouter request timed out. Check your network connection.") from exc
        except httpx.RequestError as exc:
            raise OpenRouterError(f"Unable to reach OpenRouter: {exc}") from exc

    def _post(self, path: str, payload: Dict[str, Any]) -> httpx.Response:
        try:
            return self._client.post(
                f"{OPENROUTER_BASE_URL}{path}",
                headers=self.headers,
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise OpenRouterError("OpenRouter request timed out. Check your network connection.") from exc
        except httpx.RequestError as exc:
            raise OpenRouterError(f"Unable to reach OpenRouter: {exc}") from exc

    def _download(self, url: str, target: Path) -> None:
        try:
            with self._client.stream("GET", url, headers=self.headers) as response:
                if response.status_code >= 400:
                    raise OpenRouterError(f"Video download failed with HTTP {response.status_code}")
                with target.open("wb") as file:
                    for chunk in response.iter_bytes():
                        file.write(chunk)
        except httpx.TimeoutException as exc:
            raise OpenRouterError("Video download timed out. Check your network connection.") from exc
        except httpx.RequestError as exc:
            raise OpenRouterError(f"Unable to download generated video: {exc}") from exc

    def _handle_response(self, response: httpx.Response) -> Dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400:
            message = _error_message(data) if isinstance(data, dict) else ""
            if not message:
                message = response.text.strip() or f"OpenRouter request failed with HTTP {response.status_code}"
            raise OpenRouterError(message)
        if not isinstance(data, dict):
            raise OpenRouterError("Unexpected response format from OpenRouter.")
        return data

    def close(self) -> None:
        self._client.close()
