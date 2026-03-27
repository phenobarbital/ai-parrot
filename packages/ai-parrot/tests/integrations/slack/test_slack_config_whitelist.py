"""Tests for SlackAgentConfig allowed_user_ids field (TASK-251)."""

from unittest.mock import patch

import pytest

from parrot.integrations.slack.models import SlackAgentConfig


class TestAllowedUserIdsField:
    """Tests for the allowed_user_ids config field."""

    def test_default_is_none(self):
        """allowed_user_ids defaults to None (allow all)."""
        cfg = SlackAgentConfig(name="test", chatbot_id="bot1", bot_token="xoxb-fake")
        assert cfg.allowed_user_ids is None

    def test_set_via_constructor(self):
        """allowed_user_ids can be set directly."""
        cfg = SlackAgentConfig(
            name="test",
            chatbot_id="bot1",
            bot_token="xoxb-fake",
            allowed_user_ids=["U001", "U002"],
        )
        assert cfg.allowed_user_ids == ["U001", "U002"]

    def test_empty_list_means_block_all(self):
        """An empty list blocks all users (different from None which allows all)."""
        cfg = SlackAgentConfig(
            name="test",
            chatbot_id="bot1",
            bot_token="xoxb-fake",
            allowed_user_ids=[],
        )
        assert cfg.allowed_user_ids == []


class TestAllowedUserIdsEnvVar:
    """Tests for env var resolution of allowed_user_ids."""

    @patch("parrot.integrations.slack.models.config")
    def test_resolved_from_env_var(self, mock_config):
        """allowed_user_ids resolved from {NAME}_SLACK_ALLOWED_USER_IDS."""
        mock_config.get = lambda key, **kw: {
            "MYBOT_SLACK_BOT_TOKEN": "xoxb-fake",
            "MYBOT_SLACK_SIGNING_SECRET": None,
            "MYBOT_SLACK_APP_TOKEN": None,
            "MYBOT_SLACK_ALLOWED_USER_IDS": "U001, U002, U003",
        }.get(key)

        cfg = SlackAgentConfig(name="mybot", chatbot_id="bot1")
        assert cfg.allowed_user_ids == ["U001", "U002", "U003"]

    @patch("parrot.integrations.slack.models.config")
    def test_env_var_strips_whitespace(self, mock_config):
        """Env var values are stripped of whitespace."""
        mock_config.get = lambda key, **kw: {
            "MYBOT_SLACK_BOT_TOKEN": "xoxb-fake",
            "MYBOT_SLACK_SIGNING_SECRET": None,
            "MYBOT_SLACK_APP_TOKEN": None,
            "MYBOT_SLACK_ALLOWED_USER_IDS": "  U001 , U002 ,  ",
        }.get(key)

        cfg = SlackAgentConfig(name="mybot", chatbot_id="bot1")
        assert cfg.allowed_user_ids == ["U001", "U002"]

    @patch("parrot.integrations.slack.models.config")
    def test_env_var_not_set_stays_none(self, mock_config):
        """allowed_user_ids stays None when env var is not set."""
        mock_config.get = lambda key, **kw: {
            "MYBOT_SLACK_BOT_TOKEN": "xoxb-fake",
            "MYBOT_SLACK_SIGNING_SECRET": None,
            "MYBOT_SLACK_APP_TOKEN": None,
            "MYBOT_SLACK_ALLOWED_USER_IDS": None,
        }.get(key)

        cfg = SlackAgentConfig(name="mybot", chatbot_id="bot1")
        assert cfg.allowed_user_ids is None

    @patch("parrot.integrations.slack.models.config")
    def test_env_var_empty_string_stays_none(self, mock_config):
        """allowed_user_ids stays None when env var is empty string."""
        mock_config.get = lambda key, **kw: {
            "MYBOT_SLACK_BOT_TOKEN": "xoxb-fake",
            "MYBOT_SLACK_SIGNING_SECRET": None,
            "MYBOT_SLACK_APP_TOKEN": None,
            "MYBOT_SLACK_ALLOWED_USER_IDS": "",
        }.get(key)

        cfg = SlackAgentConfig(name="mybot", chatbot_id="bot1")
        assert cfg.allowed_user_ids is None

    @patch("parrot.integrations.slack.models.config")
    def test_explicit_value_not_overridden_by_env(self, mock_config):
        """When allowed_user_ids is set explicitly, env var is not consulted."""
        mock_config.get = lambda key, **kw: {
            "MYBOT_SLACK_BOT_TOKEN": "xoxb-fake",
            "MYBOT_SLACK_SIGNING_SECRET": None,
            "MYBOT_SLACK_APP_TOKEN": None,
            "MYBOT_SLACK_ALLOWED_USER_IDS": "U999",
        }.get(key)

        cfg = SlackAgentConfig(
            name="mybot", chatbot_id="bot1", allowed_user_ids=["U001"]
        )
        assert cfg.allowed_user_ids == ["U001"]


class TestFromDict:
    """Tests for from_dict parsing of allowed_user_ids."""

    @patch("parrot.integrations.slack.models.config")
    def test_from_dict_with_user_whitelist(self, mock_config):
        """from_dict() parses allowed_user_ids from dict."""
        mock_config.get = lambda key, **kw: None

        cfg = SlackAgentConfig.from_dict("bot1", {
            "chatbot_id": "agent1",
            "bot_token": "xoxb-fake",
            "allowed_user_ids": ["U001", "U002"],
        })
        assert cfg.allowed_user_ids == ["U001", "U002"]

    @patch("parrot.integrations.slack.models.config")
    def test_from_dict_without_user_whitelist(self, mock_config):
        """from_dict() without allowed_user_ids defaults to None."""
        mock_config.get = lambda key, **kw: None

        cfg = SlackAgentConfig.from_dict("bot1", {
            "chatbot_id": "agent1",
            "bot_token": "xoxb-fake",
        })
        assert cfg.allowed_user_ids is None

    @patch("parrot.integrations.slack.models.config")
    def test_from_dict_backward_compat(self, mock_config):
        """Existing configs without allowed_user_ids still work."""
        mock_config.get = lambda key, **kw: None

        cfg = SlackAgentConfig.from_dict("bot1", {
            "chatbot_id": "agent1",
            "bot_token": "xoxb-fake",
            "allowed_channel_ids": ["C001"],
        })
        assert cfg.allowed_channel_ids == ["C001"]
        assert cfg.allowed_user_ids is None
