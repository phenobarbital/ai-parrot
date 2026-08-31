"""Tests for GoogleAuthStrategy and updated CompositeAuthStrategy with Google + OAuth2.

Covers:
- GoogleAuthStrategy class attributes (name, supports_post_auth_chain).
- build_login_keyboard returns a WebApp button with google_auth_url param.
- handle_callback decodes JWT, populates session, and respects auth_method.
- handle_callback rejects missing token or missing user_id/sub claim.
- CompositeAuthStrategy.build_login_keyboard harvests google_auth_url and
  oauth2_authorize_url params.
- Config model accepts 'google' as an auth_method and derives google_auth_url.
"""

import base64
import json

import pytest
from unittest.mock import MagicMock  # noqa: F401

from parrot.integrations.telegram.auth import (
    BasicAuthStrategy,
    CompositeAuthStrategy,
    GoogleAuthStrategy,
    TelegramUserSession,
)
from parrot.integrations.telegram.models import TelegramAgentConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session() -> TelegramUserSession:
    """Return a minimal unauthenticated TelegramUserSession."""
    return TelegramUserSession(
        telegram_id=12345,
        telegram_username="testuser",
    )


def _make_jwt(claims: dict) -> str:
    """Build a fake three-part JWT from a claims dict.

    The header and signature are stubs; only the payload matters for
    GoogleAuthStrategy._decode_jwt_payload.
    """
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=").decode()
    signature = "stub"
    return f"{header}.{payload}.{signature}"


class _DummyConfig:
    """Minimal config stand-in for keyboard tests."""
    login_page_url = "https://static.example.com/login_multi.html"


# ---------------------------------------------------------------------------
# Class attribute tests
# ---------------------------------------------------------------------------

def test_google_strategy_name():
    """GoogleAuthStrategy has the canonical name 'google'."""
    assert GoogleAuthStrategy.name == "google"


def test_google_strategy_supports_post_auth_chain():
    """GoogleAuthStrategy supports the post-auth chain."""
    assert GoogleAuthStrategy.supports_post_auth_chain is True


# ---------------------------------------------------------------------------
# build_login_keyboard tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_build_keyboard_returns_markup():
    """build_login_keyboard returns a ReplyKeyboardMarkup with WebApp button."""
    strategy = GoogleAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        google_auth_url="https://nav.example.com/api/v1/auth/google/",
        login_page_url="https://static.example.com/login_multi.html",
    )
    keyboard = await strategy.build_login_keyboard(
        config=_DummyConfig(), state="test-state"
    )

    assert keyboard is not None
    button = keyboard.keyboard[0][0]
    assert button.web_app is not None
    url = button.web_app.url
    assert "google_auth_url=" in url
    assert "nav.example.com" in url


@pytest.mark.asyncio
async def test_google_build_keyboard_with_next_auth():
    """build_login_keyboard embeds next_auth_url and next_auth_required."""
    strategy = GoogleAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        google_auth_url="https://nav.example.com/api/v1/auth/google/",
        login_page_url="https://static.example.com/login_multi.html",
    )
    keyboard = await strategy.build_login_keyboard(
        config=_DummyConfig(),
        state="test-state",
        next_auth_url="https://jira.example.com/oauth",
        next_auth_required=True,
    )

    url = keyboard.keyboard[0][0].web_app.url
    assert "next_auth_url=" in url
    assert "next_auth_required=true" in url


@pytest.mark.asyncio
async def test_google_build_keyboard_raises_without_login_page():
    """build_login_keyboard raises ValueError when no login_page_url."""
    strategy = GoogleAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        google_auth_url="https://nav.example.com/api/v1/auth/google/",
        login_page_url=None,
    )
    config = MagicMock()
    config.login_page_url = None

    with pytest.raises(ValueError, match="login_page_url"):
        await strategy.build_login_keyboard(config, "state")


# ---------------------------------------------------------------------------
# handle_callback tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_callback_success():
    """Valid Google JWT token populates the session correctly."""
    strategy = GoogleAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        google_auth_url="https://nav.example.com/api/v1/auth/google/",
    )
    session = _make_session()
    token = _make_jwt({
        "user_id": "guser42",
        "email": "alice@gmail.com",
        "name": "Alice Wonderland",
    })

    result = await strategy.handle_callback(
        {"auth_method": "google", "token": token},
        session,
    )

    assert result is True
    assert session.authenticated is True
    assert session.nav_user_id == "guser42"
    assert session.nav_email == "alice@gmail.com"
    assert session.nav_display_name == "Alice Wonderland"


@pytest.mark.asyncio
async def test_google_callback_uses_sub_claim():
    """JWT with 'sub' instead of 'user_id' is accepted."""
    strategy = GoogleAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        google_auth_url="https://nav.example.com/api/v1/auth/google/",
    )
    session = _make_session()
    token = _make_jwt({"sub": "g-sub-123", "email": "bob@gmail.com"})

    result = await strategy.handle_callback(
        {"auth_method": "google", "token": token},
        session,
    )

    assert result is True
    assert session.nav_user_id == "g-sub-123"


@pytest.mark.asyncio
async def test_google_callback_rejects_wrong_auth_method():
    """Callback with auth_method != 'google' is rejected."""
    strategy = GoogleAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        google_auth_url="https://nav.example.com/api/v1/auth/google/",
    )
    session = _make_session()
    token = _make_jwt({"user_id": "u1", "email": "a@b.com"})

    result = await strategy.handle_callback(
        {"auth_method": "azure", "token": token},
        session,
    )

    assert result is False
    assert session.authenticated is False


