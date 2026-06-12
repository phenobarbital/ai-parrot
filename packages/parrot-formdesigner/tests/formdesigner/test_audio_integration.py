"""Integration tests for the audio renderer feature (FEAT-224 TASK-1466).

Tests the complete audio form lifecycle using an aiohttp test client.
All TTS/STT services are mocked — no GPU, network, or external API calls.
"""

from __future__ import annotations

import pytest
from aiohttp import web
from unittest.mock import AsyncMock, MagicMock

from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.api.render import _seed_default_renderers
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_form() -> FormSchema:
    """Simple 2-field integration test form."""
    return FormSchema(
        form_id="integration-test",
        title="Integration Test Form",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="What is your name?",
                        required=True,
                    ),
                    FormField(
                        field_id="note",
                        field_type=FieldType.AUDIO,
                        label="Leave a note",
                    ),
                ],
            )
        ],
    )


@pytest.fixture
def mock_registry(sample_form: FormSchema) -> AsyncMock:
    """Mock FormRegistry that returns sample_form for any get()."""
    registry = AsyncMock()
    registry.get.return_value = sample_form
    return registry


@pytest.fixture
def mock_synthesizer() -> AsyncMock:
    """Mock VoiceSynthesizer that returns dummy audio bytes."""
    synth = AsyncMock()
    synth.synthesize.return_value = MagicMock(
        audio=b"fake-audio", mime_format="audio/ogg"
    )
    return synth


@pytest.fixture
def mock_transcriber() -> AsyncMock:
    """Mock FasterWhisperBackend that returns fixed transcription."""
    transcriber = AsyncMock()
    transcriber.transcribe.return_value = MagicMock(
        text="hello", confidence=0.95, language="en",
        duration_seconds=1.0, processing_time_ms=100,
    )
    return transcriber


@pytest.fixture
def mock_token_validator() -> AsyncMock:
    """Mock TokenValidator that accepts any token."""
    from parrot.voice.handler import AuthenticatedUser  # type: ignore[import-untyped]

    validator = AsyncMock()
    validator.validate.return_value = AuthenticatedUser(
        user_id="test-user", username="testuser"
    )
    return validator


@pytest.fixture
def app(
    mock_registry: AsyncMock,
    mock_synthesizer: AsyncMock,
    mock_transcriber: AsyncMock,
    mock_token_validator: AsyncMock,
) -> web.Application:
    """Configured aiohttp application with all audio routes."""
    app = web.Application()
    setup_form_api(
        app,
        mock_registry,
        synthesizer=mock_synthesizer,
        transcriber=mock_transcriber,
        token_validator=mock_token_validator,
    )
    return app


# ---------------------------------------------------------------------------
# Render endpoint tests
# ---------------------------------------------------------------------------


