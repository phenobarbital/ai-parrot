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
from typing import TYPE_CHECKING, Any, Callable, Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

if TYPE_CHECKING:  # pragma: no cover - type-checking only
    from aiogram import Bot

    from parrot.auth.jira_oauth import JiraOAuthManager

# Signature of the optional in-memory session clearer. Receives the
# Telegram user id (int) and is expected to wipe the local
# ``TelegramUserSession.jira_*`` fields so the user_context enrichment
# stops advertising the Jira identity after /disconnect_jira.
SessionClearer = Callable[[int], None]


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
    """Handle ``/connect_jira`` — send the authorization URL or a status.

    All replies use ``parse_mode=None`` because the bot is constructed with
    a default Markdown parse mode (see ``manager.py``) and command names such
    as ``/jira_status`` contain underscores that Markdown would interpret as
    unclosed italic markers, raising ``TelegramBadRequest`` on send.
    """
    if message.from_user is None:
        await message.reply(
            "I can only connect Jira for a real Telegram user.",
            parse_mode=None,
        )
        return

    user_id = str(message.from_user.id)
    if await oauth_manager.is_connected(_TELEGRAM_CHANNEL, user_id):
        await message.reply(
            "You're already connected to Jira. Use /jira_status to see details.",
            parse_mode=None,
        )
        return

    url, _nonce = await oauth_manager.create_authorization_url(
        _TELEGRAM_CHANNEL, user_id,
        extra_state={"chat_id": message.chat.id},
    )
    await message.reply(
        "Click the button below to authorize your Jira account:",
        reply_markup=_auth_keyboard(url),
        parse_mode=None,
    )


async def disconnect_jira_handler(
    message: Message,
    oauth_manager: "JiraOAuthManager",
    session_clearer: Optional[SessionClearer] = None,
) -> None:
    """Handle ``/disconnect_jira`` — revoke stored tokens and clear session.

    Args:
        message: Incoming ``/disconnect_jira`` update.
        oauth_manager: Manager used to revoke the persisted tokens.
        session_clearer: Optional callback invoked with the Telegram user id
            after revocation to wipe the in-memory ``TelegramUserSession``
            Jira fields. Without this the ``user_context`` prompt enrichment
            keeps announcing the old Jira identity until the process
            restarts or the user logs out.
    """
    if message.from_user is None:
        await message.reply(
            "I can only manage Jira connections for a real Telegram user.",
            parse_mode=None,
        )
        return
    telegram_id = message.from_user.id
    user_id = str(telegram_id)
    await oauth_manager.revoke(_TELEGRAM_CHANNEL, user_id)
    if session_clearer is not None:
        try:
            session_clearer(telegram_id)
        except Exception:  # noqa: BLE001 - never let a clearer error surface as bot failure
            logger.exception(
                "Jira session_clearer raised for tg:%s", telegram_id,
            )
    await message.reply(
        "Your Jira account has been disconnected.",
        parse_mode=None,
    )


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
            f"Site: {token.site_url}",
            parse_mode=None,
        )
    else:
        await message.reply(
            "Not connected to Jira. Use /connect_jira to link your account.",
            parse_mode=None,
        )


def register_jira_commands(
    router: Router,
    oauth_manager: "JiraOAuthManager",
    session_clearer: Optional[SessionClearer] = None,
) -> None:
    """Register the three Jira commands on *router*.

    The handlers are closed over the provided ``oauth_manager``, so there's
    no need to wire aiogram middleware for dependency injection.

    Args:
        router: Target aiogram ``Router``.
        oauth_manager: Backing Jira OAuth manager.
        session_clearer: Optional callback invoked after
            ``/disconnect_jira`` to wipe the caller's in-memory Jira
            identity on the ``TelegramUserSession``. Callers that track
            per-user sessions (``TelegramAgentWrapper``) should pass a
            closure over their ``_user_sessions`` dict.
    """

    async def _connect(message: Message) -> None:
        await connect_jira_handler(message, oauth_manager)

    async def _disconnect(message: Message) -> None:
        await disconnect_jira_handler(
            message, oauth_manager, session_clearer=session_clearer
        )

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
                parse_mode=None,
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
                parse_mode=None,
            )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "Failed to notify Telegram chat %s of Jira failure", chat_id,
            )
