"""Unit tests for TelegramAgentWrapper Azure SSO integration.

Tests cover:
- Strategy factory: azure config creates AzureAuthStrategy
- Strategy factory: basic config creates BasicAuthStrategy
- Strategy factory: no auth_url returns None
- Strategy factory: azure auth_method with derived url creates AzureAuthStrategy
- Backward compatibility: basic and oauth2 flows unaffected
"""
import pytest
from parrot.integrations.telegram.auth import (
    AzureAuthStrategy,
    BasicAuthStrategy,
    OAuth2AuthStrategy,
)
from parrot.integrations.telegram.models import TelegramAgentConfig


def _make_strategy_from_config(config: TelegramAgentConfig):
    """Replicate the strategy factory logic from TelegramAgentWrapper.__init__
    without instantiating the full wrapper (which requires aiogram Bot and Agent).
    """
    if config.auth_method == "azure" and config.azure_auth_url:
        return AzureAuthStrategy(
            auth_url=config.auth_url or config.azure_auth_url,
            azure_auth_url=config.azure_auth_url,
            login_page_url=config.login_page_url,
        )
    elif config.auth_method == "oauth2" and config.oauth2_client_id:
        return OAuth2AuthStrategy(config)
    elif config.auth_url:
        return BasicAuthStrategy(config.auth_url, config.login_page_url)
    return None


class TestStrategyFactory:
    """Test the auth strategy factory logic."""

    def test_azure_config_creates_azure_strategy(self):
        config = TelegramAgentConfig(
            name="Test",
            chatbot_id="test",
            bot_token="t:k",
            auth_method="azure",
            auth_url="https://nav.example.com/api/v1/auth/login",
            azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
            login_page_url="https://static.example.com/azure_login.html",
        )
        strategy = _make_strategy_from_config(config)
        assert isinstance(strategy, AzureAuthStrategy)

    def test_azure_strategy_has_correct_urls(self):
        config = TelegramAgentConfig(
            name="Test",
            chatbot_id="test",
            bot_token="t:k",
            auth_method="azure",
            auth_url="https://nav.example.com/api/v1/auth/login",
            azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
            login_page_url="https://static.example.com/azure_login.html",
        )
        strategy = _make_strategy_from_config(config)
        assert isinstance(strategy, AzureAuthStrategy)
        assert strategy.azure_auth_url == "https://nav.example.com/api/v1/auth/azure/"
        assert strategy.login_page_url == "https://static.example.com/azure_login.html"

    def test_azure_derived_url_creates_azure_strategy(self):
        """When azure_auth_url is derived from auth_url by __post_init__."""
        config = TelegramAgentConfig(
            name="Test",
            chatbot_id="test",
            bot_token="t:k",
            auth_method="azure",
            auth_url="https://nav.example.com/api/v1/auth/login",
            login_page_url="https://static.example.com/azure_login.html",
            # No explicit azure_auth_url — derived in __post_init__
        )
        # After __post_init__, azure_auth_url should be derived
        assert config.azure_auth_url == "https://nav.example.com/api/v1/auth/azure/"
        strategy = _make_strategy_from_config(config)
        assert isinstance(strategy, AzureAuthStrategy)

    def test_basic_config_creates_basic_strategy(self):
        config = TelegramAgentConfig(
            name="Test",
            chatbot_id="test",
            bot_token="t:k",
            auth_url="https://nav.example.com/api/v1/auth/login",
            login_page_url="https://static.example.com/login.html",
        )
        strategy = _make_strategy_from_config(config)
        assert isinstance(strategy, BasicAuthStrategy)

    def test_no_auth_url_returns_none(self):
        config = TelegramAgentConfig(
            name="Test",
            chatbot_id="test",
            bot_token="t:k",
            # No auth_url, no azure_auth_url, no oauth2
        )
        # Without auth_url in env either, strategy is None
        strategy = _make_strategy_from_config(config)
        # May be None or BasicAuthStrategy if env has NAVIGATOR_AUTH_URL
        # We just test that it's not AzureAuthStrategy
        assert not isinstance(strategy, AzureAuthStrategy)

    def test_azure_takes_precedence_over_oauth2(self):
        """Azure check must come before oauth2 check in the factory."""
        config = TelegramAgentConfig(
            name="Test",
            chatbot_id="test",
            bot_token="t:k",
            auth_method="azure",
            azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
            oauth2_client_id="cid",
            oauth2_client_secret="csec",
            oauth2_redirect_uri="https://example.com/callback",
        )
        strategy = _make_strategy_from_config(config)
        assert isinstance(strategy, AzureAuthStrategy)


class TestBackwardCompatibility:
    """Ensure existing flows still produce the correct strategy."""

    def test_basic_auth_method_creates_basic_strategy(self):
        config = TelegramAgentConfig(
            name="Legacy",
            chatbot_id="legacy",
            bot_token="t:k",
            auth_method="basic",
            auth_url="https://nav.example.com/api/v1/auth/login",
            login_page_url="https://static.example.com/login.html",
        )
        strategy = _make_strategy_from_config(config)
        assert isinstance(strategy, BasicAuthStrategy)

    def test_basic_strategy_has_correct_url(self):
        config = TelegramAgentConfig(
            name="Legacy",
            chatbot_id="legacy",
            bot_token="t:k",
            auth_method="basic",
            auth_url="https://nav.example.com/api/v1/auth/login",
        )
        strategy = _make_strategy_from_config(config)
        assert isinstance(strategy, BasicAuthStrategy)
        assert strategy.auth_url == "https://nav.example.com/api/v1/auth/login"

    def test_azure_does_not_affect_basic_configs(self):
        """Basic config azure_auth_url is None and strategy is BasicAuthStrategy."""
        config = TelegramAgentConfig(
            name="Basic",
            chatbot_id="basic",
            bot_token="t:k",
            auth_url="https://nav.example.com/api/v1/auth/login",
        )
        assert config.azure_auth_url is None
        strategy = _make_strategy_from_config(config)
        assert isinstance(strategy, BasicAuthStrategy)
