"""Tests for MSTeamsAgentConfig whitelist fields (FEAT-037)."""

from unittest.mock import patch

import pytest

from parrot.integrations.msteams.models import MSTeamsAgentConfig


class TestAllowedConversationIdsField:
    """Tests for the allowed_conversation_ids config field."""

    def test_default_is_none(self):
        """allowed_conversation_ids defaults to None (allow all)."""
        cfg = MSTeamsAgentConfig(name="test", chatbot_id="bot1")
        assert cfg.allowed_conversation_ids is None

    def test_set_via_constructor(self):
        """allowed_conversation_ids can be set directly."""
        cfg = MSTeamsAgentConfig(
            name="test",
            chatbot_id="bot1",
            allowed_conversation_ids=["19:abc@thread", "19:def@thread"],
        )
        assert cfg.allowed_conversation_ids == ["19:abc@thread", "19:def@thread"]


class TestAllowedUserIdsField:
    """Tests for the allowed_user_ids config field."""

    def test_default_is_none(self):
        """allowed_user_ids defaults to None (allow all)."""
        cfg = MSTeamsAgentConfig(name="test", chatbot_id="bot1")
        assert cfg.allowed_user_ids is None

    def test_set_via_constructor(self):
        """allowed_user_ids can be set directly."""
        cfg = MSTeamsAgentConfig(
            name="test",
            chatbot_id="bot1",
            allowed_user_ids=["29:user1", "29:user2"],
        )
        assert cfg.allowed_user_ids == ["29:user1", "29:user2"]


class TestEnvVarResolution:
    """Tests for env var resolution of whitelist fields."""

    @patch("parrot.integrations.msteams.models.config")
    def test_conversation_ids_from_env(self, mock_config):
        """allowed_conversation_ids resolved from {NAME}_ALLOWED_CONVERSATION_IDS."""
        mock_config.get = lambda key, **kw: {
            "MYBOT_MICROSOFT_APP_ID": None,
            "MYBOT_MICROSOFT_APP_PASSWORD": None,
            "MYBOT_ALLOWED_CONVERSATION_IDS": "19:abc@thread, 19:def@thread",
            "MYBOT_ALLOWED_USER_IDS": None,
        }.get(key)

        cfg = MSTeamsAgentConfig(name="mybot", chatbot_id="bot1")
        assert cfg.allowed_conversation_ids == ["19:abc@thread", "19:def@thread"]

    @patch("parrot.integrations.msteams.models.config")
    def test_user_ids_from_env(self, mock_config):
        """allowed_user_ids resolved from {NAME}_ALLOWED_USER_IDS."""
        mock_config.get = lambda key, **kw: {
            "MYBOT_MICROSOFT_APP_ID": None,
            "MYBOT_MICROSOFT_APP_PASSWORD": None,
            "MYBOT_ALLOWED_CONVERSATION_IDS": None,
            "MYBOT_ALLOWED_USER_IDS": "29:user1, 29:user2",
        }.get(key)

        cfg = MSTeamsAgentConfig(name="mybot", chatbot_id="bot1")
        assert cfg.allowed_user_ids == ["29:user1", "29:user2"]

    @patch("parrot.integrations.msteams.models.config")
    def test_env_var_strips_whitespace(self, mock_config):
        """Env var values are stripped of whitespace."""
        mock_config.get = lambda key, **kw: {
            "MYBOT_MICROSOFT_APP_ID": None,
            "MYBOT_MICROSOFT_APP_PASSWORD": None,
            "MYBOT_ALLOWED_CONVERSATION_IDS": None,
            "MYBOT_ALLOWED_USER_IDS": "  29:user1 , 29:user2 ,  ",
        }.get(key)

        cfg = MSTeamsAgentConfig(name="mybot", chatbot_id="bot1")
        assert cfg.allowed_user_ids == ["29:user1", "29:user2"]

    @patch("parrot.integrations.msteams.models.config")
    def test_env_var_not_set_stays_none(self, mock_config):
        """Whitelists stay None when env vars are not set."""
        mock_config.get = lambda key, **kw: None

        cfg = MSTeamsAgentConfig(name="mybot", chatbot_id="bot1")
        assert cfg.allowed_conversation_ids is None
        assert cfg.allowed_user_ids is None

    @patch("parrot.integrations.msteams.models.config")
    def test_explicit_value_not_overridden_by_env(self, mock_config):
        """Explicitly set values are not overridden by env vars."""
        mock_config.get = lambda key, **kw: {
            "MYBOT_MICROSOFT_APP_ID": None,
            "MYBOT_MICROSOFT_APP_PASSWORD": None,
            "MYBOT_ALLOWED_CONVERSATION_IDS": "19:env@thread",
            "MYBOT_ALLOWED_USER_IDS": "29:env-user",
        }.get(key)

        cfg = MSTeamsAgentConfig(
            name="mybot",
            chatbot_id="bot1",
            allowed_conversation_ids=["19:explicit@thread"],
            allowed_user_ids=["29:explicit-user"],
        )
        assert cfg.allowed_conversation_ids == ["19:explicit@thread"]
        assert cfg.allowed_user_ids == ["29:explicit-user"]


class TestFromDict:
    """Tests for from_dict parsing of whitelist fields."""

    def test_from_dict_with_whitelist(self):
        """from_dict() parses both whitelist fields."""
        cfg = MSTeamsAgentConfig.from_dict("bot1", {
            "chatbot_id": "agent1",
            "allowed_conversation_ids": ["19:abc@thread"],
            "allowed_user_ids": ["29:user1", "29:user2"],
        })
        assert cfg.allowed_conversation_ids == ["19:abc@thread"]
        assert cfg.allowed_user_ids == ["29:user1", "29:user2"]

    def test_from_dict_without_whitelist(self):
        """from_dict() without whitelist fields defaults to None."""
        cfg = MSTeamsAgentConfig.from_dict("bot1", {
            "chatbot_id": "agent1",
        })
        assert cfg.allowed_conversation_ids is None
        assert cfg.allowed_user_ids is None

    def test_from_dict_backward_compat(self):
        """Existing configs without whitelist fields still work."""
        cfg = MSTeamsAgentConfig.from_dict("bot1", {
            "chatbot_id": "agent1",
            "enable_group_mentions": True,
            "welcome_message": "Hello!",
        })
        assert cfg.enable_group_mentions is True
        assert cfg.welcome_message == "Hello!"
        assert cfg.allowed_conversation_ids is None
        assert cfg.allowed_user_ids is None
