"""
Unit tests for A2AAgentConfig (TASK-1706).
"""
from unittest.mock import patch

from parrot.integrations.a2a.models import A2AAgentConfig


class TestA2AAgentConfigFromDict:
    def test_from_dict_minimal(self):
        data = {"chatbot_id": "test_agent", "kind": "a2a"}
        cfg = A2AAgentConfig.from_dict("TestAgent", data)
        assert cfg.name == "TestAgent"
        assert cfg.chatbot_id == "test_agent"
        assert cfg.kind == "a2a"
        assert cfg.base_path == "/a2a"
        assert cfg.port is None

    def test_from_dict_full(self):
        data = {
            "chatbot_id": "jirachi",
            "kind": "a2a",
            "url": "https://example.com",
            "port": 8181,
            "tags": ["general"],
            "jwt_secret": "secret",
            "enable_credential_broker": True,
            "credentials": [{"provider": "fireflies", "auth": "static_key"}],
        }
        cfg = A2AAgentConfig.from_dict("Jirachi", data)
        assert cfg.url == "https://example.com"
        assert cfg.port == 8181
        assert cfg.tags == ["general"]
        assert cfg.jwt_secret == "secret"
        assert cfg.enable_credential_broker is True
        assert len(cfg.credentials) == 1
        assert cfg.credentials[0]["provider"] == "fireflies"

    def test_from_dict_defaults_base_path_and_api_key_header(self):
        data = {"chatbot_id": "agent"}
        cfg = A2AAgentConfig.from_dict("Agent", data)
        assert cfg.base_path == "/a2a"
        assert cfg.api_key_header == "X-API-Key"

    def test_from_dict_security_fields(self):
        data = {
            "chatbot_id": "agent",
            "mtls_ca_cert": "/path/to/ca.crt",
            "hmac_secret": "hmac-secret",
            "basic_credentials": {"user": "pass"},
            "security_policy": {"require_auth": True},
        }
        cfg = A2AAgentConfig.from_dict("Agent", data)
        assert cfg.mtls_ca_cert == "/path/to/ca.crt"
        assert cfg.hmac_secret == "hmac-secret"
        assert cfg.basic_credentials == {"user": "pass"}
        assert cfg.security_policy == {"require_auth": True}


class TestA2AAgentConfigDefaults:
    def test_defaults(self):
        cfg = A2AAgentConfig(name="Test", chatbot_id="test")
        assert cfg.kind == "a2a"
        assert cfg.base_path == "/a2a"
        assert cfg.enable_credential_broker is False
        assert cfg.credentials == []
        assert cfg.tags == []
        assert cfg.port is None


class TestA2AAgentConfigEnvVarFallback:
    @patch("parrot.integrations.a2a.models.config")
    def test_env_var_fallback_jwt_secret(self, mock_config):
        mock_config.get.return_value = "env-jwt-secret"
        cfg = A2AAgentConfig(name="Test", chatbot_id="test")
        assert cfg.jwt_secret == "env-jwt-secret"

    @patch("parrot.integrations.a2a.models.config")
    def test_env_var_fallback_api_key(self, mock_config):
        mock_config.get.return_value = "env-api-key"
        cfg = A2AAgentConfig(name="Test", chatbot_id="test")
        assert cfg.api_key == "env-api-key"

    @patch("parrot.integrations.a2a.models.config")
    def test_env_var_fallback_hmac_secret(self, mock_config):
        mock_config.get.return_value = "env-hmac-secret"
        cfg = A2AAgentConfig(name="Test", chatbot_id="test")
        assert cfg.hmac_secret == "env-hmac-secret"

    @patch("parrot.integrations.a2a.models.config")
    def test_explicit_value_wins_over_env(self, mock_config):
        mock_config.get.return_value = "env-value"
        cfg = A2AAgentConfig(name="Test", chatbot_id="test", jwt_secret="explicit-secret")
        assert cfg.jwt_secret == "explicit-secret"

    @patch("parrot.integrations.a2a.models.config")
    def test_no_env_var_leaves_none(self, mock_config):
        mock_config.get.return_value = None
        cfg = A2AAgentConfig(name="Test", chatbot_id="test")
        assert cfg.jwt_secret is None
        assert cfg.api_key is None
        assert cfg.hmac_secret is None
