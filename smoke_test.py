import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from memory_store import MAX_MEMORIES_IN_PROMPT, Memory, MemoryStore
from openrouter_client import (
    ModelInfo,
    OpenRouterClient,
    OpenRouterError,
    Pricing,
    SpeechSynthesisResult,
    generation_total_cost,
    build_request_messages,
    calculate_interaction_cost,
    extract_image_urls,
    image_generation_payload,
    parse_stream_data,
    sort_models,
    video_generation_payload,
    video_output_path,
)
from role_store import (
    BUILTIN_RECOMMENDED_MODELS,
    CAR_MECHANIC_ROLE_ID,
    CHRISTIAN_SPIRITUAL_TEACHER_ROLE_ID,
    DEFAULT_ROLE_ID,
    ELECTRICAL_TECHNICIAN_ROLE_ID,
    GOURMET_CHEF_ROLE_ID,
    HANDYMAN_ROLE_ID,
    HOLISTIC_DOCTOR_ROLE_ID,
    IT_SPECIALIST_ROLE_ID,
    NEURODIVERSITY_PARENT_COACH_ROLE_ID,
    OBSTETRICIAN_ROLE_ID,
    HILLBILLY_LIFE_COACH_ROLE_ID,
    HILLBILLY_LIFE_COACH_PREVIOUS_RECOMMENDED_MODEL,
    HILLBILLY_LIFE_COACH_RECOMMENDED_MODEL,
    Role,
    RoleStore,
    recommended_model_for_role,
)
from session_store import Session, SessionStore
from session_title_parse import (
    SESSION_TITLE_BEGIN,
    SESSION_TITLE_END,
    StreamingSessionTitleParser,
    sanitize_session_title,
    split_first_turn_response,
)


def test_sort_models() -> None:
    models = [
        ModelInfo("openai/gpt-4o", "GPT-4o", "Openai"),
        ModelInfo("anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet", "Anthropic"),
        ModelInfo("google/gemini-2.0-flash", "Gemini 2.0 Flash", "Google"),
    ]
    sorted_models = sort_models(models)
    assert [m.company for m in sorted_models] == ["Anthropic", "Google", "Openai"]


def test_sort_models_modes() -> None:
    models = [
        ModelInfo("zeta/new", "New", "Zeta", raw={"created": 1735689600}),
        ModelInfo("alpha/old", "Old", "Alpha", raw={"created": 1704067200}),
        ModelInfo("beta/unknown", "Unknown", "Beta"),
    ]

    assert [m.model_id for m in sort_models(models, "name_az")] == [
        "alpha/old",
        "beta/unknown",
        "zeta/new",
    ]
    assert [m.model_id for m in sort_models(models, "name_za")] == [
        "zeta/new",
        "beta/unknown",
        "alpha/old",
    ]
    assert [m.model_id for m in sort_models(models, "newest")] == [
        "zeta/new",
        "alpha/old",
        "beta/unknown",
    ]
    assert [m.model_id for m in sort_models(models, "oldest")] == [
        "alpha/old",
        "zeta/new",
        "beta/unknown",
    ]


def test_cost_calculation() -> None:
    pricing = Pricing(prompt=0.000001, completion=0.000002, request=0.001)
    cost = calculate_interaction_cost(prompt_tokens=1000, completion_tokens=500, pricing=pricing)
    assert abs(cost - 0.003) < 1e-9


def test_modality_labels_and_upload_gating() -> None:
    model = ModelInfo(
        "google/gemini-test",
        "Gemini Test",
        "Google",
        input_modalities=["text", "image", "file"],
        output_modalities=["text"],
        raw={"created": 1704067200},
    )
    assert model.supports_image_input
    assert model.supports_pdf_input
    assert model.capability_label == "In: 📝 🖼️ 📄 | Out: 📝"
    assert model.release_date_label == "Released 2024-01-01"
    assert "Released 2024-01-01" in model.label
    assert "In: 📝 🖼️ 📄 | Out: 📝" in model.label


