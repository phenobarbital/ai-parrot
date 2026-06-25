"""
Unit tests for MSAgentSDKConfig.
"""
from unittest.mock import patch


class TestMSAgentSDKConfig:
    """Tests for the MSAgentSDKConfig dataclass."""

    def test_from_dict_basic(self):
        """Config is created from a YAML-style dict with explicit credentials."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        data = {
            "chatbot_id": "test_agent",
            "client_id": "app-id-123",
            "client_secret": "secret-456",
            "tenant_id": "tenant-789",
        }
        cfg = MSAgentSDKConfig.from_dict("TestBot", data)
        assert cfg.name == "TestBot"
        assert cfg.chatbot_id == "test_agent"
        assert cfg.client_id == "app-id-123"
        assert cfg.client_secret == "secret-456"
        assert cfg.tenant_id == "tenant-789"

    def test_kind_default(self):
        """kind field always defaults to 'msagentsdk'."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        cfg = MSAgentSDKConfig.from_dict("TestBot", {"chatbot_id": "agent"})
        assert cfg.kind == "msagentsdk"

    def test_from_dict_anonymous_auth(self):
        """anonymous_auth is captured correctly."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        data = {"chatbot_id": "test_agent", "anonymous_auth": True}
        cfg = MSAgentSDKConfig.from_dict("TestBot", data)
        assert cfg.anonymous_auth is True
        assert cfg.client_id is None

    def test_from_dict_defaults(self):
        """Optional fields default to expected values."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        data = {"chatbot_id": "test_agent"}
        cfg = MSAgentSDKConfig.from_dict("TestBot", data)
        assert cfg.anonymous_auth is False
        assert cfg.welcome_message is None
        assert cfg.system_prompt_override is None

    def test_from_dict_welcome_message(self):
        """welcome_message is passed through."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        data = {"chatbot_id": "agent", "welcome_message": "Hi there!"}
        cfg = MSAgentSDKConfig.from_dict("Bot", data)
        assert cfg.welcome_message == "Hi there!"

    def test_env_fallback_client_id(self):
        """__post_init__ resolves client_id from env var when not in dict."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        with patch("parrot.integrations.msagentsdk.models.config") as mock_cfg:
            mock_cfg.get.side_effect = lambda key: (
                "env-app-id" if key == "TESTBOT_MICROSOFT_APP_ID" else None
            )
            cfg = MSAgentSDKConfig(name="TestBot", chatbot_id="agent")
        assert cfg.client_id == "env-app-id"

    def test_env_fallback_client_secret(self):
        """__post_init__ resolves client_secret from env var when not in dict."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        with patch("parrot.integrations.msagentsdk.models.config") as mock_cfg:
            mock_cfg.get.side_effect = lambda key: (
                "env-secret" if key == "TESTBOT_MICROSOFT_APP_PASSWORD" else None
            )
            cfg = MSAgentSDKConfig(name="TestBot", chatbot_id="agent")
        assert cfg.client_secret == "env-secret"

    def test_env_fallback_not_overridden_when_explicit(self):
        """Explicit values in dict take precedence over env vars."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        data = {"chatbot_id": "agent", "client_id": "explicit-id"}
        with patch("parrot.integrations.msagentsdk.models.config") as mock_cfg:
            mock_cfg.get.return_value = "env-id"
            cfg = MSAgentSDKConfig.from_dict("TestBot", data)
        # Explicit value should win; env var only fills in if not set
        assert cfg.client_id == "explicit-id"

    def test_chatbot_id_defaults_to_name(self):
        """chatbot_id falls back to name when not provided."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        cfg = MSAgentSDKConfig.from_dict("TestBot", {})
        assert cfg.chatbot_id == "TestBot"
