"""Telegram command handlers for the Jira OAuth 2.0 (3LO) flow.

Exposes three user-facing bot commands:

- ``/connect_jira`` — generates a Jira authorization URL and sends it as
  an inline button.  Clicking the button opens Atlassian's consent page in
  the user's default browser; after consent Atlassian redirects back to
  AI-Parrot's OAuth callback (see ``parrot.auth.routes``).
- ``/disconnect_jira`` — revokes the user's stored Jira tokens.
- ``/jira_status`` — reports whether a valid Jira connection is on file
  and, if so, the display name and site URL.

A ``TelegramOAuthNotifier`` helper is also exported so the OAuth callback
route can push a confirmation message back to the originating chat.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

if TYPE_CHECKING:  # pragma: no cover - type-checking only
    from aiogram import Bot

    from parrot.auth.jira_oauth import JiraOAuthManager


logger = logging.getLogger(__name__)

_TELEGRAM_CHANNEL = "telegram"


def _auth_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Connect Jira Account", url=url)],
        ]
    )


async def connect_jira_handler(
    message: Message, oauth_manager: "JiraOAuthManager"
) -> None:
    """Handle ``/connect_jira`` — send the authorization URL or a status."""
    if message.from_user is None:
        await message.reply(
            "I can only connect Jira for a real Telegram user."
        )
        return

    user_id = str(message.from_user.id)
    if await oauth_manager.is_connected(_TELEGRAM_CHANNEL, user_id):
        await message.reply(
            "You're already connected to Jira. Use /jira_status to see details."
        )
        return

    url, _nonce = await oauth_manager.create_authorization_url(
        _TELEGRAM_CHANNEL, user_id,
        extra_state={"chat_id": message.chat.id},
    )
    await message.reply(
        "Click the button below to authorize your Jira account:",
        reply_markup=_auth_keyboard(url),
    )


async def disconnect_jira_handler(
    message: Message, oauth_manager: "JiraOAuthManager"
) -> None:
    """Handle ``/disconnect_jira`` — revoke any stored tokens."""
    if message.from_user is None:
        await message.reply(
            "I can only manage Jira connections for a real Telegram user."
        )
        return
    user_id = str(message.from_user.id)
    await oauth_manager.revoke(_TELEGRAM_CHANNEL, user_id)
    await message.reply("Your Jira account has been disconnected.")


async def jira_status_handler(
    message: Message, oauth_manager: "JiraOAuthManager"
) -> None:
    """Handle ``/jira_status`` — report the user's Jira connection state."""
    if message.from_user is None:
        return
    user_id = str(message.from_user.id)
    token = await oauth_manager.get_valid_token(_TELEGRAM_CHANNEL, user_id)
    if token is not None:
        await message.reply(
            f"Connected to Jira as {token.display_name}\n"
            f"Site: {token.site_url}"
        )
    else:
        await message.reply(
            "Not connected to Jira. Use /connect_jira to link your account."
        )


def register_jira_commands(
    router: Router, oauth_manager: "JiraOAuthManager"
) -> None:
    """Register the three Jira commands on *router*.

    The handlers are closed over the provided ``oauth_manager``, so there's
    no need to wire aiogram middleware for dependency injection.
    """

    async def _connect(message: Message) -> None:
        await connect_jira_handler(message, oauth_manager)

    async def _disconnect(message: Message) -> None:
        await disconnect_jira_handler(message, oauth_manager)

    async def _status(message: Message) -> None:
        await jira_status_handler(message, oauth_manager)

    router.message.register(_connect, Command("connect_jira"))
    router.message.register(_disconnect, Command("disconnect_jira"))
    router.message.register(_status, Command("jira_status"))


class TelegramOAuthNotifier:
    """Push a confirmation message to the originating Telegram chat after
    a successful Jira OAuth callback.

    The OAuth callback route stores the chat id under ``extra_state`` when
    generating the authorization URL; this notifier reads the chat id back
    and sends a friendly confirmation.
    """

    def __init__(self, bot: "Bot") -> None:
        self._bot = bot
        self.logger = logger

    async def notify_connected(
        self,
        chat_id: int,
        display_name: str,
        site_url: str,
    ) -> None:
        try:
            await self._bot.send_message(
                chat_id,
                f"Jira connected as {display_name} ({site_url}). "
                "You can now use the Jira tools in this chat.",
            )
        except Exception:  # noqa: BLE001 - notification must never break callback
            self.logger.exception(
                "Failed to notify Telegram chat %s of Jira connection", chat_id,
            )

    async def notify_failure(self, chat_id: int, reason: str) -> None:
        try:
            await self._bot.send_message(
                chat_id,
                f"Jira authorization failed: {reason}",
            )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "Failed to notify Telegram chat %s of Jira failure", chat_id,
            )
