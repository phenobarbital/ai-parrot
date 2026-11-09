"""FEAT-854: browser-mode login registry, state format, verifier contract and pages."""

import time
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from pydantic import ValidationError

from parrot.integrations.telegram.browser_login import (
    BROWSER_LOGIN_APP_KEY,
    BROWSER_COMPLETE_PATH,
    TELEGRAM_WRAPPERS_APP_KEY,
    BrowserLoginEntry,
    BrowserLoginRegistry,
    BrowserVerificationError,
    BrowserVerifierUnavailableError,
    VerifiedBrowserIdentity,
    get_or_create_browser_login_registry,
    get_browser_identity_verifier,
    is_browser_state,
    new_browser_state,
    register_browser_identity_verifier,
    render_browser_error,
    render_browser_success,
    setup_browser_auth_routes,
    telegram_deep_link,
)

def _entry(state: str, created_at: float | None = None) -> BrowserLoginEntry:
    return BrowserLoginEntry(
        state=state,
        telegram_id=1,
        chat_id=1,
        bot_id="7001",
        bot_username="parrot_test_bot",
        created_at=time.monotonic() if created_at is None else created_at,
    )


def test_new_browser_state_format() -> None:
    state = new_browser_state()
    assert is_browser_state(state) and len(state) == len("browser.") + 43


def test_registry_register_consume_single_use() -> None:
    registry = BrowserLoginRegistry()
    entry = _entry(new_browser_state())

    registry.register(entry)

    assert registry.consume(entry.state) is entry
    assert registry.consume(entry.state) is None


def test_registry_register_supersedes_older_state_for_same_chat() -> None:
    registry = BrowserLoginRegistry()
    first, second = new_browser_state(), new_browser_state()
    registry.register(_entry(first))
    registry.register(_entry(second))
    assert registry.peek(first) is None
    assert registry.consume(second) is not None


def test_registry_ttl_expiry() -> None:
    registry = BrowserLoginRegistry()
    expired = _entry(new_browser_state(), created_at=time.monotonic() - 601)

    registry.register(expired)

    assert registry.peek(expired.state) is None
    assert registry.consume(expired.state) is None


def test_registry_rejects_non_browser_state() -> None:
    registry = BrowserLoginRegistry()

    with pytest.raises(ValueError):
        registry.register(_entry(new_browser_state().removeprefix("browser.")))


def test_registry_accessor_is_app_scoped() -> None:
    app: dict[str, object] = {}

    first = get_or_create_browser_login_registry(app)
    second = get_or_create_browser_login_registry(app)

    assert first is second
    assert app[BROWSER_LOGIN_APP_KEY] is first


def test_verifier_registry_lookup() -> None:
    class DummyVerifier:
        async def verify(
            self,
            token: str,
            *,
            auth_method: str,
            bot_id: str,
            tenant_id: str | None,
        ) -> VerifiedBrowserIdentity:
            return VerifiedBrowserIdentity(user_id=token)

    app: dict[str, object] = {}
    verifier = DummyVerifier()
    register_browser_identity_verifier(app, bot_id="7001", auth_method="basic", verifier=verifier)

    assert get_browser_identity_verifier(app, bot_id="7001", auth_method="basic") is verifier
    assert get_browser_identity_verifier(app, bot_id="7002", auth_method="basic") is None
    assert get_browser_identity_verifier(app, bot_id="7001", auth_method="azure") is None
    assert get_browser_identity_verifier(None, bot_id="7001", auth_method="basic") is None
    with pytest.raises(ValueError):
        register_browser_identity_verifier(app, bot_id="7001", auth_method="oauth2", verifier=verifier)


def test_verified_identity_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        VerifiedBrowserIdentity(user_id="1", verified=True)


def test_success_page_has_deep_link_and_escapes() -> None:
    page = render_browser_success("parrot_test_bot", "<b>x</b>")

    assert "https://t.me/parrot_test_bot" in page
    assert "<b>" not in page
    assert "&lt;b&gt;x&lt;/b&gt;" in page
    assert telegram_deep_link("bad name!") is None


def test_error_page_escapes_message() -> None:
    page = render_browser_error("<script>")

    assert "&lt;script&gt;" in page
    assert "<script>" not in page


@pytest_asyncio.fixture
async def browser_client():
    """Provide an app with the browser completion endpoint mounted."""
    app = web.Application()
    setup_browser_auth_routes(app)
    async with TestClient(TestServer(app)) as client:
        yield app, client


def _register(app: web.Application, *, created_at: float | None = None) -> BrowserLoginEntry:
    """Register and return a fresh server-owned browser-login entry."""
    entry = _entry(new_browser_state(), created_at=created_at)
    get_or_create_browser_login_registry(app).register(entry)
    return entry


def _wrapper(*, result: object = True) -> object:
    """Return a minimal wrapper double for endpoint delegation assertions."""
    wrapper = type("BrowserWrapper", (), {})()
    wrapper._complete_auth_payload = AsyncMock(return_value=result)
    return wrapper


async def test_browser_complete_handler_unknown_state_410(browser_client) -> None:
    """Unknown, non-browser, and expired states are rejected before delegation."""
    app, client = browser_client
    wrapper = _wrapper()
    app[TELEGRAM_WRAPPERS_APP_KEY] = {"7001": wrapper}
    expired = _register(app, created_at=time.monotonic() - 601)

    for state in (new_browser_state(), "legacy-state", expired.state):
        response = await client.post(BROWSER_COMPLETE_PATH, json={"state": state, "token": "secret"})
        assert response.status == 410
        assert await response.json() == {"ok": False, "error": "expired"}
    wrapper._complete_auth_payload.assert_not_awaited()


