"""Unit tests for Telegram Office365 command handlers."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.telegram.auth import TelegramUserSession
from parrot.integrations.telegram.office365_commands import (
    connect_office365_handler,
    disconnect_office365_handler,
    office365_status_handler,
    register_office365_commands,
)


def _make_message(user_id: int = 777) -> MagicMock:
    message = MagicMock()
    message.reply = AsyncMock()
    message.from_user = SimpleNamespace(id=user_id)
    return message


class TestConnectOffice365Handler:
    @pytest.mark.asyncio
    async def test_connect_requires_prior_login(self) -> None:
        session = TelegramUserSession(telegram_id=777)
        message = _make_message()

        await connect_office365_handler(message, lambda _: session)

        text = message.reply.await_args.args[0]
        assert "/login" in text

    @pytest.mark.asyncio
    async def test_connect_copies_oauth2_credentials(self) -> None:
        session = TelegramUserSession(telegram_id=777)
        session.oauth2_access_token = "access-token"
        session.oauth2_id_token = "id-token"
        session.oauth2_provider = "microsoft"
        message = _make_message()

        await connect_office365_handler(message, lambda _: session)

        assert session.o365_access_token == "access-token"
        assert session.o365_id_token == "id-token"
        assert session.o365_provider == "microsoft"

    @pytest.mark.asyncio
    async def test_connect_rejects_non_microsoft_provider(self) -> None:
        session = TelegramUserSession(telegram_id=777)
        session.oauth2_access_token = "access-token"
        session.oauth2_provider = "google"
        message = _make_message()

        await connect_office365_handler(message, lambda _: session)

        text = message.reply.await_args.args[0]
        assert "not Microsoft" in text
        assert session.o365_access_token is None


class TestOffice365StatusHandler:
    @pytest.mark.asyncio
    async def test_status_not_connected(self) -> None:
        session = TelegramUserSession(telegram_id=777)
        message = _make_message()

        await office365_status_handler(message, lambda _: session)

        text = message.reply.await_args.args[0]
        assert "/connect_office365" in text

    @pytest.mark.asyncio
    async def test_disconnect_clears_connection(self) -> None:
        session = TelegramUserSession(telegram_id=777)
        session.o365_access_token = "token"
        message = _make_message()

        await disconnect_office365_handler(message, lambda _: session)

        assert session.o365_access_token is None


class TestRegisterOffice365Commands:
    def test_registers_three_commands(self) -> None:
        from aiogram import Router

        router = Router()
        before = len(router.message.handlers)
        register_office365_commands(
            router, lambda telegram_id: TelegramUserSession(telegram_id=telegram_id)
        )
        after = len(router.message.handlers)
        assert after - before == 3

    @pytest.mark.asyncio
    async def test_office365_alias_only_when_registered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A connectable o365 provider makes the legacy names generic aliases."""
        from aiogram import Router
        from parrot.integrations.telegram import connection_commands

        connect = AsyncMock()
        disconnect = AsyncMock()
        status = AsyncMock()
        monkeypatch.setattr(connection_commands, "connect_handler", connect)
        monkeypatch.setattr(connection_commands, "disconnect_handler", disconnect)
        monkeypatch.setattr(connection_commands, "connections_handler", status)
        commands = MagicMock()
        commands.resolve_provider.return_value = SimpleNamespace(provider_id="o365")
        router = Router()
        message = _make_message()
        message.chat = SimpleNamespace(type="private")

        register_office365_commands(
            router,
            lambda telegram_id: TelegramUserSession(telegram_id=telegram_id),
            commands=commands,
            principal_source=AsyncMock(),
            context_source=MagicMock(),
            extra_state_factory=MagicMock(),
        )

        handlers = router.message.handlers[-3:]
        await handlers[0].callback(message)
        await handlers[1].callback(message)
        await handlers[2].callback(message)

        assert connect.await_args.args == (message, "o365")
        assert disconnect.await_args.args == (message, "o365")
        assert status.await_args.kwargs["only"] == "o365"

    def test_office365_fallback_keeps_session_handlers(self) -> None:
        """An unavailable o365 provider leaves the historical session flow intact."""
        from aiogram import Router

        commands = MagicMock()
        commands.resolve_provider.return_value = None
        router = Router()
        register_office365_commands(
            router,
            lambda telegram_id: TelegramUserSession(telegram_id=telegram_id),
            commands=commands,
        )
        assert len(router.message.handlers) == 3
