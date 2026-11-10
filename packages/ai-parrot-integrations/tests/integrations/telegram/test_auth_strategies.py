"""Tests for auth strategy abstraction, BasicAuthStrategy, and session OAuth2 fields."""

from urllib.parse import parse_qs, urlsplit

import pytest
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from parrot.integrations.telegram.auth import (
    AbstractAuthStrategy,
    AzureAuthStrategy,
    BasicAuthStrategy,
    CompositeAuthStrategy,
    GoogleAuthStrategy,
    OAuth2AuthStrategy,
    TelegramUserSession,
)
from parrot.integrations.telegram.browser_login import BROWSER_COMPLETE_PATH, new_browser_state
from parrot.integrations.telegram.models import TelegramAgentConfig

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
        assert "nav.example.com" in button.web_app.url  # lgtm[py/incomplete-url-substring-sanitization]

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


class TestAuthOpenModeConfig:
    """FEAT-854 M1: auth_open_mode / public_base_url config surface."""

    def test_config_auth_open_mode_default_webview(self):
        """Unset field resolves to 'webview' (legacy behavior)."""
        cfg = TelegramAgentConfig(name="t", chatbot_id="c")

        assert cfg.auth_open_mode == "webview"
        assert cfg.public_base_url is None

    def test_config_auth_open_mode_invalid_raises(self):
        """An unknown mode fails at config load."""
        with pytest.raises(ValueError, match="auth_open_mode"):
            TelegramAgentConfig(name="t", chatbot_id="c", auth_open_mode="popup")

    def test_config_browser_requires_public_base_url(self):
        """Browser mode without public_base_url fails at config load."""
        with pytest.raises(ValueError, match="browser mode requires public_base_url"):
            TelegramAgentConfig(name="t", chatbot_id="c", auth_open_mode="browser")

        with pytest.raises(ValueError, match="browser mode requires public_base_url"):
            TelegramAgentConfig(
                name="t",
                chatbot_id="c",
                auth_open_mode="browser",
                public_base_url="ftp://parrot.example",
            )

        cfg = TelegramAgentConfig(
            name="t",
            chatbot_id="c",
            auth_open_mode="browser",
            public_base_url="https://parrot.example",
        )

        assert cfg.public_base_url == "https://parrot.example"

    def test_config_from_dict_maps_open_mode(self):
        """YAML loading carries both new keys."""
        cfg = TelegramAgentConfig.from_dict(
            "t",
            {
                "auth_open_mode": "browser",
                "public_base_url": "https://parrot.example",
            },
        )

        assert cfg.auth_open_mode == "browser"
        assert cfg.public_base_url == "https://parrot.example"


class _BrowserConfig(_DummyConfig):
    """Minimal browser-mode config stand-in."""

    auth_open_mode = "browser"
    public_base_url = "https://parrot.example"


