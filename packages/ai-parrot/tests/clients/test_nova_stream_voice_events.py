"""Session-level lifecycle events for Nova Sonic voice streaming."""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from navigator_eventbus.lifecycle.trace import TraceContext

from parrot.clients.amazon.nova import NovaClient
from parrot.observability.context import current_agent_name, current_tenant


class _RecordingClient(NovaClient):
    """Nova client that records lifecycle helper invocations."""

    def __init__(self) -> None:
        with patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}):
            super().__init__(model="nova-2-sonic", region="us-east-1")
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


async def _empty_audio_iterator():
    """Yield no audio frames for the fake voice session."""
    return
    yield  # pragma: no cover


async def _events(frames, error=None, gate=None):
    """Yield fake Nova event frames or raise the supplied session error."""
    if gate is not None:
        await gate.wait()
    if error is not None:
        raise error
    for frame in frames:
        yield frame


async def _consume(client, frames=(), error=None):
    """Run a fake Nova voice session to completion."""
    with (
        patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}),
        patch.object(client, "_open_stream", return_value=AsyncMock()),
        patch.object(client, "_send_event", new=AsyncMock()),
        patch.object(client, "_iter_events", return_value=_events(frames, error)),
        patch.object(client, "_close_stream", new=AsyncMock()),
    ):
        return [response async for response in client.stream_voice(_empty_audio_iterator())]


@pytest.fixture
def client():
    """Return a Nova client that records lifecycle emissions."""
    return _RecordingClient()


@pytest.mark.asyncio
async def test_session_with_usage_event_emits_one_pair_with_totals(client):
    await _consume(
        client,
        [
            {"usageEvent": {"inputTokens": 12, "outputTokens": 30, "totalTokens": 42}},
            {"completionEnd": {}},
        ],
    )

    assert len(client.before) == 1
    assert len(client.after) == 1
    assert client.failed == []
    assert (client.after[0]["kwargs"]["input_tokens"], client.after[0]["kwargs"]["output_tokens"]) == (12, 30)


@pytest.mark.asyncio
async def test_session_error_emits_failed_only(client):
    await _consume(client, error=RuntimeError("Nova session failed"))

    assert len(client.before) == 1
    assert client.after == []
    assert len(client.failed) == 1
    assert type(client.failed[0]["exc"]).__name__ == "RuntimeError"


@pytest.mark.asyncio
async def test_idle_timeout_emits_after_not_failed(client):
    await _consume(client, error=RuntimeError("Timed out waiting for audio"))

    assert len(client.before) == 1
    assert len(client.after) == 1
    assert client.failed == []


@pytest.mark.asyncio
async def test_cancelled_and_aclosed_sessions_emit_after(client):
    gate = asyncio.Event()
    with (
        patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}),
        patch.object(client, "_open_stream", return_value=AsyncMock()),
        patch.object(client, "_send_event", new=AsyncMock()),
        patch.object(client, "_iter_events", return_value=_events((), gate=gate)),
        patch.object(client, "_close_stream", new=AsyncMock()),
    ):
        stream = client.stream_voice(_empty_audio_iterator())
        task = asyncio.create_task(stream.__anext__())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert len(client.after) == 1
    assert client.failed == []

    aclosed_client = _RecordingClient()
    with (
        patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}),
        patch.object(aclosed_client, "_open_stream", return_value=AsyncMock()),
        patch.object(aclosed_client, "_send_event", new=AsyncMock()),
        patch.object(
            aclosed_client,
            "_iter_events",
            return_value=_events(
                [{"contentStart": {"role": "ASSISTANT", "type": "TEXT"}}, {"textOutput": {"content": "hi"}}]
            ),
        ),
        patch.object(aclosed_client, "_close_stream", new=AsyncMock()),
    ):
        stream = aclosed_client.stream_voice(_empty_audio_iterator())
        await stream.__anext__()
        await stream.aclose()

    assert len(aclosed_client.after) == 1
    assert aclosed_client.failed == []


@pytest.mark.asyncio
async def test_events_carry_bound_agent_and_tenant(client):
    agent_token = current_agent_name.set("voice-agent")
    tenant_token = current_tenant.set("tenant-a")
    try:
        await _consume(client, [{"completionEnd": {}}])
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
