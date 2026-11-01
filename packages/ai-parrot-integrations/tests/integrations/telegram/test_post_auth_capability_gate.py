"""Tests for post-auth capability metadata and staged login gating.

The capability metadata remains compatible, but ``handle_login`` must never
mint secondary provider state before the primary callback is validated.

Strategy     | supports_post_auth_chain | chain fires?
-------------|--------------------------|-------------
BasicAuth    | True                     | yes
AzureAuth    | True (TASK-778)          | yes
OAuth2Auth   | False                    | no
Composite(all True) | True (AND prop)  | yes
Composite(mixed)    | False            | no
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.integrations.telegram.auth import (
    BasicAuthStrategy,
    AzureAuthStrategy,
    OAuth2AuthStrategy,
    CompositeAuthStrategy,
    TelegramUserSession,
)
from parrot.integrations.telegram.models import TelegramAgentConfig


# ---------------------------------------------------------------------------
# Helpers — build a minimal wrapper and mock the post-auth machinery
# ---------------------------------------------------------------------------

def _make_wrapper(config: TelegramAgentConfig):
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


def _inject_registry(wrapper, url: str = "https://jira.example.com/oauth") -> MagicMock:
    """Inject a fake PostAuthRegistry so _build_next_auth_url returns a URL."""
    provider = MagicMock()
    provider.provider_name = "jira"
    provider.build_auth_url = AsyncMock(return_value=url)
    wrapper._post_auth_registry._providers = {"jira": provider}
    return provider


# ---------------------------------------------------------------------------
# Direct unit test of the capability check on _build_next_auth_url call
# We patch _build_next_auth_url to observe whether it is invoked.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_primary_login_does_not_build_secondary_url_for_capable_strategy():
    """A chain-capable strategy still shows primary login without provider state."""
    cfg = TelegramAgentConfig(
        name="bot",
        chatbot_id="b",
        bot_token="tok",
        auth_methods=["basic"],
        auth_url="https://nav.example.com/api/v1/login",
        login_page_url="https://nav.example.com/static/login.html",
    )
    wrapper = _make_wrapper(cfg)
    _inject_registry(wrapper)

    # The strategy DOES support the chain.
    assert wrapper._auth_strategy.supports_post_auth_chain is True

    message = MagicMock()
    message.chat.id = 1
    message.from_user.id = 1
    message.from_user.username = None
    message.from_user.first_name = None
    message.from_user.last_name = None
    message.answer = AsyncMock()
    build_next = AsyncMock()
    build_kb = AsyncMock(return_value=MagicMock())
    with patch.object(wrapper, "_build_next_auth_url", build_next), patch.object(
        wrapper._auth_strategy, "build_login_keyboard", build_kb
    ):
        await wrapper.handle_login(message)

    build_next.assert_not_awaited()
    assert build_kb.await_args.kwargs == {}


@pytest.mark.asyncio
async def test_primary_login_does_not_build_secondary_url_for_non_capable_strategy():
    """A non-chain strategy likewise never builds secondary state at /login."""
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
    _inject_registry(wrapper)

    # OAuth2 does NOT support the chain.
    assert wrapper._auth_strategy.supports_post_auth_chain is False

    source = __import__("inspect").getsource(wrapper.handle_login)
    assert "_build_next_auth_url" not in source


# ---------------------------------------------------------------------------
# Strategy-level assertions
# ---------------------------------------------------------------------------

def test_azure_strategy_supports_post_auth_chain():
    """AzureAuthStrategy.supports_post_auth_chain is True after TASK-778."""
    assert AzureAuthStrategy.supports_post_auth_chain is True


def test_oauth2_strategy_does_not_support_post_auth_chain():
    """OAuth2AuthStrategy.supports_post_auth_chain is False."""
    assert OAuth2AuthStrategy.supports_post_auth_chain is False


def test_composite_all_capable_supports_chain():
    """Composite where all members support chain → supports_post_auth_chain True."""
    basic = MagicMock(spec=BasicAuthStrategy)
    basic.supports_post_auth_chain = True
    azure = MagicMock(spec=AzureAuthStrategy)
    azure.supports_post_auth_chain = True
    comp = CompositeAuthStrategy(
        strategies={"basic": basic, "azure": azure},
        login_page_url="https://nav.example.com/static/login_multi.html",
    )
    assert comp.supports_post_auth_chain is True


def test_composite_mixed_does_not_support_chain():
    """Composite with mixed chain support → supports_post_auth_chain False."""
    basic = MagicMock(spec=BasicAuthStrategy)
    basic.supports_post_auth_chain = True
    oauth2 = MagicMock(spec=OAuth2AuthStrategy)
    oauth2.supports_post_auth_chain = False
    comp = CompositeAuthStrategy(
        strategies={"basic": basic, "oauth2": oauth2},
        login_page_url="https://nav.example.com/static/login_multi.html",
    )
    assert comp.supports_post_auth_chain is False


def test_wrapper_does_not_use_isinstance_for_post_auth_gate():
    """Regression: handle_login contains no eager post-auth gate at all."""
    import inspect
    from parrot.integrations.telegram import wrapper as wrapper_mod
    source = inspect.getsource(wrapper_mod.TelegramAgentWrapper.handle_login)
    assert "supports_post_auth_chain" not in source
    assert "_build_next_auth_url" not in source
