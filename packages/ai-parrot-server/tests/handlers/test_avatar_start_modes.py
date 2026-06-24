"""Unit tests for _start_avatar_session mode-select + 402 auto-fallback (FEAT-256 TASK-1629).

Covers:
- avatar=false → no LiveAvatar start_session; publisher started; 200 with creds.
- avatar=true + LiveAvatar 402 → auto-fallback to publisher; 200 (not 402).
- avatar=true + credits → unchanged LiveAvatar path.
- _stop_avatar_session tears down both avatar-ON (client) and avatar-OFF (publisher).
"""
from __future__ import annotations

import json
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientResponseError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_no_credits_error() -> ClientResponseError:
    """Build an aiohttp ClientResponseError that looks like a 402/4033 no-credits error."""
    exc = ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=403,
        message="Error code 4033: No credits available",
    )
    return exc


def _fake_tokens():
    t = MagicMock()
    t.livekit_url = "wss://x.livekit.cloud"
    t.room = "sess-test"
    t.client_token = "viewer-jwt"
    t.agent_token = "agent-jwt"
    return t


def _fake_request(session_id: str = "sess-test", extra_body: dict | None = None):
    """Build a fake aiohttp.web.Request with a plain dict as the app."""
    body: dict = {"session_id": session_id}
    if extra_body:
        body.update(extra_body)
    req = MagicMock()
    req.match_info = {"agent_id": "test-agent"}
    req.app = {}
    req.json = AsyncMock(return_value=body)
    return req


def _build_fake_liveavatar_modules(
    fake_tokens,
    *,
    start_session_raises: Exception | None = None,
):
    """Build fake ``parrot.integrations.liveavatar`` + optin modules.

    Args:
        fake_tokens: Tokens returned by mint_room_tokens.
        start_session_raises: If set, client.start_session raises this exception.
    """
    fake_handle = MagicMock()
    fake_handle.session_id = "sess-test"

    fake_client = AsyncMock()
    fake_client.aopen = AsyncMock()
    fake_client.create_session_token = AsyncMock(return_value=fake_handle)
    if start_session_raises is not None:
        fake_client.start_session = AsyncMock(side_effect=start_session_raises)
    else:
        fake_client.start_session = AsyncMock(return_value=None)
    fake_client.stop_session = AsyncMock()
    fake_client.aclose = AsyncMock()

    fake_liveavatar_mod = types.ModuleType("parrot.integrations.liveavatar")
    fake_liveavatar_mod.LiveAvatarClient = MagicMock(return_value=fake_client)
    fake_liveavatar_mod.LiveAvatarConfig = MagicMock()
    fake_liveavatar_mod.LiveKitRoomManager = MagicMock()
    fake_liveavatar_mod.LiveKitRoomManager.return_value.mint_room_tokens.return_value = fake_tokens

    fake_optin_mod = types.ModuleType("parrot.integrations.liveavatar.optin")
    fake_optin_mod.is_avatar_enabled = MagicMock(return_value=True)  # type: ignore[attr-defined]

    return fake_liveavatar_mod, fake_optin_mod, fake_client, fake_handle


def _build_fake_publisher_module():
    """Build a fake ``parrot.integrations.liveavatar.room_audio_publisher`` module."""
    fake_publisher = AsyncMock()
    fake_publisher.aclose = AsyncMock()

    fake_pub_mod = types.ModuleType(
        "parrot.integrations.liveavatar.room_audio_publisher"
    )
    fake_pub_cls = MagicMock()
    fake_pub_cls.start = AsyncMock(return_value=fake_publisher)
    fake_pub_mod.RoomAudioPublisher = fake_pub_cls  # type: ignore[attr-defined]

    return fake_pub_mod, fake_publisher


_ENV = {
    "LIVEAVATAR_API_KEY": "test-key",
    "LIVEAVATAR_AVATAR_ID": "test-avatar",
    "LIVEKIT_URL": "wss://x.livekit.cloud",
    "LIVEKIT_API_KEY": "lk-key",
    "LIVEKIT_API_SECRET": "lk-secret",
}

_INJECT_KEYS = [
    "parrot.integrations.liveavatar",
    "parrot.integrations.liveavatar.optin",
    "parrot.integrations.liveavatar.room_audio_publisher",
]


def _inject_modules(modules: dict):
    saved = {k: sys.modules.get(k) for k in _INJECT_KEYS}
    for k, v in modules.items():
        if v is not None:
            sys.modules[k] = v
    return saved


def _restore_modules(saved: dict):
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_avatar_off_uses_publisher() -> None:
    """avatar=false → no LiveAvatar start_session; publisher started; 200 with creds."""
    from parrot.handlers.avatar import _start_avatar_session

    tokens = _fake_tokens()
    fake_la, fake_optin, fake_client, _ = _build_fake_liveavatar_modules(tokens)
    fake_pub_mod, fake_publisher = _build_fake_publisher_module()

    req = _fake_request(extra_body={"avatar": False})

    saved = _inject_modules({
        "parrot.integrations.liveavatar": fake_la,
        "parrot.integrations.liveavatar.optin": fake_optin,
        "parrot.integrations.liveavatar.room_audio_publisher": fake_pub_mod,
    })
    try:
        with patch.dict(os.environ, _ENV):
            response = await _start_avatar_session(req)
    finally:
        _restore_modules(saved)

    # Must be a 200
    assert response.status == 200
    data = json.loads(response.body)  # type: ignore[attr-defined]
    assert data["livekit_url"] == "wss://x.livekit.cloud"
    assert data["client_token"] == "viewer-jwt"
    assert data["session_id"] == "sess-test"

    # LiveAvatar.start_session must NOT have been called
    fake_client.start_session.assert_not_called()

    # Publisher must have been started
    fake_pub_mod.RoomAudioPublisher.start.assert_called_once()

    # Session store must carry the publisher record
    store = req.app["avatar_sessions"]
    assert "sess-test" in store
    assert store["sess-test"]["publisher"] is fake_publisher


