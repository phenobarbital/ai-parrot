"""Unit tests for parrot.mcp.registry — MCPServerRegistry and data models."""
from __future__ import annotations

import pytest

from parrot.mcp.registry import (
    ActivateMCPServerRequest,
    MCPParamType,
    MCPServerDescriptor,
    MCPServerParam,
    MCPServerRegistry,
    UserMCPServerConfig,
)


@pytest.fixture
def registry() -> MCPServerRegistry:
    """Pre-populated MCPServerRegistry instance."""
    return MCPServerRegistry()


class TestMCPServerRegistry:
    """Tests for MCPServerRegistry."""

    def test_list_servers_returns_all(self, registry: MCPServerRegistry) -> None:
        """list_servers() returns at least 8 entries covering all helpers."""
        servers = registry.list_servers()
        assert len(servers) >= 8
        names = [s.name for s in servers]
        assert "perplexity" in names
        assert "fireflies" in names
        assert "chrome-devtools" in names
        assert "google-maps" in names
        assert "alphavantage" in names
        assert "genmedia" in names
        assert "quic" in names
        assert "websocket" in names

    def test_list_servers_returns_descriptors(self, registry: MCPServerRegistry) -> None:
        """Every item in list_servers() is an MCPServerDescriptor."""
        for server in registry.list_servers():
            assert isinstance(server, MCPServerDescriptor)

    def test_get_server_found(self, registry: MCPServerRegistry) -> None:
        """get_server() finds a server by slug and returns the correct descriptor."""
        desc = registry.get_server("perplexity")
        assert desc is not None
        assert desc.name == "perplexity"
        assert desc.method_name == "add_perplexity_mcp_server"
        assert desc.display_name == "Perplexity AI"

    def test_get_server_not_found(self, registry: MCPServerRegistry) -> None:
        """get_server() returns None for an unknown slug."""
        assert registry.get_server("nonexistent") is None
        assert registry.get_server("") is None

    def test_get_server_fireflies(self, registry: MCPServerRegistry) -> None:
        """get_server() finds fireflies descriptor correctly."""
        desc = registry.get_server("fireflies")
        assert desc is not None
        assert desc.method_name == "add_fireflies_mcp_server"
        assert desc.category == "productivity"

    def test_get_server_chrome_devtools(self, registry: MCPServerRegistry) -> None:
        """get_server() finds chrome-devtools descriptor correctly."""
        desc = registry.get_server("chrome-devtools")
        assert desc is not None
        assert desc.method_name == "add_chrome_devtools_mcp_server"
        assert desc.category == "dev-tools"

    def test_validate_params_ok(self, registry: MCPServerRegistry) -> None:
        """validate_params() succeeds when all required params are supplied."""
        result = registry.validate_params("perplexity", {"api_key": "test-key"})
        assert "api_key" in result
        assert result["api_key"] == "test-key"

    def test_validate_params_missing_required(self, registry: MCPServerRegistry) -> None:
        """validate_params() raises ValueError when a required param is missing."""
        with pytest.raises(ValueError, match="api_key"):
            registry.validate_params("perplexity", {})

    def test_validate_params_unknown_server(self, registry: MCPServerRegistry) -> None:
        """validate_params() raises ValueError for an unknown server slug."""
        with pytest.raises(ValueError, match="not found"):
            registry.validate_params("nonexistent", {})

    def test_validate_params_applies_defaults(self, registry: MCPServerRegistry) -> None:
        """validate_params() fills in optional param defaults."""
        result = registry.validate_params("chrome-devtools", {})
        # browser_url is optional with a default
        assert result.get("browser_url") == "http://127.0.0.1:9222"

    def test_validate_params_no_params_server(self, registry: MCPServerRegistry) -> None:
        """validate_params() succeeds for a server with no required params."""
        result = registry.validate_params("google-maps", {})
        assert isinstance(result, dict)

    def test_validate_params_genmedia_no_required(self, registry: MCPServerRegistry) -> None:
        """validate_params() accepts empty dict for genmedia (no required params)."""
        result = registry.validate_params("genmedia", {})
        assert isinstance(result, dict)

    def test_secret_params_flagged(self, registry: MCPServerRegistry) -> None:
        """Perplexity api_key is correctly typed as SECRET."""
        desc = registry.get_server("perplexity")
        assert desc is not None
        secret_params = [p for p in desc.params if p.type == MCPParamType.SECRET]
        assert len(secret_params) > 0
        assert secret_params[0].name == "api_key"

    def test_optional_params_have_defaults(self, registry: MCPServerRegistry) -> None:
        """Chrome DevTools browser_url is optional with a non-None default."""
        desc = registry.get_server("chrome-devtools")
        assert desc is not None
        browser_url_param = next(
            (p for p in desc.params if p.name == "browser_url"), None
        )
        assert browser_url_param is not None
        assert browser_url_param.required is False
        assert browser_url_param.default is not None

    def test_alphavantage_api_key_optional(self, registry: MCPServerRegistry) -> None:
        """Alpha Vantage api_key is optional (falls back to env var)."""
        desc = registry.get_server("alphavantage")
        assert desc is not None
        api_key_param = next((p for p in desc.params if p.name == "api_key"), None)
        assert api_key_param is not None
        assert api_key_param.required is False
        assert api_key_param.type == MCPParamType.SECRET

    def test_quic_required_params(self, registry: MCPServerRegistry) -> None:
        """QUIC server has name, host, port as required params."""
        desc = registry.get_server("quic")
        assert desc is not None
        required_names = [p.name for p in desc.params if p.required]
        assert "name" in required_names
        assert "host" in required_names
        assert "port" in required_names

    def test_quic_cert_path_optional(self, registry: MCPServerRegistry) -> None:
        """QUIC server cert_path is optional."""
        desc = registry.get_server("quic")
        assert desc is not None
        cert_param = next((p for p in desc.params if p.name == "cert_path"), None)
        assert cert_param is not None
        assert cert_param.required is False

    def test_websocket_required_params(self, registry: MCPServerRegistry) -> None:
        """WebSocket server has name and url as required params."""
        desc = registry.get_server("websocket")
        assert desc is not None
        required_names = [p.name for p in desc.params if p.required]
        assert "name" in required_names
        assert "url" in required_names

    def test_validate_quic_with_valid_params(self, registry: MCPServerRegistry) -> None:
        """validate_params() accepts valid QUIC params."""
        result = registry.validate_params(
            "quic",
            {"name": "my-server", "host": "localhost", "port": 9090},
        )
        assert result["name"] == "my-server"
        assert result["host"] == "localhost"
        assert result["port"] == 9090

    def test_validate_quic_missing_host_raises(self, registry: MCPServerRegistry) -> None:
        """validate_params() raises ValueError when QUIC host is missing."""
        with pytest.raises(ValueError, match="host"):
            registry.validate_params("quic", {"name": "x", "port": 9090})

    def test_all_descriptors_have_method_name(self, registry: MCPServerRegistry) -> None:
        """Every descriptor specifies a non-empty method_name."""
        for desc in registry.list_servers():
            assert desc.method_name.startswith("add_"), (
                f"Server '{desc.name}' method_name '{desc.method_name}' "
                "should start with 'add_'"
            )

    def test_list_servers_independent_copies(self, registry: MCPServerRegistry) -> None:
        """list_servers() returns a copy, not the internal list."""
        servers1 = registry.list_servers()
        servers2 = registry.list_servers()
        assert servers1 is not servers2


