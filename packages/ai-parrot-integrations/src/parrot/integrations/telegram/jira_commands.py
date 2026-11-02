"""Telegram Jira aliases for the generic connection commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

if TYPE_CHECKING:  # pragma: no cover - type-checking only
    from parrot.integrations.core.auth.connections import ConnectionCommandService
    from parrot.integrations.telegram.connection_commands import ContextSource, ExtraStateFactory, PrincipalSource


_TELEGRAM_CHANNEL = "telegram"


def register_jira_commands(
    router: Router,
    *,
    commands: "ConnectionCommandService",
    principal_source: "PrincipalSource",
    context_source: "ContextSource",
    extra_state_factory: "ExtraStateFactory",
    on_disconnected: Optional[Callable[[int, str], None]] = None,
) -> None:
    """Register Jira-specific aliases of the generic connection handlers."""
    from parrot.integrations.telegram.connection_commands import (
        connect_handler,
        connections_handler,
        disconnect_handler,
    )

    async def _connect(message: Message) -> None:
        await connect_handler(
            message,
            "jira",
            commands=commands,
            principal_source=principal_source,
            context_source=context_source,
            extra_state_factory=extra_state_factory,
        )

    async def _disconnect(message: Message) -> None:
        await disconnect_handler(
            message,
            "jira",
            commands=commands,
            principal_source=principal_source,
            context_source=context_source,
            on_disconnected=on_disconnected,
        )

    async def _status(message: Message) -> None:
        await connections_handler(
            message,
            commands=commands,
            principal_source=principal_source,
            context_source=context_source,
            only="jira",
        )

    router.message.register(_connect, Command("connect_jira"))
    router.message.register(_disconnect, Command("disconnect_jira"))
    router.message.register(_status, Command("jira_status"))
