"""Tests for MCPClientConfig OAuth2 extensions (FEAT-262, TASK-1662)."""
import pytest
from parrot.mcp.client import MCPClientConfig, AuthCredential, AuthScheme
from parrot.mcp.oauth2_config import MCPOAuth2Config, MCPOAuth2GrantType


class TestMCPClientConfigOAuth2Fields:
    """Tests for the new oauth2 and auth_preset fields."""

    def test_oauth2_field_accepts_config(self):
        """MCPClientConfig accepts oauth2 as MCPOAuth2Config."""
        cfg = MCPClientConfig(
            name="test",
            url="http://example.com/mcp",
            oauth2=MCPOAuth2Config(client_id="my-app", scopes=["read"]),
        )
        assert cfg.oauth2 is not None
        assert cfg.oauth2.client_id == "my-app"

    def test_oauth2_defaults_to_none(self):
        """oauth2 defaults to None."""
        cfg = MCPClientConfig(name="test", url="http://example.com/mcp")
        assert cfg.oauth2 is None

    def test_auth_preset_field(self):
        """MCPClientConfig accepts auth_preset as str."""
        cfg = MCPClientConfig(
            name="test",
            url="http://example.com/mcp",
            auth_preset="netsuite",
        )
        assert cfg.auth_preset == "netsuite"

    def test_auth_preset_defaults_to_none(self):
        """auth_preset defaults to None."""
        cfg = MCPClientConfig(name="test", url="http://example.com/mcp")
        assert cfg.auth_preset is None


class TestMCPClientConfigFromYaml:
    """Tests for from_yaml_config() with oauth2 and auth_preset."""

    def test_from_yaml_inline_oauth2(self):
        """from_yaml_config parses inline oauth2 dict."""
        cfg = MCPClientConfig.from_yaml_config({
            "name": "custom",
            "url": "http://example.com/mcp",
            "oauth2": {
                "client_id": "app",
                "auth_url": "https://auth.example.com/authorize",
                "token_url": "https://auth.example.com/token",
                "scopes": ["read", "write"],
            },
        })
        assert cfg.oauth2 is not None
        assert cfg.oauth2.auth_url == "https://auth.example.com/authorize"
        assert cfg.oauth2.client_id == "app"
        assert "read" in cfg.oauth2.scopes

    def test_from_yaml_with_preset(self):
        """from_yaml_config resolves auth_preset to MCPOAuth2Config."""
        cfg = MCPClientConfig.from_yaml_config({
            "name": "ns",
            "url": "http://example.com/mcp",
            "auth_preset": "netsuite",
            "oauth2": {"client_id": "custom-id"},
        })
        assert cfg.oauth2 is not None
        assert cfg.oauth2.client_id == "custom-id"  # from inline override
        assert "mcp" in cfg.oauth2.scopes  # from preset

    def test_from_yaml_preset_provides_defaults(self):
        """Preset defaults are used when not overridden by inline oauth2."""
        cfg = MCPClientConfig.from_yaml_config({
            "name": "ns",
            "url": "http://example.com/mcp",
            "auth_preset": "netsuite",
        })
        assert cfg.oauth2 is not None
        assert "mcp" in cfg.oauth2.scopes
        assert cfg.oauth2.grant_type == MCPOAuth2GrantType.AUTHORIZATION_CODE

    def test_from_yaml_preset_inline_override(self):
        """Inline oauth2 fields override preset defaults."""
        cfg = MCPClientConfig.from_yaml_config({
            "name": "custom",
            "url": "http://example.com/mcp",
            "auth_preset": "netsuite",
            "oauth2": {"scopes": ["custom-scope"]},
        })
        # The inline scopes should override the preset scopes
        assert cfg.oauth2.scopes == ["custom-scope"]

    def test_from_yaml_unknown_preset_raises(self):
        """Unknown auth_preset raises ValueError."""
        with pytest.raises(ValueError, match="Unknown MCP OAuth2 preset"):
            MCPClientConfig.from_yaml_config({
                "name": "bad",
                "url": "http://example.com",
                "auth_preset": "nonexistent",
            })

    def test_from_yaml_backward_compatible_no_oauth2(self):
        """Existing configs without oauth2 work unchanged."""
        cfg = MCPClientConfig.from_yaml_config({
            "name": "simple",
            "url": "http://example.com/mcp",
            "headers": {"X-API-Key": "secret"},
        })
        assert cfg.oauth2 is None
        assert cfg.auth_preset is None
        assert cfg.headers == {"X-API-Key": "secret"}

    def test_from_yaml_backward_compatible_with_auth_credential(self):
        """Existing configs with auth_credential work unchanged."""
        cfg = MCPClientConfig.from_yaml_config({
            "name": "bearer",
            "url": "http://example.com/mcp",
            "auth_credential": {"scheme": "bearer", "token": "mytoken"},
        })
        assert cfg.auth_credential is not None
        assert cfg.oauth2 is None

    def test_from_yaml_auth_preset_stored(self):
        """auth_preset value is stored on the config."""
        cfg = MCPClientConfig.from_yaml_config({
            "name": "ns",
            "url": "http://example.com/mcp",
            "auth_preset": "netsuite",
        })
        assert cfg.auth_preset == "netsuite"


class TestGetHeadersOAuth2:
    """Tests for get_headers() with oauth2 config."""

    @pytest.mark.asyncio
    async def test_get_headers_skips_auth_credential_when_oauth2_set(self):
        """When oauth2 is set, auth_credential headers are skipped."""
        cfg = MCPClientConfig(
            name="test",
            url="http://example.com/mcp",
            auth_credential=AuthCredential(
                scheme=AuthScheme.BEARER,
                token="my-static-token",
            ),
            oauth2=MCPOAuth2Config(client_id="my-app", scopes=["read"]),
        )
        headers = await cfg.get_headers()
        # Bearer token should NOT appear because oauth2 is set
        assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_get_headers_includes_auth_credential_when_no_oauth2(self):
        """When oauth2 is not set, auth_credential headers ARE included."""
        cfg = MCPClientConfig(
            name="test",
            url="http://example.com/mcp",
            auth_credential=AuthCredential(
                scheme=AuthScheme.BEARER,
                token="my-static-token",
            ),
        )
        headers = await cfg.get_headers()
        assert headers.get("Authorization") == "Bearer my-static-token"

    @pytest.mark.asyncio
    async def test_get_headers_includes_static_headers_with_oauth2(self):
        """Static headers are still included when oauth2 is set."""
        cfg = MCPClientConfig(
            name="test",
            url="http://example.com/mcp",
            headers={"X-Custom": "value"},
            oauth2=MCPOAuth2Config(client_id="app"),
        )
        headers = await cfg.get_headers()
        assert headers["X-Custom"] == "value"