@pytest.mark.asyncio
async def test_google_callback_rejects_missing_token():
    """Callback without a token is rejected."""
    strategy = GoogleAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        google_auth_url="https://nav.example.com/api/v1/auth/google/",
    )
    session = _make_session()

    result = await strategy.handle_callback(
        {"auth_method": "google"},
        session,
    )

    assert result is False


@pytest.mark.asyncio
async def test_google_callback_rejects_jwt_without_user_id():
    """Callback with JWT missing user_id/sub is rejected."""
    strategy = GoogleAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        google_auth_url="https://nav.example.com/api/v1/auth/google/",
    )
    session = _make_session()
    token = _make_jwt({"email": "nobody@gmail.com"})

    result = await strategy.handle_callback(
        {"auth_method": "google", "token": token},
        session,
    )

    assert result is False
    assert session.authenticated is False


@pytest.mark.asyncio
async def test_google_callback_handles_first_last_name():
    """JWT with first_name + last_name (no 'name') builds display_name."""
    strategy = GoogleAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        google_auth_url="https://nav.example.com/api/v1/auth/google/",
    )
    session = _make_session()
    token = _make_jwt({
        "user_id": "u1",
        "first_name": "Alice",
        "last_name": "Smith",
        "email": "alice@example.com",
    })

    result = await strategy.handle_callback(
        {"auth_method": "google", "token": token},
        session,
    )

    assert result is True
    assert session.nav_display_name == "Alice Smith"


# ---------------------------------------------------------------------------
# validate_token tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_validate_empty_token():
    """Empty token is rejected without making an HTTP call."""
    strategy = GoogleAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        google_auth_url="https://nav.example.com/api/v1/auth/google/",
    )
    result = await strategy.validate_token("", session=None)
    assert result is False


# ---------------------------------------------------------------------------
# CompositeAuthStrategy: Google and OAuth2 URL harvesting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_composite_keyboard_includes_google_url():
    """Composite keyboard passes google_auth_url to login_multi.html."""
    basic = BasicAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        login_page_url="https://static.example.com/login_multi.html",
    )
    google = GoogleAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        google_auth_url="https://nav.example.com/api/v1/auth/google/",
    )
    composite = CompositeAuthStrategy(
        strategies={"basic": basic, "google": google},
        login_page_url="https://static.example.com/login_multi.html",
    )

    keyboard = await composite.build_login_keyboard(
        config=_DummyConfig(), state="state123"
    )

    url = keyboard.keyboard[0][0].web_app.url
    assert "google_auth_url=" in url
    assert "auth_url=" in url


@pytest.mark.asyncio
async def test_composite_dispatches_google_callback():
    """Composite dispatches auth_method='google' to GoogleAuthStrategy."""
    google = GoogleAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        google_auth_url="https://nav.example.com/api/v1/auth/google/",
    )
    composite = CompositeAuthStrategy(
        strategies={"google": google},
        login_page_url="https://static.example.com/login_multi.html",
    )
    session = _make_session()
    token = _make_jwt({"user_id": "gu1", "email": "a@b.com", "name": "Test"})

    result = await composite.handle_callback(
        {"auth_method": "google", "token": token},
        session,
    )

    assert result is True
    assert session.authenticated is True
    assert session.metadata.get("auth_method") == "google"


# ---------------------------------------------------------------------------
# Config model: 'google' method support
# ---------------------------------------------------------------------------

def test_config_accepts_google_method():
    """TelegramAgentConfig accepts 'google' in auth_methods."""
    cfg = TelegramAgentConfig(
        name="test",
        chatbot_id="test",
        bot_token="fake:token",
        auth_url="https://nav.example.com/api/v1/login",
        auth_methods=["basic", "google"],
        login_page_url="https://example.com/login_multi.html",
    )
    assert "google" in cfg.auth_methods
    assert cfg.google_auth_url == "https://nav.example.com/api/v1/google/"


def test_config_derives_google_url_from_auth_url():
    """google_auth_url is derived from auth_url by replacing /login with /google/."""
    cfg = TelegramAgentConfig(
        name="test",
        chatbot_id="test",
        bot_token="fake:token",
        auth_url="https://nav.example.com/api/v1/login",
        auth_methods=["google"],
    )
    assert cfg.google_auth_url == "https://nav.example.com/api/v1/google/"


def test_config_explicit_google_url_takes_priority():
    """Explicit google_auth_url in config is not overridden."""
    cfg = TelegramAgentConfig(
        name="test",
        chatbot_id="test",
        bot_token="fake:token",
        auth_url="https://nav.example.com/api/v1/login",
        auth_methods=["google"],
        google_auth_url="https://custom.example.com/google-sso/",
    )
    assert cfg.google_auth_url == "https://custom.example.com/google-sso/"


def test_config_all_four_methods():
    """All four methods are accepted together without validation errors."""
    from parrot.integrations.telegram.models import TelegramBotsConfig

    cfg = TelegramAgentConfig(
        name="full",
        chatbot_id="full",
        bot_token="fake:token",
        auth_url="https://nav.example.com/api/v1/login",
        auth_methods=["basic", "google", "azure", "oauth2"],
        oauth2_client_id="client",
        oauth2_client_secret="secret",
        login_page_url="https://example.com/login_multi.html",
    )
    bots = TelegramBotsConfig(agents={"full": cfg})
    errors = bots.validate()
    assert errors == [], f"Unexpected validation errors: {errors}"
