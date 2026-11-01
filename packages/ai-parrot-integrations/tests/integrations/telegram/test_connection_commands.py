"""FEAT-776 M6 handler tests."""

from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.principal import Principal
from parrot.integrations.core.auth.connections import ConnectOutcome
from parrot.integrations.telegram.connection_commands import (
    LOGIN_FIRST,
    PRIVATE_ONLY,
    connect_handler,
    register_connection_commands,
)


class FakeCommands:
    """Connection command fake that records the injected service-call values."""

    def __init__(self) -> None:
        self.connect = AsyncMock(
            return_value=ConnectOutcome(
                kind="auth_url", provider_id="jira", display_name="Jira", auth_url="https://example.test/connect"
            )
        )
        self.connectable_providers = MagicMock(return_value=[SimpleNamespace(provider_id="jira", display_name="Jira")])


def message(*, chat_type: str = "private") -> Any:
    """Build a minimal Telegram message double."""
    return SimpleNamespace(
        chat=SimpleNamespace(type=chat_type, id=99),
        from_user=SimpleNamespace(id=42),
        reply=AsyncMock(),
    )


def principal_source(principal: Optional[Principal]) -> AsyncMock:
    """Build an async principal source returning the supplied value."""
    return AsyncMock(return_value=principal)


def principal() -> Principal:
    """Return a Telegram-bound Navigator principal for handler tests."""
    return Principal(user_id="7", channel="telegram", channel_user_id="42")


@pytest.mark.asyncio
async def test_connect_requires_private_chat() -> None:
    """Group chats are rejected before principal resolution or service calls."""
    commands = FakeCommands()
    source = principal_source(principal())
    event = message(chat_type="group")

    await connect_handler(
        event,
        "jira",
        commands=commands,
        principal_source=source,
        context_source=MagicMock(),
        extra_state_factory=MagicMock(),
    )

    event.reply.assert_awaited_once_with(PRIVATE_ONLY, parse_mode=None)
    source.assert_not_awaited()
    commands.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_without_principal_creates_no_state() -> None:
    """Unauthenticated users do not invoke services or mint connection state."""
    commands = FakeCommands()
    extra_state_factory = MagicMock()
    event = message()

    await connect_handler(
        event,
        "jira",
        commands=commands,
        principal_source=principal_source(None),
        context_source=MagicMock(),
        extra_state_factory=extra_state_factory,
    )

    event.reply.assert_awaited_once_with(LOGIN_FIRST, parse_mode=None)
    extra_state_factory.assert_not_called()
    commands.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_picker_and_callback() -> None:
    """The picker exposes only service providers and its callback starts the chosen connection."""
    commands = FakeCommands()
    source = principal_source(principal())
    event = message()
    router = SimpleNamespace(message=MagicMock(), callback_query=MagicMock())
    state = {"chat_id": 99, "bot_id": "bot-a"}

    await connect_handler(
        event,
        "",
        commands=commands,
        principal_source=source,
        context_source=MagicMock(return_value=SimpleNamespace()),
        extra_state_factory=MagicMock(return_value=state),
    )
    markup = event.reply.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "conn:jira"

    register_connection_commands(
        router,
        commands=commands,
        principal_source=source,
        context_source=MagicMock(return_value=SimpleNamespace()),
        extra_state_factory=MagicMock(return_value=state),
    )
    on_pick = router.callback_query.register.call_args.args[0]
    callback = SimpleNamespace(message=event, data="conn:jira", answer=AsyncMock())
    await on_pick(callback)

    callback.answer.assert_awaited_once_with()
    commands.connect.assert_awaited_once()
    assert commands.connect.await_args.args[1] == "jira"


@pytest.mark.asyncio
async def test_extra_state_carries_chat_and_bot() -> None:
    """The injected state factory is forwarded unchanged to the command service."""
    commands = FakeCommands()
    event = message()
    extra_state = {"chat_id": event.chat.id, "bot_id": "bot-a"}

    await connect_handler(
        event,
        "jira",
        commands=commands,
        principal_source=principal_source(principal()),
        context_source=MagicMock(return_value=SimpleNamespace()),
        extra_state_factory=MagicMock(return_value=extra_state),
    )

    assert commands.connect.await_args.kwargs["extra_state"] == {"chat_id": 99, "bot_id": "bot-a"}
