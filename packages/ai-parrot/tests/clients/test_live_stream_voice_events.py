"""Session-level lifecycle events for Gemini Live voice streaming."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.clients.google.live import GeminiLiveClient
from parrot.observability.context import current_agent_name, current_tenant
from navigator_eventbus.lifecycle.trace import TraceContext


class _FakeLiveSession:
    def __init__(self, responses=None, error=None, gate=None):
        self._responses = responses or []
        self._error = error
        self._gate = gate
        self.send_realtime_input = AsyncMock()
        self.send_tool_response = AsyncMock()
        self.send = AsyncMock()

    async def receive(self):
        if self._gate is not None:
            await self._gate.wait()
        if self._error is not None:
            raise self._error
        for response in self._responses:
            yield response


class _FakeConnectCM:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


class _FakeSdkClient:
    def __init__(self, session):
        self.aio = SimpleNamespace(
            live=SimpleNamespace(connect=lambda model=None, config=None: _FakeConnectCM(session))
        )


async def _empty_audio_iterator():
    return
    yield  # pragma: no cover


def _usage(input_tokens, output_tokens):
    return SimpleNamespace(
        prompt_token_count=input_tokens,
        response_token_count=output_tokens,
        total_token_count=input_tokens + output_tokens,
        cached_content_token_count=None,
    )


def _turn_complete(input_tokens, output_tokens):
    return SimpleNamespace(
        server_content=SimpleNamespace(turn_complete=True),
        usage_metadata=_usage(input_tokens, output_tokens),
        tool_call=None,
        go_away=None,
    )


def _text_chunk(text="hello"):
    return SimpleNamespace(
        server_content=SimpleNamespace(
            model_turn=SimpleNamespace(parts=[SimpleNamespace(text=text, inline_data=None)]),
        ),
        usage_metadata=None,
        tool_call=None,
        go_away=None,
    )


def _configure_client(monkeypatch, client, session):
    monkeypatch.setattr(client, "get_client", AsyncMock(return_value=_FakeSdkClient(session)))


class _RecordingClient(GeminiLiveClient):
    def __init__(self):
        super().__init__(voice_name="Puck")
        self.before = []
        self.after = []
        self.failed = []

    def _emit_before_call(self, **kwargs):
        self.before.append({"kwargs": kwargs, "agent_name": current_agent_name.get(), "tenant": current_tenant.get()})
        return TraceContext.new_root()

    async def _emit_after_call(self, _tc, **kwargs):
        self.after.append({"kwargs": kwargs, "agent_name": current_agent_name.get(), "tenant": current_tenant.get()})

    async def _emit_failed_call(self, _tc, **kwargs):
        self.failed.append(kwargs)


@pytest.fixture
def client():
    return _RecordingClient()


@pytest.mark.asyncio
async def test_two_turn_session_emits_one_pair_with_summed_tokens(monkeypatch, client):
    session = _FakeLiveSession([_turn_complete(3, 4), _turn_complete(5, 6)])
    _configure_client(monkeypatch, client, session)
    [response async for response in client.stream_voice(_empty_audio_iterator())]
    await asyncio.sleep(0)

    assert len(client.before) == 1
    assert len(client.after) == 1
    assert client.failed == []
    assert (client.after[0]["kwargs"]["input_tokens"], client.after[0]["kwargs"]["output_tokens"]) == (8, 10)


@pytest.mark.asyncio
async def test_session_error_emits_failed_only(monkeypatch, client):
    session = _FakeLiveSession(error=RuntimeError("live session failed"))
    _configure_client(monkeypatch, client, session)
    [response async for response in client.stream_voice(_empty_audio_iterator())]
    await asyncio.sleep(0)

    assert len(client.before) == 1
    assert client.after == []
    assert len(client.failed) == 1
    assert type(client.failed[0]["exc"]).__name__ == "RuntimeError"


@pytest.mark.asyncio
async def test_cancelled_session_emits_after(monkeypatch, client):
    session = _FakeLiveSession(gate=asyncio.Event())
    _configure_client(monkeypatch, client, session)
    stream = client.stream_voice(_empty_audio_iterator())
    task = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)

    assert len(client.before) == 1
    assert len(client.after) == 1
    assert client.failed == []


@pytest.mark.asyncio
async def test_early_aclose_emits_after(monkeypatch, client):
    session = _FakeLiveSession([_text_chunk()])
    _configure_client(monkeypatch, client, session)
    stream = client.stream_voice(_empty_audio_iterator())

    response = await stream.__anext__()
    assert response.metadata["thinking"] == "hello"
    await stream.aclose()
    await asyncio.sleep(0)

    assert len(client.before) == 1
    assert len(client.after) == 1
    assert client.failed == []


@pytest.mark.asyncio
async def test_events_carry_bound_agent_and_tenant(monkeypatch, client):
    session = _FakeLiveSession([_turn_complete(1, 2)])
    _configure_client(monkeypatch, client, session)
    agent_token = current_agent_name.set("voice-agent")
    tenant_token = current_tenant.set("tenant-a")
    try:
        [response async for response in client.stream_voice(_empty_audio_iterator())]
        await asyncio.sleep(0)
    finally:
        current_agent_name.reset(agent_token)
        current_tenant.reset(tenant_token)

    assert len(client.before) == 1
    assert len(client.after) == 1
    assert client.failed == []
    assert client.before[0]["agent_name"] == "voice-agent"
    assert client.before[0]["tenant"] == "tenant-a"
    assert client.after[0]["agent_name"] == "voice-agent"
    assert client.after[0]["tenant"] == "tenant-a"
