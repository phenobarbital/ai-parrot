"""Unit tests for AvatarWebSocket (TASK-003).

Uses a fake WebSocket object (not a real aiohttp WS) to verify:
- No frames are sent before the connected gate is set.
- PCM is chunked and sent as base64 ``agent.speak`` JSON frames
  (≈400 ms first chunk, ≈1 s thereafter, ≤1 MB cap).
- Reconnect re-opens the (pre-authenticated) WS without any handshake.
"""
from __future__ import annotations

import asyncio
import base64
from typing import Any, List
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
    """No agent.speak frames sent until session.state_updated == 'connected'."""
    handle = _make_handle()
    ws_obj = _build_fake_ws()

    avatar_ws = AvatarWebSocket(handle)
    avatar_ws._ws = ws_obj

    # Do NOT set _connected — gate is closed
    send_task = asyncio.create_task(avatar_ws.send_audio_frame(b"\x00" * 100))
    # Give the task a moment to run
    await asyncio.sleep(0.01)
    # Must not have sent anything yet
    ws_obj.send_json.assert_not_called()

    # Now open the gate
    avatar_ws._connected.set()
    await send_task

    # Now the audio frame was sent as a base64 agent.speak message
    ws_obj.send_json.assert_called_once()
    call_arg = ws_obj.send_json.call_args[0][0]
    assert call_arg["type"] == "agent.speak"
    assert base64.b64decode(call_arg["audio"]) == b"\x00" * 100


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

    # Audio rides inside agent.speak JSON frames as base64; decode each back
    # to raw PCM bytes to verify the chunking contract.
    calls: List[bytes] = []
    for call in ws_obj.send_json.call_args_list:
        payload = call.args[0]
        assert payload["type"] == "agent.speak"
        calls.append(base64.b64decode(payload["audio"]))
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
    ws_obj.send_json.assert_not_called()


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
    ws_obj.send_json.assert_called_once()
    payload = ws_obj.send_json.call_args[0][0]
    assert payload["type"] == "agent.speak_end"
    assert payload["event_id"]  # a fresh, non-empty correlation id


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

async def test_avatar_ws_reconnect_no_handshake() -> None:
    """On reconnect, the WS is re-opened with NO in-band handshake frame."""
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

    def _fake_create_task(coro: Any, name: str | None = None) -> MagicMock:
        # Close the coroutine so it does not emit a "never awaited" warning.
        coro.close()
        return MagicMock()

    with patch("asyncio.create_task", side_effect=_fake_create_task):
        await avatar_ws._reconnect()

    # The WS is re-opened to the (pre-authenticated) ws_url …
    fake_session.ws_connect.assert_awaited_once_with(handle.ws_url)
    # … and NO handshake frame is sent (auth lives in the ws_url).
    new_ws_obj.send_json.assert_not_called()


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


# ---------------------------------------------------------------------------
# Connected-gate timeout (I-1)
# ---------------------------------------------------------------------------

async def test_await_connected_times_out() -> None:
    """_await_connected raises RuntimeError if 'connected' never arrives."""
    import parrot.integrations.liveavatar.avatar_ws as ws_mod

    handle = _make_handle()
    avatar_ws = AvatarWebSocket(handle)
    avatar_ws._ws = _build_fake_ws()

    # Shrink the timeout so the test is fast.
    with patch.object(ws_mod, "_CONNECT_TIMEOUT", 0.02):
        with pytest.raises(RuntimeError, match="timed out waiting"):
            await avatar_ws.start_speaking()


# ---------------------------------------------------------------------------
# assume_connected: reused-session path opens the gate on handshake
# ---------------------------------------------------------------------------

async def test_assume_connected_opens_gate_on_connect_without_server_event() -> None:
    """With assume_connected=True the gate opens on handshake, no server event.

    Regression for the per-turn AvatarTurnSpeaker reuse path: the LITE server
    only emits ``session.state_updated == 'connected'`` once (at the session's
    first connect), so a late-attaching WS never sees it.  assume_connected
    must open the gate as soon as ws_connect returns so the turn never times
    out waiting for an event that will never arrive.
    """
    handle = _make_handle()
    ws_obj = _build_fake_ws()

    avatar_ws = AvatarWebSocket(handle, assume_connected=True)
    fake_session = MagicMock()
    fake_session.ws_connect = AsyncMock(return_value=ws_obj)
    avatar_ws._session = fake_session

    def _fake_create_task(coro: Any, name: str | None = None) -> MagicMock:
        coro.close()  # avoid "never awaited" warning
        return MagicMock()

    with patch("asyncio.create_task", side_effect=_fake_create_task):
        await avatar_ws._connect()

    # Gate is open even though NO session.state_updated arrived.
    assert avatar_ws._connected.is_set()
    # And start_speaking returns immediately instead of timing out.
    await avatar_ws.start_speaking()


async def test_assume_connected_false_still_gates() -> None:
    """Default (orchestrator) path: gate stays closed until the server event."""
    handle = _make_handle()
    ws_obj = _build_fake_ws()

    avatar_ws = AvatarWebSocket(handle)  # assume_connected defaults to False
    fake_session = MagicMock()
    fake_session.ws_connect = AsyncMock(return_value=ws_obj)
    avatar_ws._session = fake_session

    def _fake_create_task(coro: Any, name: str | None = None) -> MagicMock:
        coro.close()
        return MagicMock()

    with patch("asyncio.create_task", side_effect=_fake_create_task):
        await avatar_ws._connect()

    assert not avatar_ws._connected.is_set()


# ---------------------------------------------------------------------------
# Reader task lifecycle (C-2): _close cancels and awaits the reader
# ---------------------------------------------------------------------------

async def test_close_cancels_reader_task() -> None:
    """_close cancels the background reader task and clears the reference."""
    handle = _make_handle()
    avatar_ws = AvatarWebSocket(handle)
    avatar_ws._ws = _build_fake_ws()

    # A long-lived fake reader coroutine standing in for _reader_loop.
    async def _never_ending() -> None:
        await asyncio.sleep(3600)

    avatar_ws._reader_task = asyncio.create_task(_never_ending())
    await asyncio.sleep(0)  # let it start

    await avatar_ws._close()

    assert avatar_ws._reader_task is None
    assert avatar_ws._ws is None
