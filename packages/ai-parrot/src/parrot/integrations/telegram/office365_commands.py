"""Telegram command handlers for Office365 delegated connection.

The Office365 connection reuses the access token already obtained by
``/login`` when the wrapper is configured with ``auth_method: oauth2``.
This mirrors the explicit opt-in UX of ``/connect_jira`` while keeping
credential ownership on ``TelegramUserSession``.
"""
from __future__ import annotations

from typing import Callable

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from .auth import TelegramUserSession

SessionProvider = Callable[[int], TelegramUserSession]


async def connect_office365_handler(
    message: Message,
    session_provider: SessionProvider,
) -> None:
    """Handle ``/connect_office365`` from Telegram chat."""
    if message.from_user is None:
        await message.reply(
            "I can only connect Office365 for a real Telegram user.",
            parse_mode=None,
        )
        return

    session = session_provider(message.from_user.id)
    if session.o365_access_token:
        await message.reply(
            "You're already connected to Office365.",
            parse_mode=None,
        )
        return

    if not session.oauth2_access_token:
        await message.reply(
            "You need to authenticate first. Use /login, then try /connect_office365.",
            parse_mode=None,
        )
        return

    session.set_o365_authenticated(
        access_token=session.oauth2_access_token,
        id_token=session.oauth2_id_token,
        provider=session.oauth2_provider,
    )
    await message.reply(
        "Office365 connected. Agents can now use your delegated credentials for mail/calendar tools.",
        parse_mode=None,
    )


async def disconnect_office365_handler(
    message: Message,
    session_provider: SessionProvider,
) -> None:
    """Handle ``/disconnect_office365`` from Telegram chat."""
    if message.from_user is None:
        return
    session = session_provider(message.from_user.id)
    session.clear_o365_auth()
    await message.reply(
        "Your Office365 account has been disconnected.",
        parse_mode=None,
    )


async def office365_status_handler(
    message: Message,
    session_provider: SessionProvider,
) -> None:
    """Handle ``/office365_status`` from Telegram chat."""
    if message.from_user is None:
        return
    session = session_provider(message.from_user.id)
    if session.o365_access_token:
        provider = session.o365_provider or "oauth2"
        await message.reply(
            f"Connected to Office365 via {provider}.",
            parse_mode=None,
        )
        return
    await message.reply(
        "Not connected to Office365. Use /connect_office365 after /login.",
        parse_mode=None,
    )


def register_office365_commands(
    router: Router,
    session_provider: SessionProvider,
) -> None:
    """Register Office365 command handlers on the router."""

    async def _connect(message: Message) -> None:
        await connect_office365_handler(message, session_provider)

    async def _disconnect(message: Message) -> None:
        await disconnect_office365_handler(message, session_provider)

    async def _status(message: Message) -> None:
        await office365_status_handler(message, session_provider)

    router.message.register(_connect, Command("connect_office365"))
    router.message.register(_disconnect, Command("disconnect_office365"))
    router.message.register(_status, Command("office365_status"))