class TestRenderEndpoint:
    """Tests for the audio render endpoint (handle_render called directly).

    These tests use handle_render without _wrap_auth to avoid the navigator-auth
    requirement in test environments. Production deployments use setup_form_api
    which wraps all render routes with is_authenticated.
    """

    @pytest.mark.asyncio
    async def test_audio_manifest_returned(
        self, aiohttp_client, sample_form: FormSchema
    ) -> None:
        """Audio render endpoint returns a valid AudioFormManifest JSON."""
        from parrot_formdesigner.api.render import _seed_default_renderers, handle_render
        from parrot_formdesigner.services.registry import FormRegistry

        _seed_default_renderers()
        registry = FormRegistry(require_tenant=False)
        await registry.register(sample_form)

        render_app = web.Application()
        render_app["form_registry"] = registry
        render_app.router.add_get(
            "/api/v1/forms/{form_id}/render/{format}", handle_render
        )

        client = await aiohttp_client(render_app)
        resp = await client.get("/api/v1/forms/integration-test/render/audio")
        assert resp.status == 200

        data = await resp.json()
        assert data["form_id"] == "integration-test"
        assert data["total_questions"] == 2
        assert "questions" in data
        assert "ws_endpoint" in data

    @pytest.mark.asyncio
    async def test_manifest_question_count(
        self, aiohttp_client, sample_form: FormSchema
    ) -> None:
        """Manifest total_questions counts only non-hidden fields."""
        from parrot_formdesigner.api.render import _seed_default_renderers, handle_render
        from parrot_formdesigner.services.registry import FormRegistry

        _seed_default_renderers()
        registry = FormRegistry(require_tenant=False)
        await registry.register(sample_form)

        render_app = web.Application()
        render_app["form_registry"] = registry
        render_app.router.add_get(
            "/api/v1/forms/{form_id}/render/{format}", handle_render
        )

        client = await aiohttp_client(render_app)
        resp = await client.get("/api/v1/forms/integration-test/render/audio")
        data = await resp.json()
        assert data["total_questions"] == 2

    @pytest.mark.asyncio
    async def test_manifest_ws_endpoint_format(
        self, aiohttp_client, sample_form: FormSchema
    ) -> None:
        """Manifest ws_endpoint contains the form ID and audio/ws path."""
        from parrot_formdesigner.api.render import _seed_default_renderers, handle_render
        from parrot_formdesigner.services.registry import FormRegistry

        _seed_default_renderers()
        registry = FormRegistry(require_tenant=False)
        await registry.register(sample_form)

        render_app = web.Application()
        render_app["form_registry"] = registry
        render_app.router.add_get(
            "/api/v1/forms/{form_id}/render/{format}", handle_render
        )

        client = await aiohttp_client(render_app)
        resp = await client.get("/api/v1/forms/integration-test/render/audio")
        data = await resp.json()
        assert "integration-test" in data["ws_endpoint"]
        assert "audio/ws" in data["ws_endpoint"]

    @pytest.mark.asyncio
    async def test_unknown_form_returns_404(
        self, aiohttp_client
    ) -> None:
        """Requesting render for a non-existent form returns 404."""
        from parrot_formdesigner.api.render import _seed_default_renderers, handle_render
        from parrot_formdesigner.services.registry import FormRegistry

        _seed_default_renderers()
        registry = FormRegistry()  # empty — no forms registered

        render_app = web.Application()
        render_app["form_registry"] = registry
        render_app.router.add_get(
            "/api/v1/forms/{form_id}/render/{format}", handle_render
        )

        client = await aiohttp_client(render_app)
        resp = await client.get("/api/v1/forms/nonexistent/render/audio")
        assert resp.status == 404


# ---------------------------------------------------------------------------
# WebSocket session lifecycle tests
# ---------------------------------------------------------------------------


