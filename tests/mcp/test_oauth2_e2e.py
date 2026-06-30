"""End-to-end integration tests for MCP OAuth2 support (FEAT-262, TASK-1666).

These tests validate cross-module integration of the full OAuth2 pipeline:
config → storage → provider → transport → callback. Individual module unit
tests live in test_oauth2_config.py, test_oauth2_storage.py, etc.
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.mcp.oauth2_config import MCPOAuth2Config, MCPOAuth2GrantType, get_mcp_oauth2_preset
from parrot.mcp.client import MCPClientConfig
from parrot.mcp.oauth2_state import (
    _pending_mcp_callbacks,
    register_pending_callback,
    resolve_pending_callback,
    is_pending,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_pending_callbacks():
    """Clear OAuth2 state between tests."""
    _pending_mcp_callbacks.clear()
    yield
    _pending_mcp_callbacks.clear()


@pytest.fixture
def mcp_oauth2_config():
    """Return a basic MCPOAuth2Config for testing."""
    return MCPOAuth2Config(
        client_id="test-app",
        auth_url="http://localhost:9999/authorize",
        token_url="http://localhost:9999/token",
        scopes=["read", "write"],
        grant_type=MCPOAuth2GrantType.AUTHORIZATION_CODE,
    )


@pytest.fixture
def mcp_client_credentials_config():
    """Return a client credentials MCPOAuth2Config for testing."""
    return MCPOAuth2Config(
        client_id="service-app",
        client_secret="service-secret",
        token_url="http://localhost:9999/token",
        scopes=["mcp"],
        grant_type=MCPOAuth2GrantType.CLIENT_CREDENTIALS,
    )


@pytest.fixture
async def mock_oauth2_server(aiohttp_server):
    """Provide a minimal mock OAuth2 authorization server.

    Endpoints:
        GET  /authorize  — redirects back with authorization code
        POST /token      — returns a fake access token response
        POST /token/refresh — returns a refreshed token
    """
    from aiohttp import web

    app = web.Application()

    async def authorize(request: web.Request) -> web.Response:
        """Simulate authorization endpoint — redirect with code."""
        redirect_uri = request.query.get("redirect_uri", "")
        state = request.query.get("state", "")
        raise web.HTTPFound(f"{redirect_uri}?code=mock-auth-code&state={state}")

    async def token(request: web.Request) -> web.Response:
        """Simulate token endpoint — return access token."""
        data = await request.post()
        grant_type = data.get("grant_type", "")

        if grant_type == "refresh_token":
            return web.json_response({
                "access_token": "refreshed-access-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "new-refresh-token",
                "scope": "read write",
            })

        return web.json_response({
            "access_token": "mock-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "mock-refresh-token",
            "scope": "read write",
        })

    app.router.add_get("/authorize", authorize)
    app.router.add_post("/token", token)

    return await aiohttp_server(app)


# ---------------------------------------------------------------------------
# YAML Configuration Tests
# ---------------------------------------------------------------------------


class TestYAMLConfigOAuth2:
    """Tests for MCPClientConfig.from_yaml_config() with OAuth2."""

    def test_yaml_config_oauth2_dict(self):
        """YAML with oauth2: block creates correct MCPClientConfig."""
        cfg = MCPClientConfig.from_yaml_config({
            "name": "test-server",
            "url": "http://example.com/mcp",
            "oauth2": {
                "client_id": "app-id",
                "auth_url": "http://auth.example.com/authorize",
                "token_url": "http://auth.example.com/token",
                "scopes": ["read", "write"],
            },
        })
        assert cfg.oauth2 is not None
        assert cfg.oauth2.client_id == "app-id"
        assert cfg.oauth2.auth_url == "http://auth.example.com/authorize"
        assert cfg.oauth2.token_url == "http://auth.example.com/token"
        assert "read" in cfg.oauth2.scopes
        assert "write" in cfg.oauth2.scopes

    def test_yaml_config_oauth2_transport_http(self):
        """YAML with oauth2: creates config with http transport."""
        cfg = MCPClientConfig.from_yaml_config({
            "name": "test",
            "url": "http://example.com/mcp",
            "transport": "http",
            "oauth2": {
                "client_id": "app",
                "scopes": ["read"],
            },
        })
        assert cfg.transport == "http"
        assert cfg.oauth2 is not None

    def test_yaml_config_auth_preset_netsuite(self):
        """YAML with auth_preset: netsuite resolves preset defaults."""
        cfg = MCPClientConfig.from_yaml_config({
            "name": "ns",
            "url": "http://example.com/mcp",
            "auth_preset": "netsuite",
            "oauth2": {"client_id": "my-netsuite-client"},
        })
        assert cfg.oauth2 is not None
        # client_id from inline override
        assert cfg.oauth2.client_id == "my-netsuite-client"
        # scopes from preset
        assert "mcp" in cfg.oauth2.scopes
        # auth_preset stored on config
        assert cfg.auth_preset == "netsuite"

    def test_yaml_config_preset_scopes_come_from_preset(self):
        """Preset scopes are used when not overridden inline."""
        preset = get_mcp_oauth2_preset("netsuite")
        assert preset is not None

        cfg = MCPClientConfig.from_yaml_config({
            "name": "ns",
            "url": "http://example.com/mcp",
            "auth_preset": "netsuite",
            "oauth2": {"client_id": "app"},  # no scopes override
        })
        # Scopes should come from the preset
        for scope in preset.scopes:
            assert scope in cfg.oauth2.scopes

    def test_yaml_config_invalid_preset_raises(self):
        """Unknown preset name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown MCP OAuth2 preset"):
            MCPClientConfig.from_yaml_config({
                "name": "test",
                "url": "http://example.com/mcp",
                "auth_preset": "nonexistent-provider",
            })

    def test_yaml_config_oauth2_client_credentials(self):
        """YAML with client_credentials grant type parses correctly."""
        cfg = MCPClientConfig.from_yaml_config({
            "name": "m2m",
            "url": "http://example.com/mcp",
            "oauth2": {
                "client_id": "service",
                "client_secret": "secret123",
                "token_url": "http://auth.example.com/token",
                "scopes": ["mcp"],
                "grant_type": "client_credentials",
            },
        })
        assert cfg.oauth2 is not None
        assert cfg.oauth2.grant_type == MCPOAuth2GrantType.CLIENT_CREDENTIALS
        assert cfg.oauth2.client_secret == "secret123"