async def test_browser_complete_handler_success(browser_client) -> None:
    """A valid state delegates once using server-owned Telegram identifiers."""
    app, client = browser_client
    entry = _register(app)
    wrapper = _wrapper()
    app[TELEGRAM_WRAPPERS_APP_KEY] = {entry.bot_id: wrapper}

    response = await client.post(
        BROWSER_COMPLETE_PATH,
        json={
            "state": entry.state,
            "auth_method": "basic",
            "token": "secret-token",
            "chat_id": 999,
            "telegram_id": 888,
            "bot_id": "untrusted",
            "browser_entry": "untrusted",
            "verified": True,
        },
    )

    assert response.status == 200
    assert await response.json() == {"ok": True, "redirect_url": "https://t.me/parrot_test_bot"}
    wrapper._complete_auth_payload.assert_awaited_once_with(
        {"auth_method": "basic", "token": "secret-token"},
        telegram_id=entry.telegram_id,
        chat_id=entry.chat_id,
        browser_entry=entry,
    )
    replay = await client.post(BROWSER_COMPLETE_PATH, json={"state": entry.state, "token": "secret-token"})
    assert replay.status == 410


async def test_browser_complete_handler_error_mapping(browser_client) -> None:
    """Malformed, rejected, unavailable, and missing-wrapper requests are mapped safely."""
    app, client = browser_client
    wrapper = _wrapper()
    app[TELEGRAM_WRAPPERS_APP_KEY] = {"7001": wrapper}

    for kwargs in ({"data": "not-json"}, {"json": []}, {"json": {}}):
        response = await client.post(BROWSER_COMPLETE_PATH, **kwargs)
        assert response.status == 400
        assert await response.json() == {"ok": False, "error": "bad_request"}

    rejected = _register(app)
    wrapper._complete_auth_payload.side_effect = BrowserVerificationError("bad token")
    response = await client.post(
        BROWSER_COMPLETE_PATH, json={"state": rejected.state, "auth_method": "basic", "token": "secret-token"}
    )
    assert response.status == 401
    assert "secret-token" not in await response.text()

    false_result = _register(app)
    wrapper._complete_auth_payload.side_effect = None
    wrapper._complete_auth_payload.return_value = False
    response = await client.post(BROWSER_COMPLETE_PATH, json={"state": false_result.state, "token": "secret-token"})
    assert response.status == 401

    invalid_method = _register(app)
    response = await client.post(
        BROWSER_COMPLETE_PATH, json={"state": invalid_method.state, "auth_method": "oauth2", "token": "secret-token"}
    )
    assert response.status == 401

    invalid_method_shape = _register(app)
    response = await client.post(
        BROWSER_COMPLETE_PATH,
        json={"state": invalid_method_shape.state, "auth_method": ["basic"], "token": "secret-token"},
    )
    assert response.status == 401

    unavailable = _register(app)
    wrapper._complete_auth_payload.side_effect = BrowserVerifierUnavailableError("down")
    response = await client.post(BROWSER_COMPLETE_PATH, json={"state": unavailable.state, "token": "secret-token"})
    assert response.status == 503

    no_wrapper = _register(app)
    app[TELEGRAM_WRAPPERS_APP_KEY] = {}
    response = await client.post(BROWSER_COMPLETE_PATH, json={"state": no_wrapper.state, "token": "secret-token"})
    assert response.status == 503


async def test_setup_browser_auth_routes_idempotent() -> None:
    """Repeated setup registers a single POST completion route."""
    app = web.Application()

    setup_browser_auth_routes(app)
    setup_browser_auth_routes(app)

    matching = [resource for resource in app.router.resources() if resource.canonical == BROWSER_COMPLETE_PATH]
    assert len(matching) == 1
    assert {route.method for route in matching[0]} == {"POST"}


async def test_browser_mode_full_flow_basic(browser_client) -> None:
    """The endpoint passes a basic browser payload through one successful completion call."""
    app, client = browser_client
    entry = _register(app)
    wrapper = _wrapper(result=True)
    app[TELEGRAM_WRAPPERS_APP_KEY] = {entry.bot_id: wrapper}

    response = await client.post(
        BROWSER_COMPLETE_PATH,
        json={"state": entry.state, "auth_method": "basic", "token": "verified-token"},
    )

    assert response.status == 200
    wrapper._complete_auth_payload.assert_awaited_once_with(
        {"auth_method": "basic", "token": "verified-token"},
        telegram_id=entry.telegram_id,
        chat_id=entry.chat_id,
        browser_entry=entry,
    )


from pathlib import Path

_WIKI_PAGE = Path(__file__).resolve().parents[5] / "wiki/integrations/telegram-auth-open-mode.md"


def test_wiki_page_documents_browser_mode():
    """The operator page names every knob and failure mode of browser mode."""
    text = _WIKI_PAGE.read_text(encoding="utf-8")
    for needle in (
        "auth_open_mode",
        "public_base_url",
        "/api/auth/telegram/browser-complete",
        "telegram_browser_identity_verifiers",
        "AUTH_SECRET_KEY",
        "parrot-browser-complete-origins",
        "browser.",
        "410",
        "Wayland",
    ):
        assert needle in text, needle