class TestWebSocketSession:
    """Tests for the WebSocket audio form session."""

    @pytest.mark.asyncio
    async def test_auth_rejected_without_token(
        self, aiohttp_client, app: web.Application,
        mock_token_validator: AsyncMock
    ) -> None:
        """WebSocket connection without JWT token receives error and closes."""
        # Validator returns None for empty/missing token
        mock_token_validator.validate.return_value = None
        client = await aiohttp_client(app)

        async with client.ws_connect(
            "/api/v1/forms/integration-test/audio/ws"
        ) as ws:
            msg = await ws.receive_json()
            assert msg["type"] == "error"
            assert "auth" in msg["message"].lower() or "AUTH" in msg.get("code", "")

    @pytest.mark.asyncio
    async def test_start_session_sends_session_started(
        self, aiohttp_client, app: web.Application
    ) -> None:
        """start_session message triggers session_started response."""
        client = await aiohttp_client(app)

        async with client.ws_connect(
            "/api/v1/forms/integration-test/audio/ws",
            protocols=["test-jwt-token"],
        ) as ws:
            await ws.send_json({
                "type": "start_session",
                "form_id": "integration-test",
            })
            msg = await ws.receive_json()
            assert msg["type"] == "session_started"
            assert "session_id" in msg
            assert msg["total_questions"] == 2

    @pytest.mark.asyncio
    async def test_start_session_delivers_first_question(
        self, aiohttp_client, app: web.Application
    ) -> None:
        """After session_started, the first question is delivered."""
        client = await aiohttp_client(app)

        async with client.ws_connect(
            "/api/v1/forms/integration-test/audio/ws",
            protocols=["test-jwt-token"],
        ) as ws:
            await ws.send_json({
                "type": "start_session",
                "form_id": "integration-test",
            })
            # session_started
            await ws.receive_json()
            # first question
            q1 = await ws.receive_json()
            assert q1["type"] == "question"
            assert q1["index"] == 0
            assert q1["field_id"] == "name"

    @pytest.mark.asyncio
    async def test_text_answer_accepted(
        self, aiohttp_client, app: web.Application
    ) -> None:
        """answer_text message triggers answer_accepted response."""
        client = await aiohttp_client(app)

        async with client.ws_connect(
            "/api/v1/forms/integration-test/audio/ws",
            protocols=["test-jwt-token"],
        ) as ws:
            await ws.send_json({"type": "start_session", "form_id": "integration-test"})
            await ws.receive_json()  # session_started
            await ws.receive_json()  # question Q1

            await ws.send_json({
                "type": "answer_text",
                "field_id": "name",
                "value": "Alice",
            })
            ack = await ws.receive_json()
            assert ack["type"] == "answer_accepted"
            assert ack["field_id"] == "name"
            assert ack["value"] == "Alice"
            assert ack["source"] == "text"

    @pytest.mark.asyncio
    async def test_full_text_session_completes(
        self, aiohttp_client, app: web.Application
    ) -> None:
        """Answering all questions via answer_text results in form_complete."""
        client = await aiohttp_client(app)

        async with client.ws_connect(
            "/api/v1/forms/integration-test/audio/ws",
            protocols=["test-jwt-token"],
        ) as ws:
            await ws.send_json({"type": "start_session", "form_id": "integration-test"})
            await ws.receive_json()  # session_started
            await ws.receive_json()  # question Q1 (name)

            # Answer Q1
            await ws.send_json({
                "type": "answer_text",
                "field_id": "name",
                "value": "Alice",
            })
            await ws.receive_json()  # answer_accepted
            await ws.receive_json()  # question Q2 (note)

            # Answer Q2
            await ws.send_json({
                "type": "answer_text",
                "field_id": "note",
                "value": "Test note",
            })
            await ws.receive_json()  # answer_accepted
            complete = await ws.receive_json()
            assert complete["type"] == "form_complete"
            assert "answers" in complete

    @pytest.mark.asyncio
    async def test_ping_returns_pong(
        self, aiohttp_client, app: web.Application
    ) -> None:
        """ping message triggers pong response."""
        client = await aiohttp_client(app)

        async with client.ws_connect(
            "/api/v1/forms/integration-test/audio/ws",
            protocols=["test-jwt-token"],
        ) as ws:
            await ws.send_json({"type": "start_session", "form_id": "integration-test"})
            await ws.receive_json()  # session_started
            await ws.receive_json()  # question

            await ws.send_json({"type": "ping"})
            pong = await ws.receive_json()
            assert pong["type"] == "pong"

    @pytest.mark.asyncio
    async def test_skip_required_field_rejected(
        self, aiohttp_client, app: web.Application
    ) -> None:
        """Skipping a required field sends answer_rejected."""
        client = await aiohttp_client(app)

        async with client.ws_connect(
            "/api/v1/forms/integration-test/audio/ws",
            protocols=["test-jwt-token"],
        ) as ws:
            await ws.send_json({"type": "start_session", "form_id": "integration-test"})
            await ws.receive_json()  # session_started
            await ws.receive_json()  # Q1 (name, required=True)

            await ws.send_json({"type": "skip_question", "field_id": "name"})
            rejection = await ws.receive_json()
            assert rejection["type"] == "answer_rejected"

    @pytest.mark.asyncio
    async def test_unknown_message_type_returns_error(
        self, aiohttp_client, app: web.Application
    ) -> None:
        """Unknown message type triggers an error response."""
        client = await aiohttp_client(app)

        async with client.ws_connect(
            "/api/v1/forms/integration-test/audio/ws",
            protocols=["test-jwt-token"],
        ) as ws:
            await ws.send_json({"type": "start_session", "form_id": "integration-test"})
            await ws.receive_json()  # session_started
            await ws.receive_json()  # question

            await ws.send_json({"type": "unknown_type_xyz"})
            error = await ws.receive_json()
            assert error["type"] == "error"