def test_image_output_does_not_enable_image_upload() -> None:
    model = ModelInfo(
        "image/provider",
        "Image Generator",
        "Image",
        input_modalities=["text"],
        output_modalities=["image"],
    )
    assert not model.supports_image_input
    assert not model.supports_pdf_input
    assert model.supports_image_output
    assert not model.supports_text_output


def test_text_and_image_output_flags() -> None:
    model = ModelInfo(
        "google/gemini-image",
        "Gemini Image",
        "Google",
        input_modalities=["text", "image"],
        output_modalities=["text", "image"],
    )
    assert model.supports_image_input
    assert model.supports_image_output
    assert model.supports_text_output


def test_video_output_flag_and_label() -> None:
    model = ModelInfo(
        "google/veo-test",
        "Veo Test",
        "Google",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        video_metadata={
            "supported_durations": [4, 6, 8],
            "supported_resolutions": ["720p", "1080p"],
            "supported_aspect_ratios": ["16:9", "9:16"],
            "generate_audio": True,
            "pricing_skus": {
                "duration_seconds_without_audio_720p": "0.03",
                "duration_seconds_with_audio_720p": "0.05",
            }
        },
    )
    assert model.supports_video_output
    assert "Generate video: yes" in model.friendly_capability_label
    assert "Out: 🎞️" in model.label
    assert "$0.0300/sec (no audio, 720p)" in model.video_pricing_label
    assert "$0.0500/sec (audio, 720p)" in model.video_pricing_label
    assert model.supported_video_durations == [4, 6, 8]
    assert model.supported_video_resolutions == ["720p", "1080p"]
    assert model.supported_video_aspect_ratios == ["16:9", "9:16"]
    assert model.supports_video_audio


def test_build_request_messages_with_system_prompt() -> None:
    history = [{"role": "user", "content": "Hello"}]
    messages = build_request_messages(history, "You are concise.")
    assert messages[0] == {"role": "system", "content": "You are concise."}
    assert messages[1:] == history
    assert build_request_messages(history, "   ") == history


def test_build_request_messages_extra_system() -> None:
    history = [{"role": "user", "content": "Hello"}]
    m = build_request_messages(history, "Base prompt.", extra_system="Extra rules.")
    assert m[0]["content"] == "Base prompt.\n\nExtra rules."
    only_extra = build_request_messages(history, "", extra_system="Rules only.")
    assert only_extra[0]["content"] == "Rules only."


def test_split_first_turn_response() -> None:
    raw = f"{SESSION_TITLE_BEGIN}\nOvercoming Doomscrolling\n{SESSION_TITLE_END}\n\nHere is my advice."
    title, answer = split_first_turn_response(raw)
    assert title == "Overcoming Doomscrolling"
    assert answer == "Here is my advice."
    assert split_first_turn_response("Plain answer only")[0] is None
    assert split_first_turn_response("Plain answer only")[1] == "Plain answer only"


def test_sanitize_session_title_long() -> None:
    long_line = "x" * 60
    assert len(sanitize_session_title(long_line)) <= 48


def test_streaming_session_title_parser_incremental() -> None:
    p = StreamingSessionTitleParser()
    chunks = [
        SESSION_TITLE_BEGIN[:10],
        SESSION_TITLE_BEGIN[10:] + "\nMy Subject Line\n",
        SESSION_TITLE_END[:5],
        SESSION_TITLE_END[5:] + "\n\nVisible reply.",
    ]
    visible = "".join(p.feed(c) for c in chunks)
    assert visible == "Visible reply."
    assert p.title == "My Subject Line"


