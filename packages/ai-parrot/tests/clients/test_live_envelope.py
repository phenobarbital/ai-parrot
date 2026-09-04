"""Envelope + voice-override tests for Gemini Live (FEAT-418, TASK-2167).

Covers spec §3 Module 3 (envelope half): canonical role on every
model-originated response, user transcription emitted as role="user"
instead of metadata["user_transcription"], and the per-call voice
override with catalog validation.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot.clients.google.live import GeminiLiveClient


class _FakeLiveSession:
    """Minimal stand-in for the google-genai Live WebSocket session."""

    def __init__(self, responses):
        self._responses = responses
        self.send_realtime_input = AsyncMock()
        self.send_tool_response = AsyncMock()
        self.send = AsyncMock()

    async def receive(self):
        for response in self._responses:
            yield response


class _FakeConnectCM:
    """Async context manager returned by ``client.aio.live.connect()``."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


class _FakeLiveNamespace:
    def __init__(self, session):
        self._session = session

    def connect(self, model=None, config=None):
        return _FakeConnectCM(self._session)


class _FakeAio:
    def __init__(self, session):
        self.live = _FakeLiveNamespace(session)


class _FakeSdkClient:
    def __init__(self, session):
        self.aio = _FakeAio(session)


async def _empty_audio_iterator():
    return
    yield  # pragma: no cover — makes this an async generator


def _mock_client(monkeypatch, client, responses):
    """Wire ``client`` to a fake SDK client that yields ``responses``."""
    session = _FakeLiveSession(responses)
    fake_sdk_client = _FakeSdkClient(session)
    monkeypatch.setattr(client, "get_client", AsyncMock(return_value=fake_sdk_client))
    return session


def _text_response(text: str):
    return SimpleNamespace(
        server_content=SimpleNamespace(
            model_turn=SimpleNamespace(
                parts=[SimpleNamespace(text=text, inline_data=None)]
            ),
        ),
        tool_call=None,
        usage_metadata=None,
        go_away=None,
    )


def _user_transcription_response(text: str):
    return SimpleNamespace(
        server_content=SimpleNamespace(
            input_transcription=SimpleNamespace(text=text),
        ),
        tool_call=None,
        usage_metadata=None,
        go_away=None,
    )


@pytest.fixture
def client():
    return GeminiLiveClient(voice_name="Puck")


class TestCanonicalRole:
    @pytest.mark.asyncio
    async def test_model_text_is_assistant(self, monkeypatch, client):
        _mock_client(monkeypatch, client, [_text_response("Hello there")])
        responses = [
            r async for r in client.stream_voice(_empty_audio_iterator())
        ]
        assert any(r.role == "assistant" for r in responses if r.text)

    @pytest.mark.asyncio
    async def test_user_transcription_is_role_user(self, monkeypatch, client):
        _mock_client(monkeypatch, client, [_user_transcription_response("hi")])
        responses = [
            r async for r in client.stream_voice(_empty_audio_iterator())
        ]
        assert any(r.role == "user" and r.text == "hi" for r in responses)

    @pytest.mark.asyncio
    async def test_no_user_transcription_metadata(self, monkeypatch, client):
        _mock_client(monkeypatch, client, [_user_transcription_response("hi")])
        responses = [
            r async for r in client.stream_voice(_empty_audio_iterator())
        ]
        assert all("user_transcription" not in r.metadata for r in responses)

    @pytest.mark.asyncio
    async def test_mixed_turn_both_roles_present(self, monkeypatch, client):
        _mock_client(monkeypatch, client, [
            _user_transcription_response("what's the weather"),
            _text_response("It's sunny"),
        ])
        responses = [
            r async for r in client.stream_voice(_empty_audio_iterator())
        ]
        roles = {r.role for r in responses if r.text}
        assert roles == {"user", "assistant"}


class TestVoiceOverride:
    def test_per_call_voice_wins(self, client):
        cfg = client._build_live_config(voice="Charon")
        assert "Charon" in str(cfg.speech_config)
        assert client.voice_name == "Puck"  # no state mutation

    def test_unknown_voice_falls_back_warned(self, client, caplog):
        with caplog.at_level("WARNING"):
            cfg = client._build_live_config(voice="matthew")  # a Nova voice
        assert "Puck" in str(cfg.speech_config)
        assert any("matthew" in r.message for r in caplog.records)
        assert client.voice_name == "Puck"  # no state mutation

    def test_no_override_uses_constructor_voice(self, client):
        cfg = client._build_live_config()
        assert "Puck" in str(cfg.speech_config)

    def test_resolve_voice_name_helper_valid(self, client):
        assert client._resolve_voice_name("Charon") == "Charon"

    def test_resolve_voice_name_helper_none(self, client):
        assert client._resolve_voice_name(None) == "Puck"

    def test_resolve_voice_name_helper_invalid_falls_back(self, client, caplog):
        with caplog.at_level("WARNING"):
            assert client._resolve_voice_name("not-a-voice") == "Puck"


class TestGeminiCapabilitiesVoiceFlip:
    def test_supports_per_call_voice_now_true(self, client):
        assert client.voice_capabilities.supports_per_call_voice is True
