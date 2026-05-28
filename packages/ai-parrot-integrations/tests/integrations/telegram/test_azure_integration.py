"""Integration tests for Azure SSO authentication flow.

Tests the complete Azure auth pipeline:
  config → strategy → keyboard → callback → authenticated session

Also verifies backward compatibility with basic and oauth2 flows.
"""
import base64
import json
import pytest

from parrot.integrations.telegram.auth import (
    AzureAuthStrategy,
    BasicAuthStrategy,
    TelegramUserSession,
)
from parrot.integrations.telegram.models import TelegramAgentConfig


# ---------------------------------------------------------------------------
# JWT test helper
# ---------------------------------------------------------------------------

def _make_jwt(claims: dict) -> str:
    """Build a fake three-part JWT with the given payload claims."""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesig"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def azure_config():
    """TelegramAgentConfig with Azure auth enabled."""
    return TelegramAgentConfig(
        name="AzureBot",
        chatbot_id="azure_bot",
        bot_token="test:token",
        auth_method="azure",
        auth_url="https://nav.example.com/api/v1/auth/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        login_page_url="https://static.example.com/telegram/azure_login.html",
        force_authentication=True,
    )


@pytest.fixture
def basic_config():
    """TelegramAgentConfig with basic Navigator auth."""
    return TelegramAgentConfig(
        name="BasicBot",
        chatbot_id="basic_bot",
        bot_token="test:token",
        auth_url="https://nav.example.com/api/v1/auth/login",
        login_page_url="https://static.example.com/telegram/login.html",
    )


# ---------------------------------------------------------------------------
# Full Azure flow
# ---------------------------------------------------------------------------

class TestAzureFullFlow:
    """Test the complete Azure SSO flow from config to authenticated session."""

    @pytest.mark.asyncio
    async def test_full_azure_login_flow(self, azure_config):
        """End-to-end: config → strategy → keyboard → callback → authenticated session."""
        strategy = AzureAuthStrategy(
            auth_url=azure_config.auth_url,
            azure_auth_url=azure_config.azure_auth_url,
            login_page_url=azure_config.login_page_url,
        )

        # Step 1: Build keyboard
        keyboard = await strategy.build_login_keyboard(azure_config, "state123")
        assert keyboard is not None
        button = keyboard.keyboard[0][0]
        assert button.web_app is not None
        assert "azure_auth_url=" in button.web_app.url
        assert "azure_login.html" in button.web_app.url

        # Step 2: Simulate callback with JWT
        session = TelegramUserSession(telegram_id=42)
        jwt = _make_jwt({
            "user_id": "emp-001",
            "email": "alice@company.com",
            "name": "Alice Johnson",
            "exp": 9999999999,
        })
        callback_data = {"auth_method": "azure", "token": jwt}
        success = await strategy.handle_callback(callback_data, session)

        # Step 3: Verify session
        assert success is True
        assert session.authenticated is True
        assert session.nav_user_id == "emp-001"
        assert session.nav_email == "alice@company.com"
        assert session.nav_display_name == "Alice Johnson"
        assert session.nav_session_token == jwt

    @pytest.mark.asyncio
    async def test_azure_with_sub_claim(self, azure_config):
        """JWT with 'sub' claim instead of 'user_id' is handled correctly."""
        strategy = AzureAuthStrategy(
            auth_url=azure_config.auth_url,
            azure_auth_url=azure_config.azure_auth_url,
            login_page_url=azure_config.login_page_url,
        )
        session = TelegramUserSession(telegram_id=42)
        jwt = _make_jwt({
            "sub": "sub-123",
            "email": "b@c.com",
            "first_name": "Bob",
            "last_name": "Smith",
        })
        success = await strategy.handle_callback(
            {"auth_method": "azure", "token": jwt}, session
        )
        assert success is True
        assert session.nav_user_id == "sub-123"
        assert "Bob" in session.nav_display_name
        assert "Smith" in session.nav_display_name

    @pytest.mark.asyncio
    async def test_azure_session_token_is_the_jwt(self, azure_config):
        """The JWT itself is stored as the session token."""
        strategy = AzureAuthStrategy(
            auth_url=azure_config.auth_url,
            azure_auth_url=azure_config.azure_auth_url,
            login_page_url=azure_config.login_page_url,
        )
        session = TelegramUserSession(telegram_id=42)
        jwt = _make_jwt({"user_id": "u1", "email": "x@y.com"})
        await strategy.handle_callback({"auth_method": "azure", "token": jwt}, session)
        assert session.nav_session_token == jwt


# ---------------------------------------------------------------------------
# Force authentication with Azure
# ---------------------------------------------------------------------------