class TestBrowserModeKeyboards:
    """FEAT-854 M3."""

    @staticmethod
    def _oauth2_config() -> TelegramAgentConfig:
        """Return a browser-mode config with OAuth2 settings."""
        return TelegramAgentConfig(
            name="telegram",
            chatbot_id="chatbot",
            auth_open_mode="browser",
            public_base_url="https://parrot.example",
            oauth2_provider="google",
            oauth2_client_id="test-client-id.apps.googleusercontent.com",
            oauth2_client_secret="test-secret",
            oauth2_redirect_uri="https://parrot.example/oauth2/callback",
            oauth2_scopes=["openid", "email", "profile"],
        )

    @staticmethod
    def _assert_browser_params(url: str, state: str) -> None:
        """Assert that a page-login URL carries the browser completion parameters."""
        query = parse_qs(urlsplit(url).query)
        assert query["return_mode"] == ["browser"]
        assert query["state"] == [state]
        assert query["complete_url"] == [f"https://parrot.example{BROWSER_COMPLETE_PATH}"]

    async def test_basic_keyboard_browser_mode_inline_url(self, basic_strategy):
        """Basic auth uses an inline browser button with completion parameters."""
        state = new_browser_state()
        keyboard = await basic_strategy.build_login_keyboard(_BrowserConfig(), state)

        assert isinstance(keyboard, InlineKeyboardMarkup)
        button = keyboard.inline_keyboard[0][0]
        assert button.url and button.web_app is None
        self._assert_browser_params(button.url, state)

    async def test_oauth2_keyboard_browser_mode_authorize_url(self):
        """OAuth2 browser mode keeps the provider URL and stores PKCE by state."""
        config = self._oauth2_config()
        strategy = OAuth2AuthStrategy(config)
        state = new_browser_state()

        keyboard = await strategy.build_login_keyboard(config, state)

        assert isinstance(keyboard, InlineKeyboardMarkup)
        button = keyboard.inline_keyboard[0][0]
        assert button.url and button.web_app is None
        assert button.url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        query = parse_qs(urlsplit(button.url).query)
        assert query["state"] == [state]
        assert "code_challenge" in query
        assert strategy._consume_state(state)

    async def test_azure_google_composite_browser_mode(self):
        """Azure, Google, and composite page logins carry browser parameters."""
        config = _BrowserConfig()
        state = new_browser_state()
        azure = AzureAuthStrategy(
            auth_url="https://nav.example.com/api/auth",
            azure_auth_url="https://nav.example.com/api/auth/azure",
            login_page_url="https://static.example.com/azure_login.html",
        )
        google = GoogleAuthStrategy(
            auth_url="https://nav.example.com/api/auth",
            google_auth_url="https://nav.example.com/api/auth/google",
            login_page_url="https://static.example.com/google_login.html",
        )
        composite = CompositeAuthStrategy(
            strategies={
                "basic": BasicAuthStrategy(
                    auth_url="https://nav.example.com/api/auth",
                    login_page_url="https://static.example.com/login_multi.html",
                )
            },
            login_page_url="https://static.example.com/login_multi.html",
        )

        for strategy in (azure, google, composite):
            keyboard = await strategy.build_login_keyboard(config, state)
            assert isinstance(keyboard, InlineKeyboardMarkup)
            button = keyboard.inline_keyboard[0][0]
            assert button.url and button.web_app is None
            self._assert_browser_params(button.url, state)

    async def test_all_strategies_webview_mode_unchanged(self, basic_strategy, dummy_config):
        """All strategies preserve reply-keyboard WebApp presentation by default."""
        oauth2_config = self._oauth2_config()
        azure = AzureAuthStrategy(
            auth_url="https://nav.example.com/api/auth",
            azure_auth_url="https://nav.example.com/api/auth/azure",
            login_page_url="https://static.example.com/azure_login.html",
        )
        google = GoogleAuthStrategy(
            auth_url="https://nav.example.com/api/auth",
            google_auth_url="https://nav.example.com/api/auth/google",
            login_page_url="https://static.example.com/google_login.html",
        )
        oauth2 = OAuth2AuthStrategy(oauth2_config)
        composite = CompositeAuthStrategy(
            strategies={"basic": basic_strategy},
            login_page_url="https://static.example.com/login_multi.html",
        )

        for strategy in (basic_strategy, azure, google, oauth2, composite):
            keyboard = await strategy.build_login_keyboard(dummy_config, "webview-state")
            assert isinstance(keyboard, ReplyKeyboardMarkup)
            button = keyboard.keyboard[0][0]
            assert button.web_app is not None
            query = parse_qs(urlsplit(button.web_app.url).query)
            assert not {"return_mode", "complete_url"}.intersection(query)

    async def test_browser_mode_without_public_base_url_raises(self, basic_strategy):
        """Browser page logins require a public absolute completion URL."""

        class _MissingPublicBaseUrlConfig(_DummyConfig):
            auth_open_mode = "browser"
            public_base_url = None

        with pytest.raises(ValueError, match="public_base_url is required"):
            await basic_strategy.build_login_keyboard(_MissingPublicBaseUrlConfig(), new_browser_state())
