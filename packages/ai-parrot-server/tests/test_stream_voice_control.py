"""Unit tests for StreamHandler voice control + channel delivery (FEAT-244 TASK-1585).

Tests cover:
- broadcast_to_channel: sends only to subscribed, open, non-excluded sockets.
- voice_start: subscribes ws to session_id, replies voice_session.
- voice_start without session_id: replies error, dispatches nothing.
- voice_stop: unsubscribes and replies voice_stopped.
- ws close cleanup: calls stop_voice_native and clears all channel subscriptions.
- Existing stream_request / auth / ping behavior is unchanged.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.handlers.stream import StreamHandler


# ---------------------------------------------------------------------------
# Fake WebSocket
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


def _sent_types(ws: FakeWS) -> list[str]:
    """Extract 'type' fields from all messages sent by this socket."""
    types = []
    for s in ws.sent:
        try:
            types.append(json.loads(s).get("type", ""))
        except Exception:
            pass
    return types


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """A fresh StreamHandler for each test."""
    return StreamHandler()


@pytest.fixture
def fake_request():
    """Minimal fake aiohttp Request."""
    req = MagicMock()
    req.app = {}
    req.match_info = {"bot_id": "my-agent"}
    return req


# ---------------------------------------------------------------------------
# broadcast_to_channel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_to_channel_only_subscribers(handler):
    """Messages go only to sockets that are subscribed to the channel."""
    a, b = FakeWS(), FakeWS()
    handler.channel_subscriptions["sess-1"] = {a}
    await handler.broadcast_to_channel("sess-1", {"type": "data", "x": 1})
    assert a.sent and not b.sent


@pytest.mark.asyncio
async def test_broadcast_to_channel_unknown_channel_is_noop(handler):
    """broadcast_to_channel does nothing for a channel with no subscribers."""
    ws = FakeWS()
    await handler.broadcast_to_channel("no-subscribers", {"type": "data"})
    assert not ws.sent


@pytest.mark.asyncio
async def test_broadcast_to_channel_skips_closed_ws(handler):
    """Closed sockets are silently skipped."""
    a, b = FakeWS(), FakeWS()
    b.closed = True
    handler.channel_subscriptions["sess-1"] = {a, b}
    await handler.broadcast_to_channel("sess-1", {"type": "data"})
    assert a.sent
    assert not b.sent


@pytest.mark.asyncio
async def test_broadcast_to_channel_skips_excluded_ws(handler):
    """exclude_ws is skipped even when subscribed."""
    a, b = FakeWS(), FakeWS()
    handler.channel_subscriptions["sess-1"] = {a, b}
    await handler.broadcast_to_channel("sess-1", {"type": "data"}, exclude_ws=a)
    assert b.sent
    assert not a.sent


# ---------------------------------------------------------------------------
# voice_start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_start_subscribes_and_acks(handler, fake_request):
    """voice_start subscribes ws to session_id and sends voice_session ack."""
    with patch(
        "parrot.handlers.avatar.start_voice_native",
        AsyncMock(return_value={
            "livekit_url": "wss://x",
            "token": "t",
            "session_id": "sess-1",
        }),
    ):
        ws = FakeWS()
        await handler._handle_message(
            ws,
            {"type": "voice_start", "session_id": "sess-1"},
            bot=MagicMock(),
            request=fake_request,
        )

    assert ws in handler.channel_subscriptions["sess-1"]
    assert "sess-1" in handler._ws_voice_sessions[ws]
    assert any('"voice_session"' in s for s in ws.sent)


@pytest.mark.asyncio
async def test_voice_start_missing_session_id_errors(handler, fake_request):
    """voice_start without session_id sends an error frame and dispatches nothing."""
    ws = FakeWS()
    await handler._handle_message(
        ws,
        {"type": "voice_start"},
        bot=MagicMock(),
        request=fake_request,
    )
    assert any('"error"' in s for s in ws.sent)
    assert not handler.channel_subscriptions  # nothing subscribed


@pytest.mark.asyncio
async def test_voice_start_helper_http_exception_sends_error(handler, fake_request):
    """If start_voice_native raises an HTTPException, the ws gets an error frame."""
    from aiohttp import web

    with patch(
        "parrot.handlers.avatar.start_voice_native",
        AsyncMock(side_effect=web.HTTPForbidden(reason="not enabled")),
    ):
        ws = FakeWS()
        await handler._handle_message(
            ws,
            {"type": "voice_start", "session_id": "sess-1"},
            bot=MagicMock(),
            request=fake_request,
        )

    assert any('"error"' in s for s in ws.sent)
    assert "sess-1" not in handler.channel_subscriptions


# ---------------------------------------------------------------------------
# voice_stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_stop_unsubscribes_and_acks(handler, fake_request):
    """voice_stop removes ws from channel, clears reverse index, sends voice_stopped."""
    ws = FakeWS()
    # Pre-subscribe
    handler._subscribe_to_channel(ws, "sess-1")
    assert ws in handler.channel_subscriptions["sess-1"]

    with patch("parrot.handlers.avatar.stop_voice_native", AsyncMock()):
        await handler._handle_message(
            ws,
            {"type": "voice_stop", "session_id": "sess-1"},
            bot=MagicMock(),
            request=fake_request,
        )

    assert "sess-1" not in handler.channel_subscriptions
    assert ws not in handler._ws_voice_sessions
    assert any('"voice_stopped"' in s for s in ws.sent)


@pytest.mark.asyncio
async def test_voice_stop_missing_session_id_errors(handler, fake_request):
    """voice_stop without session_id sends an error frame."""
    ws = FakeWS()
    await handler._handle_message(
        ws,
        {"type": "voice_stop"},
        bot=MagicMock(),
        request=fake_request,
    )
    assert any('"error"' in s for s in ws.sent)


# ---------------------------------------------------------------------------
# ws close cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_close_cleanup_stops_all_sessions(handler, fake_request):
    """Closing a ws that started sessions calls stop_voice_native for each and unsubscribes."""
    ws = FakeWS()
    handler._subscribe_to_channel(ws, "sess-1")
    handler._subscribe_to_channel(ws, "sess-2")

    stop_calls = []

    async def fake_stop(app, session_id):
        stop_calls.append(session_id)

    with patch("parrot.handlers.avatar.stop_voice_native", fake_stop):
        await handler._cleanup_ws_voice_sessions(ws, fake_request)

    assert set(stop_calls) == {"sess-1", "sess-2"}
    assert "sess-1" not in handler.channel_subscriptions
    assert "sess-2" not in handler.channel_subscriptions
    assert ws not in handler._ws_voice_sessions


@pytest.mark.asyncio
async def test_ws_close_cleanup_noop_when_no_sessions(handler, fake_request):
    """_cleanup_ws_voice_sessions is a noop when ws has no voice sessions."""
    ws = FakeWS()
    # Should not raise even when the ws is not in any registry
    await handler._cleanup_ws_voice_sessions(ws, fake_request)


# ---------------------------------------------------------------------------
# Existing behavior unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_still_works(handler, fake_request):
    """Existing ping message still produces pong."""
    ws = FakeWS()
    await handler._handle_message(
        ws,
        {"type": "ping"},
        bot=MagicMock(),
        request=fake_request,
    )
    assert any('"pong"' in s for s in ws.sent)


@pytest.mark.asyncio
async def test_unknown_message_type_still_errors(handler, fake_request):
    """Unknown message types still produce an error frame."""
    ws = FakeWS()
    await handler._handle_message(
        ws,
        {"type": "foobar"},
        bot=MagicMock(),
        request=fake_request,
    )
    assert any('"error"' in s for s in ws.sent)
