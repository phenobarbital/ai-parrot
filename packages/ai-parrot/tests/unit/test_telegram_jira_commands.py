"""Unit tests for Telegram Jira OAuth command handlers (TASK-754)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import InlineKeyboardMarkup

from parrot.integrations.telegram.jira_commands import (
    TelegramOAuthNotifier,
    connect_jira_handler,
    disconnect_jira_handler,
    jira_status_handler,
    register_jira_commands,
)


def _make_message(user_id: int = 555, chat_id: int = 101) -> MagicMock:
    message = MagicMock()
    message.reply = AsyncMock()
    message.from_user = SimpleNamespace(id=user_id)
    message.chat = SimpleNamespace(id=chat_id)
    return message


class TestConnectJiraHandler:
    @pytest.mark.asyncio
    async def test_sends_auth_url_when_not_connected(self) -> None:
        manager = MagicMock()
        manager.is_connected = AsyncMock(return_value=False)
        manager.create_authorization_url = AsyncMock(
            return_value=("https://auth.atlassian.com/authorize?state=x", "x"),
        )
        message = _make_message()

        await connect_jira_handler(message, manager)

        manager.create_authorization_url.assert_awaited_once()
        args, kwargs = manager.create_authorization_url.await_args
        assert args == ("telegram", "555")
        assert kwargs["extra_state"]["chat_id"] == 101

        message.reply.assert_awaited_once()
        call_kwargs = message.reply.await_args.kwargs
        markup = call_kwargs["reply_markup"]
        assert isinstance(markup, InlineKeyboardMarkup)
        button = markup.inline_keyboard[0][0]
        assert button.url.startswith("https://auth.atlassian.com")

    @pytest.mark.asyncio
    async def test_already_connected_message(self) -> None:
        manager = MagicMock()
        manager.is_connected = AsyncMock(return_value=True)
        message = _make_message()

        await connect_jira_handler(message, manager)

        message.reply.assert_awaited_once()
        text = message.reply.await_args.args[0]
        assert "already connected" in text.lower()

    @pytest.mark.asyncio
    async def test_missing_from_user(self) -> None:
        manager = MagicMock()
        message = MagicMock()
        message.reply = AsyncMock()
        message.from_user = None

        await connect_jira_handler(message, manager)
        message.reply.assert_awaited_once()


class TestDisconnectJiraHandler:
    @pytest.mark.asyncio
    async def test_revokes_and_confirms(self) -> None:
        manager = MagicMock()
        manager.revoke = AsyncMock()
        message = _make_message(user_id=42)

        await disconnect_jira_handler(message, manager)

        manager.revoke.assert_awaited_once_with("telegram", "42")
        message.reply.assert_awaited_once()
        assert "disconnected" in message.reply.await_args.args[0].lower()


class TestJiraStatusHandler:
    @pytest.mark.asyncio
    async def test_connected_shows_details(self) -> None:
        manager = MagicMock()
        manager.get_valid_token = AsyncMock(return_value=SimpleNamespace(
            display_name="Jesus Garcia",
            site_url="https://acme.atlassian.net",
        ))
        message = _make_message()

        await jira_status_handler(message, manager)

        text = message.reply.await_args.args[0]
        assert "Jesus Garcia" in text
        assert "acme.atlassian.net" in text

    @pytest.mark.asyncio
    async def test_not_connected_suggests_connect(self) -> None:
        manager = MagicMock()
        manager.get_valid_token = AsyncMock(return_value=None)
        message = _make_message()

        await jira_status_handler(message, manager)

        text = message.reply.await_args.args[0]
        assert "/connect_jira" in text


class TestRegisterJiraCommands:
    def test_registers_three_commands(self) -> None:
        from aiogram import Router

        router = Router()
        manager = MagicMock()

        before = len(router.message.handlers)
        register_jira_commands(router, manager)
        after = len(router.message.handlers)

        assert after - before == 3


class TestTelegramOAuthNotifier:
    @pytest.mark.asyncio
    async def test_notify_connected(self) -> None:
        bot = MagicMock()
        bot.send_message = AsyncMock()
        notifier = TelegramOAuthNotifier(bot)

        await notifier.notify_connected(
            chat_id=101, display_name="Jesus", site_url="https://acme.atlassian.net",
        )

        bot.send_message.assert_awaited_once()
        args, _ = bot.send_message.await_args
        assert args[0] == 101
        assert "Jesus" in args[1]

    @pytest.mark.asyncio
    async def test_notify_connected_swallows_exceptions(self) -> None:
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=RuntimeError("boom"))
        notifier = TelegramOAuthNotifier(bot)
        # Must not raise — notifications are best-effort.
        await notifier.notify_connected(
            chat_id=1, display_name="x", site_url="y",
        )

    @pytest.mark.asyncio
    async def test_notify_failure(self) -> None:
        bot = MagicMock()
        bot.send_message = AsyncMock()
        notifier = TelegramOAuthNotifier(bot)

        await notifier.notify_failure(chat_id=2, reason="expired nonce")

        bot.send_message.assert_awaited_once()
        args, _ = bot.send_message.await_args
        assert "expired nonce" in args[1]
