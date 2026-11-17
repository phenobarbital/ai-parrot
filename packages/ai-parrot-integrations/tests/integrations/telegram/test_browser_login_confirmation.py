"""FEAT-906: a forwarded browser login link cannot activate the initiating Telegram identity."""

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.integrations.telegram.auth import TelegramUserSession
from parrot.integrations.telegram.browser_login import (
    TELEGRAM_WRAPPERS_APP_KEY,
    BrowserLoginEntry,
    BrowserLoginRegistry,
    BrowserVerificationError,
    VerifiedBrowserIdentity,
    browser_complete_handler,
    get_or_create_browser_login_registry,
    new_browser_state,
    register_browser_identity_verifier,
    render_browser_confirmation,
)
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper


def _entry(*, bot_id: str = "7001", user_id: int = 11, chat_id: int = 11) -> BrowserLoginEntry:
    return BrowserLoginEntry(new_browser_state(), user_id, chat_id, bot_id, "test_bot", time.monotonic())


def _message(text: str, *, user_id: int = 11, chat_id: int = 11) -> Any:
    return SimpleNamespace(
        text=text,
        chat=SimpleNamespace(id=chat_id),
        from_user=SimpleNamespace(id=user_id, username="initiator", first_name="Initiator", last_name=None),
        answer=AsyncMock(),
    )


def _wrapper(*, post_auth: bool = False) -> TelegramAgentWrapper:
    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.config = SimpleNamespace(
        auth_open_mode="browser", tenant=None, post_auth_actions=[object()] if post_auth else [], auth_methods=["basic"]
    )
    wrapper.app = web.Application()
    wrapper.app[TELEGRAM_WRAPPERS_APP_KEY] = {"7001": wrapper}
    wrapper._bot_id = "7001"
    wrapper._user_sessions = {}
    wrapper._login_coordinator = None
    wrapper.logger = MagicMock()
    wrapper.bot = SimpleNamespace(send_message=AsyncMock())
    wrapper._typing_indicator = AsyncMock()
    wrapper._persist_principal_link = AsyncMock(return_value=True)
    wrapper._initialize_user_context = AsyncMock()
    wrapper._begin_login_attempt = AsyncMock()
    wrapper._is_authorized = MagicMock(return_value=True)
    wrapper._is_combined_payload = MagicMock(return_value=False)
    wrapper._get_bot_username = AsyncMock(return_value="test_bot")
    wrapper._identity_service = MagicMock(return_value=None)
    wrapper._auth_strategy = SimpleNamespace(
        name="basic", handle_callback=AsyncMock(), build_login_keyboard=AsyncMock(return_value=None)
    )
    verifier = SimpleNamespace(
        verify=AsyncMock(return_value=VerifiedBrowserIdentity(user_id="victim-42", display_name="Victim"))
    )
    register_browser_identity_verifier(wrapper.app, bot_id="7001", auth_method="basic", verifier=verifier)
    return wrapper


async def _post(wrapper: TelegramAgentWrapper, entry: BrowserLoginEntry) -> web.Response:
    request = make_mocked_request("POST", "/api/auth/telegram/browser-complete", app=wrapper.app)
    request.json = AsyncMock(return_value={"state": entry.state, "auth_method": "basic", "token": "victim-credential"})
    return await browser_complete_handler(request)


async def _prepare(wrapper: TelegramAgentWrapper) -> tuple[BrowserLoginEntry, str]:
    registry = get_or_create_browser_login_registry(wrapper.app)
    entry = _entry()
    registry.register(entry)
    response = await _post(wrapper, entry)
    assert response.status == 202
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    body = json.loads(response.text)
    assert body["pending_confirmation"] is True
    assert "victim-credential" not in response.text
    return entry, body["confirmation_code"]