# ---------------------------------------------------------------------------
# Audio renderer registration tests
# ---------------------------------------------------------------------------


class TestAudioRendererSeed:
    """Tests that the audio renderer is seeded correctly."""

    def test_audio_in_renderer_registry(self) -> None:
        """AudioFormRenderer is registered under 'audio' after seeding."""
        from parrot_formdesigner.api.render import _RENDERERS
        _seed_default_renderers()
        assert "audio" in _RENDERERS

    def test_all_default_renderers_present(self) -> None:
        """All V1+V2+FEAT-224 renderers are registered after seeding."""
        from parrot_formdesigner.api.render import _RENDERERS
        _seed_default_renderers()
        for key in ("html", "adaptive", "xml", "pdf", "audio"):
            assert key in _RENDERERS, f"Missing renderer: {key}"


# ---------------------------------------------------------------------------
# FEAT-236 TASK-1543: hybrid voice-flow integration tests
# ---------------------------------------------------------------------------


def _make_audio_app(
    form: FormSchema,
    synthesizer: AsyncMock,
    transcriber: AsyncMock,
    token_validator: AsyncMock,
) -> web.Application:
    """Build an aiohttp app with the audio WS mounted for ``form``."""
    registry = AsyncMock()
    registry.get.return_value = form
    app = web.Application()
    setup_form_api(
        app,
        registry,
        synthesizer=synthesizer,
        transcriber=transcriber,
        token_validator=token_validator,
    )
    return app


@pytest.fixture
def mixed_app(
    mixed_mode_form: FormSchema,
    mock_synthesizer: AsyncMock,
    mock_transcriber: AsyncMock,
    mock_token_validator: AsyncMock,
) -> web.Application:
    """App serving the mixed-mode form (VOICE / PROMPT_SELECT / VISUAL_FALLBACK)."""
    return _make_audio_app(
        mixed_mode_form, mock_synthesizer, mock_transcriber, mock_token_validator
    )


async def _start(ws) -> dict:
    """Send start_session and return the first question message."""
    await ws.send_json({"type": "start_session", "form_id": "mixed-mode-form"})
    await ws.receive_json()  # session_started
    return await ws.receive_json()  # first question