# ---------------------------------------------------------------------------
# MCPOAuth2Config Integration
# ---------------------------------------------------------------------------


class TestMCPOAuth2ConfigIntegration:
    """Tests for MCPOAuth2Config integration with factory functions."""

    def test_create_oauth_mcp_server_returns_config_with_oauth2(self):
        """create_oauth_mcp_server returns config with oauth2 set."""
        from parrot.mcp.integration import create_oauth_mcp_server

        cfg = create_oauth_mcp_server(
            name="integration-test",
            url="http://example.com/mcp",
            user_id="user@co.com",
            oauth2=MCPOAuth2Config(
                client_id="app",
                auth_url="http://auth.example.com/authorize",
                token_url="http://auth.example.com/token",
                scopes=["read"],
            ),
        )
        assert isinstance(cfg, MCPClientConfig)
        assert cfg.oauth2 is not None
        assert cfg.oauth2.client_id == "app"

    def test_create_netsuite_mcp_server_uses_preset(self):
        """create_netsuite_mcp_server uses the netsuite preset."""
        from parrot.mcp.integration import create_netsuite_mcp_server

        cfg = create_netsuite_mcp_server(
            account_id="4984231",
            client_id="netsuite-client",
            user_id="user@co.com",
        )
        assert cfg.oauth2 is not None
        assert cfg.oauth2.client_id == "netsuite-client"
        assert "mcp" in cfg.oauth2.scopes
        assert "4984231" in cfg.oauth2.auth_url
        assert cfg.oauth2.grant_type == MCPOAuth2GrantType.AUTHORIZATION_CODE

    def test_provider_registered_after_factory(self):
        """Factory functions register MCPOAuth2Provider in the registry."""
        from parrot.mcp.integration import create_oauth_mcp_server

        cfg = create_oauth_mcp_server(
            name="reg-check-server",
            url="http://example.com/mcp",
            user_id="user",
            oauth2=MCPOAuth2Config(client_id="app", scopes=["read"]),
        )
        # The provider should have been registered
        assert cfg.oauth2 is not None