@pytest.mark.asyncio
async def test_forwarded_link_does_not_authenticate_initiator() -> None:
    wrapper = _wrapper()
    entry, code = await _prepare(wrapper)
    assert wrapper._user_sessions == {}
    wrapper.bot.send_message.assert_not_awaited()
    wrapper._persist_principal_link.assert_not_awaited()
    wrapper._initialize_user_context.assert_not_awaited()
    assert code not in entry.state and len(code) == 22

    for text in (f"/login {entry.state}", "/login guessed-code"):
        await wrapper.handle_login(_message(text))
        assert not wrapper._user_sessions[11].authenticated

    for user_id, chat_id in ((12, 11), (11, 12)):
        await wrapper.handle_login(_message(f"/login {code}", user_id=user_id, chat_id=chat_id))
        assert not wrapper._user_sessions[11].authenticated

    await wrapper.handle_login(_message(f"/login {code}"))
    assert wrapper._user_sessions[11].nav_user_id == "victim-42"
    wrapper._persist_principal_link.assert_awaited_once()
    wrapper._initialize_user_context.assert_awaited_once()
    wrapper.bot.send_message.assert_awaited_once()
    assert code not in str(wrapper.bot.send_message.await_args)
    await wrapper.handle_login(_message(f"/login {code}"))
    wrapper._persist_principal_link.assert_awaited_once()


def test_registry_binding_replay_and_private_candidate() -> None:
    registry = BrowserLoginRegistry()
    entry = _entry()
    registry.register(entry)
    registry.consume(entry.state)
    candidate = TelegramUserSession(telegram_id=11)
    candidate.set_authenticated("victim", "secret-credential")
    code = registry.stage(entry, candidate, requires_post_auth=False)
    assert code not in registry._confirmations
    pending = next(iter(registry._confirmations.values()))
    assert "secret-credential" not in repr(pending)
    assert "secret-credential" not in str(pending.model_dump())
    assert registry.confirm(code, bot_id="other", telegram_id=11, chat_id=11) is None
    assert registry.confirm(code, bot_id="7001", telegram_id=12, chat_id=11) is None
    assert registry.confirm(code, bot_id="7001", telegram_id=11, chat_id=12) is None
    assert registry.confirm(code, bot_id="7001", telegram_id=11, chat_id=11).candidate is candidate
    assert registry.confirm(code, bot_id="7001", telegram_id=11, chat_id=11) is None


def test_confirmation_expiry_and_restart_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    now = time.monotonic()
    monkeypatch.setattr("parrot.integrations.telegram.browser_login.time.monotonic", lambda: now)
    registry = BrowserLoginRegistry(ttl_seconds=10)
    entry = _entry()
    registry.register(entry)
    registry.consume(entry.state)
    now += 9
    code = registry.stage(entry, object(), requires_post_auth=False)
    assert BrowserLoginRegistry().confirm(code, bot_id="7001", telegram_id=11, chat_id=11) is None
    now += 1
    assert registry.confirm(code, bot_id="7001", telegram_id=11, chat_id=11) is None
    assert not registry._confirmations and not registry._attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/login", "/logout"])
