"""Integration tests for OAuth2 full flow through the Telegram wrapper.

Verifies end-to-end OAuth2 flow, Basic Auth backward compatibility,
force authentication, callback endpoint, and logout behavior.
All HTTP calls to external providers are mocked.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from parrot.integrations.telegram.auth import (
    BasicAuthStrategy,
    OAuth2AuthStrategy,
    TelegramUserSession,
)
from parrot.integrations.telegram.models import TelegramAgentConfig
from parrot.integrations.telegram.oauth2_callback import setup_oauth2_routes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wrapper(config: TelegramAgentConfig):
    """Create a TelegramAgentWrapper with mocked bot/agent dependencies."""
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


def _make_message(user_id: int = 12345, chat_id: int = 12345, text: str = ""):
    """Create a mock aiogram Message."""
    msg = MagicMock()
    msg.chat.id = chat_id
    msg.from_user.id = user_id
    msg.from_user.username = "testuser"
    msg.from_user.first_name = "Test"
    msg.from_user.last_name = "User"
    msg.text = text
    msg.answer = AsyncMock()
    msg.web_app_data = None
    return msg


def _oauth2_config() -> TelegramAgentConfig:
    """Create a standard OAuth2 config for tests."""
    return TelegramAgentConfig(
        name="TestBot",
        chatbot_id="test_bot",
        bot_token="test:token",
        auth_method="oauth2",
        oauth2_provider="google",
        oauth2_client_id="test-client-id.apps.googleusercontent.com",
        oauth2_client_secret="test-secret",
        oauth2_redirect_uri="https://example.com/oauth2/callback",
    )


def _basic_config() -> TelegramAgentConfig:
    """Create a standard Basic Auth config for tests."""
    return TelegramAgentConfig(
        name="TestBot",
        chatbot_id="test_bot",
        bot_token="test:token",
        auth_url="https://nav.example.com/api/auth",
        login_page_url="https://static.example.com/login.html",
    )


# ---------------------------------------------------------------------------
# Mock HTTP responses for Google OAuth2
# ---------------------------------------------------------------------------

MOCK_GOOGLE_TOKEN_RESPONSE = {
    "access_token": "ya29.mock-access-token",
    "id_token": "eyJhbGciOiJSUzI1NiJ9.mock-id-token",
    "token_type": "Bearer",
    "expires_in": 3600,
    "scope": "openid email profile",
}

MOCK_GOOGLE_USERINFO = {
    "sub": "google-user-123456",
    "name": "Test GoogleUser",
    "email": "testuser@gmail.com",
    "picture": "https://lh3.googleusercontent.com/photo.jpg",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOAuth2FullFlow:
    """Test the complete OAuth2 flow: login → callback → exchange → session."""

    @pytest.mark.asyncio
    async def test_oauth2_full_flow_google(self):
        """Simulate complete OAuth2 flow through the wrapper."""
        config = _oauth2_config()
        wrapper = _make_wrapper(config)
        strategy = wrapper._auth_strategy
        assert isinstance(strategy, OAuth2AuthStrategy)

        # Step 1: /login — generates authorize URL keyboard
        message = _make_message()
        await wrapper.handle_login(message)

        # Verify keyboard was sent
        message.answer.assert_called_once()
        call_kwargs = message.answer.call_args
        reply_markup = call_kwargs.kwargs.get("reply_markup") or call_kwargs[1].get("reply_markup")
        assert reply_markup is not None

        # Extract the authorize URL from the keyboard button
        button = reply_markup.keyboard[0][0]
        url = button.web_app.url
        assert "accounts.google.com" in url
        assert "code_challenge" in url
        assert "state=" in url

        # Extract state from the URL
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        state = qs["state"][0]

        # Verify state is stored in strategy
        assert state in strategy._pending_states

        # Step 2: Simulate callback with code + state
        # Mock the HTTP calls for token exchange and userinfo
        session = TelegramUserSession(telegram_id=12345)

        mock_token_resp = MagicMock()
        mock_token_resp.status = 200
        mock_token_resp.json = AsyncMock(return_value=MOCK_GOOGLE_TOKEN_RESPONSE)
        mock_token_resp.__aenter__ = AsyncMock(return_value=mock_token_resp)
        mock_token_resp.__aexit__ = AsyncMock(return_value=False)

        mock_userinfo_resp = MagicMock()
        mock_userinfo_resp.status = 200
        mock_userinfo_resp.json = AsyncMock(return_value=MOCK_GOOGLE_USERINFO)
        mock_userinfo_resp.__aenter__ = AsyncMock(return_value=mock_userinfo_resp)
        mock_userinfo_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_token_resp)
        mock_session.get = MagicMock(return_value=mock_userinfo_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        callback_data = {"code": "auth-code-123", "state": state}

        with patch("aiohttp.ClientSession", return_value=mock_session):
            success = await strategy.handle_callback(callback_data, session)

        assert success is True
        assert session.authenticated is True
        assert session.nav_user_id == "google-user-123456"
        assert session.nav_display_name == "Test GoogleUser"
        assert session.nav_email == "testuser@gmail.com"
        assert session.oauth2_access_token == "ya29.mock-access-token"
        assert session.oauth2_id_token == "eyJhbGciOiJSUzI1NiJ9.mock-id-token"
        assert session.oauth2_provider == "google"

        # State should be consumed
        assert state not in strategy._pending_states


class TestBasicAuthUnchanged:
    """Verify Basic Auth flow is identical to pre-refactor behavior."""

    @pytest.mark.asyncio
    async def test_basic_auth_unchanged(self):
        """Basic Auth config produces Navigator WebApp keyboard and handles callback."""
        config = _basic_config()
        wrapper = _make_wrapper(config)
        strategy = wrapper._auth_strategy
        assert isinstance(strategy, BasicAuthStrategy)

        # Step 1: /login produces Navigator keyboard
        message = _make_message()
        await wrapper.handle_login(message)

        message.answer.assert_called_once()
        call_kwargs = message.answer.call_args
        reply_markup = call_kwargs.kwargs.get("reply_markup") or call_kwargs[1].get("reply_markup")
        assert reply_markup is not None

        button = reply_markup.keyboard[0][0]
        assert "Sign in to Navigator" in button.text
        assert "auth_url=" in button.web_app.url
        assert "nav.example.com" in button.web_app.url

        # Step 2: WebApp callback with Navigator data
        session = TelegramUserSession(telegram_id=12345)
        nav_data = {
            "user_id": "nav-user-42",
            "token": "nav-session-token",
            "display_name": "Jane Doe",
            "email": "jane@example.com",
        }
        success = await strategy.handle_callback(nav_data, session)

        assert success is True
        assert session.authenticated is True
        assert session.nav_user_id == "nav-user-42"
        assert session.nav_session_token == "nav-session-token"
        assert session.nav_display_name == "Jane Doe"
        assert session.nav_email == "jane@example.com"
        # OAuth2 fields should remain None
        assert session.oauth2_access_token is None
        assert session.oauth2_provider is None


class TestHandleLoginDelegatesToStrategy:
    """Verify /login produces the correct keyboard per auth method."""

    @pytest.mark.asyncio
    async def test_handle_login_delegates_to_strategy(self):
        """OAuth2 config → OAuth2 keyboard; Basic config → Navigator keyboard."""
        # OAuth2 login
        oauth_wrapper = _make_wrapper(_oauth2_config())
        oauth_msg = _make_message()
        await oauth_wrapper.handle_login(oauth_msg)

        oauth_call = oauth_msg.answer.call_args
        oauth_text = oauth_call[0][0] if oauth_call[0] else oauth_call.kwargs.get("text", "")
        assert "Google" in oauth_text

        oauth_markup = oauth_call.kwargs.get("reply_markup") or oauth_call[1].get("reply_markup")
        oauth_button = oauth_markup.keyboard[0][0]
        assert "Sign in with Google" in oauth_button.text

        # Basic Auth login
        basic_wrapper = _make_wrapper(_basic_config())
        basic_msg = _make_message()
        await basic_wrapper.handle_login(basic_msg)

        basic_call = basic_msg.answer.call_args
        basic_text = basic_call[0][0] if basic_call[0] else basic_call.kwargs.get("text", "")
        assert "Navigator" in basic_text

        basic_markup = basic_call.kwargs.get("reply_markup") or basic_call[1].get("reply_markup")
        basic_button = basic_markup.keyboard[0][0]
        assert "Sign in to Navigator" in basic_button.text


class TestHandleWebAppDataRoutes:
    """Verify WebApp data is routed to the correct strategy."""

    @pytest.mark.asyncio
    async def test_handle_web_app_data_routes_to_strategy(self):
        """OAuth2 data routes to OAuth2Strategy; Navigator data to BasicStrategy."""
        # OAuth2 wrapper — inject mock data via handle_web_app_data
        oauth_config = _oauth2_config()
        oauth_wrapper = _make_wrapper(oauth_config)
        strategy = oauth_wrapper._auth_strategy

        # Manually store a state so the callback can succeed
        strategy._store_state("test-state-xyz", "test-verifier")

        oauth_msg = _make_message()
        oauth_msg.web_app_data = MagicMock()
        oauth_msg.web_app_data.data = json.dumps({
            "provider": "google",
            "code": "auth-code-456",
            "state": "test-state-xyz",
        })

        # Mock HTTP for token exchange + userinfo
        mock_token_resp = MagicMock()
        mock_token_resp.status = 200
        mock_token_resp.json = AsyncMock(return_value=MOCK_GOOGLE_TOKEN_RESPONSE)
        mock_token_resp.__aenter__ = AsyncMock(return_value=mock_token_resp)
        mock_token_resp.__aexit__ = AsyncMock(return_value=False)

        mock_userinfo_resp = MagicMock()
        mock_userinfo_resp.status = 200
        mock_userinfo_resp.json = AsyncMock(return_value=MOCK_GOOGLE_USERINFO)
        mock_userinfo_resp.__aenter__ = AsyncMock(return_value=mock_userinfo_resp)
        mock_userinfo_resp.__aexit__ = AsyncMock(return_value=False)

        mock_http = MagicMock()
        mock_http.post = MagicMock(return_value=mock_token_resp)
        mock_http.get = MagicMock(return_value=mock_userinfo_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_http):
            await oauth_wrapper.handle_web_app_data(oauth_msg)

        # Should have sent success message
        oauth_msg.answer.assert_called_once()
        answer_text = oauth_msg.answer.call_args[0][0]
        assert "Authenticated" in answer_text
        assert "Test GoogleUser" in answer_text

        # Basic Auth wrapper
        basic_wrapper = _make_wrapper(_basic_config())
        basic_msg = _make_message()
        basic_msg.web_app_data = MagicMock()
        basic_msg.web_app_data.data = json.dumps({
            "user_id": "nav-99",
            "token": "tok",
            "display_name": "NavUser",
        })

        await basic_wrapper.handle_web_app_data(basic_msg)
        basic_msg.answer.assert_called_once()
        answer_text = basic_msg.answer.call_args[0][0]
        assert "Authenticated" in answer_text
        assert "NavUser" in answer_text


class TestForceAuthWithOAuth2:
    """Test force_authentication with OAuth2."""

    @pytest.mark.asyncio
    async def test_force_auth_with_oauth2(self):
        """Unauthenticated user is blocked when force_authentication=True."""
        config = TelegramAgentConfig(
            name="TestBot",
            chatbot_id="test_bot",
            bot_token="test:token",
            auth_method="oauth2",
            oauth2_provider="google",
            oauth2_client_id="test-id",
            oauth2_client_secret="test-secret",
            oauth2_redirect_uri="https://example.com/callback",
            force_authentication=True,
        )
        wrapper = _make_wrapper(config)
        message = _make_message(text="hello")

        # _check_authentication should block the message
        result = await wrapper._check_authentication(message)
        assert result is False

        message.answer.assert_called_once()
        answer_text = message.answer.call_args[0][0]
        assert "/login" in answer_text

        # After authenticating, should pass
        session = wrapper._get_user_session(message)
        session.set_authenticated(
            nav_user_id="google-123",
            session_token="access-tok",
            display_name="Auth User",
        )
        message2 = _make_message(text="hello again")
        # Use same user session by injecting it
        wrapper._user_sessions[message2.from_user.id] = session
        result2 = await wrapper._check_authentication(message2)
        assert result2 is True


class TestOAuth2CallbackEndpoint:
    """Test the aiohttp callback endpoint."""

    @pytest_asyncio.fixture
    async def client(self):
        """Create a test client for the OAuth2 callback app."""
        app = web.Application()
        setup_oauth2_routes(app)
        async with TestClient(TestServer(app)) as c:
            yield c

    @pytest.mark.asyncio
    async def test_oauth2_callback_endpoint(self, client):
        """GET /oauth2/callback with code and state returns HTML with sendData."""
        resp = await client.get(
            "/oauth2/callback?code=auth-code-abc&state=state-xyz-123"
        )
        assert resp.status == 200
        text = await resp.text()
        assert "sendData" in text
        assert "auth-code-abc" in text
        assert "state-xyz-123" in text
        assert "text/html" in resp.headers.get("Content-Type", "")
        assert "telegram-web-app.js" in text


class TestOAuth2StateMismatch:
    """Test that mismatched state is rejected."""

    @pytest.mark.asyncio
    async def test_oauth2_state_mismatch_rejected(self):
        """Callback with wrong state is rejected gracefully."""
        config = _oauth2_config()
        wrapper = _make_wrapper(config)
        strategy = wrapper._auth_strategy

        # Store state "correct-state" but send "wrong-state"
        strategy._store_state("correct-state", "test-verifier")

        session = TelegramUserSession(telegram_id=12345)
        callback_data = {"code": "some-code", "state": "wrong-state"}

        success = await strategy.handle_callback(callback_data, session)
        assert success is False
        assert session.authenticated is False
        assert session.oauth2_access_token is None


class TestLogoutClearsOAuth2Session:
    """Test that logout clears OAuth2 session fields."""

    @pytest.mark.asyncio
    async def test_logout_clears_oauth2_session(self):
        """Authenticated OAuth2 session is fully cleared on logout."""
        config = _oauth2_config()
        wrapper = _make_wrapper(config)

        # Set up an authenticated OAuth2 session
        message = _make_message()
        session = wrapper._get_user_session(message)
        session.set_authenticated(
            nav_user_id="google-user-123",
            session_token="ya29.access-token",
            display_name="Google User",
            email="user@gmail.com",
        )
        session.oauth2_access_token = "ya29.access-token"
        session.oauth2_id_token = "id-token-value"
        session.oauth2_provider = "google"

        assert session.authenticated is True
        assert session.oauth2_access_token is not None

        # Call /logout
        await wrapper.handle_logout(message)

        # Verify everything is cleared
        assert session.authenticated is False
        assert session.nav_user_id is None
        assert session.nav_session_token is None
        assert session.nav_display_name is None
        assert session.nav_email is None
        assert session.oauth2_access_token is None
        assert session.oauth2_id_token is None
        assert session.oauth2_provider is None
        assert session.authenticated_at is None

        # Verify logout message was sent
        message.answer.assert_called_once()
        answer_text = message.answer.call_args[0][0]
        assert "Logged out" in answer_text
        assert "Google User" in answer_text
