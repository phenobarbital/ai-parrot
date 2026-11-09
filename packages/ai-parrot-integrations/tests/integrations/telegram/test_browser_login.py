"""FEAT-854: browser-mode login registry, state format, verifier contract and pages."""

import time

import pytest
from pydantic import ValidationError

from parrot.integrations.telegram.browser_login import (
    BROWSER_LOGIN_APP_KEY,
    BrowserLoginEntry,
    BrowserLoginRegistry,
    VerifiedBrowserIdentity,
    get_browser_identity_verifier,
    get_or_create_browser_login_registry,
    is_browser_state,
    new_browser_state,
    register_browser_identity_verifier,
    render_browser_error,
    render_browser_success,
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