def test_parse_stream_data() -> None:
    text_event = parse_stream_data(
        '{"choices":[{"delta":{"content":"Hi"}}]}'
    )
    assert text_event == {"type": "text", "content": "Hi"}

    usage_event = parse_stream_data(
        '{"usage":{"prompt_tokens":2,"completion_tokens":3}}'
    )
    assert usage_event == {
        "type": "usage",
        "usage": {"prompt_tokens": 2, "completion_tokens": 3},
    }
    assert parse_stream_data("[DONE]") == {"type": "done"}


def test_image_generation_payload_modes() -> None:
    history = [{"role": "user", "content": "Generate a cat"}]
    native = image_generation_payload("google/image-model", history, native_image_output=True)
    assert native["modalities"] == ["text", "image"]
    assert "tools" not in native

    fallback = image_generation_payload("qwen/text-model", history, native_image_output=False)
    assert fallback["tools"] == [{"type": "openrouter:image_generation"}]
    assert "modalities" not in fallback


def test_video_generation_payload() -> None:
    refs = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}]
    frames = [
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,first"},
            "frame_type": "first_frame",
        }
    ]
    payload = video_generation_payload(
        "google/veo-test",
        "A city skyline at sunset",
        duration=8,
        resolution="720p",
        aspect_ratio="16:9",
        input_references=refs,
        frame_images=frames,
    )
    assert payload["model"] == "google/veo-test"
    assert payload["prompt"] == "A city skyline at sunset"
    assert payload["duration"] == 8
    assert payload["resolution"] == "720p"
    assert payload["aspect_ratio"] == "16:9"
    assert payload["input_references"] == refs
    assert payload["frame_images"] == frames


def test_video_generation_payload_reference_only() -> None:
    refs = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,style"}}]
    payload = video_generation_payload(
        "alibaba/wan-test",
        "A robot reading a newspaper",
        input_references=refs,
    )
    assert payload["input_references"] == refs
    assert "frame_images" not in payload


def test_video_output_path_is_sanitized(tmp_path) -> None:
    path = video_output_path(tmp_path, "job/abc:123", 0)
    assert path.name == "modeldocker_video_job_abc_123_0.mp4"


def test_capability_helpers() -> None:
    model = ModelInfo(
        "openai/example",
        "Example",
        "Openai",
        supported_parameters=["tools", "tool_choice", "temperature", "web_search_options"],
        raw={"context_length": 128_000},
    )
    assert model.supports_tools
    assert model.supports_function_calling
    assert model.supports_web_search
    assert model.supports_temperature
    assert model.context_length == 128_000
    assert not model.supports_code_interpreter

    bare = ModelInfo("local/bare", "Bare", "Local")
    assert not bare.supports_tools
    assert not bare.supports_function_calling
    assert not bare.supports_web_search
    assert not bare.supports_temperature
    assert bare.context_length is None


def test_session_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = SessionStore(Path(tmp_dir))
        session = store.create("Quick test")
        session.system_prompt = "You are concise."
        session.temperature = 0.4
        session.model_id = "openai/gpt-4o"
        session.messages.append({"id": "m1", "role": "user", "content": "Hello"})
        session.messages.append({"id": "m2", "role": "assistant", "content": "Hi there!"})
        session.feedback = {"m2": "up"}
        session.total_cost = 0.0123
        session.total_prompt_tokens = 12
        session.total_completion_tokens = 8
        store.save(session)

        loaded = store.load(session.id)
        assert loaded is not None
        assert loaded.system_prompt == "You are concise."
        assert loaded.temperature == 0.4
        assert loaded.model_id == "openai/gpt-4o"
        assert loaded.messages[0]["content"] == "Hello"
        assert loaded.feedback.get("m2") == "up"
        assert loaded.total_prompt_tokens == 12

        store.rename(session.id, "Renamed")
        renamed = store.load(session.id)
        assert renamed is not None
        assert renamed.title == "Renamed"

        listed = store.list()
        assert any(item["id"] == session.id for item in listed)

        store.delete(session.id)
        assert store.load(session.id) is None
        assert all(item["id"] != session.id for item in store.list())


