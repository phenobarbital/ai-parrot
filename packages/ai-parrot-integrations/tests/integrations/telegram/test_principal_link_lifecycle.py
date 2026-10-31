"""FEAT-776 Telegram principal-link lifecycle tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.auth.principal import Principal
from parrot.integrations.telegram.auth import TelegramUserSession
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper, principal_for_session


@pytest.fixture
def tg_session() -> TelegramUserSession:
    """Return a finalized Navigator-authenticated Telegram session."""
    session = TelegramUserSession(telegram_id=88123, telegram_username="ada")
    session.set_authenticated(
        nav_user_id="1042",
        session_token="session-token",
        display_name="Ada Lovelace",
        email="ada@example.com",
    )
    return session


@pytest.fixture
def fake_identity_service() -> MagicMock:
    """Return an async fake for the identity link service."""
    service = MagicMock()
    service.link_channel_identity = AsyncMock()
    service.unlink_channel_identity = AsyncMock(return_value=1)
    return service


def _wrapper(service: MagicMock) -> TelegramAgentWrapper:
    """Build the minimal wrapper surface needed by lifecycle tests."""
    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.app = None
    wrapper.config = SimpleNamespace(tenant="tenant-a", post_auth_actions=[])
    wrapper.logger = MagicMock()
    wrapper._identity_service_cache = service
    wrapper._user_sessions = {}
    wrapper._initialize_user_context = AsyncMock()
    return wrapper


def _message(payload: str = "{}") -> MagicMock:
    """Build a minimal aiogram message stand-in."""
    message = MagicMock()
    message.chat.id = 88123
    message.from_user = MagicMock()
    message.web_app_data.data = payload
    message.answer = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_login_persists_link_both_paths(
    tg_session: TelegramUserSession,
    fake_identity_service: MagicMock,
) -> None:
    """Single-step login links once while combined login stays delegated to TASK-5029."""
    wrapper = _wrapper(fake_identity_service)
    wrapper._auth_strategy = MagicMock()
    wrapper._auth_strategy.handle_callback = AsyncMock(return_value=True)
    wrapper._get_user_session = MagicMock(return_value=tg_session)
    wrapper._is_combined_payload = MagicMock(return_value=False)
    message = _message()

    await wrapper.handle_web_app_data(message)

    fake_identity_service.link_channel_identity.assert_awaited_once_with(
        nav_user_id="1042",
        auth_provider="telegram",
        provider_user_id="88123",
        auth_data={"telegram_id": 88123, "username": "ada"},
        display_name="Ada Lovelace",
        email="ada@example.com",
    )
    assert tg_session.principal_link_persisted is True

    wrapper._is_combined_payload.return_value = True
    wrapper._handle_combined_auth = AsyncMock()
    await wrapper.handle_web_app_data(message)
    fake_identity_service.link_channel_identity.assert_awaited_once()
    wrapper._handle_combined_auth.assert_awaited_once_with(message, {}, tg_session)


@pytest.mark.asyncio
async def test_login_succeeds_when_link_write_fails(
    tg_session: TelegramUserSession,
    fake_identity_service: MagicMock,
) -> None:
    """A failed identity write warns without rolling back successful login."""
    fake_identity_service.link_channel_identity.side_effect = RuntimeError("db unavailable")
    wrapper = _wrapper(fake_identity_service)
    wrapper._auth_strategy = MagicMock()
    wrapper._auth_strategy.handle_callback = AsyncMock(return_value=True)
    wrapper._get_user_session = MagicMock(return_value=tg_session)
    wrapper._is_combined_payload = MagicMock(return_value=False)
    message = _message()

    await wrapper.handle_web_app_data(message)

    assert tg_session.authenticated is True
    assert tg_session.principal_link_persisted is False
    assert message.answer.await_count == 2
    assert message.answer.await_args_list[-1].args == ("Connections are unavailable right now.",)
    assert message.answer.await_args_list[-1].kwargs == {"parse_mode": None}
    wrapper.logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_logout_unlinks_before_clear(
    tg_session: TelegramUserSession,
    fake_identity_service: MagicMock,
) -> None:
    """Logout awaits unlink before clearing the authenticated session."""
    events: list[str] = []

    async def unlink(auth_provider: str, provider_user_id: str) -> int:
        assert tg_session.authenticated is True
        events.append(f"unlink:{auth_provider}:{provider_user_id}")
        return 1

    original_clear = tg_session.clear_auth

    def clear_auth() -> None:
        events.append("clear")
        original_clear()

    fake_identity_service.unlink_channel_identity.side_effect = unlink
    tg_session.clear_auth = clear_auth
    wrapper = _wrapper(fake_identity_service)
    wrapper._is_authorized = MagicMock(return_value=True)
    wrapper._get_user_session = MagicMock(return_value=tg_session)
    message = _message()

    await wrapper.handle_logout(message)

    assert events == ["unlink:telegram:88123", "clear"]
    assert tg_session.authenticated is False
    assert tg_session.principal_link_persisted is False


@pytest.mark.asyncio
async def test_ensure_principal_link_backfills_once(
    tg_session: TelegramUserSession,
    fake_identity_service: MagicMock,
) -> None:
    """A finalized pre-FEAT-776 session is linked once per process session."""
    wrapper = _wrapper(fake_identity_service)

    assert await wrapper._ensure_principal_link(tg_session) is True
    assert await wrapper._ensure_principal_link(tg_session) is True

    fake_identity_service.link_channel_identity.assert_awaited_once()


@pytest.mark.asyncio
async def test_telegram_restart_retains_link(
    fake_identity_service: MagicMock,
) -> None:
    """A fresh process resolves the persisted link and fabricates no roles."""
    wrapper = _wrapper(fake_identity_service)
    session = TelegramUserSession(telegram_id=88123)
    principal = Principal(
        user_id="1042",
        tenant_id="tenant-a",
        channel="telegram",
        channel_user_id="88123",
    )

    with patch(
        "parrot.auth.principal.resolve_principal",
        new=AsyncMock(return_value=principal),
    ) as resolver:
        resolved = await principal_for_session(session, tenant_id="tenant-a")

    assert wrapper._user_sessions == {}
    assert resolved == principal
    resolver.assert_awaited_once_with("telegram", "88123")
    context = wrapper._connection_permission_context(session, resolved)
    assert context.user_id == "1042"
    assert context.channel == "telegram"
    assert context.roles == frozenset()
    assert context.extra == {"telegram_id": 88123}
