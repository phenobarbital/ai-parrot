"""Tests for the extracted _build_auth_strategy helper (TASK-781).

Verifies that TelegramAgentWrapper selects the correct strategy based on
config.auth_methods (the normalized FEAT-109 list), including Composite
selection when multiple methods are listed.
"""
import pytest
import logging
from unittest.mock import MagicMock, patch

from parrot.integrations.telegram.auth import (
    BasicAuthStrategy,
    AzureAuthStrategy,
    OAuth2AuthStrategy,
    CompositeAuthStrategy,
)
from parrot.integrations.telegram.models import TelegramAgentConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wrapper(config: TelegramAgentConfig):
    """Create a TelegramAgentWrapper with mocked dependencies."""
    mock_agent = MagicMock()
    mock_agent.get_available_tools = MagicMock(return_value=[])
    mock_bot = MagicMock()

    with patch("parrot.integrations.telegram.wrapper.CallbackRegistry") as mock_cb:
        mock_cb.return_value.discover_from_agent.return_value = 0
        mock_cb.return_value.prefixes = []

        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        wrapper = TelegramAgentWrapper(
            agent=mock_agent,
            bot=mock_bot,
            config=config,
        )
    return wrapper


# ---------------------------------------------------------------------------
# Single-method branches
# ---------------------------------------------------------------------------

def test_build_single_basic():
    """auth_methods=['basic'] with auth_url → BasicAuthStrategy."""
    cfg = TelegramAgentConfig(
        name="bot",
        chatbot_id="b",
        bot_token="tok",
        auth_methods=["basic"],
        auth_url="https://nav.example.com/api/v1/login",
    )
    wrapper = _make_wrapper(cfg)
    assert isinstance(wrapper._auth_strategy, BasicAuthStrategy)


def test_build_single_azure():
    """auth_methods=['azure'] with azure_auth_url → AzureAuthStrategy."""
    cfg = TelegramAgentConfig(
        name="bot",
        chatbot_id="b",
        bot_token="tok",
        auth_methods=["azure"],
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        auth_url="https://nav.example.com/api/v1/login",
    )
    wrapper = _make_wrapper(cfg)
    assert isinstance(wrapper._auth_strategy, AzureAuthStrategy)


def test_build_single_oauth2():
    """auth_methods=['oauth2'] with credentials → OAuth2AuthStrategy."""
    cfg = TelegramAgentConfig(
        name="bot",
        chatbot_id="b",
        bot_token="tok",
        auth_methods=["oauth2"],
        oauth2_client_id="cid",
        oauth2_client_secret="csecret",
        oauth2_redirect_uri="https://nav.example.com/oauth2/callback",
    )
    wrapper = _make_wrapper(cfg)
    assert isinstance(wrapper._auth_strategy, OAuth2AuthStrategy)


# ---------------------------------------------------------------------------
# Multi-method → Composite
# ---------------------------------------------------------------------------

def test_build_composite_basic_and_azure():
    """auth_methods=['basic', 'azure'] → CompositeAuthStrategy."""
    cfg = TelegramAgentConfig(
        name="bot",
        chatbot_id="b",
        bot_token="tok",
        auth_methods=["basic", "azure"],
        auth_url="https://nav.example.com/api/v1/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        login_page_url="https://nav.example.com/static/telegram/login_multi.html",
    )
    wrapper = _make_wrapper(cfg)
    assert isinstance(wrapper._auth_strategy, CompositeAuthStrategy)
    assert set(wrapper._auth_strategy.strategies.keys()) == {"basic", "azure"}


def test_composite_members_have_correct_types():
    """Composite members are real strategy instances, not mocks."""
    cfg = TelegramAgentConfig(
        name="bot",
        chatbot_id="b",
        bot_token="tok",
        auth_methods=["basic", "azure"],
        auth_url="https://nav.example.com/api/v1/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        login_page_url="https://nav.example.com/static/telegram/login_multi.html",
    )
    wrapper = _make_wrapper(cfg)
    composite = wrapper._auth_strategy
    assert isinstance(composite.strategies["basic"], BasicAuthStrategy)
    assert isinstance(composite.strategies["azure"], AzureAuthStrategy)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_methods_yields_none():
    """auth_methods=[] (no auth) → strategy is None."""
    cfg = TelegramAgentConfig(
        name="bot",
        chatbot_id="b",
        bot_token="tok",
        auth_method="",
        auth_methods=[],
    )
    wrapper = _make_wrapper(cfg)
    assert wrapper._auth_strategy is None


def test_missing_config_for_listed_method_skips_it(caplog):
    """OAuth2 without client_id is skipped; basic still builds.

    Note: Azure auto-derives its URL from auth_url, so we use oauth2 as
    the "misconfigured" method to test the skip logic.
    """
    cfg = TelegramAgentConfig(
        name="bot",
        chatbot_id="b",
        bot_token="tok",
        auth_methods=["basic", "oauth2"],
        auth_url="https://nav.example.com/api/v1/login",
        # No oauth2_client_id → oauth2 skipped
    )
    with caplog.at_level(logging.WARNING):
        wrapper = _make_wrapper(cfg)
    # Only basic survived; Composite with 1 member simplifies to BasicAuthStrategy.
    assert isinstance(wrapper._auth_strategy, BasicAuthStrategy)
    assert any("oauth2" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# Legacy back-compat
# ---------------------------------------------------------------------------

def test_legacy_auth_method_basic_still_works():
    """Legacy auth_method='basic' (no auth_methods) → BasicAuthStrategy."""
    cfg = TelegramAgentConfig(
        name="bot",
        chatbot_id="b",
        bot_token="tok",
        auth_method="basic",
        auth_url="https://nav.example.com/api/v1/login",
    )
    wrapper = _make_wrapper(cfg)
    assert isinstance(wrapper._auth_strategy, BasicAuthStrategy)


def test_legacy_auth_method_azure_still_works():
    """Legacy auth_method='azure' (no auth_methods) → AzureAuthStrategy."""
    cfg = TelegramAgentConfig(
        name="bot",
        chatbot_id="b",
        bot_token="tok",
        auth_method="azure",
        auth_url="https://nav.example.com/api/v1/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
    )
    wrapper = _make_wrapper(cfg)
    assert isinstance(wrapper._auth_strategy, AzureAuthStrategy)
