"""Cross-module integration tests for unified voice control (FEAT-244 TASK-1587).

Tests the end-to-end path:
  Redis envelope → run_output_subscriber → _FanOutSink → StreamHandler.broadcast_to_channel
  → FakeWS.sent

And the coexistence of text (stream_request) and voice (voice_start) on one socket.

No real Redis, LiveKit, or network connections — all replaced by fakes/mocks.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.handlers.liveavatar_output import _FanOutSink
from parrot.handlers.stream import StreamHandler
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
# Test 1: end-to-end structured output reaches a StreamHandler socket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_structured_output_to_stream_ws():
    """A Redis envelope reaches a StreamHandler socket subscribed to that session_id.

    Drive the real run_output_subscriber with a one-shot FakeRedis whose envelope
    has channel=sess-1, wired through _FanOutSink to a StreamHandler with a
    FakeWS subscribed to sess-1.
    """
    handler = StreamHandler()
    ws = FakeWS()
    # Pre-subscribe the socket (simulates what voice_start does)
    handler.channel_subscriptions["sess-1"] = {ws}

    envelope = {
        "channel": "sess-1",
        "message": {
            "type": "data",
            "session_id": "sess-1",
            "payload": {"data": {"x": 1}},
            "turn_id": None,
        },
    }

    sink = _FanOutSink([handler])
    await run_output_subscriber(
        FakeRedis(envelope), sink, channel="liveavatar:structured-outputs"
    )

    assert len(ws.sent) == 1
    received = json.loads(ws.sent[0])
    assert received["type"] == "data"
    assert received["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_end_to_end_unsubscribed_socket_gets_nothing():
    """A socket NOT subscribed to the session_id channel receives nothing."""
    handler = StreamHandler()
    ws_subscribed = FakeWS()
    ws_other = FakeWS()
    handler.channel_subscriptions["sess-subscribed"] = {ws_subscribed}
    # ws_other is subscribed to a different channel
    handler.channel_subscriptions["sess-other"] = {ws_other}

    envelope = {
        "channel": "sess-subscribed",
        "message": {"type": "canvas", "session_id": "sess-subscribed", "payload": {}},
    }

    sink = _FanOutSink([handler])
    await run_output_subscriber(FakeRedis(envelope), sink, channel="liveavatar:structured-outputs")

    assert ws_subscribed.sent  # got the message
    assert not ws_other.sent  # wrong channel — got nothing


@pytest.mark.asyncio
async def test_end_to_end_fanout_delivers_to_both_managers():
    """When both user_socket_manager and StreamHandler are present, both receive the envelope."""
    handler = StreamHandler()
    sh_ws = FakeWS()
    handler.channel_subscriptions["sess-1"] = {sh_ws}

    # Simulate a user_socket_manager (duck-typed)
    user_sm = MagicMock()
    user_sm.broadcast_to_channel = AsyncMock()

    envelope = {
        "channel": "sess-1",
        "message": {"type": "tool_call", "session_id": "sess-1", "payload": {}},
    }

    sink = _FanOutSink([user_sm, handler])
    await run_output_subscriber(FakeRedis(envelope), sink, channel="liveavatar:structured-outputs")

    # StreamHandler socket got the message
    assert sh_ws.sent
    # user_socket_manager also got it
    user_sm.broadcast_to_channel.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 2: text and voice coexist on one socket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_and_voice_same_socket():
    """One socket can interleave stream_request (text) and voice_start (voice).

    Verifies:
    - stream_request produces stream_start + content + stream_complete frames.
    - voice_start subscribes the socket to session_id and produces voice_session.
    - The channel subscription from voice_start persists after both operations.
    """
    handler = StreamHandler()
    ws = FakeWS()

    fake_request = MagicMock()
    fake_request.app = {}
    fake_request.match_info = {"bot_id": "my-agent"}

    # --- text: stream_request ---
    fake_bot = MagicMock()

    async def fake_ask_stream(prompt, **kwargs):
        yield "Hello"
        yield "!"

    fake_bot.ask_stream.return_value = fake_ask_stream("hi")

    await handler._handle_message(
        ws,
        {"type": "stream_request", "prompt": "hi"},
        bot=fake_bot,
        request=fake_request,
    )

    text_types = []
    for s in ws.sent:
        try:
            text_types.append(json.loads(s).get("type"))
        except Exception:
            pass

    assert "stream_start" in text_types
    assert "stream_complete" in text_types

    # Clear sent buffer for voice messages
    ws.sent.clear()

    # --- voice: voice_start ---
    with patch(
        "parrot.handlers.avatar.start_voice_native",
        AsyncMock(return_value={
            "livekit_url": "wss://x",
            "token": "tok",
            "session_id": "sess-voice",
        }),
    ):
        await handler._handle_message(
            ws,
            {"type": "voice_start", "session_id": "sess-voice"},
            bot=fake_bot,
            request=fake_request,
        )

    voice_types = []
    for s in ws.sent:
        try:
            voice_types.append(json.loads(s).get("type"))
        except Exception:
            pass

    assert "voice_session" in voice_types
    # Channel subscription persists
    assert ws in handler.channel_subscriptions["sess-voice"]
    assert "sess-voice" in handler._ws_voice_sessions[ws]