class TestMCPServerParam:
    """Tests for MCPServerParam model."""

    def test_defaults(self) -> None:
        """MCPServerParam has sensible defaults."""
        param = MCPServerParam(name="foo")
        assert param.type == MCPParamType.STRING
        assert param.required is True
        assert param.default is None
        assert param.description == ""

    def test_secret_type(self) -> None:
        """SECRET type is correctly stored."""
        param = MCPServerParam(name="api_key", type=MCPParamType.SECRET, required=True)
        assert param.type == MCPParamType.SECRET


class TestUserMCPServerConfig:
    """Tests for UserMCPServerConfig model."""

    def test_required_fields(self) -> None:
        """UserMCPServerConfig validates required fields."""
        config = UserMCPServerConfig(
            server_name="perplexity",
            agent_id="agent-1",
            user_id="user-42",
        )
        assert config.server_name == "perplexity"
        assert config.agent_id == "agent-1"
        assert config.user_id == "user-42"
        assert config.active is True
        assert config.params == {}
        assert config.vault_credential_name is None

    def test_with_vault_credential(self) -> None:
        """vault_credential_name is stored correctly."""
        config = UserMCPServerConfig(
            server_name="perplexity",
            agent_id="a1",
            user_id="u1",
            vault_credential_name="mcp_perplexity_a1",
        )
        assert config.vault_credential_name == "mcp_perplexity_a1"


class TestActivateMCPServerRequest:
    """Tests for ActivateMCPServerRequest model."""

    def test_required_server_field(self) -> None:
        """server field is required."""
        req = ActivateMCPServerRequest(server="perplexity")
        assert req.server == "perplexity"
        assert req.params == {}

    def test_with_params(self) -> None:
        """params dict is stored correctly."""
        req = ActivateMCPServerRequest(
            server="perplexity",
            params={"api_key": "sk-test"},
        )
        assert req.params["api_key"] == "sk-test"
