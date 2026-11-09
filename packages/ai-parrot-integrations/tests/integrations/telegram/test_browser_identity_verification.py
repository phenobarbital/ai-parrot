"""FEAT-854: browser identity verification with real Navigator-issued tokens."""

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from aiogram.types import ReplyKeyboardRemove

from parrot.integrations.telegram.browser_login import (
    BrowserLoginEntry,
    BrowserVerificationError,
    BrowserVerifierUnavailableError,
    VerifiedBrowserIdentity,
    get_browser_identity_verifier,
    register_browser_identity_verifier,
)
from parrot.integrations.telegram.browser_verifiers import (
    NavigatorJWTVerifier,
    ensure_navigator_browser_verifiers,
)
from parrot.integrations.telegram.auth import CompositeAuthStrategy, TelegramUserSession
from parrot.integrations.telegram.models import PostAuthAction, TelegramAgentConfig
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

TEST_KEY = "feat-854-contract-test-key-0123456789abcdef"


@pytest.fixture
def issuer(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Return a real IdentityProvider configured with a known test key."""
    monkeypatch.setattr("navigator_auth.backends.idp.SECRET_KEY", TEST_KEY)
    from navigator_auth.backends.idp import IdentityProvider

    return IdentityProvider()


def _mint(idp: Any, **claims: Any) -> str:
    token, _refresh, _exp, _scheme = idp.create_token(data={"session_id": "s-1", **claims})
    return token


async def test_browser_mode_real_verifier_contract(issuer: Any) -> None:
    """Issuer-produced basic and SSO tokens verify to authoritative identity."""
    verifier = NavigatorJWTVerifier(idp=issuer)

    basic = await verifier.verify(
        _mint(issuer, user_id=42, username="alice"),
        auth_method="basic",
        bot_id="7001",
        tenant_id=None,
    )
    azure = await verifier.verify(
        _mint(
            issuer,
            user_id="azure-42",
            username="alice",
            name="Alice Example",
            email="alice@example.test",
            auth_method="azure",
        ),
        auth_method="azure",
        bot_id="7001",
        tenant_id=None,
    )

    assert basic.user_id == "42"
    assert basic.display_name is None
    assert basic.email is None
    assert azure.user_id == "azure-42"
    assert azure.display_name == "Alice Example"
    assert azure.email == "alice@example.test"


async def test_browser_sso_rejects_invalid_tokens(issuer: Any) -> None:
    """Forged or context-inappropriate credentials fail closed."""
    from navigator_auth.conf import AUTH_TOKEN_ISSUER

    now = int(time.time())
    base_claims = {
        "exp": now + 300,
        "iat": now,
        "iss": AUTH_TOKEN_ISSUER,
        "session_id": "s-1",
        "user_id": "42",
        "auth_method": "azure",
    }
    forged = jwt.encode(base_claims, "different-signing-key-0123456789abcdef", algorithm="HS256")
    unsigned = jwt.encode(base_claims, key="", algorithm="none")
    valid = _mint(issuer, user_id="42", auth_method="azure")
    header, payload, signature = valid.split(".")
    replacement = "A" if payload[-1] != "A" else "B"
    tampered = ".".join((header, payload[:-1] + replacement, signature))
    expired = jwt.encode({**base_claims, "exp": now - 120}, TEST_KEY, algorithm="HS256")
    wrong_issuer, _refresh, _exp, _scheme = issuer.create_token(
        data={"session_id": "s-1", "user_id": "42", "auth_method": "azure"},
        issuer="urn:Other",
    )
    audience_token, _refresh, _exp, _scheme = issuer.create_token(
        data={"session_id": "s-1", "user_id": "42", "auth_method": "azure"},
        audience="app",
    )
    invalid_cases = [
        (forged, "azure", None),
        (unsigned, "azure", None),
        (tampered, "azure", None),
        (expired, "azure", None),
        (wrong_issuer, "azure", None),
        (audience_token, "azure", None),
        (_mint(issuer, auth_method="azure"), "azure", None),
        (f"other:{valid}", "azure", "acme"),
        (f"other:{valid}", "azure", None),
        (_mint(issuer, user_id="42", auth_method="azure"), "google", None),
        (_mint(issuer, user_id="42", auth_method="basic"), "azure", None),
        (_mint(issuer, user_id="42", auth_method="azure"), "basic", None),
        ("", "azure", None),
        (None, "azure", None),
    ]

    for token, auth_method, tenant_id in invalid_cases:
        with pytest.raises(BrowserVerificationError):
            await NavigatorJWTVerifier(idp=issuer, tenant_id=tenant_id).verify(
                token,
                auth_method=auth_method,
                bot_id="7001",
                tenant_id=tenant_id,
            )


async def test_browser_verifier_unavailable_maps_to_503() -> None:
    """Navigator provider/configuration errors map to verifier unavailable."""
    from navigator_auth.exceptions import AuthException

    class UnavailableIdentityProvider:
        def decode_token(self, token: str, *, issuer: str) -> None:
            raise AuthException("provider unavailable", status=501)

    token = jwt.encode(
        {"exp": int(time.time()) + 300, "iss": "ignored", "user_id": "42"},
        TEST_KEY,
        algorithm="HS256",
    )
    verifier = NavigatorJWTVerifier(idp=UnavailableIdentityProvider())

    with pytest.raises(BrowserVerifierUnavailableError):
        await verifier.verify(token, auth_method="basic", bot_id="7001", tenant_id=None)


def test_ensure_verifiers_respects_host_and_key_material(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default wiring preserves host verifiers and reports missing page methods."""
    from parrot.integrations.telegram import browser_verifiers

    host_verifier = object()
    app: dict[str, Any] = {
        "telegram_browser_identity_verifiers": {"7001": {"basic": host_verifier}},
    }
    methods = ["google", "oauth2", "basic", "azure"]
    monkeypatch.setattr(browser_verifiers, "navigator_key_material_configured", lambda: False)

    missing = ensure_navigator_browser_verifiers(app, bot_id="7001", methods=methods, tenant_id="acme")

    assert missing == ["azure", "google"]
    assert get_browser_identity_verifier(app, bot_id="7001", auth_method="basic") is host_verifier

    monkeypatch.setattr(browser_verifiers, "navigator_key_material_configured", lambda: True)
    missing = ensure_navigator_browser_verifiers(app, bot_id="7001", methods=methods, tenant_id="acme")

    assert missing == []
    assert get_browser_identity_verifier(app, bot_id="7001", auth_method="basic") is host_verifier
    assert isinstance(get_browser_identity_verifier(app, bot_id="7001", auth_method="azure"), NavigatorJWTVerifier)
    assert isinstance(get_browser_identity_verifier(app, bot_id="7001", auth_method="google"), NavigatorJWTVerifier)
    assert get_browser_identity_verifier(app, bot_id="7001", auth_method="oauth2") is None


def _wrapper(*, post_auth: bool = False) -> TelegramAgentWrapper:
    """Build a narrow wrapper double around authentication completion methods."""
    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.config = TelegramAgentConfig(
        name="bot",
        chatbot_id="bot",
        tenant="tenant-a",
        post_auth_actions=[PostAuthAction(provider="jira", required=True)] if post_auth else [],
    )
    wrapper.app = {}
    wrapper.bot = MagicMock()
    wrapper.bot.send_message = AsyncMock()
    wrapper.bot.send_chat_action = AsyncMock()
    wrapper.logger = MagicMock()
    wrapper._bot_id = "7001"
    wrapper._user_sessions = {}
    wrapper._persist_principal_link = AsyncMock(return_value=True)
    wrapper._initialize_user_context = AsyncMock()
    wrapper._is_combined_payload = MagicMock(return_value=False)
    wrapper._begin_login_attempt = AsyncMock()
    strategy = MagicMock()
    strategy.name = "basic"
    strategy.handle_callback = AsyncMock()
    wrapper._auth_strategy = strategy
    return wrapper


def _entry() -> BrowserLoginEntry:
    """Return browser correlation state owned by the server."""
    return BrowserLoginEntry(
        state="browser." + "a" * 43,
        telegram_id=88123,
        chat_id=88124,
        bot_id="7001",
        bot_username="bot",
        created_at=time.monotonic(),
    )


@pytest.mark.asyncio
async def test_complete_auth_payload_success_notifies_chat() -> None:
    """A successful legacy callback stores, links, initializes, and notifies once."""
    wrapper = _wrapper()

    async def authenticate(_data: dict[str, Any], session: TelegramUserSession) -> bool:
        session.set_authenticated("42", "token", "Alice")
        return True

    wrapper._auth_strategy.handle_callback.side_effect = authenticate

    assert await wrapper._complete_auth_payload({}, telegram_id=88123, chat_id=88124)

    assert wrapper._user_sessions[88123].nav_user_id == "42"
    wrapper._persist_principal_link.assert_awaited_once_with(wrapper._user_sessions[88123])
    wrapper._initialize_user_context.assert_awaited_once_with(wrapper._user_sessions[88123])
    assert wrapper.bot.send_message.await_args.kwargs["chat_id"] == 88124


@pytest.mark.asyncio
async def test_handle_web_app_data_delegates_to_complete() -> None:
    """Webview parsing delegates to the core while retaining its reply keyboard behavior."""
    wrapper = _wrapper()
    session = TelegramUserSession(telegram_id=88123, telegram_first_name="Alice")
    session.set_authenticated("42", "token", "Alice")
    wrapper._get_user_session = MagicMock(return_value=session)
    wrapper._complete_auth_payload = AsyncMock(return_value=True)
    message = MagicMock()
    message.web_app_data.data = '{"token": "token"}'
    message.from_user.id = 88123
    message.chat.id = 88124
    message.answer = AsyncMock()

    await wrapper.handle_web_app_data(message)

    wrapper._complete_auth_payload.assert_awaited_once_with(
        {"token": "token"}, telegram_id=88123, chat_id=88124, notify=False
    )
    assert isinstance(message.answer.await_args.kwargs["reply_markup"], ReplyKeyboardRemove)


@pytest.mark.asyncio
async def test_browser_basic_rejects_forged_identity() -> None:
    """Browser basic credentials never reach the trusting legacy callback."""
    wrapper = _wrapper()

    with pytest.raises(BrowserVerificationError):
        await wrapper._complete_auth_payload(
            {"auth_method": "basic", "user_id": "admin", "token": ""},
            telegram_id=88123,
            chat_id=88124,
            browser_entry=_entry(),
        )

    wrapper._auth_strategy.handle_callback.assert_not_awaited()
    assert wrapper._user_sessions == {}
    wrapper._persist_principal_link.assert_not_awaited()
    wrapper._initialize_user_context.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_identity_uses_verified_claims() -> None:
    """Payload identity claims must match verifier claims and are never authoritative."""
    wrapper = _wrapper()
    verifier = MagicMock()
    verifier.verify = AsyncMock(return_value=VerifiedBrowserIdentity(user_id="42", display_name="Alice"))
    register_browser_identity_verifier(wrapper.app, bot_id="7001", auth_method="basic", verifier=verifier)

    with pytest.raises(BrowserVerificationError):
        await wrapper._complete_auth_payload(
            {"auth_method": "basic", "user_id": "43", "token": "verified-token"},
            telegram_id=88123,
            chat_id=88124,
            browser_entry=_entry(),
        )
    assert await wrapper._complete_auth_payload(
        {"auth_method": "basic", "token": "verified-token"},
        telegram_id=88123,
        chat_id=88124,
        browser_entry=_entry(),
    )
    assert wrapper._user_sessions[88123].nav_user_id == "42"

    composite = CompositeAuthStrategy({"basic": wrapper._auth_strategy}, "https://example.test/login")
    wrapper._auth_strategy = composite
    with pytest.raises(BrowserVerificationError):
        await wrapper._complete_auth_payload(
            {"auth_method": "unknown", "token": "verified-token"},
            telegram_id=88123,
            chat_id=88124,
            browser_entry=_entry(),
        )


@pytest.mark.asyncio
async def test_browser_verifier_unavailable_fails_closed() -> None:
    """Missing or unavailable verifiers propagate typed errors without legacy fallback."""
    wrapper = _wrapper()
    with pytest.raises(BrowserVerifierUnavailableError):
        await wrapper._complete_auth_payload(
            {"auth_method": "basic", "token": "token"},
            telegram_id=88123,
            chat_id=88124,
            browser_entry=_entry(),
        )

    verifier = MagicMock()
    verifier.verify = AsyncMock(side_effect=BrowserVerifierUnavailableError("offline"))
    register_browser_identity_verifier(wrapper.app, bot_id="7001", auth_method="basic", verifier=verifier)
    with pytest.raises(BrowserVerifierUnavailableError):
        await wrapper._complete_auth_payload(
            {"auth_method": "basic", "token": "token"},
            telegram_id=88123,
            chat_id=88124,
            browser_entry=_entry(),
        )
    wrapper._auth_strategy.handle_callback.assert_not_awaited()
    assert wrapper._user_sessions == {}


@pytest.mark.asyncio
async def test_browser_mode_combined_post_auth() -> None:
    """Browser combined login stages a candidate with entry-owned chat correlation."""
    wrapper = _wrapper(post_auth=True)
    verifier = MagicMock()
    verifier.verify = AsyncMock(return_value=VerifiedBrowserIdentity(user_id="42", display_name="Alice"))
    register_browser_identity_verifier(wrapper.app, bot_id="7001", auth_method="basic", verifier=verifier)

    assert await wrapper._complete_auth_payload(
        {"auth_method": "basic", "token": "verified-token"},
        telegram_id=88123,
        chat_id=88124,
        browser_entry=_entry(),
    )

    candidate = wrapper._begin_login_attempt.await_args.args[0]
    assert candidate.nav_user_id == "42"
    assert wrapper._begin_login_attempt.await_args.kwargs["chat_id"] == 88124
    assert wrapper._user_sessions == {}
