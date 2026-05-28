"""Tests for auth strategy abstraction, BasicAuthStrategy, and session OAuth2 fields."""

import pytest
from aiogram.types import ReplyKeyboardMarkup

from parrot.integrations.telegram.auth import (
    AbstractAuthStrategy,
    BasicAuthStrategy,
    TelegramUserSession,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def basic_strategy():
    """BasicAuthStrategy with test URLs."""
    return BasicAuthStrategy(
        auth_url="https://nav.example.com/api/auth",
        login_page_url="https://static.example.com/login.html",
    )


@pytest.fixture
def session():
    """Fresh TelegramUserSession for testing."""
    return TelegramUserSession(
        telegram_id=12345,
        telegram_username="testuser",
        telegram_first_name="Test",
        telegram_last_name="User",
    )


class _DummyConfig:
    """Minimal config stand-in for tests."""
    login_page_url = "https://static.example.com/login.html"


@pytest.fixture
def dummy_config():
    return _DummyConfig()


# ---------------------------------------------------------------------------
# AbstractAuthStrategy tests
# ---------------------------------------------------------------------------

class TestAbstractAuthStrategy:
    """Verify the ABC contract."""

    def test_cannot_instantiate_abstract(self):
        """AbstractAuthStrategy cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AbstractAuthStrategy()  # type: ignore[abstract]

    def test_has_three_abstract_methods(self):
        """ABC defines exactly three abstract methods."""
        abstracts = AbstractAuthStrategy.__abstractmethods__
        assert "build_login_keyboard" in abstracts
        assert "handle_callback" in abstracts
        assert "validate_token" in abstracts
        assert len(abstracts) == 3


# ---------------------------------------------------------------------------
# BasicAuthStrategy tests
# ---------------------------------------------------------------------------

class TestBasicAuthStrategy:
    """Tests for the Navigator Basic Auth strategy."""

    @pytest.mark.asyncio
    async def test_build_login_keyboard(self, basic_strategy, dummy_config):
        """build_login_keyboard returns a ReplyKeyboardMarkup with WebApp button."""
        keyboard = await basic_strategy.build_login_keyboard(
            config=dummy_config, state="unused-state"
        )
        assert isinstance(keyboard, ReplyKeyboardMarkup)
        assert keyboard.resize_keyboard is True
        assert keyboard.one_time_keyboard is True

        # Single row, single button
        assert len(keyboard.keyboard) == 1
        assert len(keyboard.keyboard[0]) == 1

        button = keyboard.keyboard[0][0]
        assert "Sign in to Navigator" in button.text
        assert button.web_app is not None
        assert "auth_url=" in button.web_app.url
        assert "nav.example.com" in button.web_app.url

    @pytest.mark.asyncio
    async def test_build_login_keyboard_includes_login_page_url(
        self, basic_strategy, dummy_config
    ):
        """The WebApp URL starts with the configured login_page_url."""
        keyboard = await basic_strategy.build_login_keyboard(
            config=dummy_config, state="s"
        )
        url = keyboard.keyboard[0][0].web_app.url
        assert url.startswith("https://static.example.com/login.html?")

    @pytest.mark.asyncio
    async def test_build_login_keyboard_no_page_url_raises(self):
        """ValueError raised when no login_page_url is configured."""
        strategy = BasicAuthStrategy(
            auth_url="https://nav.example.com/api/auth",
            login_page_url=None,
        )

        class _EmptyConfig:
            login_page_url = None

        with pytest.raises(ValueError, match="login_page_url is required"):
            await strategy.build_login_keyboard(
                config=_EmptyConfig(), state="s"
            )

    @pytest.mark.asyncio
    async def test_handle_callback_success(self, basic_strategy, session):
        """handle_callback populates session on valid data."""
        data = {
            "user_id": "nav-42",
            "token": "tok-abc",
            "display_name": "Alice",
            "email": "alice@example.com",
        }
        result = await basic_strategy.handle_callback(data, session)

        assert result is True
        assert session.authenticated is True
        assert session.nav_user_id == "nav-42"
        assert session.nav_session_token == "tok-abc"
        assert session.nav_display_name == "Alice"
        assert session.nav_email == "alice@example.com"

    @pytest.mark.asyncio
    async def test_handle_callback_missing_user_id(self, basic_strategy, session):
        """handle_callback returns False when user_id is missing."""
        data = {"token": "tok-abc", "display_name": "Alice"}
        result = await basic_strategy.handle_callback(data, session)

        assert result is False
        assert session.authenticated is False

    @pytest.mark.asyncio
    async def test_handle_callback_minimal_data(self, basic_strategy, session):
        """handle_callback works with only user_id present."""
        data = {"user_id": "nav-99"}
        result = await basic_strategy.handle_callback(data, session)

        assert result is True
        assert session.authenticated is True
        assert session.nav_user_id == "nav-99"
        assert session.nav_session_token == ""
        assert session.nav_display_name == ""

    @pytest.mark.asyncio
    async def test_validate_token(self, basic_strategy):
        """validate_token delegates to NavigatorAuthClient."""
        assert await basic_strategy.validate_token("some-token") is True
        assert await basic_strategy.validate_token("") is False


# ---------------------------------------------------------------------------
# TelegramUserSession OAuth2 field tests
# ---------------------------------------------------------------------------

class TestTelegramUserSessionOAuth2:
    """Tests for OAuth2-specific session fields."""

    def test_oauth2_fields_default_none(self, session):
        """OAuth2 fields default to None."""
        assert session.oauth2_access_token is None
        assert session.oauth2_id_token is None
        assert session.oauth2_provider is None

    def test_oauth2_fields_can_be_set(self, session):
        """OAuth2 fields can be assigned."""
        session.oauth2_access_token = "ya29.test"
        session.oauth2_id_token = "eyJ.test"
        session.oauth2_provider = "google"

        assert session.oauth2_access_token == "ya29.test"
        assert session.oauth2_id_token == "eyJ.test"
        assert session.oauth2_provider == "google"

    def test_clear_auth_clears_oauth2_fields(self, session):
        """clear_auth() resets OAuth2 fields to None."""
        session.oauth2_access_token = "ya29.test"
        session.oauth2_id_token = "eyJ.test"
        session.oauth2_provider = "google"
        session.authenticated = True

        session.clear_auth()

        assert session.oauth2_access_token is None
        assert session.oauth2_id_token is None
        assert session.oauth2_provider is None
        assert session.authenticated is False

    def test_clear_auth_also_clears_nav_fields(self, session):
        """clear_auth() clears both Navigator and OAuth2 state."""
        session.set_authenticated(
            nav_user_id="u1",
            session_token="t1",
            display_name="Bob",
        )
        session.oauth2_access_token = "ya29.x"

        session.clear_auth()

        assert session.nav_user_id is None
        assert session.nav_session_token is None
        assert session.oauth2_access_token is None
        assert session.authenticated is False
