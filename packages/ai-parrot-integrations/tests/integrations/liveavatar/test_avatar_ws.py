"""Unit tests for AvatarWebSocket (TASK-003).

Uses a fake WebSocket object (not a real aiohttp WS) to verify:
- No frames are sent before the connected gate is set.
- PCM chunking respects ≈400 ms first chunk, ≈1 s thereafter, ≤1 MB cap.
- Reconnect replays the start handshake.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.liveavatar import AvatarWebSocket
from parrot.integrations.liveavatar.avatar_ws import (
    _FIRST_CHUNK_BYTES,
    _MAX_PACKET_BYTES,
    _NORMAL_CHUNK_BYTES,
)
from parrot.integrations.liveavatar.models import AvatarSessionHandle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handle() -> AvatarSessionHandle:
    return AvatarSessionHandle(
        session_id="sess-1",
        liveavatar_session_id="sess-1",
        session_token="tok-1",
        ws_url="wss://media.liveavatar.com/ws/sess-1",
        agent_name="bot",
    )


def _build_fake_ws(closed: bool = False) -> MagicMock:
    """Build a mock WS response that records send calls."""
    ws = MagicMock()
    ws.closed = closed
    ws.send_json = AsyncMock()
    ws.send_bytes = AsyncMock()
    ws.close = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# Gate: no commands before connected
# ---------------------------------------------------------------------------

async def test_avatar_ws_waits_for_connected() -> None:
    """No frames sent until session.state_updated == 'connected'."""
    handle = _make_handle()
    ws_obj = _build_fake_ws()

    avatar_ws = AvatarWebSocket(handle)
    avatar_ws._ws = ws_obj

    # Do NOT set _connected — gate is closed
    send_task = asyncio.create_task(avatar_ws.start_speaking())
    # Give the task a moment to run
    await asyncio.sleep(0.01)
    # Must not have sent anything yet
    ws_obj.send_json.assert_not_called()

    # Now open the gate
    avatar_ws._connected.set()
    await send_task

    # Now the frame was sent
    ws_obj.send_json.assert_called_once()
    call_arg = ws_obj.send_json.call_args[0][0]
    assert call_arg == {"type": "agent.speak"}


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

async def test_avatar_ws_chunking() -> None:
    """First chunk ≈400 ms, then ≈1 s; no packet > 1 MB."""
    handle = _make_handle()
    ws_obj = _build_fake_ws()

    avatar_ws = AvatarWebSocket(handle)
    avatar_ws._ws = ws_obj
    avatar_ws._connected.set()  # open gate

    # 3 seconds of PCM: 3 * 48 000 = 144 000 bytes
    pcm_3s = b"\x00" * (48_000 * 3)
    await avatar_ws.send_audio_frame(pcm_3s)

    calls: List[bytes] = [
        call.args[0] for call in ws_obj.send_bytes.call_args_list
    ]
    assert len(calls) >= 2, "Expected at least 2 chunks for 3 s of PCM"

    # First chunk ≈ 400 ms
    assert len(calls[0]) == _FIRST_CHUNK_BYTES, (
        f"First chunk should be {_FIRST_CHUNK_BYTES} bytes, got {len(calls[0])}"
    )

    # All subsequent chunks ≤ normal chunk size
    for chunk in calls[1:]:
        assert len(chunk) <= _NORMAL_CHUNK_BYTES, (
            f"Subsequent chunk {len(chunk)} > {_NORMAL_CHUNK_BYTES}"
        )

    # No packet exceeds 1 MB
    for chunk in calls:
        assert len(chunk) <= _MAX_PACKET_BYTES, (
            f"Packet {len(chunk)} exceeds 1 MB cap"
        )

    # Total bytes round-trip correctly
    total = sum(len(c) for c in calls)
    assert total == len(pcm_3s)


async def test_avatar_ws_empty_pcm() -> None:
    """Empty PCM bytes produces no send_bytes calls."""
    handle = _make_handle()
    ws_obj = _build_fake_ws()

    avatar_ws = AvatarWebSocket(handle)
    avatar_ws._ws = ws_obj
    avatar_ws._connected.set()

    await avatar_ws.send_audio_frame(b"")
    ws_obj.send_bytes.assert_not_called()


# ---------------------------------------------------------------------------
# Finish and interrupt
# ---------------------------------------------------------------------------

async def test_avatar_ws_finish_speaking() -> None:
    """finish_speaking sends agent.speak_end after the gate opens."""
    handle = _make_handle()
    ws_obj = _build_fake_ws()

    avatar_ws = AvatarWebSocket(handle)
    avatar_ws._ws = ws_obj
    avatar_ws._connected.set()

    await avatar_ws.finish_speaking()
    ws_obj.send_json.assert_called_once_with({"type": "agent.speak_end"})


async def test_avatar_ws_interrupt() -> None:
    """interrupt sends agent.interrupt after the gate opens."""
    handle = _make_handle()
    ws_obj = _build_fake_ws()

    avatar_ws = AvatarWebSocket(handle)
    avatar_ws._ws = ws_obj
    avatar_ws._connected.set()

    await avatar_ws.interrupt()
    ws_obj.send_json.assert_called_once_with({"type": "agent.interrupt"})


# ---------------------------------------------------------------------------
# Reconnect replay
# ---------------------------------------------------------------------------

async def test_avatar_ws_reconnect_replay() -> None:
    """On reconnect, the start handshake is replayed."""
    handle = _make_handle()
    ws_obj = _build_fake_ws()

    # Build a new WS object returned after reconnect
    new_ws_obj = _build_fake_ws()
    new_ws_obj.send_json = AsyncMock()

    avatar_ws = AvatarWebSocket(handle)
    avatar_ws._ws = ws_obj

    fake_session = MagicMock()
    fake_session.ws_connect = AsyncMock(return_value=new_ws_obj)
    avatar_ws._session = fake_session

    with patch("asyncio.create_task"):
        await avatar_ws._reconnect()

    # The start handshake must be sent to the new WS
    new_ws_obj.send_json.assert_called_once()
    args = new_ws_obj.send_json.call_args[0][0]
    assert args["type"] == "session.start"
    assert args["sessionId"] == handle.liveavatar_session_id
    assert args["sessionToken"] == handle.session_token


# ---------------------------------------------------------------------------
# Connected gate via server message
# ---------------------------------------------------------------------------

async def test_avatar_ws_connected_gate_set_by_server() -> None:
    """_handle_server_message with state='connected' sets the _connected event."""
    handle = _make_handle()
    avatar_ws = AvatarWebSocket(handle)

    assert not avatar_ws._connected.is_set()
    await avatar_ws._handle_server_message(
        '{"type": "session.state_updated", "state": "connected"}'
    )
    assert avatar_ws._connected.is_set()


async def test_avatar_ws_connected_gate_not_set_for_other_state() -> None:
    """_handle_server_message with state!='connected' does not set the gate."""
    handle = _make_handle()
    avatar_ws = AvatarWebSocket(handle)

    await avatar_ws._handle_server_message(
        '{"type": "session.state_updated", "state": "starting"}'
    )
    assert not avatar_ws._connected.is_set()