def test_session_title_derivation() -> None:
    session = Session(
        id="x",
        title="New Session",
        created_at=0.0,
        updated_at=0.0,
        messages=[
            {"role": "user", "content": "What is the capital of France?"},
        ],
    )
    assert session.derive_title().startswith("What is the capital")


def test_role_store_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "roles.json"
        store = RoleStore(path)

        # Seeded roles: Default + built-in specialist roles (when missing).
        default = store.ensure_default()
        assert default.id == DEFAULT_ROLE_ID
        assert default.title == "AI Assistant"
        listed_ids = [role.id for role in store.list()]
        assert listed_ids[0] == DEFAULT_ROLE_ID
        assert HOLISTIC_DOCTOR_ROLE_ID in listed_ids
        assert CAR_MECHANIC_ROLE_ID in listed_ids
        assert ELECTRICAL_TECHNICIAN_ROLE_ID in listed_ids
        assert IT_SPECIALIST_ROLE_ID in listed_ids
        assert GOURMET_CHEF_ROLE_ID in listed_ids
        assert CHRISTIAN_SPIRITUAL_TEACHER_ROLE_ID in listed_ids
        assert HANDYMAN_ROLE_ID in listed_ids
        assert NEURODIVERSITY_PARENT_COACH_ROLE_ID in listed_ids
        assert OBSTETRICIAN_ROLE_ID in listed_ids
        assert HILLBILLY_LIFE_COACH_ROLE_ID in listed_ids
        holistic = store.get(HOLISTIC_DOCTOR_ROLE_ID)
        assert holistic is not None
        assert holistic.title == "Holistic doctor"
        assert "evidence-based holistic" in holistic.prompt
        mechanic = store.get(CAR_MECHANIC_ROLE_ID)
        assert mechanic is not None
        assert mechanic.title == "Car mechanic"
        assert "evidence-based car mechanic" in mechanic.prompt
        elec = store.get(ELECTRICAL_TECHNICIAN_ROLE_ID)
        assert elec is not None
        assert elec.title == "Electrical Technician"
        assert "skilled electrical technician" in elec.prompt
        it_spec = store.get(IT_SPECIALIST_ROLE_ID)
        assert it_spec is not None
        assert it_spec.title == "IT Specialist"
        assert "highly competent computer support" in it_spec.prompt
        chef = store.get(GOURMET_CHEF_ROLE_ID)
        assert chef is not None
        assert chef.title == "Gourmet chef"
        assert "skilled gourmet chef" in chef.prompt
        spiritual = store.get(CHRISTIAN_SPIRITUAL_TEACHER_ROLE_ID)
        assert spiritual is not None
        assert spiritual.title == "Christian spiritual teacher"
        assert "compassionate Christian spiritual guide" in spiritual.prompt
        handyman = store.get(HANDYMAN_ROLE_ID)
        assert handyman is not None
        assert handyman.title == "Handyman"
        assert "skilled, safety-conscious home handyman" in handyman.prompt
        parent_coach = store.get(NEURODIVERSITY_PARENT_COACH_ROLE_ID)
        assert parent_coach is not None
        assert parent_coach.title == "Neurodiversity parent coach"
        assert "Pathological Demand Avoidance" in parent_coach.prompt
        assert "complete agenesis of the corpus callosum" in parent_coach.prompt
        obstetrician = store.get(OBSTETRICIAN_ROLE_ID)
        assert obstetrician is not None
        assert obstetrician.title == "Obstetrician"
        assert "evidence-based obstetrician" in obstetrician.prompt
        hillbilly = store.get(HILLBILLY_LIFE_COACH_ROLE_ID)
        assert hillbilly is not None
        assert hillbilly.title == "Hillbilly Life Coach"
        assert "wise Southern life coach" in hillbilly.prompt
        assert "Marcus Aurelius" in hillbilly.prompt

        # All built-in specialist roles get a recommended model on seed.
        for role_id, expected_model in BUILTIN_RECOMMENDED_MODELS.items():
            seeded = store.get(role_id)
            assert seeded is not None, role_id
            assert seeded.model_id == expected_model, (role_id, seeded.model_id)

        # ensure_default is idempotent.
        again = store.ensure_default()
        assert again.id == DEFAULT_ROLE_ID
        assert len(store.list()) == 11

        # Add a custom role; it appears after the built-in default role.
        custom = RoleStore.new_role("Electrical Specialist", "You are an EE expert.")
        store.upsert(custom)
        roles = store.list()
        assert len(roles) == 12
        assert roles[0].id == DEFAULT_ROLE_ID
        assert roles[1].id == HOLISTIC_DOCTOR_ROLE_ID
        assert roles[2].id == CAR_MECHANIC_ROLE_ID
        assert roles[3].id == ELECTRICAL_TECHNICIAN_ROLE_ID
        assert roles[4].id == IT_SPECIALIST_ROLE_ID
        assert roles[5].id == GOURMET_CHEF_ROLE_ID
        assert roles[6].id == CHRISTIAN_SPIRITUAL_TEACHER_ROLE_ID
        assert roles[7].id == HANDYMAN_ROLE_ID
        assert roles[8].id == NEURODIVERSITY_PARENT_COACH_ROLE_ID
        assert roles[9].id == OBSTETRICIAN_ROLE_ID
        assert roles[10].id == HILLBILLY_LIFE_COACH_ROLE_ID
        assert roles[11].id == custom.id
        assert store.get(custom.id).title == "Electrical Specialist"

        # Update via upsert; same id, new content. model_id round-trips too.
        updated = Role(
            id=custom.id,
            title="EE Specialist",
            prompt="Updated prompt",
            model_id="anthropic/claude-sonnet-4.6",
        )
        store.upsert(updated)
        round_trip = store.get(custom.id)
        assert round_trip.title == "EE Specialist"
        assert round_trip.prompt == "Updated prompt"
        assert round_trip.model_id == "anthropic/claude-sonnet-4.6"
        assert len(store.list()) == 12

        # set_model_id helper writes a per-role override and survives reload.
        store.set_model_id(custom.id, "openai/gpt-5.4")
        assert store.get(custom.id).model_id == "openai/gpt-5.4"
        # An explicit empty string means "fall through to global default" and
        # must not be replaced by recommendation backfill on a built-in.
        store.set_model_id(HOLISTIC_DOCTOR_ROLE_ID, "")
        assert store.get(HOLISTIC_DOCTOR_ROLE_ID).model_id == ""
        # Re-opening the store runs backfill again; the empty-string override
        # is preserved (only None is eligible for backfill).
        reopened_for_backfill = RoleStore(path)
        assert reopened_for_backfill.get(HOLISTIC_DOCTOR_ROLE_ID).model_id == ""
        # Restore the recommendation for the rest of the assertions below.
        store.set_model_id(
            HOLISTIC_DOCTOR_ROLE_ID,
            recommended_model_for_role(HOLISTIC_DOCTOR_ROLE_ID),
        )

        # Delete on the built-in default role id is a no-op.
        store.delete(DEFAULT_ROLE_ID)
        assert store.get(DEFAULT_ROLE_ID) is not None
        assert any(role.id == DEFAULT_ROLE_ID for role in store.list())

        # Delete a real role removes it.
        store.delete(custom.id)
        assert store.get(custom.id) is None
        assert len(store.list()) == 11

        # Persisted across instances.
        reopened = RoleStore(path)
        assert reopened.get(DEFAULT_ROLE_ID) is not None
        assert reopened.get(HOLISTIC_DOCTOR_ROLE_ID) is not None
        assert reopened.get(CAR_MECHANIC_ROLE_ID) is not None
        assert reopened.get(ELECTRICAL_TECHNICIAN_ROLE_ID) is not None
        assert reopened.get(IT_SPECIALIST_ROLE_ID) is not None
        assert reopened.get(GOURMET_CHEF_ROLE_ID) is not None
        assert reopened.get(CHRISTIAN_SPIRITUAL_TEACHER_ROLE_ID) is not None
        assert reopened.get(HANDYMAN_ROLE_ID) is not None
        assert reopened.get(NEURODIVERSITY_PARENT_COACH_ROLE_ID) is not None
        assert reopened.get(OBSTETRICIAN_ROLE_ID) is not None
        assert reopened.get(HILLBILLY_LIFE_COACH_ROLE_ID) is not None
        assert len(reopened.list()) == 11


