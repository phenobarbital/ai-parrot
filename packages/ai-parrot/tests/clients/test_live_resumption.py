"""Resumption + reconnect-signal tests for Gemini Live (FEAT-418, TASK-2168).

Covers spec §3 Module 5: GoAway/1008-close mapped to
metadata["reconnect_required"] (in addition to the existing metadata["go_away"]
flag), session resumption enabled on connect with the handle retained across
reconnects, and a rejected/expired handle falling back to a cold reconnect.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot.clients.live import GeminiLiveClient


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


class _FailingLiveSession:
    """A session whose receive() raises immediately (mid-stream failure)."""

    def __init__(self, error: Exception):
        self._error = error
        self.send_realtime_input = AsyncMock()
        self.send_tool_response = AsyncMock()
        self.send = AsyncMock()

    async def receive(self):
        raise self._error
        yield  # pragma: no cover — makes this an async generator


class _FakeConnectCM:
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
    yield  # pragma: no cover


def _mock_session(monkeypatch, client, session):
    fake_sdk_client = _FakeSdkClient(session)
    monkeypatch.setattr(client, "get_client", AsyncMock(return_value=fake_sdk_client))


def _goaway_response(reason="Session ending soon"):
    return SimpleNamespace(
        server_content=None,
        tool_call=None,
        usage_metadata=None,
        go_away=SimpleNamespace(time_left=reason),
        session_resumption_update=None,
    )


def _resumption_update_response(handle="handle-123", resumable=True):
    return SimpleNamespace(
        server_content=None,
        tool_call=None,
        usage_metadata=None,
        go_away=None,
        session_resumption_update=SimpleNamespace(
            new_handle=handle, resumable=resumable,
            last_consumed_client_message_index=None,
        ),
    )


@pytest.fixture
def client():
    return GeminiLiveClient(voice_name="Puck")


class TestReconnectSignal:
    @pytest.mark.asyncio
    async def test_goaway_sets_reconnect_required(self, monkeypatch, client):
        _mock_session(monkeypatch, client, _FakeLiveSession([_goaway_response()]))
        responses = [
            r async for r in client.stream_voice(_empty_audio_iterator())
        ]
        assert any(r.metadata.get("reconnect_required") for r in responses)

    @pytest.mark.asyncio
    async def test_goaway_flag_preserved(self, monkeypatch, client):
        """handler.py:298 still reacts to go_away — do not drop it."""
        _mock_session(monkeypatch, client, _FakeLiveSession([_goaway_response()]))
        responses = [
            r async for r in client.stream_voice(_empty_audio_iterator())
        ]
        assert any(r.metadata.get("go_away") for r in responses)

    @pytest.mark.asyncio
    async def test_server_close_1008_also_signals(self, monkeypatch, client):
        error = RuntimeError("Operation is not implemented (1008 policy violation)")
        _mock_session(monkeypatch, client, _FailingLiveSession(error))
        responses = [
            r async for r in client.stream_voice(_empty_audio_iterator())
        ]
        assert any(r.metadata.get("reconnect_required") for r in responses)
        assert any(r.metadata.get("go_away") for r in responses)


class TestResumption:
    def test_resumption_config_included_by_default(self, client):
        cfg = client._build_live_config()
        assert cfg.session_resumption is not None

    def test_resumption_handle_threaded_into_config(self, client):
        client._resumption_handle = "abc123"
        cfg = client._build_live_config()
        assert cfg.session_resumption.handle == "abc123"

    def test_no_handle_on_first_connect(self, client):
        cfg = client._build_live_config()
        assert cfg.session_resumption.handle is None

    @pytest.mark.asyncio
    async def test_handle_retained(self, monkeypatch, client):
        _mock_session(
            monkeypatch, client,
            _FakeLiveSession([_resumption_update_response(handle="handle-123")]),
        )
        [r async for r in client.stream_voice(_empty_audio_iterator())]
        assert client._resumption_handle == "handle-123"

    @pytest.mark.asyncio
    async def test_non_resumable_update_not_retained(self, monkeypatch, client):
        _mock_session(
            monkeypatch, client,
            _FakeLiveSession([
                _resumption_update_response(handle="", resumable=False),
            ]),
        )
        [r async for r in client.stream_voice(_empty_audio_iterator())]
        assert client._resumption_handle is None

    @pytest.mark.asyncio
    async def test_expired_handle_falls_back_cold(self, monkeypatch, client):
        client._resumption_handle = "stale-handle"
        error = RuntimeError("session resumption handle expired")
        _mock_session(monkeypatch, client, _FailingLiveSession(error))
        responses = [
            r async for r in client.stream_voice(_empty_audio_iterator())
        ]
        assert any(r.metadata.get("resumed") is False for r in responses)
        assert client._resumption_handle is None

    @pytest.mark.asyncio
    async def test_expired_handle_also_signals_reconnect(self, monkeypatch, client):
        client._resumption_handle = "stale-handle"
        error = RuntimeError("session resumption handle expired")
        _mock_session(monkeypatch, client, _FailingLiveSession(error))
        responses = [
            r async for r in client.stream_voice(_empty_audio_iterator())
        ]
        assert any(r.metadata.get("reconnect_required") for r in responses)

    @pytest.mark.asyncio
    async def test_generic_error_without_handle_not_treated_as_resumption(
        self, monkeypatch, client
    ):
        """A generic error with no resumption handle set must not be
        misclassified as a resumption failure."""
        error = RuntimeError("network unreachable")
        _mock_session(monkeypatch, client, _FailingLiveSession(error))
        responses = [
            r async for r in client.stream_voice(_empty_audio_iterator())
        ]
        assert not any(r.metadata.get("resumed") is False for r in responses)
        assert any("error" in r.metadata for r in responses)


class TestGeminiCapabilitiesResumptionFlip:
    def test_emits_reconnect_signal_now_true(self, client):
        assert client.voice_capabilities.emits_reconnect_signal is True

    def test_supports_session_resumption_now_true(self, client):
        assert client.voice_capabilities.supports_session_resumption is True
