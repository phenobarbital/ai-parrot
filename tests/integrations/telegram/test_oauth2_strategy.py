"""Tests for OAuth2AuthStrategy with PKCE support."""

import base64
import hashlib
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from aiogram.types import ReplyKeyboardMarkup

from parrot.integrations.telegram.auth import (
    OAuth2AuthStrategy,
    TelegramUserSession,
    _TOKEN_TTL,
    _STATE_TTL_SECONDS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _FakeOAuth2Config:
    """Minimal config stand-in for OAuth2AuthStrategy."""

    oauth2_provider = "google"
    oauth2_client_id = "test-client-id.apps.googleusercontent.com"
    oauth2_client_secret = "test-secret"
    oauth2_redirect_uri = "https://example.com/oauth2/callback"
    oauth2_scopes = ["openid", "email", "profile"]


@pytest.fixture
def oauth2_config():
    return _FakeOAuth2Config()


@pytest.fixture
def strategy(oauth2_config):
    return OAuth2AuthStrategy(oauth2_config)


@pytest.fixture
def session():
    return TelegramUserSession(
        telegram_id=12345,
        telegram_username="testuser",
    )


@pytest.fixture
def mock_token_response():
    return {
        "access_token": "ya29.a0AfB_test",
        "id_token": "eyJhbGciOiJSUzI1NiJ9.test",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "openid email profile",
    }


@pytest.fixture
def mock_userinfo():
    return {
        "sub": "118234567890",
        "email": "user@example.com",
        "name": "Test User",
        "picture": "https://lh3.googleusercontent.com/a/test",
        "email_verified": True,
    }


# ---------------------------------------------------------------------------
# PKCE tests
# ---------------------------------------------------------------------------

class TestPKCE:
    """Verify PKCE code_verifier and code_challenge generation."""

    def test_generate_pkce_returns_tuple(self, strategy):
        """_generate_pkce returns (code_verifier, code_challenge)."""
        verifier, challenge = strategy._generate_pkce()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)
        assert len(verifier) > 40  # token_urlsafe(64) produces ~86 chars

    def test_pkce_challenge_is_valid_s256(self, strategy):
        """code_challenge is the base64url-encoded SHA256 of code_verifier."""
        verifier, challenge = strategy._generate_pkce()

        # Recompute expected challenge
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

        assert challenge == expected

    def test_pkce_generates_unique_values(self, strategy):
        """Each call generates different verifier/challenge pairs."""
        v1, c1 = strategy._generate_pkce()
        v2, c2 = strategy._generate_pkce()
        assert v1 != v2
        assert c1 != c2


# ---------------------------------------------------------------------------
# State management tests
# ---------------------------------------------------------------------------

class TestStateManagement:
    """Tests for OAuth2 state storage and consumption."""

    def test_store_and_consume_state(self, strategy):
        """Stored state can be consumed once."""
        strategy._store_state("state-abc", "verifier-xyz")
        result = strategy._consume_state("state-abc")
        assert result == "verifier-xyz"

    def test_consume_state_removes_it(self, strategy):
        """Consuming a state removes it (single use)."""
        strategy._store_state("state-abc", "verifier-xyz")
        strategy._consume_state("state-abc")
        assert strategy._consume_state("state-abc") is None

    def test_consume_unknown_state_returns_none(self, strategy):
        """Unknown state returns None."""
        assert strategy._consume_state("unknown") is None

    def test_expired_states_are_cleaned(self, strategy):
        """States older than TTL are cleaned up."""
        # Manually insert an expired state
        expired_ts = time.monotonic() - _STATE_TTL_SECONDS - 1
        strategy._pending_states["old-state"] = ("verifier", expired_ts)

        # Cleanup happens on consume
        assert strategy._consume_state("old-state") is None


# ---------------------------------------------------------------------------
# build_login_keyboard tests
# ---------------------------------------------------------------------------

