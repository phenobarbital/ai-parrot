"""Unit tests for LiveAvatarClient (TASK-002).

All HTTP calls are intercepted with ``aiohttp-pytest`` / ``aioresponses``.
Because the project uses aiohttp and has ``aiohttp`` as a test dependency,
we mock at the session level using ``unittest.mock`` and a simple fake
ClientSession.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.liveavatar import LiveAvatarClient
from parrot.integrations.liveavatar.models import AvatarSessionHandle, LiveAvatarConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg() -> LiveAvatarConfig:
    """Minimal LiveAvatarConfig for testing."""
    return LiveAvatarConfig(api_key="test-key", avatar_id="test-avatar", is_sandbox=True)


def _fake_session(
    status: int = 200,
    response_json: Optional[Dict[str, Any]] = None,
) -> MagicMock:
    """Build a mock aiohttp.ClientSession with a preset response."""
    if response_json is None:
        response_json = {
            "sessionId": "sess-123",
            "sessionToken": "tok-abc",
            "wsUrl": "wss://media.liveavatar.com/ws/sess-123",
        }

    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.content_type = "application/json"
    mock_resp.raise_for_status = MagicMock()  # no-op for 2xx
    mock_resp.json = AsyncMock(return_value=response_json)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_sess = MagicMock()
    mock_sess.post = MagicMock(return_value=mock_ctx)
    mock_sess.close = AsyncMock()
    return mock_sess


def _make_handle() -> AvatarSessionHandle:
    return AvatarSessionHandle(
        session_id="sess-123",
        liveavatar_session_id="sess-123",
        session_token="tok-abc",
        ws_url="wss://media.liveavatar.com/ws/sess-123",
        agent_name="test-avatar",
    )


# ---------------------------------------------------------------------------
# Auth header tests
# ---------------------------------------------------------------------------

async def test_liveavatar_client_auth_headers_on_create(cfg: LiveAvatarConfig) -> None:
    """create_session_token uses X-API-KEY, NOT Bearer."""
    fake_session = _fake_session()
    client = LiveAvatarClient(cfg, session=fake_session)
    # We need the session to be set; don't use context manager here.
    client._session = fake_session

    await client.create_session_token(cfg)

    call_args = fake_session.post.call_args
    headers = call_args.kwargs.get("headers", call_args[1].get("headers", {}))
    assert headers.get("X-API-KEY") == "test-key"
    assert "Authorization" not in headers


async def test_liveavatar_client_auth_headers_on_start(cfg: LiveAvatarConfig) -> None:
    """start_session uses Bearer <session_token>, NOT X-API-KEY."""
    fake_session = _fake_session(response_json={})
    client = LiveAvatarClient(cfg, session=fake_session)
    client._session = fake_session
    handle = _make_handle()

    # Suppress the keep-alive loop
    with patch.object(client, "_start_keep_alive"):
        await client.start_session(handle)

    call_args = fake_session.post.call_args
    headers = call_args.kwargs.get("headers", call_args[1].get("headers", {}))
    assert headers.get("Authorization") == f"Bearer {handle.session_token}"
    assert "X-API-KEY" not in headers


# ---------------------------------------------------------------------------
# Lifecycle: stop_session called on error exit path
# ---------------------------------------------------------------------------

async def test_session_lifecycle_stop_on_error(cfg: LiveAvatarConfig) -> None:
    """stop_session is called even when an exception occurs inside __aexit__."""
    stop_called = False

    async def fake_stop(handle: AvatarSessionHandle) -> None:
        nonlocal stop_called
        stop_called = True

    fake_session = _fake_session()
    client = LiveAvatarClient(cfg, session=fake_session)
    client._owns_session = False  # don't close the injected session

    handle = _make_handle()
    client._handle = handle

    with patch.object(client, "stop_session", side_effect=fake_stop):
        try:
            async with client:
                raise RuntimeError("simulated error inside context")
        except RuntimeError:
            pass  # expected

    assert stop_called, "stop_session must be called on every exit path"


# ---------------------------------------------------------------------------
# Keep-alive scheduling
# ---------------------------------------------------------------------------

async def test_keep_alive_loop_under_5min(cfg: LiveAvatarConfig) -> None:
    """Keep-alive is scheduled at < 300 s interval."""
    from parrot.integrations.liveavatar import client as client_module

    assert client_module._KEEP_ALIVE_INTERVAL < 300, (
        f"_KEEP_ALIVE_INTERVAL={client_module._KEEP_ALIVE_INTERVAL} must be < 300 s"
    )


async def test_keep_alive_task_started_on_start(cfg: LiveAvatarConfig) -> None:
    """_start_keep_alive is triggered after start_session."""
    fake_session = _fake_session(response_json={})
    client = LiveAvatarClient(cfg, session=fake_session)
    client._session = fake_session
    handle = _make_handle()

    start_ka_called = False

    def fake_start_keep_alive(h: AvatarSessionHandle) -> None:
        nonlocal start_ka_called
        start_ka_called = True

    with patch.object(client, "_start_keep_alive", side_effect=fake_start_keep_alive):
        await client.start_session(handle)

    assert start_ka_called


# ---------------------------------------------------------------------------
# max_session_duration forwarded
# ---------------------------------------------------------------------------

async def test_max_session_duration_forwarded(cfg: LiveAvatarConfig) -> None:
    """max_session_duration is included in the create_session_token payload."""
    cfg_with_dur = LiveAvatarConfig(
        api_key="test-key", avatar_id="test-avatar", max_session_duration=600
    )
    fake_session = _fake_session()
    client = LiveAvatarClient(cfg_with_dur, session=fake_session)
    client._session = fake_session

    await client.create_session_token(cfg_with_dur)

    call_args = fake_session.post.call_args
    body = call_args.kwargs.get("json", {})
    assert body.get("maxSessionDuration") == 600


# ---------------------------------------------------------------------------
# Idempotent stop (404 treated as success)
# ---------------------------------------------------------------------------

async def test_stop_session_idempotent_on_404(cfg: LiveAvatarConfig) -> None:
    """stop_session does not raise when the session is already closed (404)."""
    import aiohttp

    err_resp = MagicMock()
    err_resp.status = 404
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=err_resp)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    # Simulate raise_for_status raising a 404
    err_resp.raise_for_status = MagicMock(
        side_effect=aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=404
        )
    )

    fake_session = MagicMock()
    fake_session.post = MagicMock(return_value=mock_ctx)

    client = LiveAvatarClient(cfg, session=fake_session)
    client._session = fake_session
    handle = _make_handle()

    # Must not raise
    await client.stop_session(handle)