def test_neurodiversity_parent_coach_prompt_migration() -> None:
    """Older installs with the stock parent-coach prompt get upgraded on load."""
    import json

    from role_store import NEURODIVERSITY_PARENT_COACH_ROLE_ID, NEURODIVERSITY_PARENT_COACH_TITLE

    old_prompt = (
        "You are a compassionate, evidence-informed parent coach helping an imaginary parent "
        "support a child with agenesis of the corpus callosum, ADHD, and Tourette syndrome.\n\n"
        "Your goal is to help.\n"
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "roles.json"
        payload = [
            {"id": DEFAULT_ROLE_ID, "title": "Default", "prompt": "You are a helpful assistant."},
            {
                "id": NEURODIVERSITY_PARENT_COACH_ROLE_ID,
                "title": NEURODIVERSITY_PARENT_COACH_TITLE,
                "prompt": old_prompt,
                "model_id": "anthropic/claude-opus-4.7",
            },
        ]
        path.write_text(json.dumps(payload), encoding="utf-8")

        store = RoleStore(path)
        upgraded = store.get(NEURODIVERSITY_PARENT_COACH_ROLE_ID)
        assert upgraded is not None
        assert "Pathological Demand Avoidance" in upgraded.prompt
        assert upgraded.model_id == "anthropic/claude-opus-4.7"
        assert store.get(DEFAULT_ROLE_ID).title == "AI Assistant"


def test_hillbilly_life_coach_model_migrates_from_previous_default() -> None:
    """Installs pinned to any prior Hillbilly default (Opus or the brief Veo
    mistake) get bumped to the current recommendation."""
    import json

    for prior_model in ("anthropic/claude-opus-4.7", "google/veo-3.1-lite"):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "roles.json"
            payload = [
                {"id": DEFAULT_ROLE_ID, "title": "AI Assistant", "prompt": "x", "model_id": "openrouter/free"},
                {
                    "id": HILLBILLY_LIFE_COACH_ROLE_ID,
                    "title": "Hillbilly Life Coach",
                    "prompt": "Howdy.",
                    "model_id": prior_model,
                },
            ]
            path.write_text(json.dumps(payload), encoding="utf-8")

            store = RoleStore(path)
            hb = store.get(HILLBILLY_LIFE_COACH_ROLE_ID)
            assert hb is not None, prior_model
            assert hb.model_id == HILLBILLY_LIFE_COACH_RECOMMENDED_MODEL, (
                prior_model,
                hb.model_id,
            )


def test_role_recommended_model_backfill() -> None:
    """A roles.json written by an older build (no model_id key on built-in
    roles) should get the per-role recommendations filled in on next load."""
    import json

    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "roles.json"
        legacy = [
            {"id": DEFAULT_ROLE_ID, "title": "Default", "prompt": "You are a helpful assistant."},
            {"id": HOLISTIC_DOCTOR_ROLE_ID, "title": "Holistic doctor", "prompt": "..."},
            {"id": OBSTETRICIAN_ROLE_ID, "title": "Obstetrician", "prompt": "..."},
        ]
        path.write_text(json.dumps(legacy), encoding="utf-8")

        store = RoleStore(path)
        # Built-ins without a model_id get the curated recommendation on init.
        assert store.get(HOLISTIC_DOCTOR_ROLE_ID).model_id == recommended_model_for_role(
            HOLISTIC_DOCTOR_ROLE_ID
        )
        assert store.get(OBSTETRICIAN_ROLE_ID).model_id == recommended_model_for_role(
            OBSTETRICIAN_ROLE_ID
        )
        assert store.get(DEFAULT_ROLE_ID).model_id == recommended_model_for_role(DEFAULT_ROLE_ID)
        assert store.get(DEFAULT_ROLE_ID).title == "AI Assistant"


def test_session_role_id_default_fallback() -> None:
    legacy = Session.from_dict({
        "id": "abc",
        "title": "Legacy",
        "created_at": 0.0,
        "updated_at": 0.0,
        "messages": [],
    })
    assert legacy.role_id == DEFAULT_ROLE_ID

    explicit = Session.from_dict({
        "id": "abc",
        "title": "Has role",
        "created_at": 0.0,
        "updated_at": 0.0,
        "role_id": "custom123",
    })
    assert explicit.role_id == "custom123"


def test_extract_image_urls() -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "images": [
                        {
                            "image_url": {
                                "url": "data:image/png;base64,abc"
                            }
                        }
                    ],
                    "content": [
                        {"type": "text", "text": "done"},
                        {"imageUrl": "https://example.com/generated.png"},
                    ],
                }
            }
        ]
    }
    assert extract_image_urls(payload) == [
        "data:image/png;base64,abc",
        "https://example.com/generated.png",
    ]


