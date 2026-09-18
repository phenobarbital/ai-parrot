"""Unit tests for FEAT-135 — NetSuite MCP Integration.

Covers:
- VaultTokenStore (get, set, delete, _vault_name)
- create_netsuite_mcp_server() factory (URL construction, scope, transport, token hooks)
- Registry entry and factory map
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault_store():
    """Return a fresh VaultTokenStore instance."""
    from parrot.mcp.oauth import VaultTokenStore

    return VaultTokenStore()


@pytest.fixture
def sample_token():
    """Sample OAuth token dict for tests."""
    return {
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token",
        "expires_at": 9999999999,
        "token_type": "Bearer",
    }


# ---------------------------------------------------------------------------
# VaultTokenStore Tests
# ---------------------------------------------------------------------------


class TestVaultTokenStore:
    """Tests for VaultTokenStore CRUD and error-handling behaviour."""

    @pytest.mark.asyncio
    async def test_set_stores_credential(self, vault_store, sample_token):
        """set() calls store_vault_credential with correct vault name."""
        with patch(
            "parrot.mcp.oauth.store_vault_credential", new_callable=AsyncMock
        ) as mock_store:
            await vault_store.set("user1", "netsuite", sample_token)
            mock_store.assert_called_once_with(
                "user1", "mcp_oauth_netsuite_user1", sample_token
            )

    @pytest.mark.asyncio
    async def test_set_does_not_raise_on_vault_unavailable(self, vault_store, sample_token):
        """set() logs a warning and returns without raising when vault keys are unavailable."""
        with patch(
            "parrot.mcp.oauth.store_vault_credential",
            new_callable=AsyncMock,
            side_effect=RuntimeError("vault keys unavailable"),
        ):
            # Must not raise — token stays in memory only
            await vault_store.set("user1", "netsuite", sample_token)

    @pytest.mark.asyncio
    async def test_get_retrieves_credential(self, vault_store, sample_token):
        """get() returns the token dict on a successful vault read."""
        with patch(
            "parrot.mcp.oauth.retrieve_vault_credential",
            new_callable=AsyncMock,
            return_value=sample_token,
        ):
            result = await vault_store.get("user1", "netsuite")
            assert result == sample_token

    @pytest.mark.asyncio
    async def test_get_returns_none_on_missing(self, vault_store):
        """get() returns None (does not raise) when the credential is absent."""
        with patch(
            "parrot.mcp.oauth.retrieve_vault_credential",
            new_callable=AsyncMock,
            side_effect=KeyError("not found"),
        ):
            result = await vault_store.get("user1", "netsuite")
            assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_none_on_runtime_error(self, vault_store):
        """get() returns None (does not raise) when vault keys are unavailable."""
        with patch(
            "parrot.mcp.oauth.retrieve_vault_credential",
            new_callable=AsyncMock,
            side_effect=RuntimeError("vault keys unavailable"),
        ):
            result = await vault_store.get("user1", "netsuite")
            assert result is None

    @pytest.mark.asyncio
    async def test_delete_removes_credential(self, vault_store):
        """delete() calls delete_vault_credential with correct vault name."""
        with patch(
            "parrot.mcp.oauth.delete_vault_credential", new_callable=AsyncMock
        ) as mock_del:
            await vault_store.delete("user1", "netsuite")
            mock_del.assert_called_once_with("user1", "mcp_oauth_netsuite_user1")

    @pytest.mark.asyncio
    async def test_delete_tolerates_missing_credential(self, vault_store):
        """delete() does not raise when the credential is already absent (double-delete)."""
        with patch(
            "parrot.mcp.oauth.delete_vault_credential",
            new_callable=AsyncMock,
            side_effect=KeyError("not found"),
        ):
            await vault_store.delete("user1", "netsuite")

    @pytest.mark.asyncio
    async def test_delete_does_not_raise_on_vault_unavailable(self, vault_store):
        """delete() logs a warning and returns without raising when vault keys are unavailable."""
        with patch(
            "parrot.mcp.oauth.delete_vault_credential",
            new_callable=AsyncMock,
            side_effect=RuntimeError("vault keys unavailable"),
        ):
            await vault_store.delete("user1", "netsuite")

    def test_vault_name_format(self, vault_store):
        """_vault_name(user_id, server_name) returns the expected pattern."""
        name = vault_store._vault_name("user@co.com", "netsuite")
        assert name == "mcp_oauth_netsuite_user@co.com"

    def test_vault_name_includes_server_and_user(self, vault_store):
        """_vault_name() embeds both user_id and server_name."""
        name = vault_store._vault_name("42", "my-server")
        assert "my-server" in name
        assert "42" in name


# ---------------------------------------------------------------------------
# Factory Tests
# ---------------------------------------------------------------------------


class TestCreateNetsuiteMcpServer:
    """Tests for create_netsuite_mcp_server() factory function."""

    def _make_cfg(self, **extra):
        from parrot.mcp.integration import create_netsuite_mcp_server

        return create_netsuite_mcp_server(
            account_id="4984231",
            client_id="test-client",
            user_id="user@co.com",
            **extra,
        )

    def test_url_construction(self):
        """MCP endpoint URL is correctly templated from account_id."""
        cfg = self._make_cfg()
        assert cfg.url == (
            "https://4984231.suitetalk.api.netsuite.com"
            "/services/mcp/v1/suiteapp/com.netsuite.mcpstandardtools"
        )

    def test_auth_url_construction(self):
        """OAuth2 auth URL is correctly templated from account_id."""
        cfg = self._make_cfg()
        assert cfg.oauth2.auth_url == (
            "https://4984231.app.netsuite.com/app/login/oauth2/authorize.nl"
        )

    def test_token_url_construction(self):
        """OAuth2 token URL is correctly templated from account_id."""
        cfg = self._make_cfg()
        assert cfg.oauth2.token_url == (
            "https://4984231.suitetalk.api.netsuite.com"
            "/services/rest/auth/oauth2/v1/token"
        )

    def test_scopes_are_mcp_only(self):
        """Scopes are hard-coded to ['mcp']."""
        cfg = self._make_cfg()
        assert cfg.oauth2.scopes == ["mcp"]

    def test_transport_is_http(self):
        """Transport is set to 'http'."""
        cfg = self._make_cfg()
        assert cfg.transport == "http"

    def test_name_is_netsuite(self):
        """Server name is 'netsuite'."""
        cfg = self._make_cfg()
        assert cfg.name == "netsuite"

    def test_auth_type_is_oauth2_without_legacy_supplier(self):
        """auth_type is 'oauth2'; the legacy OAuthManager token_supplier is gone (TASK-1665)."""
        cfg = self._make_cfg()
        assert cfg.auth_type == "oauth2"
        assert cfg.token_supplier is None
        assert not hasattr(cfg, "_ensure_oauth_token")

    def test_grant_type_is_authorization_code(self):
        """The NetSuite preset uses the Authorization Code (+PKCE) grant."""
        from parrot.mcp.oauth2_config import MCPOAuth2GrantType

        cfg = self._make_cfg()
        assert cfg.oauth2.grant_type == MCPOAuth2GrantType.AUTHORIZATION_CODE

    def test_provider_registered_in_oauth2_registry(self):
        """The factory registers an 'mcp:<name>' provider in the unified registry."""
        from parrot.auth.oauth2.registry import OAuth2ProviderRegistry

        self._make_cfg()
        provider = OAuth2ProviderRegistry().get("mcp:netsuite")
        assert provider is not None
        assert provider.default_scopes == ["mcp"]

    def test_token_store_kwarg_removed(self):
        """token_store is no longer accepted — storage moved to VaultMCPTokenStorage (TASK-1665)."""
        from parrot.mcp.oauth import VaultTokenStore
        from parrot.mcp.integration import create_netsuite_mcp_server

        with pytest.raises(TypeError):
            create_netsuite_mcp_server(
                account_id="4984231",
                client_id="test-client",
                user_id="user@co.com",
                token_store=VaultTokenStore(),
            )

    def test_client_id_in_oauth2_config(self):
        """client_id is included in the OAuth2 config."""
        cfg = self._make_cfg()
        assert cfg.oauth2.client_id == "test-client"

    def test_redirect_path_in_oauth2_config(self):
        """The OAuth2 callback is served by the unified MCP OAuth2 route."""
        cfg = self._make_cfg()
        assert cfg.oauth2.redirect_path == "/api/auth/oauth2/mcp/callback"

    def test_custom_name_overrides_default(self):
        """Passing name= changes both cfg.name and the token-store scope key."""
        from parrot.mcp.integration import create_netsuite_mcp_server

        cfg = create_netsuite_mcp_server(
            account_id="4984231",
            client_id="test-client",
            user_id="user@co.com",
            name="netsuite-sandbox",
        )
        assert cfg.name == "netsuite-sandbox"


# ---------------------------------------------------------------------------
# Registry Tests
# ---------------------------------------------------------------------------


class TestNetsuiteRegistry:
    """Tests for the NetSuite MCPServerDescriptor registry entry."""

    def test_netsuite_in_registry(self):
        """MCPServerRegistry().get_server('netsuite') returns the descriptor."""
        from parrot.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry()
        desc = registry.get_server("netsuite")
        assert desc is not None
        assert desc.name == "netsuite"

    def test_netsuite_method_name(self):
        """Registry entry points to the correct mixin method."""
        from parrot.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry()
        desc = registry.get_server("netsuite")
        assert desc.method_name == "add_netsuite_mcp_server"

    def test_netsuite_category_is_erp(self):
        """Registry entry has category='erp'."""
        from parrot.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry()
        desc = registry.get_server("netsuite")
        assert desc.category == "erp"

    def test_netsuite_params(self):
        """Registry entry has the three required params."""
        from parrot.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry()
        desc = registry.get_server("netsuite")
        param_names = [p.name for p in desc.params]
        assert "account_id" in param_names
        assert "client_id" in param_names
        assert "user_id" in param_names

    def test_netsuite_in_factory_map(self):
        """get_factory_map() contains 'netsuite' and the callable is the factory."""
        from parrot.mcp.registry import get_factory_map
        from parrot.mcp.integration import create_netsuite_mcp_server

        fmap = get_factory_map()
        assert "netsuite" in fmap
        assert callable(fmap["netsuite"])
        assert fmap["netsuite"] is create_netsuite_mcp_server

    def test_validate_params_requires_account_id(self):
        """validate_params raises ValueError when account_id is missing."""
        from parrot.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry()
        with pytest.raises((ValueError, KeyError)):
            registry.validate_params(
                "netsuite", {"client_id": "cid", "user_id": "uid"}
            )

    def test_validate_params_requires_client_id(self):
        """validate_params raises ValueError when client_id is missing."""
        from parrot.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry()
        with pytest.raises((ValueError, KeyError)):
            registry.validate_params(
                "netsuite", {"account_id": "4984231", "user_id": "uid"}
            )
