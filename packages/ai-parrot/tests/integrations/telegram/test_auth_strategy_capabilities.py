"""Tests for AbstractAuthStrategy capability class attributes (TASK-777).

Verifies:
- AbstractAuthStrategy.name and supports_post_auth_chain defaults.
- Concrete strategy name / supports_post_auth_chain overrides.
- BasicAuthStrategy.handle_callback backward-compatibility with payloads
  that include or omit auth_method.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.integrations.telegram.auth import (
    AbstractAuthStrategy,
    BasicAuthStrategy,
    AzureAuthStrategy,
    OAuth2AuthStrategy,
    TelegramUserSession,
)


# ---------------------------------------------------------------------------
# Class attribute tests (no instance needed)
# ---------------------------------------------------------------------------

def test_abstract_defaults():
    """AbstractAuthStrategy has the expected class-level defaults."""
    assert AbstractAuthStrategy.name == "abstract"
    assert AbstractAuthStrategy.supports_post_auth_chain is False


def test_concrete_class_names():
    """Each concrete strategy exposes its canonical name."""
    assert BasicAuthStrategy.name == "basic"
    assert AzureAuthStrategy.name == "azure"
    assert OAuth2AuthStrategy.name == "oauth2"


def test_post_auth_chain_capability():
    """BasicAuth and Azure support the post-auth chain; OAuth2 does not."""
    assert BasicAuthStrategy.supports_post_auth_chain is True
    assert AzureAuthStrategy.supports_post_auth_chain is True   # flipped by TASK-778
    assert OAuth2AuthStrategy.supports_post_auth_chain is False


# ---------------------------------------------------------------------------
# BasicAuthStrategy.handle_callback backward-compatibility tests
# ---------------------------------------------------------------------------

def _make_session() -> TelegramUserSession:
    """Return a minimal unauthenticated TelegramUserSession."""
    return TelegramUserSession(
        telegram_id=12345,
        telegram_username="testuser",
    )


@pytest.mark.asyncio
async def test_basic_callback_accepts_payload_with_auth_method():
    """Payload that includes auth_method='basic' is accepted normally."""
    strategy = BasicAuthStrategy(auth_url="https://nav.example.com/api/v1/login")
    session = _make_session()

    result = await strategy.handle_callback(
        {
            "auth_method": "basic",
            "user_id": "u1",
            "token": "tok",
            "display_name": "Alice",
            "email": "alice@example.com",
        },
        session,
    )

    assert result is True
    assert session.authenticated is True
    assert session.nav_user_id == "u1"


@pytest.mark.asyncio
async def test_basic_callback_accepts_legacy_payload_without_auth_method():
    """Legacy payloads that omit auth_method are accepted (backward-compat)."""
    strategy = BasicAuthStrategy(auth_url="https://nav.example.com/api/v1/login")
    session = _make_session()

    result = await strategy.handle_callback(
        {
            "user_id": "u2",
            "token": "tok2",
            "display_name": "Bob",
            "email": "bob@example.com",
        },
        session,
    )

    assert result is True
    assert session.authenticated is True
    assert session.nav_user_id == "u2"


@pytest.mark.asyncio
async def test_basic_callback_tolerates_mismatched_auth_method(caplog):
    """Payloads with a different auth_method log a warning but still succeed."""
    import logging

    strategy = BasicAuthStrategy(auth_url="https://nav.example.com/api/v1/login")
    session = _make_session()

    with caplog.at_level(logging.WARNING, logger="parrot.Telegram.Auth.Basic"):
        result = await strategy.handle_callback(
            {
                "auth_method": "azure",  # mismatch — should warn, not fail
                "user_id": "u3",
                "token": "tok3",
                "display_name": "Carol",
                "email": "carol@example.com",
            },
            session,
        )

    assert result is True
    assert any("ignoring mismatch" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_basic_callback_rejects_missing_user_id():
    """Payload without user_id returns False regardless of auth_method."""
    strategy = BasicAuthStrategy(auth_url="https://nav.example.com/api/v1/login")
    session = _make_session()

    result = await strategy.handle_callback(
        {"auth_method": "basic", "token": "tok"},
        session,
    )

    assert result is False
    assert session.authenticated is False


# ---------------------------------------------------------------------------
# build_login_keyboard signature — kwargs accepted by all strategies
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_basic_build_keyboard_accepts_next_auth_url():
    """BasicAuthStrategy.build_login_keyboard accepts next_auth_url kwarg."""
    strategy = BasicAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        login_page_url="https://nav.example.com/static/login.html",
    )
    config = MagicMock()
    config.login_page_url = None

    keyboard = await strategy.build_login_keyboard(
        config,
        "state123",
        next_auth_url="https://jira.example.com/oauth",
        next_auth_required=True,
    )

    assert keyboard is not None
    # Verify next_auth_url appears in the button URL
    button_url = keyboard.keyboard[0][0].web_app.url
    assert "next_auth_url=" in button_url
    assert "next_auth_required=true" in button_url


@pytest.mark.asyncio
async def test_azure_build_keyboard_accepts_next_auth_kwargs():
    """AzureAuthStrategy.build_login_keyboard accepts next_auth_url without error."""
    strategy = AzureAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        login_page_url="https://nav.example.com/static/azure_login.html",
    )
    config = MagicMock()
    config.login_page_url = None

    # Should not raise even though Azure ignores these kwargs.
    keyboard = await strategy.build_login_keyboard(
        config,
        "state456",
        next_auth_url="https://jira.example.com/oauth",
        next_auth_required=False,
    )

    assert keyboard is not None
