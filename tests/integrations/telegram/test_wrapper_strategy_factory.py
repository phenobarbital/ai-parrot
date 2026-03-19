"""Tests for TelegramAgentWrapper auth strategy factory.

Verifies that the wrapper creates the correct auth strategy based on
the TelegramAgentConfig settings.
"""

from unittest.mock import MagicMock, patch

import pytest

from parrot.integrations.telegram.auth import (
    BasicAuthStrategy,
    OAuth2AuthStrategy,
)
from parrot.integrations.telegram.models import TelegramAgentConfig


def _make_wrapper(config: TelegramAgentConfig):
    """Create a TelegramAgentWrapper with mocked bot/agent dependencies.

    We patch the parts of __init__ that require real aiogram/agent objects
    so we can test just the strategy factory logic.
    """
    mock_agent = MagicMock()
    mock_agent.get_available_tools = MagicMock(return_value=[])
    mock_bot = MagicMock()

    with patch(
        "parrot.integrations.telegram.wrapper.CallbackRegistry"
    ) as mock_cb:
        mock_cb.return_value.discover_from_agent.return_value = 0
        mock_cb.return_value.prefixes = []

        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        wrapper = TelegramAgentWrapper(
            agent=mock_agent,
            bot=mock_bot,
            config=config,
        )
    return wrapper


class TestStrategyFactory:
    """Tests for the auth strategy creation in TelegramAgentWrapper.__init__."""

    def test_strategy_factory_basic(self):
        """Config with auth_url creates BasicAuthStrategy."""
        config = TelegramAgentConfig(
            name="TestBot",
            chatbot_id="test_bot",
            bot_token="test:token",
            auth_url="https://nav.example.com/api/auth",
            login_page_url="https://static.example.com/login.html",
        )
        wrapper = _make_wrapper(config)

        assert wrapper._auth_strategy is not None
        assert isinstance(wrapper._auth_strategy, BasicAuthStrategy)

    def test_strategy_factory_oauth2(self):
        """Config with auth_method='oauth2' creates OAuth2AuthStrategy."""
        config = TelegramAgentConfig(
            name="TestBot",
            chatbot_id="test_bot",
            bot_token="test:token",
            auth_method="oauth2",
            oauth2_provider="google",
            oauth2_client_id="test-client-id.apps.googleusercontent.com",
            oauth2_client_secret="test-secret",
            oauth2_redirect_uri="https://example.com/oauth2/callback",
        )
        wrapper = _make_wrapper(config)

        assert wrapper._auth_strategy is not None
        assert isinstance(wrapper._auth_strategy, OAuth2AuthStrategy)

    def test_backward_compat_no_auth_method(self):
        """Config without auth_method defaults to BasicAuth when auth_url set."""
        config = TelegramAgentConfig(
            name="TestBot",
            chatbot_id="test_bot",
            bot_token="test:token",
            auth_url="https://nav.example.com/api/auth",
            login_page_url="https://static.example.com/login.html",
            # auth_method not specified — defaults to "basic"
        )
        wrapper = _make_wrapper(config)

        assert config.auth_method == "basic"
        assert isinstance(wrapper._auth_strategy, BasicAuthStrategy)

    def test_strategy_none_when_no_auth(self):
        """Config without auth_url or oauth2_client_id results in None strategy."""
        config = TelegramAgentConfig(
            name="TestBot",
            chatbot_id="test_bot",
            bot_token="test:token",
        )
        wrapper = _make_wrapper(config)

        assert wrapper._auth_strategy is None

    def test_oauth2_takes_priority_over_auth_url(self):
        """When auth_method='oauth2', OAuth2AuthStrategy is used even if auth_url is set."""
        config = TelegramAgentConfig(
            name="TestBot",
            chatbot_id="test_bot",
            bot_token="test:token",
            auth_url="https://nav.example.com/api/auth",
            auth_method="oauth2",
            oauth2_client_id="test-id",
            oauth2_client_secret="test-secret",
            oauth2_redirect_uri="https://example.com/callback",
        )
        wrapper = _make_wrapper(config)

        assert isinstance(wrapper._auth_strategy, OAuth2AuthStrategy)

    def test_oauth2_without_client_id_falls_back_to_none(self):
        """auth_method='oauth2' without client_id results in None (no auth_url either)."""
        config = TelegramAgentConfig(
            name="TestBot",
            chatbot_id="test_bot",
            bot_token="test:token",
            auth_method="oauth2",
            # No oauth2_client_id, no auth_url
        )
        wrapper = _make_wrapper(config)

        assert wrapper._auth_strategy is None