class TestHybridVoiceFlows:
    """End-to-end hybrid voice flows over a real (in-process) WebSocket."""

    @pytest.mark.asyncio
    async def test_ws_prompt_select_flow(
        self, aiohttp_client, mixed_app: web.Application
    ) -> None:
        """PROMPT_SELECT question carries options; answer_selection advances."""
        client = await aiohttp_client(mixed_app)
        async with client.ws_connect(
            "/api/v1/forms/mixed-mode-form/audio/ws", protocols=["t"]
        ) as ws:
            q1 = await _start(ws)
            assert q1["field_id"] == "name"
            assert q1["voice_mode"] == "voice"

            await ws.send_json({"type": "answer_text", "field_id": "name", "value": "Alice"})
            await ws.receive_json()  # answer_accepted
            q2 = await ws.receive_json()  # color (PROMPT_SELECT)
            assert q2["field_id"] == "color"
            assert q2["voice_mode"] == "prompt_select"
            assert q2["render_mode"] == "select"
            assert q2["options"]

            await ws.send_json(
                {"type": "answer_selection", "field_id": "color", "value": "red"}
            )
            ack = await ws.receive_json()
            assert ack["type"] == "answer_accepted"
            assert ack["source"] == "selection"

    @pytest.mark.asyncio
    async def test_ws_multi_select_values(
        self, aiohttp_client, mock_synthesizer: AsyncMock,
        mock_transcriber: AsyncMock, mock_token_validator: AsyncMock,
    ) -> None:
        """answer_selection {values:[...]} is stored for a multi_select field."""
        from parrot_formdesigner.core.options import FieldOption

        form = FormSchema(
            form_id="multi-form", title="Multi",
            sections=[FormSection(section_id="s1", fields=[
                FormField(
                    field_id="tags", field_type=FieldType.MULTI_SELECT,
                    label="Pick tags", required=True,
                    options=[
                        FieldOption(value="a", label="A"),
                        FieldOption(value="b", label="B"),
                        FieldOption(value="c", label="C"),
                    ],
                ),
            ])],
        )
        app = _make_audio_app(
            form, mock_synthesizer, mock_transcriber, mock_token_validator
        )
        client = await aiohttp_client(app)
        async with client.ws_connect(
            "/api/v1/forms/multi-form/audio/ws", protocols=["t"]
        ) as ws:
            await ws.send_json({"type": "start_session", "form_id": "multi-form"})
            await ws.receive_json()  # session_started
            q = await ws.receive_json()
            assert q["voice_mode"] == "prompt_select"

            await ws.send_json(
                {"type": "answer_selection", "field_id": "tags", "values": ["a", "c"]}
            )
            ack = await ws.receive_json()
            assert ack["type"] == "answer_accepted"
            assert ack["value"] == "a,c"
            complete = await ws.receive_json()
            assert complete["type"] == "form_complete"

    @pytest.mark.asyncio
    async def test_ws_visual_fallback_flow(
        self, aiohttp_client, mixed_app: web.Application
    ) -> None:
        """A required REST field is completed via answer_payload → form_complete."""
        client = await aiohttp_client(mixed_app)
        async with client.ws_connect(
            "/api/v1/forms/mixed-mode-form/audio/ws", protocols=["t"]
        ) as ws:
            await _start(ws)  # name
            await ws.send_json({"type": "answer_text", "field_id": "name", "value": "Alice"})
            await ws.receive_json()  # accepted
            await ws.receive_json()  # color
            await ws.send_json(
                {"type": "answer_selection", "field_id": "color", "value": "blue"}
            )
            await ws.receive_json()  # accepted
            q3 = await ws.receive_json()  # doc (REST, VISUAL_FALLBACK)
            assert q3["field_id"] == "doc"
            assert q3["voice_mode"] == "visual_fallback"
            assert q3["render_mode"] == "visual"
            assert q3.get("fallback_html")

            await ws.send_json(
                {"type": "answer_payload", "field_id": "doc", "value": "blob://doc-1"}
            )
            await ws.receive_json()  # accepted
            complete = await ws.receive_json()
            assert complete["type"] == "form_complete"
            assert complete["answers"]["doc"]["value"] == "blob://doc-1"

    @pytest.mark.asyncio
    async def test_ws_low_confidence_confirm(
        self, aiohttp_client, mixed_app: web.Application,
        mock_transcriber: AsyncMock,
    ) -> None:
        """Low-confidence speech → confirm_request; confirm true stores it."""
        mock_transcriber.transcribe.return_value = MagicMock(
            text="Alice", confidence=0.2, language="en",
        )
        client = await aiohttp_client(mixed_app)
        async with client.ws_connect(
            "/api/v1/forms/mixed-mode-form/audio/ws", protocols=["t"]
        ) as ws:
            await _start(ws)  # name
            await ws.send_bytes(b"fake-audio-frame")
            await ws.receive_json()  # transcription
            confirm = await ws.receive_json()
            assert confirm["type"] == "confirm_request"
            assert confirm["field_id"] == "name"

            await ws.send_json(
                {"type": "confirm_answer", "field_id": "name", "confirmed": True}
            )
            ack = await ws.receive_json()
            assert ack["type"] == "answer_accepted"
            assert ack["value"] == "Alice"

    @pytest.mark.asyncio
    async def test_ws_low_confidence_reject_reprompts(
        self, aiohttp_client, mixed_app: web.Application,
        mock_transcriber: AsyncMock,
    ) -> None:
        """confirm false re-sends the same question and stores nothing."""
        mock_transcriber.transcribe.return_value = MagicMock(
            text="Alice", confidence=0.2, language="en",
        )
        client = await aiohttp_client(mixed_app)
        async with client.ws_connect(
            "/api/v1/forms/mixed-mode-form/audio/ws", protocols=["t"]
        ) as ws:
            await _start(ws)  # name
            await ws.send_bytes(b"fake-audio-frame")
            await ws.receive_json()  # transcription
            await ws.receive_json()  # confirm_request

            await ws.send_json(
                {"type": "confirm_answer", "field_id": "name", "confirmed": False}
            )
            requeued = await ws.receive_json()
            assert requeued["type"] == "question"
            assert requeued["field_id"] == "name"

    @pytest.mark.asyncio
    async def test_ws_high_confidence_auto_advance(
        self, aiohttp_client, mixed_app: web.Application,
        mock_transcriber: AsyncMock,
    ) -> None:
        """High-confidence speech auto-advances (no confirm_request)."""
        mock_transcriber.transcribe.return_value = MagicMock(
            text="Alice", confidence=0.96, language="en",
        )
        client = await aiohttp_client(mixed_app)
        async with client.ws_connect(
            "/api/v1/forms/mixed-mode-form/audio/ws", protocols=["t"]
        ) as ws:
            await _start(ws)  # name
            await ws.send_bytes(b"fake-audio-frame")
            await ws.receive_json()  # transcription
            nxt = await ws.receive_json()
            # Next message is answer_accepted, then the next question — never a
            # confirm_request.
            assert nxt["type"] in ("answer_accepted", "question")
            assert nxt["type"] != "confirm_request"

    @pytest.mark.asyncio
    async def test_ws_sensitive_no_audio(
        self, aiohttp_client, mock_synthesizer: AsyncMock,
        mock_transcriber: AsyncMock, mock_token_validator: AsyncMock,
    ) -> None:
        """A password question is delivered without TTS audio."""
        form = FormSchema(
            form_id="pw-form", title="PW",
            sections=[FormSection(section_id="s1", fields=[
                FormField(
                    field_id="pw", field_type=FieldType.PASSWORD,
                    label="Choose a password", required=True,
                ),
            ])],
        )
        app = _make_audio_app(
            form, mock_synthesizer, mock_transcriber, mock_token_validator
        )
        client = await aiohttp_client(app)
        async with client.ws_connect(
            "/api/v1/forms/pw-form/audio/ws", protocols=["t"]
        ) as ws:
            await ws.send_json({"type": "start_session", "form_id": "pw-form"})
            await ws.receive_json()  # session_started
            q = await ws.receive_json()
            assert q["field_id"] == "pw"
            assert q["sensitive"] is True
            assert "audio" not in q

    @pytest.mark.asyncio
    async def test_ws_supertonic_to_google_degradation(
        self, aiohttp_client, mixed_app: web.Application,
        mock_synthesizer: AsyncMock,
    ) -> None:
        """When the synthesizer fails, questions still deliver (text-only)."""
        mock_synthesizer.synthesize.side_effect = RuntimeError(
            "SuperTonic weights unavailable"
        )
        client = await aiohttp_client(mixed_app)
        async with client.ws_connect(
            "/api/v1/forms/mixed-mode-form/audio/ws", protocols=["t"]
        ) as ws:
            q1 = await _start(ws)
            # Degraded to text-only: the question is delivered without audio,
            # and the session is fully usable.
            assert q1["type"] == "question"
            assert q1["field_id"] == "name"
            assert "audio" not in q1

            await ws.send_json({"type": "answer_text", "field_id": "name", "value": "Bob"})
            ack = await ws.receive_json()
            assert ack["type"] == "answer_accepted"