class TestAzureForceAuthentication:
    """Test that force_authentication works with Azure auth method."""

    def test_config_force_auth_with_azure(self, azure_config):
        assert azure_config.force_authentication is True
        assert azure_config.auth_method == "azure"

    @pytest.mark.asyncio
    async def test_unauthenticated_session_is_not_authenticated(self, azure_config):
        session = TelegramUserSession(telegram_id=42)
        assert session.authenticated is False
        assert session.nav_user_id is None

    @pytest.mark.asyncio
    async def test_session_becomes_authenticated_after_flow(self, azure_config):
        strategy = AzureAuthStrategy(
            auth_url=azure_config.auth_url,
            azure_auth_url=azure_config.azure_auth_url,
            login_page_url=azure_config.login_page_url,
        )
        session = TelegramUserSession(telegram_id=42)
        assert not session.authenticated
        jwt = _make_jwt({"user_id": "u1", "email": "x@y.com"})
        await strategy.handle_callback({"auth_method": "azure", "token": jwt}, session)
        assert session.authenticated


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Ensure existing auth flows are not broken by the Azure additions."""

    def test_basic_config_defaults_unchanged(self, basic_config):
        assert basic_config.auth_method == "basic"
        assert basic_config.azure_auth_url is None

    @pytest.mark.asyncio
    async def test_basic_strategy_keyboard_unchanged(self, basic_config):
        strategy = BasicAuthStrategy(
            auth_url=basic_config.auth_url,
            login_page_url=basic_config.login_page_url,
        )
        kb = await strategy.build_login_keyboard(basic_config, "state")
        button = kb.keyboard[0][0]
        # Basic strategy uses auth_url param, not azure_auth_url
        assert "auth_url=" in button.web_app.url
        assert "azure" not in button.web_app.url.lower()

    @pytest.mark.asyncio
    async def test_basic_callback_unchanged(self, basic_config):
        strategy = BasicAuthStrategy(
            auth_url=basic_config.auth_url,
            login_page_url=basic_config.login_page_url,
        )
        session = TelegramUserSession(telegram_id=42)
        data = {
            "user_id": "nav-1",
            "token": "tok",
            "display_name": "Nav User",
            "email": "n@n.com",
        }
        success = await strategy.handle_callback(data, session)
        assert success is True
        assert session.nav_user_id == "nav-1"
        assert session.nav_display_name == "Nav User"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestAzureEdgeCases:
    """Edge cases for Azure auth flow."""

    @pytest.mark.asyncio
    async def test_empty_token_rejected(self, azure_config):
        strategy = AzureAuthStrategy(
            auth_url=azure_config.auth_url,
            azure_auth_url=azure_config.azure_auth_url,
        )
        session = TelegramUserSession(telegram_id=42)
        result = await strategy.handle_callback(
            {"auth_method": "azure", "token": ""}, session
        )
        assert result is False
        assert not session.authenticated

    @pytest.mark.asyncio
    async def test_malformed_jwt_rejected(self, azure_config):
        strategy = AzureAuthStrategy(
            auth_url=azure_config.auth_url,
            azure_auth_url=azure_config.azure_auth_url,
        )
        session = TelegramUserSession(telegram_id=42)
        result = await strategy.handle_callback(
            {"auth_method": "azure", "token": "garbage"}, session
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_jwt_without_user_id_rejected(self, azure_config):
        strategy = AzureAuthStrategy(
            auth_url=azure_config.auth_url,
            azure_auth_url=azure_config.azure_auth_url,
        )
        session = TelegramUserSession(telegram_id=42)
        jwt = _make_jwt({"email": "a@b.com", "name": "No ID"})
        result = await strategy.handle_callback(
            {"auth_method": "azure", "token": jwt}, session
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_logout_clears_azure_session(self, azure_config):
        """After /logout, session returns to unauthenticated state."""
        strategy = AzureAuthStrategy(
            auth_url=azure_config.auth_url,
            azure_auth_url=azure_config.azure_auth_url,
            login_page_url=azure_config.login_page_url,
        )
        session = TelegramUserSession(telegram_id=42)
        jwt = _make_jwt({"user_id": "42", "email": "a@b.com", "name": "Alice"})
        await strategy.handle_callback(
            {"auth_method": "azure", "token": jwt}, session
        )
        assert session.authenticated is True
        assert session.nav_user_id == "42"

        # Simulate /logout
        session.clear_auth()

        assert session.authenticated is False
        assert session.nav_user_id is None
        assert session.nav_session_token is None
        assert session.nav_display_name is None
        assert session.nav_email is None

    @pytest.mark.asyncio
    async def test_no_login_page_url_raises_on_keyboard(self, azure_config):
        """Building keyboard without login_page_url raises ValueError."""
        strategy = AzureAuthStrategy(
            auth_url=azure_config.auth_url,
            azure_auth_url=azure_config.azure_auth_url,
            # No login_page_url
        )
        config = type("Cfg", (), {"login_page_url": None})()
        with pytest.raises(ValueError, match="login_page_url"):
            await strategy.build_login_keyboard(config, "state")

    def test_azure_config_has_azure_auth_url_after_post_init(self, azure_config):
        """Config post_init properly sets azure_auth_url."""
        assert azure_config.azure_auth_url == "https://nav.example.com/api/v1/auth/azure/"

    def test_azure_url_derived_when_only_auth_url_set(self):
        """azure_auth_url is auto-derived when auth_method=azure and auth_url is set."""
        config = TelegramAgentConfig(
            name="DerivBot",
            chatbot_id="deriv",
            bot_token="t:k",
            auth_method="azure",
            auth_url="https://nav.example.com/api/v1/auth/login",
        )
        assert config.azure_auth_url == "https://nav.example.com/api/v1/auth/azure/"
