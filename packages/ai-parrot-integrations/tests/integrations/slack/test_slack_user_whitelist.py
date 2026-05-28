"""Tests for SlackWrapper user whitelist authorization (FEAT-037)."""

from unittest.mock import MagicMock, patch

import pytest

from parrot.integrations.slack.models import SlackAgentConfig


def _make_config(**kwargs) -> SlackAgentConfig:
    """Create a SlackAgentConfig with defaults and overrides."""
    defaults = {
        "name": "test",
        "chatbot_id": "bot1",
        "bot_token": "xoxb-fake",
        "signing_secret": "fake-secret",
    }
    defaults.update(kwargs)
    with patch("parrot.integrations.slack.models.config") as mock_config:
        mock_config.get = lambda key, **kw: None
        return SlackAgentConfig(**defaults)


def _make_wrapper(config):
    """Create a SlackWrapper with mocked dependencies."""
    mock_agent = MagicMock()
    mock_agent.get_available_tools = MagicMock(return_value=[])

    with patch("parrot.integrations.slack.wrapper.SlackAgentWrapper.__init__", return_value=None):
        from parrot.integrations.slack.wrapper import SlackAgentWrapper
        wrapper = SlackAgentWrapper.__new__(SlackAgentWrapper)
        wrapper.config = config
        wrapper.logger = MagicMock()
    return wrapper


class TestIsAuthorizedWithUsers:
    """Tests for _is_authorized() with user_id parameter."""

    def test_authorized_channel_and_user(self):
        """Both channel and user in whitelists passes."""
        config = _make_config(
            allowed_channel_ids=["C001"],
            allowed_user_ids=["U001", "U002"],
        )
        wrapper = _make_wrapper(config)

        assert wrapper._is_authorized("C001", "U001") is True

    def test_unauthorized_user(self):
        """User not in whitelist is blocked."""
        config = _make_config(
            allowed_user_ids=["U001"],
        )
        wrapper = _make_wrapper(config)

        assert wrapper._is_authorized("C-any", "U999") is False

    def test_channel_authorized_user_not(self):
        """Channel OK but user not in whitelist is blocked (AND logic)."""
        config = _make_config(
            allowed_channel_ids=["C001"],
            allowed_user_ids=["U001"],
        )
        wrapper = _make_wrapper(config)

        assert wrapper._is_authorized("C001", "U999") is False

    def test_no_whitelists_allows_all(self):
        """None whitelists allow all."""
        config = _make_config()
        wrapper = _make_wrapper(config)

        assert wrapper._is_authorized("C-any", "U-any") is True

    def test_user_id_none_skips_user_check(self):
        """When user_id is None, only channel check is applied (backward compat)."""
        config = _make_config(
            allowed_channel_ids=["C001"],
            allowed_user_ids=["U001"],
        )
        wrapper = _make_wrapper(config)

        # user_id=None should skip user check
        assert wrapper._is_authorized("C001") is True
        assert wrapper._is_authorized("C999") is False

    def test_only_user_whitelist_no_channel(self):
        """User whitelist without channel whitelist works."""
        config = _make_config(
            allowed_user_ids=["U001"],
        )
        wrapper = _make_wrapper(config)

        assert wrapper._is_authorized("C-any", "U001") is True
        assert wrapper._is_authorized("C-any", "U999") is False