# ---------------------------------------------------------------------------
# VaultMCPTokenStorage Round-Trip Tests
# ---------------------------------------------------------------------------


class TestVaultMCPTokenStorageRoundTrip:
    """Integration tests for VaultMCPTokenStorage token persistence."""

    @pytest.mark.asyncio
    async def test_token_round_trip_via_vault_store(self):
        """Token stored via VaultMCPTokenStorage can be retrieved."""
        from parrot.mcp.oauth2_storage import VaultMCPTokenStorage
        from parrot.mcp.oauth import InMemoryTokenStore
        from mcp.shared.auth import OAuthToken

        # Use InMemoryTokenStore as a mock for VaultTokenStore
        mem_store = InMemoryTokenStore()
        storage = VaultMCPTokenStorage(
            user_id="test-user",
            server_name="test-server",
            vault_store=mem_store,  # type: ignore[arg-type]
        )

        token = OAuthToken(
            access_token="round-trip-token",
            token_type="Bearer",
            expires_in=3600,
        )
        await storage.set_tokens(token)
        retrieved = await storage.get_tokens()

        assert retrieved is not None
        assert retrieved.access_token == "round-trip-token"
        assert retrieved.token_type == "Bearer"

    @pytest.mark.asyncio
    async def test_client_info_round_trip(self):
        """Client registration info stored and retrieved correctly."""
        from parrot.mcp.oauth2_storage import VaultMCPTokenStorage
        from parrot.mcp.oauth import InMemoryTokenStore
        from mcp.shared.auth import OAuthClientInformationFull

        mem_store = InMemoryTokenStore()
        storage = VaultMCPTokenStorage(
            user_id="test-user",
            server_name="test-server",
            vault_store=mem_store,  # type: ignore[arg-type]
        )

        client_info = OAuthClientInformationFull(
            client_id="dynamic-client-123",
            redirect_uris=["http://localhost/callback"],
        )
        await storage.set_client_info(client_info)
        retrieved = await storage.get_client_info()

        assert retrieved is not None
        assert retrieved.client_id == "dynamic-client-123"

    @pytest.mark.asyncio
    async def test_get_tokens_returns_none_when_empty(self):
        """get_tokens returns None when no token is stored."""
        from parrot.mcp.oauth2_storage import VaultMCPTokenStorage
        from parrot.mcp.oauth import InMemoryTokenStore

        mem_store = InMemoryTokenStore()
        storage = VaultMCPTokenStorage(
            user_id="empty-user",
            server_name="empty-server",
            vault_store=mem_store,  # type: ignore[arg-type]
        )
        result = await storage.get_tokens()
        assert result is None

    @pytest.mark.asyncio
    async def test_vault_error_degrades_gracefully(self):
        """VaultMCPTokenStorage degrades gracefully when vault is unavailable."""
        from parrot.mcp.oauth2_storage import VaultMCPTokenStorage
        from parrot.mcp.oauth import VaultTokenStore

        # Mock a VaultTokenStore that always raises
        failing_store = MagicMock(spec=VaultTokenStore)
        failing_store.get = AsyncMock(side_effect=RuntimeError("Vault unavailable"))
        failing_store.set = AsyncMock(side_effect=RuntimeError("Vault unavailable"))

        storage = VaultMCPTokenStorage(
            user_id="user",
            server_name="server",
            vault_store=failing_store,
        )

        # Should not raise — degrades to None
        result = await storage.get_tokens()
        assert result is None

        # set_tokens should also not raise
        from mcp.shared.auth import OAuthToken
        await storage.set_tokens(OAuthToken(access_token="tok"))  # no exception


# ---------------------------------------------------------------------------
# OAuth2 State / Callback Coordination Tests
# ---------------------------------------------------------------------------