@pytest.mark.asyncio
async def test_start_402_autofalls_back() -> None:
    """avatar=true + LiveAvatar 402 → auto-fallback to publisher; 200 (not 402)."""
    from parrot.handlers.avatar import _start_avatar_session

    tokens = _fake_tokens()
    no_credits_exc = _make_no_credits_error()
    fake_la, fake_optin, fake_client, _ = _build_fake_liveavatar_modules(
        tokens, start_session_raises=no_credits_exc
    )
    fake_pub_mod, fake_publisher = _build_fake_publisher_module()

    req = _fake_request(extra_body={"avatar": True})

    saved = _inject_modules({
        "parrot.integrations.liveavatar": fake_la,
        "parrot.integrations.liveavatar.optin": fake_optin,
        "parrot.integrations.liveavatar.room_audio_publisher": fake_pub_mod,
    })
    try:
        with patch.dict(os.environ, _ENV):
            response = await _start_avatar_session(req)
    finally:
        _restore_modules(saved)

    # Must be 200 (NOT 402)
    assert response.status == 200
    data = json.loads(response.body)  # type: ignore[attr-defined]
    assert "livekit_url" in data
    assert "client_token" in data

    # LiveAvatar client must have been closed (cleanup) before fallback
    fake_client.aclose.assert_called_once()

    # Publisher must have been started (fallback)
    fake_pub_mod.RoomAudioPublisher.start.assert_called_once()

    # Session store must carry the publisher record
    store = req.app["avatar_sessions"]
    assert store["sess-test"]["publisher"] is fake_publisher


@pytest.mark.asyncio
async def test_start_avatar_on_unchanged() -> None:
    """avatar=true + credits → unchanged LiveAvatar path; client stored."""
    from parrot.handlers.avatar import _start_avatar_session

    tokens = _fake_tokens()
    fake_la, fake_optin, fake_client, _ = _build_fake_liveavatar_modules(tokens)
    fake_pub_mod, _ = _build_fake_publisher_module()

    req = _fake_request(extra_body={"avatar": True})

    saved = _inject_modules({
        "parrot.integrations.liveavatar": fake_la,
        "parrot.integrations.liveavatar.optin": fake_optin,
        "parrot.integrations.liveavatar.room_audio_publisher": fake_pub_mod,
    })
    try:
        with patch.dict(os.environ, _ENV):
            response = await _start_avatar_session(req)
    finally:
        _restore_modules(saved)

    assert response.status == 200
    data = json.loads(response.body)  # type: ignore[attr-defined]
    assert data["client_token"] == "viewer-jwt"

    # LiveAvatar must have been used
    fake_client.start_session.assert_called_once()
    # Publisher must NOT have been started
    fake_pub_mod.RoomAudioPublisher.start.assert_not_called()

    # Session store must carry the client record (not publisher)
    store = req.app["avatar_sessions"]
    assert "client" in store["sess-test"]
    assert "publisher" not in store["sess-test"]


@pytest.mark.asyncio
async def test_stop_tears_down_publisher() -> None:
    """_stop_avatar_session calls publisher.aclose() for avatar-OFF sessions."""
    from parrot.handlers.avatar import _stop_avatar_session

    fake_publisher = AsyncMock()
    fake_publisher.aclose = AsyncMock()

    req = MagicMock()
    req.app = {
        "avatar_sessions": {
            "sess-test": {"publisher": fake_publisher},
        }
    }
    req.json = AsyncMock(return_value={"session_id": "sess-test"})

    response = await _stop_avatar_session(req)

    assert response.status == 204
    fake_publisher.aclose.assert_called_once()
    # Session must have been removed from the store
    assert "sess-test" not in req.app["avatar_sessions"]


@pytest.mark.asyncio
async def test_stop_tears_down_liveavatar_client() -> None:
    """_stop_avatar_session calls stop_session + aclose() for avatar-ON sessions."""
    from parrot.handlers.avatar import _stop_avatar_session

    fake_client = AsyncMock()
    fake_handle = MagicMock()

    req = MagicMock()
    req.app = {
        "avatar_sessions": {
            "sess-test": {"client": fake_client, "handle": fake_handle},
        }
    }
    req.json = AsyncMock(return_value={"session_id": "sess-test"})

    response = await _stop_avatar_session(req)

    assert response.status == 204
    fake_client.stop_session.assert_called_once_with(fake_handle)
    fake_client.aclose.assert_called_once()
    assert "sess-test" not in req.app["avatar_sessions"]


@pytest.mark.asyncio
async def test_start_default_avatar_flag_is_true() -> None:
    """When avatar is omitted from the body it defaults to True (back-compat)."""
    from parrot.handlers.avatar import _start_avatar_session

    tokens = _fake_tokens()
    fake_la, fake_optin, fake_client, _ = _build_fake_liveavatar_modules(tokens)
    fake_pub_mod, _ = _build_fake_publisher_module()

    # NO "avatar" key in body
    req = _fake_request()

    saved = _inject_modules({
        "parrot.integrations.liveavatar": fake_la,
        "parrot.integrations.liveavatar.optin": fake_optin,
        "parrot.integrations.liveavatar.room_audio_publisher": fake_pub_mod,
    })
    try:
        with patch.dict(os.environ, _ENV):
            response = await _start_avatar_session(req)
    finally:
        _restore_modules(saved)

    assert response.status == 200
    # LiveAvatar must have been used (default is avatar=True)
    fake_client.start_session.assert_called_once()
    fake_pub_mod.RoomAudioPublisher.start.assert_not_called()
