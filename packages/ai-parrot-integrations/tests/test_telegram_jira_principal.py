"""Principal-keyed Telegram Jira commands and integrations wiring (FEAT-773)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEventPublisher
from parrot.auth.principal import Principal
from parrot.integrations.manager import (
    _build_principal_resolver,
    _connection_publisher,
)
from parrot.integrations.telegram.jira_commands import connect_jira_handler


def _message(telegram_id: int = 88123) -> MagicMock:
    """Build a minimal Telegram message mock."""
    message = MagicMock()
    message.from_user = SimpleNamespace(id=telegram_id)
    message.chat = SimpleNamespace(id=77)
    message.reply = AsyncMock()
    return message


@pytest.fixture(autouse=True)
def _reset_notifier_registry() -> None:
    """Keep the process-global notifier registry isolated between tests."""
    ChannelNotifierRegistry._reset()
    yield
    ChannelNotifierRegistry._reset()


@pytest.mark.asyncio
async def test_telegram_connect_jira_requires_principal() -> None:
    """An unlinked Telegram user is told to log in and creates no OAuth state."""
    manager = MagicMock()
    manager.validate_token = AsyncMock()
    manager.create_authorization_url = AsyncMock()
    message = _message()

    with patch(
        "parrot.integrations.telegram.jira_commands.resolve_principal",
        AsyncMock(return_value=None),
    ):
        await connect_jira_handler(message, manager)

    manager.validate_token.assert_not_awaited()
    manager.create_authorization_url.assert_not_awaited()
    message.reply.assert_awaited_once_with(
        "Please /login first to link your Telegram account, then run /connect_jira again.",
        parse_mode=None,
    )


@pytest.mark.asyncio
async def test_telegram_connect_uses_session_principal() -> None:
    """A logged-in Telegram session binds OAuth state to its Navigator user."""
    manager = MagicMock()
    manager.validate_token = AsyncMock(return_value=None)
    manager.create_authorization_url = AsyncMock(return_value=("https://jira.example/auth", "nonce"))
    message = _message()

    await connect_jira_handler(
        message,
        manager,
        session_lookup=lambda _tid: SimpleNamespace(nav_user_id="1042"),
    )

    manager.validate_token.assert_awaited_once_with("telegram", "1042")
    call = manager.create_authorization_url.await_args
    assert call.args == ("telegram", "88123")
    assert call.kwargs["extra_state"] == {"chat_id": 77}
    assert call.kwargs["principal"] == Principal(
        user_id="1042",
        channel="telegram",
        channel_user_id="88123",
    )


@pytest.mark.asyncio
async def test_telegram_connect_uses_registered_identity_principal() -> None:
    """A linked Telegram identity reuses its principal without authorization."""
    manager = MagicMock()
    manager.validate_token = AsyncMock(return_value=SimpleNamespace(display_name="Jira User"))
    manager.create_authorization_url = AsyncMock()
    message = _message()
    principal = Principal(user_id="1042", channel="telegram", channel_user_id="88123")

    with patch(
        "parrot.integrations.telegram.jira_commands.resolve_principal",
        AsyncMock(return_value=principal),
    ):
        await connect_jira_handler(message, manager)

    manager.validate_token.assert_awaited_once_with("telegram", "1042")
    manager.create_authorization_url.assert_not_awaited()
    assert "already connected" in message.reply.await_args.args[0].lower()


def test_connection_publisher_is_shared_and_registers_all_adapters() -> None:
    """The app keeps one publisher backed by all three channel adapters."""
    app: dict[str, object] = {}

    first = _connection_publisher(app)
    second = _connection_publisher(app)

    assert first is second
    assert isinstance(first, ConnectionEventPublisher)
    assert {notifier.channel for notifier in ChannelNotifierRegistry().all()} == {
        "telegram",
        "slack",
        "msteams",
    }


def test_build_principal_resolver_registers_authdb() -> None:
    """An auth database produces and registers the server resolver."""
    db_pool = object()
    resolver = MagicMock()
    with (
        patch(
            "parrot.services.identity_principal.IdentityPrincipalResolver",
            return_value=resolver,
        ) as resolver_cls,
        patch("parrot.integrations.manager.set_principal_resolver") as setter,
    ):
        result = _build_principal_resolver({"authdb": db_pool})

    resolver_cls.assert_called_once_with(db_pool)
    setter.assert_called_once_with(resolver)
    assert result is resolver
