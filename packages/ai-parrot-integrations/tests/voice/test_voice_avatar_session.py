"""Unit tests for VoiceAvatarSession helper (FEAT-245 — TASK-1588).

All external calls (LiveKitRoomManager, LiveAvatarClient, AvatarWebSocket) are
mocked — no real network, LiveKit, or LiveAvatar connections.
"""
from __future__ import annotations

import pytest
from parrot.integrations.liveavatar.voice_session import VoiceAvatarSession


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_stack(mocker):
    """Mock the entire LiveAvatar transport stack.

    Returns:
        Tuple of (room_manager, client, ws, tokens) mocks.
    """
    # Room manager
    rm = mocker.Mock()
    tokens = mocker.Mock(
        livekit_url="wss://x",
        room="sess-1",
        client_token="viewer-jwt",
        agent_token="agent-jwt",
    )
    rm.mint_room_tokens.return_value = tokens
    mocker.patch(
        "parrot.integrations.liveavatar.voice_session.LiveKitRoomManager",
        return_value=rm,
    )

    # LiveAvatarClient
    client = mocker.Mock()
    client.aopen = mocker.AsyncMock(return_value=client)
    handle = mocker.Mock()
    handle.session_id = ""
    handle.tenant_id = None
    client.create_session_token = mocker.AsyncMock(return_value=handle)
    client.start_session = mocker.AsyncMock()
    client.stop_session = mocker.AsyncMock()
    client.aclose = mocker.AsyncMock()
    mocker.patch(
        "parrot.integrations.liveavatar.voice_session.LiveAvatarClient",
        return_value=client,
    )

    # AvatarWebSocket
    ws = mocker.Mock()
    ws.__aenter__ = mocker.AsyncMock(return_value=ws)
    ws.__aexit__ = mocker.AsyncMock(return_value=None)
    ws.start_speaking = mocker.AsyncMock()
    ws.send_audio_frame = mocker.AsyncMock()
    ws.finish_speaking = mocker.AsyncMock()
    ws.interrupt = mocker.AsyncMock()
    mocker.patch(
        "parrot.integrations.liveavatar.voice_session.AvatarWebSocket",
        return_value=ws,
    )

    # Required env vars
    mocker.patch.dict("os.environ", {"LIVEAVATAR_API_KEY": "k", "LIVEAVATAR_AVATAR_ID": "a"})

    return rm, client, ws, tokens


# ---------------------------------------------------------------------------
# TASK-1588 tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_and_viewer_credentials(patched_stack):
    """start() mints tokens, starts a LITE session, opens ws, awaits connected gate.
    viewer_credentials returns {livekit_url, client_token, room}.
    """
    rm, client, ws, tokens = patched_stack
    s = await VoiceAvatarSession.start(agent_id="ag", session_id="sess-1", tenant_id=None)
    assert s.viewer_credentials == {
        "livekit_url": "wss://x",
        "client_token": "viewer-jwt",
        "room": "sess-1",
    }
    client.start_session.assert_awaited_once()
    ws.start_speaking.assert_awaited_once()


@pytest.mark.asyncio
async def test_speak_no_transform(patched_stack):
    """speak(pcm) forwards bytes unchanged to send_audio_frame — no resampling."""
    _, _, ws, _ = patched_stack
    s = await VoiceAvatarSession.start(agent_id="ag", session_id="sess-1", tenant_id=None)
    pcm = b"\x00\x01" * 100
    await s.speak(pcm)
    ws.send_audio_frame.assert_awaited_once_with(pcm)


@pytest.mark.asyncio
async def test_finish_turn_delegates(patched_stack):
    """finish_turn() calls AvatarWebSocket.finish_speaking."""
    _, _, ws, _ = patched_stack
    s = await VoiceAvatarSession.start(agent_id="ag", session_id="sess-1", tenant_id=None)
    await s.finish_turn()
    ws.finish_speaking.assert_awaited_once()


@pytest.mark.asyncio
async def test_interrupt_delegates(patched_stack):
    """interrupt() calls AvatarWebSocket.interrupt."""
    _, _, ws, _ = patched_stack
    s = await VoiceAvatarSession.start(agent_id="ag", session_id="sess-1", tenant_id=None)
    await s.interrupt()
    ws.interrupt.assert_awaited_once()


@pytest.mark.asyncio
async def test_aclose_idempotent(patched_stack):
    """aclose() stops session + closes ws; safe to call twice without raising."""
    _, client, ws, _ = patched_stack
    s = await VoiceAvatarSession.start(agent_id="ag", session_id="sess-1", tenant_id=None)
    await s.aclose()
    await s.aclose()  # must not raise and must not double-call stop_session
    # stop_session and aclose are called exactly once (idempotent guard)
    client.stop_session.assert_awaited_once()
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_viewer_credentials_no_agent_token(patched_stack):
    """viewer_credentials must NOT expose agent_token."""
    s = await VoiceAvatarSession.start(agent_id="ag", session_id="sess-1", tenant_id=None)
    creds = s.viewer_credentials
    assert "agent_token" not in creds
    assert "session_token" not in creds
    assert "ws_url" not in creds
    # Only these three keys
    assert set(creds.keys()) == {"livekit_url", "client_token", "room"}


@pytest.mark.asyncio
async def test_start_with_avatar_id_override(patched_stack, mocker):
    """avatar_id override uses that ID instead of LIVEAVATAR_AVATAR_ID env var."""
    rm, client, ws, _ = patched_stack
    # Capture the LiveAvatarConfig constructed
    from parrot.integrations.liveavatar import LiveAvatarConfig

    captured_cfg: list = []
    original_patch = mocker.patch(
        "parrot.integrations.liveavatar.voice_session.LiveAvatarConfig",
        side_effect=lambda **kwargs: (
            captured_cfg.append(kwargs) or LiveAvatarConfig(**kwargs)
        ),
    )
    await VoiceAvatarSession.start(
        agent_id="ag", session_id="sess-1", tenant_id=None, avatar_id="custom-av"
    )
    assert captured_cfg[0]["avatar_id"] == "custom-av"


@pytest.mark.asyncio
async def test_start_cleanup_on_failure_start_session(patched_stack, mocker):
    """On start_session failure, client is cleaned up; ws not yet opened."""
    rm, client, ws, _ = patched_stack
    client.start_session.side_effect = RuntimeError("session API down")

    with pytest.raises(RuntimeError, match="session API down"):
        await VoiceAvatarSession.start(agent_id="ag", session_id="sess-1", tenant_id=None)

    # ws.__aenter__ was NOT yet called (ws is opened after start_session succeeds)
    ws.__aenter__.assert_not_awaited()
    # client.aclose must have been called in cleanup
    client.aclose.assert_awaited()


@pytest.mark.asyncio
async def test_start_cleanup_on_ws_failure(patched_stack, mocker):
    """On AvatarWebSocket.start_speaking failure, ws and client are cleaned up."""
    rm, client, ws, _ = patched_stack
    ws.start_speaking.side_effect = RuntimeError("timeout waiting for connected")

    with pytest.raises(RuntimeError, match="timeout"):
        await VoiceAvatarSession.start(agent_id="ag", session_id="sess-1", tenant_id=None)

    # ws.__aenter__ was called (ws was entered before start_speaking)
    ws.__aenter__.assert_awaited()
    # ws.__aexit__ must have been called in cleanup
    ws.__aexit__.assert_awaited()
    # client.aclose was called in cleanup
    client.aclose.assert_awaited()
