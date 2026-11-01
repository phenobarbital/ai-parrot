"""Generic Telegram connection commands: /connect, /disconnect, /connections (FEAT-776 M6)."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from parrot.auth.permission import PermissionContext
from parrot.auth.principal import Principal
from parrot.integrations.core.auth.connections import ConnectionCommandService, ConnectOutcome

logger = logging.getLogger(__name__)

Update = Union[Message, CallbackQuery]
PrincipalSource = Callable[[Update], Awaitable[Optional[Principal]]]
ContextSource = Callable[[Update, Principal], PermissionContext]
ExtraStateFactory = Callable[[Update], Dict[str, Any]]

PRIVATE_ONLY = "Please use a private chat with the bot to manage connections."
LOGIN_FIRST = "Please /login first to link your Telegram account."
CALLBACK_PREFIX = "conn:"


def render_connect_outcome(outcome: ConnectOutcome) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    """Return plain text and an optional URL button for a connection outcome."""
    if outcome.kind == "auth_url" and outcome.auth_url:
        return (
            f"Click below to connect {outcome.display_name}.",
            InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=f"Connect {outcome.display_name}", url=outcome.auth_url)]]
            ),
        )
    if outcome.kind == "denied":
        return f"Connecting {outcome.display_name} is not allowed for your account.", None
    if outcome.kind == "needs_login":
        return LOGIN_FIRST, None
    return outcome.message or "Unable to manage that connection.", None


async def connect_handler(
    message: Message,
    provider_arg: str,
    *,
    commands: ConnectionCommandService,
    principal_source: PrincipalSource,
    context_source: ContextSource,
    extra_state_factory: ExtraStateFactory,
) -> None:
    """Handle ``/connect [<provider>]`` with a picker when no provider is supplied."""
    if message.chat.type != "private":
        await message.reply(PRIVATE_ONLY, parse_mode=None)
        return
    principal = await principal_source(message)
    if principal is None:
        await message.reply(LOGIN_FIRST, parse_mode=None)
        return
    provider_id = provider_arg.strip()
    if not provider_id:
        providers = commands.connectable_providers()
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=provider.display_name, callback_data=f"{CALLBACK_PREFIX}{provider.provider_id}"
                    )
                ]
                for provider in providers
            ]
        )
        await message.reply("Choose an account to connect:", reply_markup=keyboard, parse_mode=None)
        return
    outcome = await commands.connect(
        principal,
        provider_id,
        extra_state=extra_state_factory(message),
        permission_context=context_source(message, principal),
    )
    text, reply_markup = render_connect_outcome(outcome)
    await message.reply(text, reply_markup=reply_markup, parse_mode=None)


async def disconnect_handler(
    message: Message,
    provider_arg: str,
    *,
    commands: ConnectionCommandService,
    principal_source: PrincipalSource,
    context_source: ContextSource,
    on_disconnected: Optional[Callable[[int, str], None]] = None,
) -> None:
    """Handle ``/disconnect <provider>`` and invoke the disconnect callback on success."""
    if message.chat.type != "private":
        await message.reply(PRIVATE_ONLY, parse_mode=None)
        return
    principal = await principal_source(message)
    if principal is None:
        await message.reply(LOGIN_FIRST, parse_mode=None)
        return
    provider_id = provider_arg.strip()
    if not provider_id:
        await message.reply("Usage: /disconnect <provider>", parse_mode=None)
        return
    outcome = await commands.disconnect(
        principal,
        provider_id,
        permission_context=context_source(message, principal),
    )
    if outcome.kind == "disconnected" and on_disconnected is not None and message.from_user is not None:
        on_disconnected(message.from_user.id, outcome.provider_id)
    text, reply_markup = render_connect_outcome(outcome)
    if outcome.kind == "disconnected":
        text = outcome.message or f"{outcome.display_name} disconnected."
    await message.reply(text, reply_markup=reply_markup, parse_mode=None)


async def connections_handler(
    message: Message,
    *,
    commands: ConnectionCommandService,
    principal_source: PrincipalSource,
    context_source: ContextSource,
    only: Optional[str] = None,
) -> None:
    """Handle ``/connections`` and report each allowed provider's connection status."""
    if message.chat.type != "private":
        await message.reply(PRIVATE_ONLY, parse_mode=None)
        return
    principal = await principal_source(message)
    if principal is None:
        await message.reply(LOGIN_FIRST, parse_mode=None)
        return
    statuses = await commands.statuses(principal, permission_context=context_source(message, principal))
    if only is not None:
        provider = commands.resolve_provider(only)
        statuses = [
            status for status in statuses if provider is not None and status.provider_id == provider.provider_id
        ]
    if not statuses:
        await message.reply("No connections found.", parse_mode=None)
        return
    lines = []
    for status in statuses:
        account = f" as {status.account_display_name}" if status.account_display_name else ""
        lines.append(f"{status.display_name}: {status.status}{account}")
    await message.reply("\n".join(lines), parse_mode=None)


def register_connection_commands(
    router: Router,
    *,
    commands: ConnectionCommandService,
    principal_source: PrincipalSource,
    context_source: ContextSource,
    extra_state_factory: ExtraStateFactory,
    on_disconnected: Optional[Callable[[int, str], None]] = None,
) -> List[Tuple[str, str]]:
    """Register connection commands and their provider-picker callback route."""

    def _argument(command: CommandObject) -> str:
        return (command.args or "").split(maxsplit=1)[0] if command.args else ""

    async def _connect(message: Message, command: CommandObject) -> None:
        await connect_handler(
            message,
            _argument(command),
            commands=commands,
            principal_source=principal_source,
            context_source=context_source,
            extra_state_factory=extra_state_factory,
        )

    async def _disconnect(message: Message, command: CommandObject) -> None:
        await disconnect_handler(
            message,
            _argument(command),
            commands=commands,
            principal_source=principal_source,
            context_source=context_source,
            on_disconnected=on_disconnected,
        )

    async def _connections(message: Message) -> None:
        await connections_handler(
            message,
            commands=commands,
            principal_source=principal_source,
            context_source=context_source,
        )

    async def _on_pick(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.message is None:
            return
        provider_id = (callback.data or "")[len(CALLBACK_PREFIX) :]
        await connect_handler(
            callback.message,
            provider_id,
            commands=commands,
            principal_source=lambda _message: principal_source(callback),
            context_source=lambda _message, principal: context_source(callback, principal),
            extra_state_factory=lambda _message: extra_state_factory(callback),
        )

    router.message.register(_connect, Command("connect"))
    router.message.register(_disconnect, Command("disconnect"))
    router.message.register(_connections, Command("connections"))
    router.callback_query.register(_on_pick, F.data.startswith(CALLBACK_PREFIX))
    return [
        ("connect", "Connect an account"),
        ("disconnect", "Disconnect an account"),
        ("connections", "Show your connections"),
    ]