def test_create_speech_request_shape() -> None:
    client = OpenRouterClient("test-key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"fake-mp3-bytes"
    mock_resp.headers = MagicMock()
    mock_resp.headers.get = MagicMock(side_effect=lambda k, default=None: "gen-123" if k.lower() == "x-generation-id" else default)
    captured: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = dict(json) if json else {}
        return mock_resp

    client._client.post = MagicMock(side_effect=fake_post)
    result = client.create_speech("hello world", model="openai/gpt-4o-mini-tts", voice="alloy")
    assert isinstance(result, SpeechSynthesisResult)
    assert result.audio == b"fake-mp3-bytes"
    assert result.generation_id == "gen-123"
    assert captured["url"].endswith("/audio/speech")
    body = captured["json"]
    assert body["input"] == "hello world"
    assert body["model"] == "openai/gpt-4o-mini-tts"
    assert body["voice"] == "alloy"
    assert body["response_format"] == "mp3"
    assert body["speed"] == 1.0

    mock_err = MagicMock()
    mock_err.status_code = 402
    mock_err.json.return_value = {"error": {"message": "Insufficient credits"}}
    mock_err.text = ""
    client._client.post = MagicMock(return_value=mock_err)
    try:
        client.create_speech("x", model="m", voice="v")
    except OpenRouterError as exc:
        assert "Insufficient" in str(exc)
    else:
        raise AssertionError("expected OpenRouterError")


def test_generation_total_cost_parses_payload() -> None:
    assert generation_total_cost({}) == 0.0
    assert generation_total_cost({"data": {}}) == 0.0
    assert abs(generation_total_cost({"data": {"total_cost": 0.001234}}) - 0.001234) < 1e-12
    assert generation_total_cost({"data": {"total_cost": None}}) == 0.0
    assert generation_total_cost({"data": {"total_cost": "bad"}}) == 0.0


def test_get_generation_uses_quoted_id() -> None:
    client = OpenRouterClient("k")
    captured: list[str] = []

    def fake_get(url, headers=None):
        captured.append(url)
        mock_r = MagicMock()
        mock_r.status_code = 200
        mock_r.json.return_value = {"data": {"id": "x", "total_cost": 0.01}}
        return mock_r

    client._client.get = MagicMock(side_effect=fake_get)
    out = client.get_generation("gen/a+b")
    assert out["data"]["total_cost"] == 0.01
    assert "generation?id=" in captured[0]
    assert "gen%2Fa%2Bb" in captured[0] or "gen%2fa%2bb" in captured[0].lower()


def test_memory_store_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "memories.json"
        store = MemoryStore(path)
        mem = Memory(
            id="",
            text="  Prefer dark mode  ",
            role_id=None,
            enabled=True,
            created_at=0.0,
            updated_at=0.0,
        )
        store.upsert(mem)
        store2 = MemoryStore(path)
        loaded = store2.get(mem.id)
        assert loaded is not None
        assert loaded.text == "Prefer dark mode"


def test_memory_role_scoping_and_disabled() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mem.json"
        store = MemoryStore(path)
        store.upsert(
            Memory(id="g", text="global", role_id=None, enabled=True, created_at=0, updated_at=0)
        )
        store.upsert(
            Memory(
                id="c",
                text="car only",
                role_id=CAR_MECHANIC_ROLE_ID,
                enabled=True,
                created_at=0,
                updated_at=0,
            )
        )
        store.upsert(
            Memory(id="h", text="hidden", role_id=None, enabled=False, created_at=0, updated_at=0)
        )

        txt_default = store.format_for_prompt(DEFAULT_ROLE_ID)
        assert "global" in txt_default
        assert "car only" not in txt_default
        assert "hidden" not in txt_default

        txt_car = store.format_for_prompt(CAR_MECHANIC_ROLE_ID)
        assert "global" in txt_car
        assert "car only" in txt_car


def test_memory_format_respects_limit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mem.json"
        store = MemoryStore(path)
        for i in range(MAX_MEMORIES_IN_PROMPT + 3):
            store.upsert(
                Memory(
                    id="",
                    text=f"entry-{i}",
                    role_id=None,
                    enabled=True,
                    created_at=0,
                    updated_at=0,
                )
            )
        blob = store.format_for_prompt(DEFAULT_ROLE_ID, limit=MAX_MEMORIES_IN_PROMPT)
        assert blob.count("- ") == MAX_MEMORIES_IN_PROMPT
        bullet_lines = [ln for ln in blob.splitlines() if ln.strip().startswith("- ")]
        assert len(bullet_lines) == MAX_MEMORIES_IN_PROMPT


def test_build_request_messages_combines_memory_style_extra() -> None:
    extra = (
        "First extra block\n\n"
        "Relevant saved memory:\n"
        "- Fact one\n\n"
        "Use these memories only when relevant."
    )
    msgs = build_request_messages([{"role": "user", "content": "hi"}], "SYS", extra_system=extra)
    assert msgs[0]["role"] == "system"
    assert "SYS" in msgs[0]["content"]
    assert "Fact one" in msgs[0]["content"]


if __name__ == "__main__":
    test_sort_models()
    test_sort_models_modes()
    test_cost_calculation()
    test_modality_labels_and_upload_gating()
    test_image_output_does_not_enable_image_upload()
    test_text_and_image_output_flags()
    test_video_output_flag_and_label()
    test_build_request_messages_with_system_prompt()
    test_build_request_messages_extra_system()
    test_split_first_turn_response()
    test_sanitize_session_title_long()
    test_streaming_session_title_parser_incremental()
    test_parse_stream_data()
    test_image_generation_payload_modes()
    test_video_generation_payload()
    test_video_generation_payload_reference_only()
    test_video_output_path_is_sanitized(Path("."))
    test_capability_helpers()
    test_session_round_trip()
    test_session_title_derivation()
    test_role_store_round_trip()
    test_hillbilly_life_coach_model_migrates_from_previous_default()
    test_session_role_id_default_fallback()
    test_extract_image_urls()
    test_create_speech_request_shape()
    test_generation_total_cost_parses_payload()
    test_get_generation_uses_quoted_id()
    test_memory_store_round_trip()
    test_memory_role_scoping_and_disabled()
    test_memory_format_respects_limit()
    test_build_request_messages_combines_memory_style_extra()
    print("Smoke tests passed.")
