"""Unit tests for LiveAvatarClient (TASK-002, TASK-1592).

All HTTP calls are intercepted with ``aiohttp-pytest`` / ``aioresponses``.
Because the project uses aiohttp and has ``aiohttp`` as a test dependency,
we mock at the session level using ``unittest.mock`` and a simple fake
ClientSession.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.liveavatar import LiveAvatarClient
from parrot.integrations.liveavatar.models import (
    AvatarSessionHandle,
    FullModeConfig,
    FullModeSessionHandle,
    LiveAvatarConfig,
)


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
        # The /token response wraps the payload in a ``data`` envelope and uses
        # snake_case keys (matches LiveAvatar's SDKSessionTokenSchema).
        response_json = {
            "code": 0,
            "message": "ok",
            "data": {
                "session_id": "sess-123",
                "session_token": "tok-abc",
            },
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
    # Endpoint is /v1/sessions/token (NOT the bare /v1/sessions, which 405s).
    url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
    assert url.endswith("/v1/sessions/token")
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


async def test_keep_alive_sends_session_id_in_body(cfg: LiveAvatarConfig) -> None:
    """keep_alive POSTs the session_id in the body (empty body → 400)."""
    fake_session = _fake_session(response_json={})
    client = LiveAvatarClient(cfg, session=fake_session)
    client._session = fake_session
    handle = _make_handle()

    await client.keep_alive(handle)

    call_args = fake_session.post.call_args
    url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
    assert url.endswith("/v1/sessions/keep-alive")
    assert call_args.kwargs.get("json") == {"session_id": "sess-123"}


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
    assert body.get("max_session_duration") == 600


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


# ---------------------------------------------------------------------------
# create_session_token leaves session_id empty for the caller (I-2)
# ---------------------------------------------------------------------------

async def test_create_session_token_leaves_session_id_empty(cfg: LiveAvatarConfig) -> None:
    """session_id is the ai-parrot id (unknown here) → empty; liveavatar id set."""
    fake_session = _fake_session()
    client = LiveAvatarClient(cfg, session=fake_session)
    client._session = fake_session

    handle = await client.create_session_token(cfg)

    assert handle.session_id == "", "HTTP layer must not invent the ai-parrot session_id"
    assert handle.liveavatar_session_id == "sess-123"


# ---------------------------------------------------------------------------
# aclose awaits keep-alive cancellation (C-4)
# ---------------------------------------------------------------------------

async def test_aclose_cancels_and_awaits_keep_alive(cfg: LiveAvatarConfig) -> None:
    """aclose cancels the keep-alive task and awaits its termination."""
    fake_session = _fake_session()
    client = LiveAvatarClient(cfg, session=fake_session)
    client._owns_session = False  # keep the injected session

    async def _never_ending() -> None:
        await asyncio.sleep(3600)

    client._keep_alive_task = asyncio.create_task(_never_ending())
    await asyncio.sleep(0)  # let it start

    await client.aclose()

    assert client._keep_alive_task is None


# ---------------------------------------------------------------------------
# FEAT-248 TASK-1592: FULL Mode Client Extension tests
# ---------------------------------------------------------------------------


@pytest.fixture
def fullmode_cfg() -> FullModeConfig:
    """FullModeConfig fixture for FULL mode tests."""
    return FullModeConfig(
        api_key="test-key",
        avatar_id="test-avatar",
        voice_id="test-voice",
        language="en",
        is_sandbox=True,
    )


def _fake_get_session(
    response_json: Optional[Dict[str, Any]] = None,
) -> MagicMock:
    """Build a mock aiohttp.ClientSession that handles GET requests."""
    if response_json is None:
        response_json = {
            "code": 200,
            "data": [],
            "message": "success",
        }

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.content_type = "application/json"
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = AsyncMock(return_value=response_json)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_sess = MagicMock()
    mock_sess.get = MagicMock(return_value=mock_ctx)
    mock_sess.post = MagicMock(return_value=mock_ctx)
    mock_sess.close = AsyncMock()
    return mock_sess


class TestCreateFullSessionToken:
    """Tests for LiveAvatarClient.create_full_session_token()."""

    async def test_payload_mode_full(self, fullmode_cfg: FullModeConfig) -> None:
        """Payload contains mode=FULL, avatar_persona, no context_id."""
        fake_session = _fake_session()
        client = LiveAvatarClient(fullmode_cfg, session=fake_session)
        client._session = fake_session

        await client.create_full_session_token(fullmode_cfg)

        call_args = fake_session.post.call_args
        body = call_args.kwargs.get("json", {})
        assert body.get("mode") == "FULL"
        assert body.get("avatar_id") == "test-avatar"
        assert "avatar_persona" in body
        assert "context_id" not in body
        assert "llm_configuration_id" not in body

    async def test_no_llm_configuration(self, fullmode_cfg: FullModeConfig) -> None:
        """llm_configuration_id and context_id are absent from payload."""
        fake_session = _fake_session()
        client = LiveAvatarClient(fullmode_cfg, session=fake_session)
        client._session = fake_session

        await client.create_full_session_token(fullmode_cfg)

        call_args = fake_session.post.call_args
        body = call_args.kwargs.get("json", {})
        assert "llm_configuration_id" not in body
        assert "context_id" not in body

    async def test_avatar_persona_with_voice_id(self, fullmode_cfg: FullModeConfig) -> None:
        """avatar_persona contains voice_id and language when set."""
        fake_session = _fake_session()
        client = LiveAvatarClient(fullmode_cfg, session=fake_session)
        client._session = fake_session

        await client.create_full_session_token(fullmode_cfg)

        call_args = fake_session.post.call_args
        body = call_args.kwargs.get("json", {})
        persona = body.get("avatar_persona", {})
        assert persona.get("voice_id") == "test-voice"
        assert persona.get("language") == "en"

    async def test_no_avatar_persona_without_voice_id(self) -> None:
        """When voice_id is None and language is empty, no avatar_persona is sent."""
        cfg = FullModeConfig(api_key="k", avatar_id="a", voice_id=None, language="")
        fake_session = _fake_session()
        client = LiveAvatarClient(cfg, session=fake_session)
        client._session = fake_session

        await client.create_full_session_token(cfg)

        call_args = fake_session.post.call_args
        body = call_args.kwargs.get("json", {})
        assert "avatar_persona" not in body

    async def test_returns_fullmode_handle(self, fullmode_cfg: FullModeConfig) -> None:
        """create_full_session_token returns FullModeSessionHandle."""
        fake_session = _fake_session()
        client = LiveAvatarClient(fullmode_cfg, session=fake_session)
        client._session = fake_session

        handle = await client.create_full_session_token(fullmode_cfg)

        assert isinstance(handle, FullModeSessionHandle)
        assert handle.liveavatar_session_id == "sess-123"
        assert handle.session_token == "tok-abc"
        assert handle.session_id == ""  # populated by caller

    async def test_interactivity_type_in_payload(self, fullmode_cfg: FullModeConfig) -> None:
        """interactivity_type is included in the payload."""
        fake_session = _fake_session()
        client = LiveAvatarClient(fullmode_cfg, session=fake_session)
        client._session = fake_session

        await client.create_full_session_token(fullmode_cfg)

        call_args = fake_session.post.call_args
        body = call_args.kwargs.get("json", {})
        assert body.get("interactivity_type") == "CONVERSATIONAL"


class TestStartSessionFullMode:
    """Tests for start_session() behavior with FullModeSessionHandle."""

    async def test_populates_livekit_fields(self) -> None:
        """start_session sets livekit_url and livekit_client_token on FullModeSessionHandle."""
        cfg = FullModeConfig(api_key="k", avatar_id="a")
        start_response = {
            "code": 200,
            "data": {
                "livekit_url": "wss://test.livekit.cloud",
                "livekit_client_token": "eyJtest...",
            },
            "message": "success",
        }
        fake_session = _fake_session(response_json=start_response)
        client = LiveAvatarClient(cfg, session=fake_session)
        client._session = fake_session

        handle = FullModeSessionHandle(
            session_id="s1",
            liveavatar_session_id="la1",
            session_token="tok",
            ws_url="",
            agent_name="agent",
        )
        with patch.object(client, "_start_keep_alive"):
            await client.start_session(handle)

        assert handle.livekit_url == "wss://test.livekit.cloud"
        assert handle.livekit_client_token == "eyJtest..."

    async def test_lite_handle_not_affected(self) -> None:
        """start_session does not set livekit fields on a plain AvatarSessionHandle."""
        cfg = LiveAvatarConfig(api_key="k", avatar_id="a")
        start_response = {
            "code": 200,
            "data": {"ws_url": "wss://media.liveavatar.com/ws/sess-123"},
            "message": "success",
        }
        fake_session = _fake_session(response_json=start_response)
        client = LiveAvatarClient(cfg, session=fake_session)
        client._session = fake_session

        handle = AvatarSessionHandle(
            session_id="s1",
            liveavatar_session_id="la1",
            session_token="tok",
            ws_url="",
            agent_name="agent",
        )
        with patch.object(client, "_start_keep_alive"):
            await client.start_session(handle)

        assert handle.ws_url == "wss://media.liveavatar.com/ws/sess-123"
        # Plain handle does not have livekit fields
        assert not hasattr(handle, "livekit_url")


class TestListAvatars:
    """Tests for LiveAvatarClient.list_avatars()."""

    async def test_calls_get_avatars(self, fullmode_cfg: FullModeConfig) -> None:
        """GET /v1/avatars is called with X-API-KEY header."""
        avatars_response = {
            "code": 200,
            "data": [{"id": "av1", "name": "Avatar 1"}],
            "message": "success",
        }
        fake_session = _fake_get_session(response_json=avatars_response)
        client = LiveAvatarClient(fullmode_cfg, session=fake_session)
        client._session = fake_session

        result = await client.list_avatars(fullmode_cfg)

        call_args = fake_session.get.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert url.endswith("/v1/avatars")
        headers = call_args.kwargs.get("headers", {})
        assert headers.get("X-API-KEY") == "test-key"
        assert result == [{"id": "av1", "name": "Avatar 1"}]

    async def test_returns_list(self, fullmode_cfg: FullModeConfig) -> None:
        """list_avatars returns a list."""
        avatars_response = {"code": 200, "data": [], "message": "success"}
        fake_session = _fake_get_session(response_json=avatars_response)
        client = LiveAvatarClient(fullmode_cfg, session=fake_session)
        client._session = fake_session

        result = await client.list_avatars(fullmode_cfg)

        assert isinstance(result, list)


class TestListVoices:
    """Tests for LiveAvatarClient.list_voices()."""

    async def test_calls_get_voices(self, fullmode_cfg: FullModeConfig) -> None:
        """GET /v1/voices is called with X-API-KEY header."""
        voices_response = {
            "code": 200,
            "data": [{"id": "v1", "name": "Voice 1"}],
            "message": "success",
        }
        fake_session = _fake_get_session(response_json=voices_response)
        client = LiveAvatarClient(fullmode_cfg, session=fake_session)
        client._session = fake_session

        result = await client.list_voices(fullmode_cfg)

        call_args = fake_session.get.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert url.endswith("/v1/voices")
        headers = call_args.kwargs.get("headers", {})
        assert headers.get("X-API-KEY") == "test-key"
        assert result == [{"id": "v1", "name": "Voice 1"}]


class TestGetSessionTranscript:
    """Tests for LiveAvatarClient.get_session_transcript()."""

    async def test_calls_get_transcript(self, fullmode_cfg: FullModeConfig) -> None:
        """GET /v1/sessions/{id}/transcript is called correctly."""
        transcript_response = {
            "code": 200,
            "data": {"entries": [{"speaker": "user", "text": "Hello"}]},
            "message": "success",
        }
        fake_session = _fake_get_session(response_json=transcript_response)
        client = LiveAvatarClient(fullmode_cfg, session=fake_session)
        client._session = fake_session

        result = await client.get_session_transcript(fullmode_cfg, "session-123")

        call_args = fake_session.get.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert "session-123" in url
        assert url.endswith("/transcript")
        assert result == {"entries": [{"speaker": "user", "text": "Hello"}]}
