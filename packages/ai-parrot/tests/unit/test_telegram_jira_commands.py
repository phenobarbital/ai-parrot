"""Tests for Telegram Jira generic-connection aliases."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Router

from parrot.auth.principal import Principal
from parrot.integrations.telegram.jira_commands import register_jira_commands


def _message() -> MagicMock:
    """Build a private-chat message used by registered alias callbacks."""
    message = MagicMock()
    message.from_user = SimpleNamespace(id=55)
    message.chat = SimpleNamespace(id=101, type="private")
    return message


@pytest.mark.asyncio
async def test_jira_aliases_route_to_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each Jira alias preserves its provider argument and generic handler inputs."""
    from parrot.integrations.telegram import connection_commands

    connect = AsyncMock()
    disconnect = AsyncMock()
    status = AsyncMock()
    monkeypatch.setattr(connection_commands, "connect_handler", connect)
    monkeypatch.setattr(connection_commands, "disconnect_handler", disconnect)
    monkeypatch.setattr(connection_commands, "connections_handler", status)
    router = Router()
    commands = MagicMock()

    async def principal_source(_message: MagicMock) -> Principal:
        return Principal(user_id="nav-55", channel="telegram", channel_user_id="55")

    def context_source(_message: MagicMock, _principal: Principal) -> MagicMock:
        return MagicMock()

    def extra_state_factory(_message: MagicMock) -> dict[str, int]:
        return {"chat_id": 101}

    disconnected = MagicMock()
    register_jira_commands(
        router,
        commands=commands,
        principal_source=principal_source,
        context_source=context_source,
        extra_state_factory=extra_state_factory,
        on_disconnected=disconnected,
    )

    handlers = router.message.handlers[-3:]
    message = _message()
    await handlers[0].callback(message)
    await handlers[1].callback(message)
    await handlers[2].callback(message)

    assert connect.await_args.args == (message, "jira")
    assert connect.await_args.kwargs["commands"] is commands
    assert disconnect.await_args.args == (message, "jira")
    assert disconnect.await_args.kwargs["on_disconnected"] is disconnected
    assert status.await_args.args == (message,)
    assert status.await_args.kwargs["only"] == "jira"


def test_registers_three_jira_aliases() -> None:
    """The Jira compatibility surface remains exactly three commands."""
    router = Router()
    before = len(router.message.handlers)
    register_jira_commands(
        router,
        commands=MagicMock(),
        principal_source=AsyncMock(),
        context_source=MagicMock(),
        extra_state_factory=MagicMock(),
    )
    assert len(router.message.handlers) - before == 3
