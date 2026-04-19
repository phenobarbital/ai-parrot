"""Unit tests for AzureAuthStrategy.

Tests cover:
- Initialization and field storage
- build_login_keyboard: URL construction, missing page_url error
- handle_callback: success with user_id, sub claim, first/last name
- handle_callback: missing token, invalid JWT, missing user_id
- _decode_jwt_payload: valid JWT, padding handling, invalid format
- validate_token: delegates to NavigatorAuthClient
"""
import base64
import json
import pytest

from parrot.integrations.telegram.auth import AzureAuthStrategy, TelegramUserSession


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
def strategy():
    """AzureAuthStrategy with all fields configured."""
    return AzureAuthStrategy(
        auth_url="https://nav.example.com/api/v1/auth/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        login_page_url="https://static.example.com/telegram/azure_login.html",
    )


@pytest.fixture
def session():
    """Fresh TelegramUserSession."""
    return TelegramUserSession(telegram_id=12345)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestAzureAuthStrategyInit:
    def test_init_stores_auth_url(self, strategy):
        assert strategy.auth_url == "https://nav.example.com/api/v1/auth/login"

    def test_init_stores_azure_auth_url(self, strategy):
        assert strategy.azure_auth_url == "https://nav.example.com/api/v1/auth/azure/"

    def test_init_stores_login_page_url(self, strategy):
        assert strategy.login_page_url == "https://static.example.com/telegram/azure_login.html"

    def test_init_creates_nav_client(self, strategy):
        assert strategy._client is not None

    def test_init_sets_logger(self, strategy):
        assert strategy.logger is not None


# ---------------------------------------------------------------------------
# build_login_keyboard
# ---------------------------------------------------------------------------

class TestBuildLoginKeyboard:
    @pytest.mark.asyncio
    async def test_keyboard_has_webapp_button(self, strategy):
        config = type("Cfg", (), {"login_page_url": None})()
        kb = await strategy.build_login_keyboard(config, "state123")
        assert kb.keyboard
        assert len(kb.keyboard) == 1
        button = kb.keyboard[0][0]
        assert button.web_app is not None

    @pytest.mark.asyncio
    async def test_keyboard_url_contains_azure_auth_url_param(self, strategy):
        config = type("Cfg", (), {"login_page_url": None})()
        kb = await strategy.build_login_keyboard(config, "state123")
        button = kb.keyboard[0][0]
        assert "azure_auth_url=" in button.web_app.url

    @pytest.mark.asyncio
    async def test_keyboard_url_contains_login_page(self, strategy):
        config = type("Cfg", (), {"login_page_url": None})()
        kb = await strategy.build_login_keyboard(config, "state123")
        button = kb.keyboard[0][0]
        assert "azure_login.html" in button.web_app.url

    @pytest.mark.asyncio
    async def test_keyboard_uses_config_login_page_as_fallback(self):
        s = AzureAuthStrategy(
            auth_url="https://x.com",
            azure_auth_url="https://x.com/azure/",
        )
        config = type("Cfg", (), {"login_page_url": "https://fallback.com/azure_login.html"})()
        kb = await s.build_login_keyboard(config, "state")
        button = kb.keyboard[0][0]
        assert "fallback.com" in button.web_app.url

    @pytest.mark.asyncio
    async def test_keyboard_no_page_url_raises_value_error(self):
        s = AzureAuthStrategy(
            auth_url="https://x.com",
            azure_auth_url="https://x.com/azure/",
        )
        config = type("Cfg", (), {"login_page_url": None})()
        with pytest.raises(ValueError, match="login_page_url"):
            await s.build_login_keyboard(config, "state")

    @pytest.mark.asyncio
    async def test_keyboard_resize_and_one_time(self, strategy):
        config = type("Cfg", (), {"login_page_url": None})()
        kb = await strategy.build_login_keyboard(config, "state")
        assert kb.resize_keyboard is True
        assert kb.one_time_keyboard is True


# ---------------------------------------------------------------------------
# handle_callback
# ---------------------------------------------------------------------------