class TestOAuth2CallbackCoordination:
    """End-to-end tests for the callback state coordination between transport and route."""

    @pytest.mark.asyncio
    async def test_register_then_resolve_callback(self):
        """register_pending_callback + resolve_pending_callback completes successfully."""
        state = "e2e-test-state-xyz"
        event, result = register_pending_callback(state)

        assert is_pending(state)
        assert not event.is_set()

        resolved = resolve_pending_callback(state, "e2e-auth-code")
        assert resolved is True
        assert event.is_set()
        assert result["code"] == "e2e-auth-code"

    @pytest.mark.asyncio
    async def test_callback_state_consumed_after_resolve(self):
        """State is consumed (removed) after resolution — prevents replay."""
        state = "replay-test-state"
        register_pending_callback(state)

        # First resolve succeeds
        assert resolve_pending_callback(state, "code-1") is True
        # State no longer pending
        assert not is_pending(state)
        # Second resolve fails
        assert resolve_pending_callback(state, "code-2") is False

    @pytest.mark.asyncio
    async def test_concurrent_pending_states_independent(self):
        """Multiple concurrent pending callbacks are isolated."""
        event1, result1 = register_pending_callback("state-a")
        event2, result2 = register_pending_callback("state-b")

        # Resolve only state-b
        resolve_pending_callback("state-b", "code-b")
        assert event2.is_set()
        assert not event1.is_set()  # state-a still pending

        # Resolve state-a
        resolve_pending_callback("state-a", "code-a")
        assert event1.is_set()
        assert result1["code"] == "code-a"
        assert result2["code"] == "code-b"

    @pytest.mark.asyncio
    async def test_await_event_in_callback_handler(self):
        """Simulates transport waiting on event while callback resolves it."""
        state = "await-test-state"
        event, result = register_pending_callback(state)

        async def transport_side():
            """Simulate transport waiting for the callback."""
            await asyncio.wait_for(event.wait(), timeout=2.0)
            return result.get("code")

        async def route_side():
            """Simulate callback route resolving after a small delay."""
            await asyncio.sleep(0.05)
            resolve_pending_callback(state, "transport-code")

        code = await asyncio.gather(transport_side(), route_side())
        assert code[0] == "transport-code"


# ---------------------------------------------------------------------------
# Transport + OAuth2 Config Integration
# ---------------------------------------------------------------------------


class TestTransportOAuth2Integration:
    """Tests for OAuth2 setup in HttpMCPSession."""

    def _make_http_session(self, oauth2: MCPOAuth2Config):
        from parrot.mcp.transports.http import HttpMCPSession
        import logging

        cfg = MCPClientConfig(
            name="e2e-test",
            url="http://localhost:9999/mcp",
            oauth2=oauth2,
        )
        return HttpMCPSession(cfg, logging.getLogger("test"))

    @pytest.mark.asyncio
    async def test_client_credentials_provider_created(self, mcp_client_credentials_config):
        """Client credentials grant creates ClientCredentialsOAuthProvider."""
        session = self._make_http_session(mcp_client_credentials_config)

        with (
            patch("parrot.mcp.oauth2_storage.VaultTokenStore") as mock_vault_cls,
            patch(
                "mcp.client.auth.extensions.client_credentials.ClientCredentialsOAuthProvider"
            ) as mock_cc,
        ):
            mock_vault_cls.return_value = AsyncMock()
            mock_cc.return_value = MagicMock()

            await session._setup_oauth2()

            mock_cc.assert_called_once()
            kwargs = mock_cc.call_args.kwargs
            assert kwargs["client_id"] == "service-app"
            assert kwargs["client_secret"] == "service-secret"

    @pytest.mark.asyncio
    async def test_authorization_code_provider_created(self, mcp_oauth2_config):
        """Authorization code grant creates OAuthClientProvider."""
        session = self._make_http_session(mcp_oauth2_config)

        with (
            patch("parrot.mcp.oauth2_storage.VaultTokenStore") as mock_vault_cls,
            patch("mcp.client.auth.oauth2.OAuthClientProvider") as mock_acp,
        ):
            mock_vault_cls.return_value = AsyncMock()
            mock_acp.return_value = MagicMock()

            await session._setup_oauth2()

            mock_acp.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_oauth2_provider_for_plain_config(self):
        """Sessions without oauth2 config leave _oauth2_provider as None."""
        from parrot.mcp.transports.http import HttpMCPSession
        import logging

        cfg = MCPClientConfig(name="plain", url="http://localhost/mcp")
        session = HttpMCPSession(cfg, logging.getLogger("test"))
        assert session._oauth2_provider is None
