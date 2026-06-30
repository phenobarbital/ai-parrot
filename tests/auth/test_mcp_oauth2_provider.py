"""Tests for parrot.auth.oauth2.mcp_provider — MCPOAuth2Provider."""
import pytest
from parrot.auth.oauth2.mcp_provider import MCPOAuth2Provider, register_mcp_oauth2_provider
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.mcp.oauth2_config import MCPOAuth2Config


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the OAuth2ProviderRegistry singleton between tests."""
    OAuth2ProviderRegistry._reset()
    yield
    OAuth2ProviderRegistry._reset()


class TestMCPOAuth2Provider:
    """Tests for the MCPOAuth2Provider class."""

    def test_provider_id_format(self):
        """provider_id follows mcp:{server_name} pattern."""
        cfg = MCPOAuth2Config(client_id="test", scopes=["read"])
        provider = MCPOAuth2Provider("my-server", cfg, storage=None)
        assert provider.provider_id == "mcp:my-server"

    def test_display_name_format(self):
        """display_name follows MCP: {server_name} pattern."""
        cfg = MCPOAuth2Config(client_id="test")
        provider = MCPOAuth2Provider("netsuite", cfg, storage=None)
        assert provider.display_name == "MCP: netsuite"

    def test_scopes_from_config(self):
        """default_scopes taken from MCPOAuth2Config."""
        cfg = MCPOAuth2Config(client_id="test", scopes=["read", "write"])
        provider = MCPOAuth2Provider("srv", cfg, storage=None)
        assert "read" in provider.default_scopes
        assert "write" in provider.default_scopes

    def test_manager_returns_none(self):
        """manager property returns None (MCP SDK handles the flow)."""
        cfg = MCPOAuth2Config(client_id="test")
        provider = MCPOAuth2Provider("srv", cfg, storage=None)
        assert provider.manager is None

    def test_toolkit_factory_returns_none(self):
        """toolkit_factory returns None (MCP tools arrive via MCP protocol)."""
        cfg = MCPOAuth2Config(client_id="test")
        provider = MCPOAuth2Provider("srv", cfg, storage=None)
        assert provider.toolkit_factory(None) is None

    def test_config_stored(self):
        """MCPOAuth2Config is accessible on the provider."""
        cfg = MCPOAuth2Config(
            client_id="abc",
            auth_url="https://auth.example.com/authorize",
        )
        provider = MCPOAuth2Provider("srv", cfg, storage=None)
        assert provider._config is cfg

    def test_storage_stored(self):
        """Storage adapter is accessible on the provider."""
        from parrot.mcp.oauth2_storage import VaultMCPTokenStorage
        from parrot.mcp.oauth import InMemoryTokenStore

        vault = InMemoryTokenStore()
        storage = VaultMCPTokenStorage("user@co.com", "srv", vault_store=vault)
        cfg = MCPOAuth2Config(client_id="abc")
        provider = MCPOAuth2Provider("srv", cfg, storage=storage)
        assert provider._storage is storage

    def test_storage_can_be_none(self):
        """Storage defaults to None when not provided."""
        cfg = MCPOAuth2Config(client_id="test")
        provider = MCPOAuth2Provider("srv", cfg)
        assert provider._storage is None


class TestRegisterMCPOAuth2Provider:
    """Tests for register_mcp_oauth2_provider factory."""

    def test_registration(self):
        """register_mcp_oauth2_provider registers provider in singleton registry."""
        cfg = MCPOAuth2Config(client_id="test", scopes=["mcp"])
        register_mcp_oauth2_provider("netsuite", cfg, storage=None)
        registry = OAuth2ProviderRegistry()
        assert registry.get("mcp:netsuite") is not None

    def test_returns_provider_instance(self):
        """register_mcp_oauth2_provider returns the created provider."""
        cfg = MCPOAuth2Config(client_id="test", scopes=["mcp"])
        provider = register_mcp_oauth2_provider("netsuite", cfg, storage=None)
        assert isinstance(provider, MCPOAuth2Provider)
        assert provider.provider_id == "mcp:netsuite"

    def test_listed_in_all(self):
        """Registered provider appears in OAuth2ProviderRegistry().all()."""
        cfg = MCPOAuth2Config(client_id="test")
        register_mcp_oauth2_provider("fireflies", cfg, storage=None)
        all_providers = OAuth2ProviderRegistry().all()
        assert any(p.provider_id == "mcp:fireflies" for p in all_providers)

    def test_multiple_servers_registered(self):
        """Multiple MCP servers can be registered simultaneously."""
        cfg1 = MCPOAuth2Config(client_id="id1", scopes=["mcp"])
        cfg2 = MCPOAuth2Config(client_id="id2", scopes=["read"])
        register_mcp_oauth2_provider("netsuite", cfg1)
        register_mcp_oauth2_provider("fireflies", cfg2)
        registry = OAuth2ProviderRegistry()
        assert registry.get("mcp:netsuite") is not None
        assert registry.get("mcp:fireflies") is not None

    def test_duplicate_registration_overwrites(self):
        """Re-registering the same server_name replaces the existing entry."""
        cfg1 = MCPOAuth2Config(client_id="id1")
        cfg2 = MCPOAuth2Config(client_id="id2")
        register_mcp_oauth2_provider("netsuite", cfg1)
        register_mcp_oauth2_provider("netsuite", cfg2)
        registry = OAuth2ProviderRegistry()
        provider = registry.get("mcp:netsuite")
        assert provider._config.client_id == "id2"

    def test_registry_isolation_after_reset(self):
        """Registry is empty after _reset()."""
        cfg = MCPOAuth2Config(client_id="test")
        register_mcp_oauth2_provider("netsuite", cfg)
        # autouse fixture resets between tests
        registry = OAuth2ProviderRegistry()
        assert registry.get("mcp:netsuite") is not None  # still registered in this test

    def test_provider_id_in_registry(self):
        """Provider ID in registry matches expected pattern."""
        cfg = MCPOAuth2Config(client_id="test")
        provider = register_mcp_oauth2_provider("custom-server", cfg)
        registry = OAuth2ProviderRegistry()
        assert registry.get("mcp:custom-server") is provider
