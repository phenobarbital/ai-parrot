"""Integration tests for MCP Transport OAuth2 (FEAT-262, TASK-1663)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.mcp.oauth2_config import MCPOAuth2Config, MCPOAuth2GrantType
from parrot.mcp.client import MCPClientConfig


class TestOAuth2TransportSetup:
    """Tests for OAuth2 provider setup in HttpMCPSession."""

    def _make_http_session(self, oauth2_config=None):
        """Create an HttpMCPSession with optional oauth2 config."""
        from parrot.mcp.transports.http import HttpMCPSession
        import logging

        cfg = MCPClientConfig(
            name="test-server",
            url="http://localhost:8888/mcp",
            oauth2=oauth2_config,
        )
        return HttpMCPSession(cfg, logging.getLogger("test"))

    @pytest.mark.asyncio
    async def test_client_credentials_setup(self):
        """Client credentials grant creates ClientCredentialsOAuthProvider."""
        oauth2 = MCPOAuth2Config(
            client_id="my-client",
            client_secret="my-secret",
            grant_type=MCPOAuth2GrantType.CLIENT_CREDENTIALS,
            scopes=["mcp"],
        )
        session = self._make_http_session(oauth2)

        with (
            patch("parrot.mcp.oauth2_storage.VaultTokenStore") as mock_vault_cls,
            patch(
                "mcp.client.auth.extensions.client_credentials.ClientCredentialsOAuthProvider"
            ) as mock_provider_cls,
        ):
            mock_vault = AsyncMock()
            mock_vault.get = AsyncMock(return_value=None)
            mock_vault_cls.return_value = mock_vault
            mock_provider_cls.return_value = MagicMock()

            await session._setup_oauth2()

            mock_provider_cls.assert_called_once()
            call_kwargs = mock_provider_cls.call_args.kwargs
            assert call_kwargs["client_id"] == "my-client"
            assert call_kwargs["client_secret"] == "my-secret"

    @pytest.mark.asyncio
    async def test_authorization_code_setup(self):
        """Authorization code grant creates OAuthClientProvider."""
        oauth2 = MCPOAuth2Config(
            client_id="my-app",
            grant_type=MCPOAuth2GrantType.AUTHORIZATION_CODE,
            scopes=["read"],
        )
        session = self._make_http_session(oauth2)

        with (
            patch("parrot.mcp.oauth2_storage.VaultTokenStore") as mock_vault_cls,
            patch(
                "mcp.client.auth.oauth2.OAuthClientProvider"
            ) as mock_provider_cls,
        ):
            mock_vault = AsyncMock()
            mock_vault.get = AsyncMock(return_value=None)
            mock_vault_cls.return_value = mock_vault
            mock_provider_cls.return_value = MagicMock()

            await session._setup_oauth2()

            mock_provider_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_oauth2_config_skips_setup(self):
        """Sessions without oauth2 config don't set up OAuth2 provider."""
        from parrot.mcp.transports.http import HttpMCPSession
        import logging

        cfg = MCPClientConfig(
            name="test",
            url="http://localhost:8888/mcp",
        )
        session = HttpMCPSession(cfg, logging.getLogger("test"))
        assert session._oauth2_provider is None


class TestOAuth2ConnectIntegration:
    """Tests for OAuth2 injection during connect()."""

    @pytest.mark.asyncio
    async def test_connect_with_oauth2_calls_setup(self):
        """connect() calls _setup_oauth2 when config.oauth2 is set."""
        from parrot.mcp.transports.http import HttpMCPSession
        import logging

        oauth2 = MCPOAuth2Config(
            client_id="app",
            grant_type=MCPOAuth2GrantType.AUTHORIZATION_CODE,
            scopes=["read"],
        )
        cfg = MCPClientConfig(
            name="test",
            url="http://localhost:9999/mcp",
            oauth2=oauth2,
        )
        session = HttpMCPSession(cfg, logging.getLogger("test"))

        with patch.object(session, "_setup_oauth2", new_callable=AsyncMock) as mock_setup:
            with patch("aiohttp.ClientSession") as mock_session_cls:
                mock_session = AsyncMock()
                mock_session_cls.return_value = mock_session
                with patch.object(session, "_initialize_session", new_callable=AsyncMock):
                    await session.connect()

            mock_setup.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_without_oauth2_does_not_call_setup(self):
        """connect() skips OAuth2 setup when config.oauth2 is None."""
        from parrot.mcp.transports.http import HttpMCPSession
        import logging

        cfg = MCPClientConfig(
            name="test",
            url="http://localhost:9999/mcp",
        )
        session = HttpMCPSession(cfg, logging.getLogger("test"))

        with patch.object(session, "_setup_oauth2", new_callable=AsyncMock) as mock_setup:
            with patch("aiohttp.ClientSession") as mock_session_cls:
                mock_session = AsyncMock()
                mock_session_cls.return_value = mock_session
                with patch.object(session, "_initialize_session", new_callable=AsyncMock):
                    await session.connect()

            mock_setup.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_legacy_auth_type_still_works(self):
        """Existing auth_type auth method works when oauth2 is not set."""
        from parrot.mcp.transports.http import HttpMCPSession
        import logging

        cfg = MCPClientConfig(
            name="test",
            url="http://localhost:9999/mcp",
            auth_type="bearer",
            auth_config={"token": "my-token"},
        )
        session = HttpMCPSession(cfg, logging.getLogger("test"))

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session_cls.return_value = AsyncMock()
            with patch.object(session, "_initialize_session", new_callable=AsyncMock):
                await session.connect()

        assert "Authorization" in session._base_headers
        assert session._base_headers["Authorization"] == "Bearer my-token"


class TestNonOAuth2BackwardCompatibility:
    """Tests verifying non-OAuth2 HTTP connections still work."""

    @pytest.mark.asyncio
    async def test_no_oauth2_no_auth_type(self):
        """Sessions with neither oauth2 nor auth_type connect without auth."""
        from parrot.mcp.transports.http import HttpMCPSession
        import logging

        cfg = MCPClientConfig(
            name="plain",
            url="http://localhost:7777/mcp",
        )
        session = HttpMCPSession(cfg, logging.getLogger("test"))

        with patch("aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = AsyncMock()
            with patch.object(session, "_initialize_session", new_callable=AsyncMock):
                await session.connect()

        assert session._oauth2_provider is None
        assert "Authorization" not in session._base_headers

    @pytest.mark.asyncio
    async def test_custom_headers_preserved_with_oauth2(self):
        """Custom headers are retained when oauth2 is configured."""
        from parrot.mcp.transports.http import HttpMCPSession
        import logging

        oauth2 = MCPOAuth2Config(
            client_id="app",
            grant_type=MCPOAuth2GrantType.CLIENT_CREDENTIALS,
            scopes=["read"],
            client_secret="secret",
        )
        cfg = MCPClientConfig(
            name="test",
            url="http://localhost:9999/mcp",
            headers={"X-Custom-Header": "custom-value"},
            oauth2=oauth2,
        )
        session = HttpMCPSession(cfg, logging.getLogger("test"))

        with patch.object(session, "_setup_oauth2", new_callable=AsyncMock):
            with patch("aiohttp.ClientSession") as mock_cls:
                mock_cls.return_value = AsyncMock()
                with patch.object(session, "_initialize_session", new_callable=AsyncMock):
                    await session.connect()

        assert session._base_headers.get("X-Custom-Header") == "custom-value"