async def test_cancellation_invalidates_staged_code(command: str, monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = _wrapper()
    monkeypatch.setattr("parrot.integrations.telegram.wrapper.principal_for_session", AsyncMock(return_value=None))
    _, code = await _prepare(wrapper)
    if command == "/login":
        await wrapper.handle_login(_message(command))
    else:
        await wrapper.handle_logout(_message(command))
    await wrapper.handle_login(_message(f"/login {code}"))
    assert not wrapper._user_sessions[11].authenticated
    wrapper._persist_principal_link.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/login", "/logout"])
async def test_cancellation_while_verifier_awaits(command: str, monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = _wrapper()
    monkeypatch.setattr("parrot.integrations.telegram.wrapper.principal_for_session", AsyncMock(return_value=None))
    entered, resume = asyncio.Event(), asyncio.Event()

    async def verify(*_args: Any, **_kwargs: Any) -> VerifiedBrowserIdentity:
        entered.set()
        await resume.wait()
        return VerifiedBrowserIdentity(user_id="victim")

    verifier = wrapper.app["telegram_browser_identity_verifiers"]["7001"]["basic"]
    verifier.verify.side_effect = verify
    entry = _entry()
    registry = get_or_create_browser_login_registry(wrapper.app)
    registry.register(entry)
    callback = asyncio.create_task(_post(wrapper, entry))
    await entered.wait()
    if command == "/login":
        await wrapper.handle_login(_message(command))
    else:
        await wrapper.handle_logout(_message(command))
    resume.set()
    assert (await callback).status == 401
    assert not registry._confirmations
    wrapper._persist_principal_link.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_callbacks_and_redemptions_publish_once() -> None:
    wrapper = _wrapper()
    entry = _entry()
    get_or_create_browser_login_registry(wrapper.app).register(entry)
    responses = await asyncio.gather(_post(wrapper, entry), _post(wrapper, entry))
    assert sorted(r.status for r in responses) == [202, 410]
    code = next(json.loads(r.text)["confirmation_code"] for r in responses if r.status == 202)
    await asyncio.gather(*(wrapper.handle_login(_message(f"/login {code}")) for _ in range(2)))
    wrapper._persist_principal_link.assert_awaited_once()
    wrapper._initialize_user_context.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_session_unchanged_before_confirmation() -> None:
    wrapper = _wrapper()
    session = TelegramUserSession(telegram_id=11)
    session.set_authenticated("old-user", "old-token")
    wrapper._user_sessions[11] = session
    await _prepare(wrapper)
    assert wrapper._user_sessions[11] is session
    assert session.nav_user_id == "old-user" and session.nav_session_token == "old-token"
    wrapper._persist_principal_link.assert_not_awaited()


@pytest.mark.asyncio
async def test_logout_cannot_interleave_with_confirmation_publication(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = _wrapper()
    entered, resume = asyncio.Event(), asyncio.Event()
    order: list[str] = []

    async def notify(**_kwargs: Any) -> None:
        entered.set()
        await resume.wait()

    async def persist(_session: TelegramUserSession) -> bool:
        order.append("persist")
        return True

    service = SimpleNamespace(unlink_channel_identity=AsyncMock(side_effect=lambda *_a, **_k: order.append("unlink")))
    wrapper._identity_service.return_value = service
    wrapper.bot.send_message.side_effect = notify
    wrapper._persist_principal_link.side_effect = persist
    monkeypatch.setattr("parrot.integrations.telegram.wrapper.principal_for_session", AsyncMock(return_value=None))
    _, code = await _prepare(wrapper)
    confirmation = asyncio.create_task(wrapper.handle_login(_message(f"/login {code}")))
    await entered.wait()
    logout = asyncio.create_task(wrapper.handle_logout(_message("/logout")))
    await asyncio.sleep(0)
    service.unlink_channel_identity.assert_not_awaited()
    resume.set()
    await asyncio.gather(confirmation, logout)
    assert order == ["persist", "unlink"]
    assert not wrapper._user_sessions[11].authenticated


@pytest.mark.asyncio
async def test_post_auth_actions_wait_for_confirmation() -> None:
    wrapper = _wrapper(post_auth=True)
    _, code = await _prepare(wrapper)
    wrapper._begin_login_attempt.assert_not_awaited()
    await wrapper.handle_login(_message(f"/login {code}"))
    wrapper._begin_login_attempt.assert_awaited_once()
    assert not wrapper._user_sessions[11].authenticated
    wrapper._persist_principal_link.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_completion_cannot_bypass_browser_confirmation() -> None:
    wrapper = _wrapper()
    with pytest.raises(BrowserVerificationError, match="confirmation"):
        await wrapper._complete_auth_payload(
            {"auth_method": "basic", "token": "victim-credential"},
            telegram_id=11,
            chat_id=11,
            browser_entry=_entry(),
        )
    assert wrapper._user_sessions == {}


def test_confirmation_page_escapes_untrusted_text() -> None:
    page = render_browser_confirmation("test_bot", "<script>alert(1)</script>")
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "Do not share this code" in page
    assert "Authentication is complete" not in page
