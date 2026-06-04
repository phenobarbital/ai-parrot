"""Integration tests for the audio renderer feature (FEAT-224 TASK-1466).

Tests the complete audio form lifecycle using an aiohttp test client.
All TTS/STT services are mocked — no GPU, network, or external API calls.
"""

from __future__ import annotations

import json
import pytest
from aiohttp import web
from unittest.mock import AsyncMock, MagicMock

from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.api.render import _seed_default_renderers
from parrot_formdesigner.audio.models import AudioFormManifest
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
        from parrot_formdesigner.api.render import _RENDERERS, _seed_default_renderers, handle_render
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
        from parrot_formdesigner.api.render import _RENDERERS, _seed_default_renderers, handle_render
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
        from parrot_formdesigner.api.render import _RENDERERS, _seed_default_renderers, handle_render
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
        from parrot_formdesigner.api.render import _RENDERERS, _seed_default_renderers, handle_render
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
