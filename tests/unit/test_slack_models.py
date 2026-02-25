"""Unit tests for Slack integration models."""
import pytest
from unittest.mock import patch
from parrot.integrations.slack.models import SlackAgentConfig


class TestSlackAgentConfig:
    """Tests for SlackAgentConfig dataclass."""

    def test_default_values(self):
        """New fields have sensible defaults."""
        with patch('parrot.integrations.slack.models.config.get', return_value=None):
            cfg = SlackAgentConfig(name="test", chatbot_id="bot")

        assert cfg.connection_mode == "webhook"
        assert cfg.enable_assistant is False
        assert cfg.max_concurrent_requests == 10
        assert cfg.app_token is None
        assert cfg.suggested_prompts is None

    def test_socket_mode_requires_app_token(self):
        """Socket mode raises error without app_token."""
        with patch('parrot.integrations.slack.models.config.get', return_value=None):
            with pytest.raises(ValueError, match="Socket Mode requires"):
                SlackAgentConfig(
                    name="test",
                    chatbot_id="bot",
                    connection_mode="socket",
                    app_token=None
                )

    def test_socket_mode_with_app_token(self):
        """Socket mode works with app_token."""
        with patch('parrot.integrations.slack.models.config.get', return_value=None):
            cfg = SlackAgentConfig(
                name="test",
                chatbot_id="bot",
                connection_mode="socket",
                app_token="xapp-123-456"
            )

        assert cfg.connection_mode == "socket"
        assert cfg.app_token == "xapp-123-456"

    def test_socket_mode_with_env_app_token(self):
        """Socket mode works with app_token from environment."""
        def mock_get(key):
            if key == "TEST_SLACK_APP_TOKEN":
                return "xapp-from-env"
            return None

        with patch('parrot.integrations.slack.models.config.get', side_effect=mock_get):
            cfg = SlackAgentConfig(
                name="test",
                chatbot_id="bot",
                connection_mode="socket"
            )

        assert cfg.connection_mode == "socket"
        assert cfg.app_token == "xapp-from-env"

    def test_from_dict_parses_new_fields(self):
        """from_dict correctly parses all new fields."""
        data = {
            "chatbot_id": "bot",
            "connection_mode": "socket",
            "app_token": "xapp-123",
            "enable_assistant": True,
            "suggested_prompts": [{"title": "Help", "message": "Help me"}],
            "max_concurrent_requests": 5,
        }

        with patch('parrot.integrations.slack.models.config.get', return_value=None):
            cfg = SlackAgentConfig.from_dict("test", data)

        assert cfg.connection_mode == "socket"
        assert cfg.app_token == "xapp-123"
        assert cfg.enable_assistant is True
        assert cfg.suggested_prompts is not None
        assert len(cfg.suggested_prompts) == 1
        assert cfg.suggested_prompts[0]["title"] == "Help"
        assert cfg.max_concurrent_requests == 5

    def test_backward_compatibility(self):
        """Old configs without new fields still work."""
        data = {"chatbot_id": "bot"}

        with patch('parrot.integrations.slack.models.config.get', return_value=None):
            cfg = SlackAgentConfig.from_dict("test", data)

        assert cfg.connection_mode == "webhook"
        assert cfg.enable_assistant is False
        assert cfg.max_concurrent_requests == 10
        assert cfg.app_token is None
        assert cfg.suggested_prompts is None

    def test_existing_fields_preserved(self):
        """Existing fields continue to work correctly."""
        with patch('parrot.integrations.slack.models.config.get', return_value=None):
            cfg = SlackAgentConfig(
                name="test_bot",
                chatbot_id="my_agent",
                bot_token="xoxb-test-token",
                signing_secret="test_secret",
                welcome_message="Hello!",
                commands={"ask": "Ask a question"},
                allowed_channel_ids=["C123", "C456"],
                webhook_path="/custom/webhook"
            )

        assert cfg.name == "test_bot"
        assert cfg.chatbot_id == "my_agent"
        assert cfg.bot_token == "xoxb-test-token"
        assert cfg.signing_secret == "test_secret"
        assert cfg.kind == "slack"
        assert cfg.welcome_message == "Hello!"
        assert cfg.commands == {"ask": "Ask a question"}
        assert cfg.allowed_channel_ids == ["C123", "C456"]
        assert cfg.webhook_path == "/custom/webhook"

    def test_from_dict_existing_fields(self):
        """from_dict parses existing fields correctly."""
        data = {
            "chatbot_id": "my_agent",
            "bot_token": "xoxb-test",
            "signing_secret": "secret",
            "welcome_message": "Welcome!",
            "commands": {"cmd": "description"},
            "allowed_channel_ids": ["C111"],
            "webhook_path": "/slack/events",
        }

        with patch('parrot.integrations.slack.models.config.get', return_value=None):
            cfg = SlackAgentConfig.from_dict("test", data)

        assert cfg.chatbot_id == "my_agent"
        assert cfg.bot_token == "xoxb-test"
        assert cfg.signing_secret == "secret"
        assert cfg.welcome_message == "Welcome!"
        assert cfg.commands == {"cmd": "description"}
        assert cfg.allowed_channel_ids == ["C111"]
        assert cfg.webhook_path == "/slack/events"

    def test_env_var_fallback_for_tokens(self):
        """Tokens are loaded from environment variables if not provided."""
        def mock_get(key):
            mapping = {
                "MYBOT_SLACK_BOT_TOKEN": "xoxb-from-env",
                "MYBOT_SLACK_SIGNING_SECRET": "secret-from-env",
                "MYBOT_SLACK_APP_TOKEN": "xapp-from-env",
            }
            return mapping.get(key)

        with patch('parrot.integrations.slack.models.config.get', side_effect=mock_get):
            cfg = SlackAgentConfig(name="mybot", chatbot_id="bot")

        assert cfg.bot_token == "xoxb-from-env"
        assert cfg.signing_secret == "secret-from-env"
        assert cfg.app_token == "xapp-from-env"

    def test_enable_assistant_with_prompts(self):
        """Assistant mode with suggested prompts works correctly."""
        prompts = [
            {"title": "Summarize", "message": "Summarize this channel"},
            {"title": "Draft", "message": "Help me draft a message"},
        ]

        with patch('parrot.integrations.slack.models.config.get', return_value=None):
            cfg = SlackAgentConfig(
                name="test",
                chatbot_id="bot",
                enable_assistant=True,
                suggested_prompts=prompts
            )

        assert cfg.enable_assistant is True
        assert cfg.suggested_prompts == prompts
        assert len(cfg.suggested_prompts) == 2

    def test_max_concurrent_requests_custom_value(self):
        """Custom max_concurrent_requests value is respected."""
        with patch('parrot.integrations.slack.models.config.get', return_value=None):
            cfg = SlackAgentConfig(
                name="test",
                chatbot_id="bot",
                max_concurrent_requests=20
            )

        assert cfg.max_concurrent_requests == 20
