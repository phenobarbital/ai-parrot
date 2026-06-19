"""Cross-module integration tests for the structured-output transport (FEAT-249).

Tests the end-to-end path:
  Redis envelope → run_output_subscriber → _FanOutSink → UserSocketManager.broadcast_to_channel

No real Redis or network connections — all replaced by fakes/mocks.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.handlers.liveavatar_output import _FanOutSink
from parrot.integrations.liveavatar.output_transport import run_output_subscriber


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


class FakeWS:
    """Minimal WebSocket mock that records sent messages."""

    def __init__(self):
        self.closed = False
        self.sent: list[str] = []

    async def send_str(self, s: str) -> None:
        self.sent.append(s)

    async def send_json(self, data: dict) -> None:
        self.sent.append(json.dumps(data))


class _OneShotPubSub:
    """Async-generator pubsub that yields exactly one message then stops."""

    def __init__(self, envelope: dict) -> None:
        self._envelope = envelope

    async def subscribe(self, channel: str) -> None:
        pass

    async def unsubscribe(self, channel: str) -> None:
        pass

    async def listen(self):
        yield {"type": "message", "data": json.dumps(self._envelope)}


class FakeRedis:
    """Minimal Redis fake backed by a one-shot pubsub."""

    def __init__(self, envelope: dict) -> None:
        self._envelope = envelope

    def pubsub(self) -> _OneShotPubSub:
        return _OneShotPubSub(self._envelope)


# ---------------------------------------------------------------------------
# Test 1: end-to-end structured output reaches a UserSocketManager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_structured_output_to_user_socket_manager():
    """A Redis envelope reaches a UserSocketManager subscribed to that session_id.

    Drive the real run_output_subscriber with a one-shot FakeRedis whose envelope
    has channel=sess-1, wired through _FanOutSink to a UserSocketManager duck-type.
    """
    user_sm = MagicMock()
    user_sm.broadcast_to_channel = AsyncMock()

    envelope = {
        "channel": "sess-1",
        "message": {
            "type": "data",
            "session_id": "sess-1",
            "payload": {"data": {"x": 1}},
            "turn_id": None,
        },
    }

    sink = _FanOutSink([user_sm])
    await run_output_subscriber(
        FakeRedis(envelope), sink, channel="liveavatar:structured-outputs"
    )

    user_sm.broadcast_to_channel.assert_awaited_once()
    call_args = user_sm.broadcast_to_channel.call_args
    assert call_args[0][0] == "sess-1"  # positional channel
    assert call_args[0][1] == envelope["message"]  # positional message


@pytest.mark.asyncio
async def test_end_to_end_fanout_delivers_to_multiple_managers():
    """When multiple managers are present, all receive the envelope."""
    user_sm1 = MagicMock()
    user_sm1.broadcast_to_channel = AsyncMock()
    user_sm2 = MagicMock()
    user_sm2.broadcast_to_channel = AsyncMock()

    envelope = {
        "channel": "sess-1",
        "message": {"type": "tool_call", "session_id": "sess-1", "payload": {}},
    }

    sink = _FanOutSink([user_sm1, user_sm2])
    await run_output_subscriber(FakeRedis(envelope), sink, channel="liveavatar:structured-outputs")

    user_sm1.broadcast_to_channel.assert_awaited_once()
    user_sm2.broadcast_to_channel.assert_awaited_once()


@pytest.mark.asyncio
async def test_cross_process_simulation():
    """Two-process simulation: published on worker-A reaches WS subscriber on worker-B.

    Worker A: OutputBridge -> RedisBroadcastForwarder.broadcast_to_channel -> Redis publish
    Worker B: run_output_subscriber -> _FanOutSink -> UserSocketManager.broadcast_to_channel

    Uses FakeRedis so no actual Redis connection is needed.
    """
    from parrot.integrations.liveavatar.models import StructuredOutputMessage
    from parrot.integrations.liveavatar.output_bridge import OutputBridge
    from parrot.integrations.liveavatar.output_transport import RedisBroadcastForwarder

    # Track what would be published to Redis
    published: list[dict] = []

    class FakeRedisPub:
        async def publish(self, channel: str, data: str) -> None:
            published.append({"channel": channel, "data": data})

    # Worker A side: publish a StructuredOutputMessage
    forwarder = RedisBroadcastForwarder(FakeRedisPub())
    msg = StructuredOutputMessage(
        type="chart",
        session_id="sess-cross",
        payload={"chart": "bar"},
        turn_id="t-1",
    )
    bridge = OutputBridge(forwarder)
    await bridge.publish(msg)

    assert len(published) == 1
    envelope = json.loads(published[0]["data"])
    assert envelope["channel"] == "sess-cross"
    assert envelope["message"]["type"] == "chart"

    # Worker B side: receive and re-broadcast
    user_sm = MagicMock()
    user_sm.broadcast_to_channel = AsyncMock()

    class _OneShotPubSubFromEnvelope:
        async def subscribe(self, channel: str) -> None:
            pass

        async def unsubscribe(self, channel: str) -> None:
            pass

        async def listen(self):
            yield {"type": "message", "data": published[0]["data"]}

    class FakeRedisSub:
        def pubsub(self):
            return _OneShotPubSubFromEnvelope()

    sink = _FanOutSink([user_sm])
    await run_output_subscriber(
        FakeRedisSub(), sink, channel="liveavatar:structured-outputs"
    )

    user_sm.broadcast_to_channel.assert_awaited_once()
    call_args = user_sm.broadcast_to_channel.call_args
    assert call_args[0][0] == "sess-cross"
    assert call_args[0][1]["type"] == "chart"
