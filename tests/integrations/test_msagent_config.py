"""
Unit tests for MSAgentIntegrationConfig (TASK-1707).
"""
from unittest.mock import patch

from parrot.integrations.msagentsdk.models import (
    MSAgentIntegrationConfig,
    MSAgentSDKConfig,
)


class TestMSAgentIntegrationConfigFromDict:
    def test_from_dict_minimal(self):
        data = {"chatbot_id": "jirachi", "kind": "msagent"}
        cfg = MSAgentIntegrationConfig.from_dict("Jirachi", data)
        assert cfg.name == "Jirachi"
        assert cfg.chatbot_id == "jirachi"
        assert cfg.kind == "msagent"

    def test_from_dict_full(self):
        data = {
            "chatbot_id": "jirachi",
            "kind": "msagent",
            "microsoft_app_id": "app-id",
            "microsoft_app_password": "secret",
            "microsoft_tenant_id": "tenant",
            "url": "https://example.com",
            "tags": ["general"],
            "enable_credential_broker": True,
            "credentials": [{"provider": "o365", "auth": "oauth2"}],
            "o365_client_id": "o365-id",
            "o365_client_secret": "o365-secret",
            "o365_tenant_id": "o365-tenant",
            "redirect_uri": "https://example.com/callback",
            "jwt_secret": "jwt-secret",
            "debug": True,
        }
        cfg = MSAgentIntegrationConfig.from_dict("Jirachi", data)
        assert cfg.microsoft_app_id == "app-id"
        assert cfg.microsoft_app_password == "secret"
        assert cfg.microsoft_tenant_id == "tenant"
        assert cfg.url == "https://example.com"
        assert cfg.tags == ["general"]
        assert cfg.enable_credential_broker is True
        assert len(cfg.credentials) == 1
        assert cfg.o365_client_id == "o365-id"
        assert cfg.o365_client_secret == "o365-secret"
        assert cfg.o365_tenant_id == "o365-tenant"
        assert cfg.redirect_uri == "https://example.com/callback"
        assert cfg.jwt_secret == "jwt-secret"
        assert cfg.debug is True

    def test_from_dict_defaults(self):
        cfg = MSAgentIntegrationConfig.from_dict("Agent", {"chatbot_id": "x"})
        assert cfg.app_type == "SingleTenant"
        assert cfg.api_key_header == "x-api-key"
        assert cfg.anonymous_auth is False
        assert cfg.tags == []
        assert cfg.credentials == []


class TestMSAgentIntegrationConfigToMsagentsdkConfig:
    def test_to_msagentsdk_config(self):
        cfg = MSAgentIntegrationConfig(
            name="Test",
            chatbot_id="test",
            microsoft_app_id="app-id",
            microsoft_app_password="secret",
            microsoft_tenant_id="tenant",
        )
        sdk_cfg = cfg.to_msagentsdk_config()
        assert isinstance(sdk_cfg, MSAgentSDKConfig)
        assert sdk_cfg.name == "Test"
        assert sdk_cfg.chatbot_id == "test"
        assert sdk_cfg.client_id == "app-id"
        assert sdk_cfg.client_secret == "secret"
        assert sdk_cfg.tenant_id == "tenant"

    def test_to_msagentsdk_config_preserves_oauth_and_obo(self):
        cfg = MSAgentIntegrationConfig(
            name="Test",
            chatbot_id="test",
            oauth_connections={"o365": "graph_sso"},
            obo_scopes={"o365": ["https://graph.microsoft.com/.default"]},
        )
        sdk_cfg = cfg.to_msagentsdk_config()
        assert sdk_cfg.oauth_connections == {"o365": "graph_sso"}
        assert sdk_cfg.obo_scopes == {"o365": ["https://graph.microsoft.com/.default"]}

    def test_to_msagentsdk_config_does_not_leak_broker_fields(self):
        """The inner MSAgentSDKConfig has no credentials/broker/O365 fields."""
        cfg = MSAgentIntegrationConfig(
            name="Test",
            chatbot_id="test",
            enable_credential_broker=True,
            credentials=[{"provider": "o365", "auth": "oauth2"}],
            o365_client_id="cid",
        )
        sdk_cfg = cfg.to_msagentsdk_config()
        assert not hasattr(sdk_cfg, "credentials")
        assert not hasattr(sdk_cfg, "enable_credential_broker")
        assert not hasattr(sdk_cfg, "o365_client_id")


class TestMSAgentIntegrationConfigEnvVarFallback:
    @patch("parrot.integrations.msagentsdk.models.config")
    def test_env_var_fallback_microsoft_credentials(self, mock_config):
        mock_config.get.return_value = "env-value"
        cfg = MSAgentIntegrationConfig(name="Test", chatbot_id="test")
        assert cfg.microsoft_app_id == "env-value"
        assert cfg.microsoft_app_password == "env-value"
        assert cfg.microsoft_tenant_id == "env-value"

    @patch("parrot.integrations.msagentsdk.models.config")
    def test_env_var_fallback_o365_credentials(self, mock_config):
        mock_config.get.return_value = "env-o365-value"
        cfg = MSAgentIntegrationConfig(name="Test", chatbot_id="test")
        assert cfg.o365_client_id == "env-o365-value"
        assert cfg.o365_client_secret == "env-o365-value"
        assert cfg.o365_tenant_id == "env-o365-value"

    @patch("parrot.integrations.msagentsdk.models.config")
    def test_env_var_fallback_jwt_secret(self, mock_config):
        mock_config.get.return_value = "env-jwt-secret"
        cfg = MSAgentIntegrationConfig(name="Test", chatbot_id="test")
        assert cfg.jwt_secret == "env-jwt-secret"

    @patch("parrot.integrations.msagentsdk.models.config")
    def test_explicit_value_wins_over_env(self, mock_config):
        mock_config.get.return_value = "env-value"
        cfg = MSAgentIntegrationConfig(
            name="Test", chatbot_id="test", microsoft_app_id="explicit-id"
        )
        assert cfg.microsoft_app_id == "explicit-id"
