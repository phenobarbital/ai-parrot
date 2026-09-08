"""Unit tests for VoiceAvatarSession helper (FEAT-245 — TASK-1588).

All external calls (LiveKitRoomManager, LiveAvatarClient, AvatarWebSocket) are
mocked — no real network, LiveKit, or LiveAvatar connections.
"""
from __future__ import annotations

import pytest
from parrot.integrations.liveavatar.voice_session import VoiceAvatarSession


# patched_stack fixture lives in conftest.py (shared with integration tests)

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
    mocker.patch(
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


# ---------------------------------------------------------------------------
# FEAT-537 (TASK-2957): injected room credentials, callbacks, startup deadline
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402

from parrot.integrations.liveavatar.voice_session import (  # noqa: E402
    AvatarStartupTimeout,
)

_INJECTED = {
    "livekit_url": "wss://broadcast.livekit.cloud",
    "room_name": "room-b1",
    "avatar_publisher_token": "avatar-publisher-jwt",
}


@pytest.mark.asyncio
async def test_start_with_injected_room_skips_minting(patched_stack):
    """The broadcast allocates the room first; the avatar must not mint another."""
    rm, client, _ws, _tokens = patched_stack
    session = await VoiceAvatarSession.start(
        agent_id="ag",
        session_id="b1",
        tenant_id="t",
        avatar_identity="avatar-b1",
        broadcast=True,
        **_INJECTED,
    )
    rm.mint_room_tokens.assert_not_called()

    config = client.create_session_token.await_args.kwargs["livekit_config"]
    # Exactly the three OpenAPI-verified keys, carrying the AVATAR publisher
    # token — not the direct publisher's and not the fixed avatar-agent one.
    assert config == {
        "livekit_url": "wss://broadcast.livekit.cloud",
        "livekit_room": "room-b1",
        "livekit_client_token": "avatar-publisher-jwt",
    }
    assert session.room_name == "room-b1"
    assert session.avatar_identity == "avatar-b1"
    assert session.closed is False


@pytest.mark.asyncio
async def test_legacy_path_still_mints(patched_stack):
    rm, client, _ws, _tokens = patched_stack
    await VoiceAvatarSession.start(agent_id="ag", session_id="sess-1", tenant_id=None)
    rm.mint_room_tokens.assert_called_once()
    config = client.create_session_token.await_args.kwargs["livekit_config"]
    assert config["livekit_client_token"] == "agent-jwt"


@pytest.mark.asyncio
async def test_partial_injection_is_rejected(patched_stack):
    """Half-supplied credentials would silently fall back to minting a new room."""
    with pytest.raises(ValueError, match="must be supplied together"):
        await VoiceAvatarSession.start(
            agent_id="ag",
            session_id="b1",
            tenant_id="t",
            livekit_url="wss://x",
            room_name="room-b1",
        )


@pytest.mark.asyncio
async def test_viewer_credentials_on_the_injected_path(patched_stack):
    session = await VoiceAvatarSession.start(
        agent_id="ag",
        session_id="b1",
        tenant_id="t",
        viewer_token="per-lease-jwt",
        **_INJECTED,
    )
    assert session.viewer_credentials == {
        "livekit_url": "wss://broadcast.livekit.cloud",
        "client_token": "per-lease-jwt",
        "room": "room-b1",
    }
    # The publisher token never appears in the browser-facing projection.
    assert "avatar-publisher-jwt" not in str(session.viewer_credentials)


@pytest.mark.asyncio
async def test_viewer_credentials_default_to_empty_without_a_viewer_token(
    patched_stack,
):
    session = await VoiceAvatarSession.start(
        agent_id="ag", session_id="b1", tenant_id="t", **_INJECTED
    )
    assert session.viewer_credentials["client_token"] == ""


@pytest.mark.asyncio
async def test_broadcast_mode_configures_ws_callbacks(patched_stack, mocker):
    """Broadcast semantics: no silent reconnect, aggregation on, callbacks wired."""
    captured: list = []
    real_ws = patched_stack[2]

    def _factory(handle, **kwargs):
        captured.append(kwargs)
        return real_ws

    mocker.patch(
        "parrot.integrations.liveavatar.voice_session.AvatarWebSocket",
        side_effect=_factory,
    )

    def _on_event(_event: dict) -> None:
        return None

    def _on_close(_reason: str) -> None:
        return None

    await VoiceAvatarSession.start(
        agent_id="ag",
        session_id="b1",
        tenant_id="t",
        broadcast=True,
        on_event=_on_event,
        on_close=_on_close,
        send_timeout_s=2.0,
        **_INJECTED,
    )
    assert captured == [
        {
            "on_event": _on_event,
            "on_close": _on_close,
            "auto_reconnect": False,
            "aggregate": True,
            "send_timeout_s": 2.0,
        }
    ]


@pytest.mark.asyncio
async def test_non_broadcast_mode_builds_the_plain_websocket(patched_stack, mocker):
    """The single-user path must keep its exact pre-FEAT-537 construction."""
    captured: list = []
    real_ws = patched_stack[2]

    def _factory(handle, **kwargs):
        captured.append(kwargs)
        return real_ws

    mocker.patch(
        "parrot.integrations.liveavatar.voice_session.AvatarWebSocket",
        side_effect=_factory,
    )
    await VoiceAvatarSession.start(agent_id="ag", session_id="sess-1", tenant_id=None)
    assert captured == [{}]


@pytest.mark.asyncio
async def test_max_session_duration_reaches_the_config(patched_stack, mocker):
    from parrot.integrations.liveavatar import LiveAvatarConfig

    captured: list = []
    mocker.patch(
        "parrot.integrations.liveavatar.voice_session.LiveAvatarConfig",
        side_effect=lambda **kwargs: (
            captured.append(kwargs) or LiveAvatarConfig(**kwargs)
        ),
    )
    await VoiceAvatarSession.start(
        agent_id="ag",
        session_id="b1",
        tenant_id="t",
        max_session_duration_s=600,
        **_INJECTED,
    )
    assert captured[0]["max_session_duration"] == 600


# ── Startup deadline ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_startup_deadline_cleans_up(patched_stack):
    """A slow vendor must not leave a live session billing in the background."""
    _rm, client, ws, _tokens = patched_stack

    async def _stall(_handle):
        await asyncio.sleep(5)

    client.start_session.side_effect = _stall

    with pytest.raises(AvatarStartupTimeout, match="0.01s"):
        await VoiceAvatarSession.start(
            agent_id="ag",
            session_id="b1",
            tenant_id="t",
            startup_deadline_s=0.01,
            broadcast=True,
            **_INJECTED,
        )
    # Cancellation arrives as CancelledError, which a bare `except Exception`
    # would miss — the vendor session and HTTP client must still be released.
    client.stop_session.assert_awaited()
    client.aclose.assert_awaited()
    ws.__aenter__.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_deadline_cleans_up_an_opened_websocket(patched_stack):
    _rm, client, ws, _tokens = patched_stack

    async def _stall():
        await asyncio.sleep(5)

    ws.start_speaking.side_effect = _stall

    with pytest.raises(AvatarStartupTimeout):
        await VoiceAvatarSession.start(
            agent_id="ag",
            session_id="b1",
            tenant_id="t",
            startup_deadline_s=0.01,
            broadcast=True,
            **_INJECTED,
        )
    ws.__aenter__.assert_awaited()
    ws.__aexit__.assert_awaited()
    client.stop_session.assert_awaited()
    client.aclose.assert_awaited()


@pytest.mark.asyncio
async def test_startup_deadline_not_applied_when_unset(patched_stack):
    session = await VoiceAvatarSession.start(
        agent_id="ag", session_id="b1", tenant_id="t", **_INJECTED
    )
    assert session.closed is False


@pytest.mark.asyncio
async def test_avatar_startup_timeout_is_a_runtime_error(patched_stack):
    assert issubclass(AvatarStartupTimeout, RuntimeError)


@pytest.mark.asyncio
async def test_audit_properties(patched_stack):
    _rm, client, _ws, _tokens = patched_stack
    client.create_session_token.return_value.liveavatar_session_id = "vendor-123"
    session = await VoiceAvatarSession.start(
        agent_id="ag", session_id="b1", tenant_id="t", **_INJECTED
    )
    assert session.liveavatar_session_id == "vendor-123"
    await session.aclose()
    assert session.closed is True
