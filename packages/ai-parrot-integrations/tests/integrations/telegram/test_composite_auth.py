"""Tests for CompositeAuthStrategy multi-method router (TASK-779).

Verifies:
- build_login_keyboard emits a single URL with params from all member strategies.
- handle_callback dispatches based on auth_method.
- Unknown auth_method returns False and logs a warning.
- supports_post_auth_chain is a property with AND semantics.
- Empty strategies dict raises ValueError on construction.
- validate_token delegates, preferring "basic" first.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.integrations.telegram.auth import (
    CompositeAuthStrategy,
    BasicAuthStrategy,
    AzureAuthStrategy,
    TelegramUserSession,
)

LOGIN_MULTI_URL = "https://nav.example.com/static/telegram/login_multi.html"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _basic_mock() -> MagicMock:
    s = MagicMock(spec=BasicAuthStrategy)
    s.name = "basic"
    s.supports_post_auth_chain = True
    s.auth_url = "https://nav.example.com/api/v1/login"
    return s


def _azure_mock() -> MagicMock:
    s = MagicMock(spec=AzureAuthStrategy)
    s.name = "azure"
    s.supports_post_auth_chain = True
    s.azure_auth_url = "https://nav.example.com/api/v1/auth/azure/"
    return s


@pytest.fixture
def composite():
    return CompositeAuthStrategy(
        strategies={"basic": _basic_mock(), "azure": _azure_mock()},
        login_page_url=LOGIN_MULTI_URL,
    )


def _make_session() -> TelegramUserSession:
    return TelegramUserSession(telegram_id=99, telegram_username="tester")


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_empty_strategies_raises():
    """Empty strategies dict must raise ValueError."""
    with pytest.raises(ValueError, match="at least one"):
        CompositeAuthStrategy(
            strategies={},
            login_page_url=LOGIN_MULTI_URL,
        )


def test_name_is_composite():
    assert CompositeAuthStrategy.name == "composite"


# ---------------------------------------------------------------------------
# build_login_keyboard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_login_keyboard_emits_all_urls(composite):
    """The WebApp URL contains both auth_url and azure_auth_url."""
    kb = await composite.build_login_keyboard(MagicMock(), "nonce")
    url = kb.keyboard[0][0].web_app.url
    assert "auth_url=https" in url
    assert "azure_auth_url=https" in url
    assert "login_multi.html" in url


@pytest.mark.asyncio
async def test_build_login_keyboard_includes_next_auth_url(composite):
    """next_auth_url and next_auth_required are forwarded to the URL."""
    kb = await composite.build_login_keyboard(
        MagicMock(),
        "nonce",
        next_auth_url="https://jira.example.com/oauth",
        next_auth_required=True,
    )
    url = kb.keyboard[0][0].web_app.url
    assert "next_auth_url=" in url
    assert "next_auth_required=true" in url


@pytest.mark.asyncio
async def test_build_login_keyboard_only_basic():
    """With only a basic strategy, only auth_url appears in the URL."""
    comp = CompositeAuthStrategy(
        strategies={"basic": _basic_mock()},
        login_page_url=LOGIN_MULTI_URL,
    )
    kb = await comp.build_login_keyboard(MagicMock(), "s")
    url = kb.keyboard[0][0].web_app.url
    assert "auth_url=" in url
    assert "azure_auth_url" not in url


@pytest.mark.asyncio
async def test_build_login_keyboard_only_azure():
    """With only an azure strategy, only azure_auth_url appears (no bare auth_url param)."""
    comp = CompositeAuthStrategy(
        strategies={"azure": _azure_mock()},
        login_page_url=LOGIN_MULTI_URL,
    )
    kb = await comp.build_login_keyboard(MagicMock(), "s")
    url = kb.keyboard[0][0].web_app.url
    assert "azure_auth_url=" in url
    # There should be no separate bare auth_url= param (no basic strategy registered).
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(url)
    qp = parse_qs(parsed.query)
    assert "auth_url" not in qp
    assert "azure_auth_url" in qp


# ---------------------------------------------------------------------------
# handle_callback dispatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_basic(composite):
    """Callback with auth_method='basic' delegates to the basic strategy."""
    composite.strategies["basic"].handle_callback = AsyncMock(return_value=True)
    session = _make_session()

    ok = await composite.handle_callback(
        {"auth_method": "basic", "user_id": "u1", "token": "t"},
        session,
    )

    assert ok is True
    composite.strategies["basic"].handle_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_azure(composite):
    """Callback with auth_method='azure' delegates to the azure strategy."""
    composite.strategies["azure"].handle_callback = AsyncMock(return_value=True)
    session = _make_session()

    ok = await composite.handle_callback(
        {"auth_method": "azure", "token": "jwt"},
        session,
    )

    assert ok is True
    composite.strategies["azure"].handle_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_unknown_returns_false(composite):
    """Unknown auth_method returns False without calling any strategy."""
    session = _make_session()
    ok = await composite.handle_callback(
        {"auth_method": "linkedin"},
        session,
    )
    assert ok is False


@pytest.mark.asyncio
async def test_dispatch_missing_auth_method_returns_false(composite):
    """Missing auth_method key returns False."""
    session = _make_session()
    ok = await composite.handle_callback({}, session)
    assert ok is False


# ---------------------------------------------------------------------------
# supports_post_auth_chain — AND semantics
# ---------------------------------------------------------------------------

def test_capability_flag_all_members_support(composite):
    """All members support chain → composite.supports_post_auth_chain is True."""
    assert composite.supports_post_auth_chain is True


def test_capability_flag_partial_support(composite):
    """One member without chain support → composite flag is False."""
    composite.strategies["azure"].supports_post_auth_chain = False
    assert composite.supports_post_auth_chain is False


def test_capability_flag_no_support():
    """No member supports chain → composite flag is False."""
    basic = _basic_mock()
    basic.supports_post_auth_chain = False
    azure = _azure_mock()
    azure.supports_post_auth_chain = False
    comp = CompositeAuthStrategy(
        strategies={"basic": basic, "azure": azure},
        login_page_url=LOGIN_MULTI_URL,
    )
    assert comp.supports_post_auth_chain is False


# ---------------------------------------------------------------------------
# validate_token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validate_token_delegates_to_basic_first(composite):
    """validate_token tries 'basic' strategy first."""
    composite.strategies["basic"].validate_token = AsyncMock(return_value=True)
    composite.strategies["azure"].validate_token = AsyncMock(return_value=True)

    result = await composite.validate_token("tok")

    assert result is True
    composite.strategies["basic"].validate_token.assert_awaited_once_with("tok")
    # Azure is not tried because basic succeeded first.
    composite.strategies["azure"].validate_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_validate_token_falls_back_to_other_strategies(composite):
    """If basic rejects, the next member is tried."""
    composite.strategies["basic"].validate_token = AsyncMock(return_value=False)
    composite.strategies["azure"].validate_token = AsyncMock(return_value=True)

    result = await composite.validate_token("tok")

    assert result is True
    composite.strategies["basic"].validate_token.assert_awaited_once()
    composite.strategies["azure"].validate_token.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_token_returns_false_when_all_fail(composite):
    """Returns False when no member accepts the token."""
    composite.strategies["basic"].validate_token = AsyncMock(return_value=False)
    composite.strategies["azure"].validate_token = AsyncMock(return_value=False)

    result = await composite.validate_token("bad_tok")

    assert result is False