class TestBuildLoginKeyboard:
    """Tests for the authorize URL and keyboard generation."""

    @pytest.mark.asyncio
    async def test_returns_reply_keyboard_markup(self, strategy, oauth2_config):
        """build_login_keyboard returns a ReplyKeyboardMarkup."""
        keyboard = await strategy.build_login_keyboard(
            config=oauth2_config, state="test-state"
        )
        assert isinstance(keyboard, ReplyKeyboardMarkup)
        assert keyboard.resize_keyboard is True
        assert keyboard.one_time_keyboard is True

    @pytest.mark.asyncio
    async def test_authorize_url_contains_required_params(
        self, strategy, oauth2_config
    ):
        """Authorization URL includes all required OAuth2+PKCE params."""
        keyboard = await strategy.build_login_keyboard(
            config=oauth2_config, state="test-state"
        )
        url = keyboard.keyboard[0][0].web_app.url

        assert "accounts.google.com/o/oauth2/v2/auth" in url
        assert "client_id=test-client-id" in url
        assert "redirect_uri=" in url
        assert "response_type=code" in url
        assert "scope=openid+email+profile" in url
        assert "state=test-state" in url
        assert "code_challenge=" in url
        assert "code_challenge_method=S256" in url
        assert "access_type=offline" in url

    @pytest.mark.asyncio
    async def test_stores_state_with_verifier(self, strategy, oauth2_config):
        """build_login_keyboard stores the state → code_verifier mapping."""
        await strategy.build_login_keyboard(
            config=oauth2_config, state="my-state"
        )
        verifier = strategy._consume_state("my-state")
        assert verifier is not None
        assert len(verifier) > 40

    @pytest.mark.asyncio
    async def test_button_text_includes_provider_name(
        self, strategy, oauth2_config
    ):
        """Button text mentions the provider name."""
        keyboard = await strategy.build_login_keyboard(
            config=oauth2_config, state="s"
        )
        text = keyboard.keyboard[0][0].text
        assert "Google" in text


# ---------------------------------------------------------------------------
# exchange_code tests
# ---------------------------------------------------------------------------

class TestExchangeCode:
    """Tests for the token exchange HTTP call."""

    @pytest.mark.asyncio
    async def test_exchange_code_success(self, strategy, mock_token_response):
        """exchange_code returns token data on 200 response."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_token_response)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession", return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_session),
            __aexit__=AsyncMock(return_value=False),
        )):
            result = await strategy.exchange_code("auth-code", "verifier-123")

        assert result == mock_token_response

    @pytest.mark.asyncio
    async def test_exchange_code_failure_http_error(self, strategy):
        """exchange_code returns None on non-200 response."""
        mock_resp = AsyncMock()
        mock_resp.status = 400
        mock_resp.text = AsyncMock(return_value='{"error": "invalid_grant"}')

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession", return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_session),
            __aexit__=AsyncMock(return_value=False),
        )):
            result = await strategy.exchange_code("bad-code", "verifier")

        assert result is None

    @pytest.mark.asyncio
    async def test_exchange_code_network_error(self, strategy):
        """exchange_code returns None on network error."""
        import aiohttp as _aiohttp

        with patch("aiohttp.ClientSession", side_effect=_aiohttp.ClientError("conn failed")):
            result = await strategy.exchange_code("code", "verifier")

        assert result is None


# ---------------------------------------------------------------------------
# fetch_userinfo tests
# ---------------------------------------------------------------------------

class TestFetchUserinfo:
    """Tests for the userinfo HTTP call."""

    @pytest.mark.asyncio
    async def test_fetch_userinfo_success(self, strategy, mock_userinfo):
        """fetch_userinfo returns user profile on 200 response."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_userinfo)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession", return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_session),
            __aexit__=AsyncMock(return_value=False),
        )):
            result = await strategy.fetch_userinfo("ya29.test-token")

        assert result == mock_userinfo
        assert result["sub"] == "118234567890"
        assert result["email"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_fetch_userinfo_failure(self, strategy):
        """fetch_userinfo returns None on non-200 response."""
        mock_resp = AsyncMock()
        mock_resp.status = 401

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession", return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_session),
            __aexit__=AsyncMock(return_value=False),
        )):
            result = await strategy.fetch_userinfo("expired-token")

        assert result is None


# ---------------------------------------------------------------------------
# handle_callback tests
# ---------------------------------------------------------------------------

