"""Tests for parrot.mcp.oauth2_config — MCPOAuth2Config and presets registry."""
import pytest
from parrot.mcp.oauth2_config import (
    MCPOAuth2Config,
    MCPOAuth2Preset,
    MCPOAuth2GrantType,
    get_mcp_oauth2_preset,
    list_mcp_oauth2_presets,
)


class TestMCPOAuth2Config:
    """Tests for MCPOAuth2Config model."""

    def test_defaults(self):
        """Defaults: client_id=None, grant_type=authorization_code."""
        cfg = MCPOAuth2Config()
        assert cfg.client_id is None
        assert cfg.grant_type == MCPOAuth2GrantType.AUTHORIZATION_CODE
        assert cfg.redirect_path == "/api/auth/oauth2/mcp/callback"
        assert cfg.scopes == []
        assert cfg.client_secret is None
        assert cfg.auth_url is None
        assert cfg.token_url is None
        assert cfg.extra_token_params is None

    def test_with_client_id(self):
        """client_id accepted when provided."""
        cfg = MCPOAuth2Config(client_id="my-app", scopes=["read"])
        assert cfg.client_id == "my-app"
        assert cfg.scopes == ["read"]

    def test_grant_type_enum_from_string(self):
        """grant_type accepts string values."""
        cfg = MCPOAuth2Config(grant_type="client_credentials")
        assert cfg.grant_type == MCPOAuth2GrantType.CLIENT_CREDENTIALS

    def test_grant_type_enum_from_enum(self):
        """grant_type accepts enum values directly."""
        cfg = MCPOAuth2Config(grant_type=MCPOAuth2GrantType.CLIENT_CREDENTIALS)
        assert cfg.grant_type == MCPOAuth2GrantType.CLIENT_CREDENTIALS

    def test_full_config(self):
        """All fields accepted."""
        cfg = MCPOAuth2Config(
            client_id="app",
            client_secret="secret",
            auth_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            scopes=["read", "write"],
            grant_type=MCPOAuth2GrantType.AUTHORIZATION_CODE,
            redirect_path="/custom/callback",
            extra_token_params={"audience": "https://api.example.com"},
        )
        assert cfg.client_id == "app"
        assert cfg.client_secret == "secret"
        assert cfg.auth_url == "https://auth.example.com/authorize"
        assert cfg.extra_token_params == {"audience": "https://api.example.com"}

    def test_dynamic_client_registration_no_client_id(self):
        """RFC 7591: client_id=None triggers dynamic registration."""
        cfg = MCPOAuth2Config(
            auth_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
        )
        assert cfg.client_id is None


class TestMCPOAuth2GrantType:
    """Tests for MCPOAuth2GrantType enum."""

    def test_authorization_code_value(self):
        assert MCPOAuth2GrantType.AUTHORIZATION_CODE == "authorization_code"

    def test_client_credentials_value(self):
        assert MCPOAuth2GrantType.CLIENT_CREDENTIALS == "client_credentials"


class TestPresets:
    """Tests for the built-in preset registry."""

    def test_netsuite_preset_exists(self):
        """NetSuite preset is registered."""
        preset = get_mcp_oauth2_preset("netsuite")
        assert preset is not None
        assert preset.name == "netsuite"
        assert "mcp" in preset.scopes

    def test_netsuite_preset_fields(self):
        """NetSuite preset has expected URLs and required params."""
        preset = get_mcp_oauth2_preset("netsuite")
        assert "netsuite.com" in preset.auth_url
        assert "netsuite.com" in preset.token_url
        assert "account_id" in preset.required_params
        assert "client_id" in preset.required_params

    def test_fireflies_preset_exists(self):
        """Fireflies preset is registered."""
        preset = get_mcp_oauth2_preset("fireflies")
        assert preset is not None
        assert preset.name == "fireflies"

    def test_fireflies_preset_fields(self):
        """Fireflies preset has expected scopes."""
        preset = get_mcp_oauth2_preset("fireflies")
        assert "read:transcript" in preset.scopes
        assert "write:transcript" in preset.scopes

    def test_unknown_preset(self):
        """Non-existent preset returns None."""
        assert get_mcp_oauth2_preset("nonexistent") is None

    def test_unknown_preset_case_sensitive(self):
        """Preset lookup is case-sensitive."""
        assert get_mcp_oauth2_preset("NetSuite") is None
        assert get_mcp_oauth2_preset("NETSUITE") is None

    def test_list_presets(self):
        """list_mcp_oauth2_presets returns all presets."""
        presets = list_mcp_oauth2_presets()
        assert len(presets) >= 1
        assert any(p.name == "netsuite" for p in presets)

    def test_list_presets_returns_list(self):
        """list_mcp_oauth2_presets returns a list (copy, not the internal list)."""
        presets = list_mcp_oauth2_presets()
        assert isinstance(presets, list)

    def test_list_presets_contains_fireflies(self):
        """Fireflies appears in preset list."""
        presets = list_mcp_oauth2_presets()
        assert any(p.name == "fireflies" for p in presets)

    def test_preset_is_mcp_oauth2_preset(self):
        """Presets are MCPOAuth2Preset instances."""
        presets = list_mcp_oauth2_presets()
        for preset in presets:
            assert isinstance(preset, MCPOAuth2Preset)

    def test_netsuite_preset_grant_type(self):
        """NetSuite uses authorization_code by default."""
        preset = get_mcp_oauth2_preset("netsuite")
        assert preset.grant_type == MCPOAuth2GrantType.AUTHORIZATION_CODE