class TestHandleCallback:
    @pytest.mark.asyncio
    async def test_success_with_user_id_claim(self, strategy, session):
        token = _make_jwt({"user_id": "42", "email": "a@b.com", "name": "Alice"})
        result = await strategy.handle_callback(
            {"auth_method": "azure", "token": token}, session
        )
        assert result is True
        assert session.authenticated is True
        assert session.nav_user_id == "42"
        assert session.nav_email == "a@b.com"
        assert session.nav_display_name == "Alice"
        assert session.nav_session_token == token

    @pytest.mark.asyncio
    async def test_success_with_sub_claim(self, strategy, session):
        token = _make_jwt({
            "sub": "99",
            "email": "b@c.com",
            "first_name": "Bob",
            "last_name": "Smith",
        })
        result = await strategy.handle_callback(
            {"auth_method": "azure", "token": token}, session
        )
        assert result is True
        assert session.nav_user_id == "99"
        assert session.nav_display_name == "Bob Smith"

    @pytest.mark.asyncio
    async def test_missing_token_returns_false(self, strategy, session):
        result = await strategy.handle_callback({"auth_method": "azure"}, session)
        assert result is False
        assert not session.authenticated

    @pytest.mark.asyncio
    async def test_empty_token_returns_false(self, strategy, session):
        result = await strategy.handle_callback(
            {"auth_method": "azure", "token": ""}, session
        )
        assert result is False
        assert not session.authenticated

    @pytest.mark.asyncio
    async def test_invalid_jwt_format_returns_false(self, strategy, session):
        result = await strategy.handle_callback(
            {"auth_method": "azure", "token": "not.a.valid.jwt.format.extra"},
            session,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_two_part_jwt_returns_false(self, strategy, session):
        result = await strategy.handle_callback(
            {"auth_method": "azure", "token": "onlytwo.parts"},
            session,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_jwt_missing_user_id_and_sub_returns_false(self, strategy, session):
        token = _make_jwt({"email": "a@b.com", "name": "No ID"})
        result = await strategy.handle_callback(
            {"auth_method": "azure", "token": token}, session
        )
        assert result is False
        assert not session.authenticated

    @pytest.mark.asyncio
    async def test_user_id_takes_precedence_over_sub(self, strategy, session):
        token = _make_jwt({"user_id": "uid-1", "sub": "sub-2", "email": "x@y.com"})
        result = await strategy.handle_callback(
            {"auth_method": "azure", "token": token}, session
        )
        assert result is True
        assert session.nav_user_id == "uid-1"


# ---------------------------------------------------------------------------
# _decode_jwt_payload
# ---------------------------------------------------------------------------

class TestDecodeJwtPayload:
    def test_decode_valid_jwt_returns_claims(self):
        claims = {"user_id": "1", "email": "test@test.com"}
        token = _make_jwt(claims)
        decoded = AzureAuthStrategy._decode_jwt_payload(token)
        assert decoded["user_id"] == "1"
        assert decoded["email"] == "test@test.com"

    def test_decode_handles_base64_padding(self):
        """Different payload lengths require different padding amounts."""
        for i in range(4):
            # Create payloads of varying lengths to exercise padding paths
            claims = {"a": "x" * i}
            token = _make_jwt(claims)
            decoded = AzureAuthStrategy._decode_jwt_payload(token)
            assert decoded["a"] == "x" * i

    def test_two_parts_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid JWT"):
            AzureAuthStrategy._decode_jwt_payload("onlytwoparts.here")

    def test_one_part_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid JWT"):
            AzureAuthStrategy._decode_jwt_payload("onlyonepart")

    def test_non_json_payload_raises_json_decode_error(self):
        bad = (
            "header."
            + base64.urlsafe_b64encode(b"not-json-payload").rstrip(b"=").decode()
            + ".sig"
        )
        with pytest.raises(json.JSONDecodeError):
            AzureAuthStrategy._decode_jwt_payload(bad)

    def test_decode_navigator_style_jwt(self):
        """Matches the Navigator JWT format from the spec."""
        claims = {
            "user_id": "12345",
            "email": "user@company.com",
            "first_name": "Test",
            "last_name": "User",
            "sub": "12345",
            "iss": "navigator-auth",
            "exp": 9999999999,
        }
        token = _make_jwt(claims)
        decoded = AzureAuthStrategy._decode_jwt_payload(token)
        assert decoded["user_id"] == "12345"
        assert decoded["email"] == "user@company.com"
        assert decoded["iss"] == "navigator-auth"


# ---------------------------------------------------------------------------
# validate_token
# ---------------------------------------------------------------------------

class TestValidateToken:
    @pytest.mark.asyncio
    async def test_validates_non_empty_token(self, strategy):
        result = await strategy.validate_token("some.valid.token")
        assert result is True

    @pytest.mark.asyncio
    async def test_rejects_empty_token(self, strategy):
        result = await strategy.validate_token("")
        assert result is False
