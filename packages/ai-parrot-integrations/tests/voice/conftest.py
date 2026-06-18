"""Shared fixtures for voice + liveavatar tests (FEAT-245).

Centralises ``patched_stack`` so that test_voice_avatar_session.py and
test_voicechat_avatar_integration.py share a single authoritative definition.
If AvatarWebSocket gains a new async method in the future, update it here.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def patched_stack(mocker):
    """Mock the entire LiveAvatar transport stack.

    Patches LiveKitRoomManager, LiveAvatarClient, and AvatarWebSocket so no
    real network, LiveKit, or LiveAvatar connection is made.

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
    mocker.patch.dict(
        "os.environ",
        {"LIVEAVATAR_API_KEY": "k", "LIVEAVATAR_AVATAR_ID": "a"},
    )

    return rm, client, ws, tokens
