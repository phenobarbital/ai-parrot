"""Unit tests for VoiceChatHandler avatar wiring (FEAT-245 — TASK-1589).

All external calls (VoiceAvatarSession, is_avatar_enabled) are mocked — no real
network, LiveKit, or LiveAvatar connections.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.clients.live import LiveVoiceResponse
from parrot.voice.handler import BotConfig, VoiceChatHandler, WebSocketConnection


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_mock_ws():
    """Return a minimal fake WebSocketResponse."""
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.send_str = AsyncMock()
    return ws


@pytest.fixture
def handler():
    """VoiceChatHandler with a no-op bot factory."""

    def _bot_factory():
        bot = MagicMock()
        bot.close = AsyncMock()
        return bot

    return VoiceChatHandler(
        bot_factory=_bot_factory,
        default_config=BotConfig(name="test-agent"),
    )


@pytest.fixture
def connection():
    """Minimal WebSocketConnection for testing."""
    conn = WebSocketConnection(
        ws=_make_mock_ws(),
        session_id="sess-test-123",
    )
    conn.authenticated = True
    return conn


@pytest.fixture
def avatar_session(mocker):
    """Mock VoiceAvatarSession."""
    s = mocker.Mock()
    s.viewer_credentials = {
        "livekit_url": "wss://x",
        "client_token": "viewer-jwt",
        "room": "sess-test-123",
    }
    s.speak = AsyncMock()
    s.finish_turn = AsyncMock()
    s.interrupt = AsyncMock()
    s.aclose = AsyncMock()
    return s


# ---------------------------------------------------------------------------
# TASK-1589: _send_voice_response avatar tee
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_voice_response_tees_audio_and_keeps_browser(
    handler, connection, avatar_session
):
    """_send_voice_response tees audio_data to avatar AND still sends browser chunk."""
    connection.avatar_session = avatar_session
    pcm = b"\x00\x01" * 50

    resp = LiveVoiceResponse(text="hi", audio_data=pcm, is_complete=False)
    await handler._send_voice_response(connection, resp)

    avatar_session.speak.assert_awaited_once_with(pcm)
    # Browser response_chunk must also have been sent
    assert connection.ws.send_json.await_count >= 1
    sent_types = [
        call.args[0]["type"]
        for call in connection.ws.send_json.await_args_list
        if call.args
    ]
    assert "response_chunk" in sent_types


@pytest.mark.asyncio
async def test_send_voice_response_finish_turn_on_complete(
    handler, connection, avatar_session
):
    """is_complete triggers avatar.finish_turn()."""
    connection.avatar_session = avatar_session
    resp = LiveVoiceResponse(audio_data=b"\x00\x01" * 50, is_complete=True)
    await handler._send_voice_response(connection, resp)
    avatar_session.finish_turn.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_voice_response_interrupt_routes_to_avatar(
    handler, connection, avatar_session
):
    """is_interrupted → avatar.interrupt(); speak must NOT be called."""
    connection.avatar_session = avatar_session
    resp = LiveVoiceResponse(is_interrupted=True)
    await handler._send_voice_response(connection, resp)
    avatar_session.interrupt.assert_awaited_once()
    avatar_session.speak.assert_not_awaited()


@pytest.mark.asyncio
async def test_avatar_failure_does_not_break_voice(handler, connection, avatar_session):
    """An exception in avatar.speak must NOT propagate — browser audio keeps flowing."""
    connection.avatar_session = avatar_session
    avatar_session.speak.side_effect = RuntimeError("avatar WS dropped")

    resp = LiveVoiceResponse(audio_data=b"\x00\x01" * 50, is_complete=False)
    # Must not raise
    await handler._send_voice_response(connection, resp)

    # Browser chunk still sent
    assert connection.ws.send_json.await_count >= 1


@pytest.mark.asyncio
async def test_no_avatar_no_tee(handler, connection):
    """Without an avatar_session, _send_voice_response works exactly as before."""
    assert connection.avatar_session is None
    resp = LiveVoiceResponse(audio_data=b"\x00\x01" * 50, is_complete=False)
    # Must not raise
    await handler._send_voice_response(connection, resp)
    # Browser chunk sent
    assert connection.ws.send_json.await_count >= 1


# ---------------------------------------------------------------------------
# TASK-1589: _cleanup_connection tears down avatar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_closes_avatar_session(handler, connection, avatar_session):
    """_cleanup_connection calls avatar_session.aclose()."""
    connection.avatar_session = avatar_session
    await handler._cleanup_connection(connection)
    avatar_session.aclose.assert_awaited_once()
    assert connection.avatar_session is None


@pytest.mark.asyncio
async def test_cleanup_without_avatar_does_not_raise(handler, connection):
    """_cleanup_connection without avatar_session must not raise."""
    assert connection.avatar_session is None
    await handler._cleanup_connection(connection)  # must not raise


# ---------------------------------------------------------------------------
# TASK-1589: _handle_start_session avatar wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_session_avatar_active(handler, connection, avatar_session, mocker):
    """start_session with avatar:true (opted-in) adds avatar.active=true + creds."""
    # Intercept the lazy import inside _handle_start_session
    import sys

    mock_session_cls = MagicMock()
    mock_session_cls.start = AsyncMock(return_value=avatar_session)

    fake_liveavatar_mod = MagicMock()
    fake_liveavatar_mod.VoiceAvatarSession = mock_session_cls

    fake_optin_mod = MagicMock()
    fake_optin_mod.is_avatar_enabled = MagicMock(return_value=True)

    mocker.patch.dict(
        sys.modules,
        {
            "parrot.integrations.liveavatar": fake_liveavatar_mod,
            "parrot.integrations.liveavatar.optin": fake_optin_mod,
        },
    )

    # Use buffered mode so _run_voice_session is NOT scheduled (avoids blocking queue wait)
    msg = {
        "type": "start_session",
        "avatar": True,
        "tenant_id": "acme",
        "streaming_mode": "buffered",
    }
    await handler._handle_start_session(connection, msg)

    # Avatar session should be attached
    assert connection.avatar_session is avatar_session
    # session_started message should carry avatar block
    sent_calls = connection.ws.send_json.await_args_list
    session_started = next(
        (c.args[0] for c in sent_calls if c.args and c.args[0].get("type") == "session_started"),
        None,
    )
    assert session_started is not None
    assert session_started.get("avatar", {}).get("active") is True
    assert "client_token" in session_started.get("avatar", {})
    assert session_started["avatar"].get("audio") == "dual"


@pytest.mark.asyncio
async def test_start_session_no_avatar_flag(handler, connection, mocker):
    """start_session WITHOUT avatar:true does not set avatar_session."""
    # buffered to avoid background task
    msg = {"type": "start_session", "streaming_mode": "buffered"}
    await handler._handle_start_session(connection, msg)
    assert connection.avatar_session is None
    # session_started should have no avatar key
    sent_calls = connection.ws.send_json.await_args_list
    session_started = next(
        (c.args[0] for c in sent_calls if c.args and c.args[0].get("type") == "session_started"),
        None,
    )
    assert session_started is not None
    assert "avatar" not in session_started


@pytest.mark.asyncio
async def test_start_session_avatar_optin_denied(handler, connection, mocker):
    """Opt-in denied → avatar.active=false with reason; voice session still starts."""
    import sys

    fake_optin_mod = MagicMock()
    fake_optin_mod.is_avatar_enabled = MagicMock(return_value=False)
    fake_liveavatar_mod = MagicMock()

    mocker.patch.dict(
        sys.modules,
        {
            "parrot.integrations.liveavatar": fake_liveavatar_mod,
            "parrot.integrations.liveavatar.optin": fake_optin_mod,
        },
    )

    msg = {
        "type": "start_session",
        "avatar": True,
        "tenant_id": "no-tenant",
        "streaming_mode": "buffered",
    }
    await handler._handle_start_session(connection, msg)

    assert connection.avatar_session is None
    sent_calls = connection.ws.send_json.await_args_list
    session_started = next(
        (c.args[0] for c in sent_calls if c.args and c.args[0].get("type") == "session_started"),
        None,
    )
    assert session_started is not None
    assert session_started.get("avatar", {}).get("active") is False
    # Voice still works — session_started was sent
    assert session_started.get("session_id") == connection.session_id


# ---------------------------------------------------------------------------
# TASK-1589: _handle_end_session / _handle_reset_session avatar teardown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_session_closes_avatar(handler, connection, avatar_session):
    """_handle_end_session must tear down avatar_session (no orphan WS)."""
    connection.avatar_session = avatar_session
    await handler._handle_end_session(connection, {})
    avatar_session.aclose.assert_awaited_once()
    assert connection.avatar_session is None


@pytest.mark.asyncio
async def test_end_session_without_avatar_does_not_raise(handler, connection):
    """_handle_end_session with no avatar_session must not raise."""
    assert connection.avatar_session is None
    await handler._handle_end_session(connection, {})  # must not raise


@pytest.mark.asyncio
async def test_reset_session_no_orphan(handler, connection, avatar_session, mocker):
    """_handle_reset_session tears down the old avatar before starting a new session.

    Verifies that the old avatar_session.aclose() is called exactly once,
    preventing a dangling LiveAvatar WS after a reset.
    """
    connection.avatar_session = avatar_session

    # Stub _handle_start_session so the reset doesn't attempt real bot creation
    mocker.patch.object(handler, "_handle_start_session", new=AsyncMock())

    await handler._handle_reset_session(connection, {})

    # Old avatar session must have been closed
    avatar_session.aclose.assert_awaited_once()
    assert connection.avatar_session is None


# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_session_avatar_failure_degrades(handler, connection, mocker):
    """Avatar start raises → avatar.active=false; voice session still usable."""
    import sys

    fake_session_cls = MagicMock()
    fake_session_cls.start = AsyncMock(side_effect=RuntimeError("LIVEAVATAR down"))

    fake_liveavatar_mod = MagicMock()
    fake_liveavatar_mod.VoiceAvatarSession = fake_session_cls

    fake_optin_mod = MagicMock()
    fake_optin_mod.is_avatar_enabled = MagicMock(return_value=True)

    mocker.patch.dict(
        sys.modules,
        {
            "parrot.integrations.liveavatar": fake_liveavatar_mod,
            "parrot.integrations.liveavatar.optin": fake_optin_mod,
        },
    )

    msg = {
        "type": "start_session",
        "avatar": True,
        "tenant_id": "acme",
        "streaming_mode": "buffered",
    }
    # Must NOT raise
    await handler._handle_start_session(connection, msg)

    assert connection.avatar_session is None
    sent_calls = connection.ws.send_json.await_args_list
    session_started = next(
        (c.args[0] for c in sent_calls if c.args and c.args[0].get("type") == "session_started"),
        None,
    )
    assert session_started is not None
    assert session_started.get("avatar", {}).get("active") is False
    # Reason should mention the failure
    assert "reason" in session_started.get("avatar", {})
    # Voice session started regardless
    assert session_started.get("session_id") == connection.session_id
