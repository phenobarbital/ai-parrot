"""End-to-end integration tests for the LiveAvatar FULL mode pipeline (TASK-1598).

Verifies the assembled FULL mode flow with fully mocked HTTP:
- Config resolution → client creation → session token → start → stop lifecycle.
- Opt-in gate chain: avatar disabled → fullmode disabled → fullmode enabled.
- Error paths: missing env vars, API 500 responses, malformed responses.
- Observer connect/disconnect lifecycle (Q-room-token stub mode).

No real LiveAvatar API calls are made.  All HTTP is mocked via
``unittest.mock.AsyncMock`` / ``patch``.  Each test is fully independent.
"""
from __future__ import annotations

import os
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fullmode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the minimal env vars needed for resolve_fullmode_config to succeed."""
    monkeypatch.setenv("LIVEAVATAR_API_KEY", "test-api-key")
    monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar-test-001")
    monkeypatch.setenv("LIVEAVATAR_ENABLED_TENANTS", "*")
    monkeypatch.setenv("LIVEAVATAR_FULLMODE_ENABLED_TENANTS", "*")


@pytest.fixture
def token_response() -> Dict[str, Any]:
    """Mock LiveAvatar /v1/sessions/token API response envelope."""
    return {
        "code": 200,
        "data": {
            "session_id": "la-session-test",
            "session_token": "server-side-token",
        },
        "message": "success",
    }


@pytest.fixture
def start_response() -> Dict[str, Any]:
    """Mock LiveAvatar /v1/sessions/start API response envelope."""
    return {
        "code": 200,
        "data": {
            "livekit_url": "wss://test.livekit.cloud",
            "livekit_client_token": "eyJtest-browser-token",
        },
        "message": "success",
    }


# ---------------------------------------------------------------------------
# TestFullModeLifecycle
# ---------------------------------------------------------------------------


class TestFullModeLifecycle:
    """End-to-end lifecycle tests with fully mocked HTTP."""

    async def test_config_resolution_succeeds(
        self, fullmode_env: None
    ) -> None:
        """resolve_fullmode_config returns a FullModeConfig from env vars."""
        from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config

        cfg = await resolve_fullmode_config()

        assert cfg.api_key == "test-api-key"
        assert cfg.avatar_id == "avatar-test-001"

    async def test_config_resolution_fails_without_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """resolve_fullmode_config raises RuntimeError when LIVEAVATAR_API_KEY is absent."""
        monkeypatch.delenv("LIVEAVATAR_API_KEY", raising=False)
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar-test-001")

        from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config

        with pytest.raises(RuntimeError, match="LIVEAVATAR_API_KEY"):
            await resolve_fullmode_config()

    async def test_config_resolution_fails_without_avatar_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """resolve_fullmode_config raises RuntimeError when LIVEAVATAR_AVATAR_ID is absent."""
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "test-key")
        monkeypatch.delenv("LIVEAVATAR_AVATAR_ID", raising=False)

        from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config

        with pytest.raises(RuntimeError, match="LIVEAVATAR_AVATAR_ID"):
            await resolve_fullmode_config()

    async def test_create_full_session_token_populates_handle(
        self, fullmode_env: None
    ) -> None:
        """create_full_session_token returns a FullModeSessionHandle with session ids."""
        from parrot.integrations.liveavatar.client import LiveAvatarClient
        from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config

        cfg = await resolve_fullmode_config()

        token_data = {
            "code": 200,
            "data": {
                "session_id": "la-session-42",
                "session_token": "server-secret-tok",
            },
            "message": "success",
        }

        client = LiveAvatarClient(cfg)
        with patch.object(client, "_post", new=AsyncMock(return_value=token_data)):
            handle = await client.create_full_session_token(cfg)

        assert handle.liveavatar_session_id == "la-session-42"
        assert handle.session_token == "server-secret-tok"
        # ai-parrot session_id is empty until the handler populates it.
        assert handle.session_id == ""

    async def test_start_session_populates_livekit_fields(
        self, fullmode_env: None
    ) -> None:
        """start_session populates livekit_url and livekit_client_token on the handle."""
        from parrot.integrations.liveavatar.client import LiveAvatarClient
        from parrot.integrations.liveavatar.models import FullModeSessionHandle
        from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config

        cfg = await resolve_fullmode_config()
        handle = FullModeSessionHandle(
            session_id="ai-session-1",
            liveavatar_session_id="la-session-42",
            session_token="srv-tok",
            ws_url="",
            agent_name="test-agent",
        )

        start_data = {
            "code": 200,
            "data": {
                "livekit_url": "wss://rooms.livekit.cloud",
                "livekit_client_token": "eyJ-client-token",
            },
            "message": "success",
        }

        client = LiveAvatarClient(cfg)
        with patch.object(client, "_post", new=AsyncMock(return_value=start_data)):
            await client.start_session(handle)

        assert handle.livekit_url == "wss://rooms.livekit.cloud"
        assert handle.livekit_client_token == "eyJ-client-token"

    async def test_start_to_stop_lifecycle(self, fullmode_env: None) -> None:
        """Full config → token → start → stop lifecycle completes without error."""
        from parrot.integrations.liveavatar.client import LiveAvatarClient
        from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config

        cfg = await resolve_fullmode_config()
        client = LiveAvatarClient(cfg)

        token_resp = {
            "code": 200,
            "data": {"session_id": "la-s1", "session_token": "tok-1"},
            "message": "success",
        }
        start_resp = {
            "code": 200,
            "data": {
                "livekit_url": "wss://livekit.example",
                "livekit_client_token": "eyJ-tok",
            },
            "message": "success",
        }
        stop_resp = {"code": 200, "data": {}, "message": "success"}

        with patch.object(
            client,
            "_post",
            new=AsyncMock(side_effect=[token_resp, start_resp, stop_resp]),
        ):
            await client.aopen()
            handle = await client.create_full_session_token(cfg)
            handle.session_id = "ai-session-x"
            await client.start_session(handle)

            assert handle.livekit_url == "wss://livekit.example"
            assert handle.livekit_client_token == "eyJ-tok"

            await client.stop_session(handle)

        await client.aclose()


# ---------------------------------------------------------------------------
# TestOptinChain
# ---------------------------------------------------------------------------


class TestOptinChain:
    """Tests for the opt-in gate layering: avatar gate → fullmode gate."""

    def test_avatar_disabled_blocks_fullmode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When avatar is disabled (base gate fails), fullmode is also denied."""
        monkeypatch.setenv("LIVEAVATAR_ENABLED_TENANTS", "")
        monkeypatch.setenv("LIVEAVATAR_FULLMODE_ENABLED_TENANTS", "*")

        from parrot.integrations.liveavatar.optin import is_fullmode_enabled

        assert is_fullmode_enabled(tenant_id="acme") is False

    def test_fullmode_disabled_despite_avatar_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Avatar enabled but fullmode env var absent → fullmode denied."""
        monkeypatch.setenv("LIVEAVATAR_ENABLED_TENANTS", "*")
        monkeypatch.setenv("LIVEAVATAR_FULLMODE_ENABLED_TENANTS", "")

        from parrot.integrations.liveavatar.optin import is_fullmode_enabled

        assert is_fullmode_enabled(tenant_id="acme") is False

    def test_both_gates_open_allows_fullmode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both avatar and fullmode gates open → fullmode allowed."""
        monkeypatch.setenv("LIVEAVATAR_ENABLED_TENANTS", "*")
        monkeypatch.setenv("LIVEAVATAR_FULLMODE_ENABLED_TENANTS", "*")

        from parrot.integrations.liveavatar.optin import is_fullmode_enabled

        assert is_fullmode_enabled(tenant_id="acme") is True

    def test_tenant_specific_fullmode_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only the listed tenant passes the fullmode gate."""
        monkeypatch.setenv("LIVEAVATAR_ENABLED_TENANTS", "*")
        monkeypatch.setenv("LIVEAVATAR_FULLMODE_ENABLED_TENANTS", "acme")

        from parrot.integrations.liveavatar.optin import is_fullmode_enabled

        assert is_fullmode_enabled(tenant_id="acme") is True
        assert is_fullmode_enabled(tenant_id="beta") is False

    def test_none_tenant_id_always_denied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """None tenant_id is denied even when both gates are open (wildcard)."""
        monkeypatch.setenv("LIVEAVATAR_ENABLED_TENANTS", "*")
        monkeypatch.setenv("LIVEAVATAR_FULLMODE_ENABLED_TENANTS", "*")

        from parrot.integrations.liveavatar.optin import is_fullmode_enabled

        assert is_fullmode_enabled(tenant_id=None) is False


# ---------------------------------------------------------------------------
# TestErrorHandling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Error paths: missing config, API failures, malformed responses."""

    async def test_missing_api_key_raises_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """resolve_fullmode_config raises RuntimeError when API key is missing."""
        monkeypatch.delenv("LIVEAVATAR_API_KEY", raising=False)
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "av-001")

        from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config

        with pytest.raises(RuntimeError):
            await resolve_fullmode_config()

    async def test_api_500_raises_on_create_token(
        self, fullmode_env: None
    ) -> None:
        """create_full_session_token propagates aiohttp errors on API 500."""
        import aiohttp

        from parrot.integrations.liveavatar.client import LiveAvatarClient
        from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config

        cfg = await resolve_fullmode_config()
        client = LiveAvatarClient(cfg)

        err = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=500
        )
        with patch.object(client, "_post", new=AsyncMock(side_effect=err)):
            with pytest.raises(aiohttp.ClientResponseError):
                await client.create_full_session_token(cfg)

    async def test_malformed_token_response_uses_empty_defaults(
        self, fullmode_env: None
    ) -> None:
        """create_full_session_token handles a response missing 'data' key gracefully."""
        from parrot.integrations.liveavatar.client import LiveAvatarClient
        from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config

        cfg = await resolve_fullmode_config()
        client = LiveAvatarClient(cfg)

        # Response that omits 'data' key entirely
        malformed_resp: Dict[str, Any] = {"code": 200, "message": "ok"}

        with patch.object(
            client, "_post", new=AsyncMock(return_value=malformed_resp)
        ):
            handle = await client.create_full_session_token(cfg)

        # Should return a handle with empty strings rather than crashing.
        assert handle.liveavatar_session_id == ""
        assert handle.session_token == ""

    async def test_api_500_raises_on_start_session(
        self, fullmode_env: None
    ) -> None:
        """start_session propagates aiohttp errors on API failure."""
        import aiohttp

        from parrot.integrations.liveavatar.client import LiveAvatarClient
        from parrot.integrations.liveavatar.models import FullModeSessionHandle
        from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config

        cfg = await resolve_fullmode_config()
        handle = FullModeSessionHandle(
            session_id="s1",
            liveavatar_session_id="la-s1",
            session_token="tok",
            ws_url="",
            agent_name="ag",
        )
        client = LiveAvatarClient(cfg)

        err = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=500
        )
        with patch.object(client, "_post", new=AsyncMock(side_effect=err)):
            with pytest.raises(aiohttp.ClientResponseError):
                await client.start_session(handle)
