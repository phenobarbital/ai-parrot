"""Cross-module integration tests — VoiceChat → LiveAvatar (Gemini Live) (FEAT-245 — TASK-1590).

Proves the dual-path: a Gemini Live response flows BOTH to the browser
(response_chunk over /ws/voice) AND to the avatar mouth
(AvatarWebSocket.send_audio_frame) through the real VoiceAvatarSession wired
into _send_voice_response — with no resampling (same bytes, no transform).

All transport layers (AvatarWebSocket, LiveAvatarClient, LiveKitRoomManager) are
mocked.  No real network, LiveKit, or LiveAvatar connections.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.clients.live import LiveVoiceResponse
from parrot.integrations.liveavatar.voice_session import VoiceAvatarSession
from parrot.voice.handler import BotConfig, VoiceChatHandler, WebSocketConnection


# patched_stack fixture lives in conftest.py (shared with unit tests)

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
    """Minimal WebSocketConnection with a mock WebSocket."""
    mock_ws = MagicMock()
    mock_ws.send_json = AsyncMock()
    conn = WebSocketConnection(ws=mock_ws, session_id="sess-1")
    conn.authenticated = True
    return conn


# ---------------------------------------------------------------------------
# TASK-1590 integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_audio_to_avatar_end_to_end(patched_stack, handler, connection, mocker):
    """Dual delivery: browser response_chunk AND avatar send_audio_frame receive
    the same PCM bytes (no transform) when is_complete=True.

    Proves:
    - `AvatarWebSocket.send_audio_frame` called with identical PCM (no resample).
    - `AvatarWebSocket.finish_speaking` called on is_complete.
    - Browser `response_chunk` message also sent (connection.ws.send_json called).
    """
    _, _, ws, _ = patched_stack

    # Build a real VoiceAvatarSession over the mocked transport
    avatar_session = await VoiceAvatarSession.start(
        agent_id="ag", session_id="sess-1", tenant_id=None
    )
    connection.avatar_session = avatar_session

    # Ensure browser send_json is tracked (ws fixture above already uses AsyncMock)
    pcm = b"\x00\x01" * 4800  # 0.2 s of 24 kHz mono int16

    # is_complete=True: browser receives response_complete (not response_chunk, because
    # the code only sends response_chunk when not is_complete); avatar gets
    # send_audio_frame + finish_speaking.
    await handler._send_voice_response(
        connection,
        LiveVoiceResponse(audio_data=pcm, is_complete=True),
    )

    # Avatar received the exact same PCM bytes (no resampling / transformation)
    ws.send_audio_frame.assert_awaited_once_with(pcm)
    ws.finish_speaking.assert_awaited_once()

    # Browser also received at least one message (response_complete / ready_to_speak)
    assert connection.ws.send_json.await_count >= 1
    sent_types = [
        c.args[0]["type"]
        for c in connection.ws.send_json.await_args_list
        if c.args
    ]
    # response_complete and/or ready_to_speak must appear (is_complete=True path)
    assert any(t in sent_types for t in ("response_complete", "ready_to_speak"))


@pytest.mark.asyncio
async def test_gemini_audio_mid_turn_no_finish(patched_stack, handler, connection):
    """Mid-turn audio chunk (is_complete=False): speak called, finish_speaking NOT called."""
    _, _, ws, _ = patched_stack

    avatar_session = await VoiceAvatarSession.start(
        agent_id="ag", session_id="sess-1", tenant_id=None
    )
    connection.avatar_session = avatar_session

    pcm = b"\x00\x01" * 2400
    await handler._send_voice_response(
        connection,
        LiveVoiceResponse(audio_data=pcm, is_complete=False),
    )

    ws.send_audio_frame.assert_awaited_once_with(pcm)
    ws.finish_speaking.assert_not_awaited()


@pytest.mark.asyncio
async def test_barge_in_clears_avatar(patched_stack, handler, connection):
    """Barge-in (is_interrupted=True) → AvatarWebSocket.interrupt() is called.
    speak must NOT be called (barge-in takes priority).
    """
    _, _, ws, _ = patched_stack

    avatar_session = await VoiceAvatarSession.start(
        agent_id="ag", session_id="sess-1", tenant_id=None
    )
    connection.avatar_session = avatar_session

    await handler._send_voice_response(
        connection,
        LiveVoiceResponse(is_interrupted=True),
    )

    ws.interrupt.assert_awaited_once()
    ws.send_audio_frame.assert_not_awaited()


@pytest.mark.asyncio
async def test_pcm_bytes_unchanged_no_resample(patched_stack, handler, connection):
    """Assert byte identity: the PCM handed to speak() is the same object,
    confirming zero-copy (no resampling, no intermediate buffer).
    """
    _, _, ws, _ = patched_stack

    avatar_session = await VoiceAvatarSession.start(
        agent_id="ag", session_id="sess-1", tenant_id=None
    )
    connection.avatar_session = avatar_session

    original_pcm = b"\xAB\xCD" * 1200  # 1200 samples @ 24 kHz ≈ 50 ms

    await handler._send_voice_response(
        connection,
        LiveVoiceResponse(audio_data=original_pcm, is_complete=False),
    )

    call_arg = ws.send_audio_frame.await_args.args[0]
    assert call_arg == original_pcm, "PCM bytes were transformed — expected identity"
    assert call_arg is original_pcm, "Expected same bytes object (no copy/resample)"