class TestHandleCallback:
    """Tests for the full callback handling flow."""

    @pytest.mark.asyncio
    async def test_handle_callback_success(
        self, strategy, session, mock_token_response, mock_userinfo
    ):
        """Full callback flow populates session correctly."""
        # Set up a pending state
        strategy._store_state("valid-state", "code-verifier-abc")

        with (
            patch.object(
                strategy, "exchange_code",
                new_callable=AsyncMock,
                return_value=mock_token_response,
            ),
            patch.object(
                strategy, "fetch_userinfo",
                new_callable=AsyncMock,
                return_value=mock_userinfo,
            ),
        ):
            result = await strategy.handle_callback(
                {"code": "auth-code-123", "state": "valid-state"},
                session,
            )

        assert result is True
        assert session.authenticated is True
        assert session.nav_user_id == "118234567890"
        assert session.nav_display_name == "Test User"
        assert session.nav_email == "user@example.com"
        assert session.oauth2_access_token == "ya29.a0AfB_test"
        assert session.oauth2_id_token == "eyJhbGciOiJSUzI1NiJ9.test"
        assert session.oauth2_provider == "google"

    @pytest.mark.asyncio
    async def test_handle_callback_missing_code(self, strategy, session):
        """Returns False when code is missing."""
        result = await strategy.handle_callback(
            {"state": "s"}, session
        )
        assert result is False
        assert session.authenticated is False

    @pytest.mark.asyncio
    async def test_handle_callback_missing_state(self, strategy, session):
        """Returns False when state is missing."""
        result = await strategy.handle_callback(
            {"code": "c"}, session
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_callback_invalid_state(self, strategy, session):
        """Returns False when state doesn't match any pending state."""
        strategy._store_state("real-state", "verifier")

        result = await strategy.handle_callback(
            {"code": "c", "state": "wrong-state"}, session
        )
        assert result is False
        assert session.authenticated is False

    @pytest.mark.asyncio
    async def test_handle_callback_token_exchange_fails(
        self, strategy, session
    ):
        """Returns False when token exchange fails."""
        strategy._store_state("s", "v")

        with patch.object(
            strategy, "exchange_code",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await strategy.handle_callback(
                {"code": "c", "state": "s"}, session
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_handle_callback_userinfo_fails(self, strategy, session):
        """Returns False when userinfo fetch fails."""
        strategy._store_state("s", "v")

        with (
            patch.object(
                strategy, "exchange_code",
                new_callable=AsyncMock,
                return_value={"access_token": "tok", "id_token": "id"},
            ),
            patch.object(
                strategy, "fetch_userinfo",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await strategy.handle_callback(
                {"code": "c", "state": "s"}, session
            )

        assert result is False


# ---------------------------------------------------------------------------
# validate_token and session expiry tests
# ---------------------------------------------------------------------------

class TestTokenValidation:
    """Tests for token validation and session TTL."""

    @pytest.mark.asyncio
    async def test_validate_token_non_empty(self, strategy):
        """Non-empty token is valid."""
        assert await strategy.validate_token("some-token") is True

    @pytest.mark.asyncio
    async def test_validate_token_empty(self, strategy):
        """Empty token is invalid."""
        assert await strategy.validate_token("") is False

    def test_session_not_expired_within_ttl(self, strategy, session):
        """Session within 7-day TTL is not expired."""
        session.authenticated = True
        session.authenticated_at = datetime.now() - timedelta(days=6)
        assert strategy.is_session_expired(session) is False

    def test_session_expired_after_ttl(self, strategy, session):
        """Session older than 7 days is expired."""
        session.authenticated = True
        session.authenticated_at = datetime.now() - timedelta(days=8)
        assert strategy.is_session_expired(session) is True

    def test_session_expired_when_not_authenticated(self, strategy, session):
        """Unauthenticated session is considered expired."""
        assert strategy.is_session_expired(session) is True

    def test_session_expired_when_no_timestamp(self, strategy, session):
        """Session without authenticated_at is considered expired."""
        session.authenticated = True
        session.authenticated_at = None
        assert strategy.is_session_expired(session) is True
