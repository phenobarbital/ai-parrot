"""Generic Telegram ChannelNotifier for connection events (FEAT-776 M7)."""

from __future__ import annotations

import inspect
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, MutableMapping, Optional, Tuple

from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEvent
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry

if TYPE_CHECKING:  # pragma: no cover
    from aiogram import Bot

SessionHook = Callable[[int, ConnectionEvent], "Awaitable[None] | None"]
_APP_KEY = "telegram_connection_notifier"
_SEEN_MAX = 1024


class TelegramConnectionNotifier:
    """Deliver connection events to Telegram chats; log failures, never raise."""

    channel: str = "telegram"

    def __init__(self, *, identity_service: Optional[Any] = None) -> None:
        self._identity_service = identity_service
        self._bots: Dict[str, "Bot"] = {}
        self._last_connect_bot: Dict[str, str] = {}
        self._hooks: Dict[str, Tuple[Optional[SessionHook], Optional[SessionHook]]] = {}
        self._login_coordinator: Optional[Any] = None
        self._login_coordinators: Dict[str, Any] = {}
        # Bounded LRU of delivered event keys; only successful sends are recorded.
        self._seen: "OrderedDict[Tuple[str, str, str, float], None]" = OrderedDict()
        self.logger = logging.getLogger(__name__)

    def attach(self, bot_id: str, bot: "Bot") -> None:
        """Make ``bot`` available for deliveries recorded with ``bot_id``."""
        self._bots[str(bot_id)] = bot

    def record_connect_bot(self, user_id: str, bot_id: str) -> None:
        """Remember the bot of the latest /connect for a principal."""
        self._last_connect_bot[str(user_id)] = str(bot_id)

    def register_session_hook(
        self,
        provider_id: str,
        *,
        on_completed: Optional[SessionHook] = None,
        on_revoked: Optional[SessionHook] = None,
    ) -> None:
        """Register provider-specific session effects."""
        self._hooks[provider_id] = (on_completed, on_revoked)

    def set_login_coordinator(self, coordinator: Any, bot_id: Optional[str] = None) -> None:
        """Route staged-login completions to a pending-login coordinator.

        With ``bot_id`` the coordinator serves only that bot (completions carry the issuing bot's id), so several
        Telegram bots sharing one app each finalize their own attempts; without it the coordinator is the default.
        """
        if bot_id:
            self._login_coordinators[str(bot_id)] = coordinator
        else:
            self._login_coordinator = coordinator

    async def _resolve_target(
        self,
        event: ConnectionEvent,
        state_payload: Dict[str, Any],
    ) -> Optional[Tuple[int, "Bot"]]:
        extra = state_payload.get("extra")
        if isinstance(extra, dict):
            chat_id = extra.get("chat_id")
            bot_id = extra.get("bot_id")
            if chat_id is not None and bot_id is not None:
                bot = self._bots.get(str(bot_id))
                if bot is None:
                    self.logger.warning("Telegram bot %s is not attached; notification skipped", bot_id)
                    return None
                try:
                    return int(chat_id), bot
                except (TypeError, ValueError):
                    self.logger.warning("Invalid Telegram chat id for connection notification: %r", chat_id)
                    return None

        if self._identity_service is None:
            self.logger.warning(
                "Cannot resolve Telegram target without an identity service (user=%s provider=%s)",
                event.user_id,
                event.provider,
            )
            return None

        identity = await self._identity_service.get_identity(event.user_id, "telegram")
        if not identity or identity.get("provider_user_id") is None:
            self.logger.warning("No Telegram identity found for principal %s", event.user_id)
            return None

        try:
            telegram_id = int(identity["provider_user_id"])
        except (TypeError, ValueError):
            self.logger.warning(
                "Invalid Telegram identity for principal %s: %r",
                event.user_id,
                identity.get("provider_user_id"),
            )
            return None

        bot = None
        bot_id = self._last_connect_bot.get(str(event.user_id))
        if bot_id is not None:
            bot = self._bots.get(bot_id)
        if bot is None and len(self._bots) == 1:
            bot = next(iter(self._bots.values()))
        if bot is None:
            self.logger.warning(
                "Cannot resolve Telegram bot for principal %s (recorded_bot=%s attached=%d)",
                event.user_id,
                bot_id,
                len(self._bots),
            )
            return None
        return telegram_id, bot

    def _text(self, event: ConnectionEvent) -> Optional[str]:
        provider = OAuth2ProviderRegistry().get(event.provider)
        provider_name = provider.display_name if provider is not None else event.provider
        if event.kind == "connection.completed":
            return f"{provider_name} connected as {event.display_name}."
        if event.kind == "connection.revoked":
            return f"{provider_name} disconnected."
        if event.kind == "connection.refresh_failed":
            return f"{provider_name} access expired — /connect {event.provider} to reconnect."
        return None

    async def _run_hook(self, telegram_id: int, event: ConnectionEvent) -> None:
        hooks = self._hooks.get(event.provider)
        if hooks is None:
            return
        if event.kind == "connection.completed":
            hook = hooks[0]
        elif event.kind in {"connection.revoked", "connection.refresh_failed"}:
            hook = hooks[1]
        else:
            hook = None
        if hook is None:
            return
        try:
            result = hook(telegram_id, event)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 - a session hook must not fail event delivery
            self.logger.exception(
                "Telegram connection session hook failed (provider=%s kind=%s)",
                event.provider,
                event.kind,
            )

    def _mark_seen(self, key: Tuple[str, str, str, float]) -> None:
        """Record a delivered event key, evicting the oldest beyond ``_SEEN_MAX``."""
        self._seen[key] = None
        self._seen.move_to_end(key)
        while len(self._seen) > _SEEN_MAX:
            self._seen.popitem(last=False)

    async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:
        """Resolve target, send plain text, and run the session hook without raising."""
        extra = state_payload.get("extra")
        combined = isinstance(extra, dict) and extra.get("combined") is True
        coordinator = None
        if combined:
            coordinator = self._login_coordinators.get(str(extra.get("bot_id"))) or self._login_coordinator
        if coordinator is not None:
            try:
                await coordinator.on_provider_completed(event, state_payload)
            except Exception:  # noqa: BLE001 - lifecycle dispatch is independent of notification delivery
                self.logger.exception(
                    "Pending Telegram login completion dispatch failed (provider=%s)",
                    event.provider,
                )
        try:
            text = self._text(event)
            if text is None:
                self.logger.warning("Unsupported Telegram connection event kind: %s", event.kind)
                return

            dedupe_key = (event.kind, event.provider, event.user_id, event.occurred_at)
            if dedupe_key in self._seen:
                self._seen.move_to_end(dedupe_key)
                return

            target = await self._resolve_target(event, state_payload)
            if target is None:
                return
            telegram_id, bot = target
            await bot.send_message(chat_id=telegram_id, text=text, parse_mode=None)
            self._mark_seen(dedupe_key)
            if not combined:
                await self._run_hook(telegram_id, event)
        except Exception:  # noqa: BLE001 - notifier contract: log, never raise
            self.logger.exception(
                "Telegram connection notification failed (provider=%s kind=%s)",
                event.provider,
                event.kind,
            )


def get_or_create_telegram_notifier(
    app: MutableMapping[str, Any],
    *,
    identity_service: Optional[Any] = None,
) -> TelegramConnectionNotifier:
    """Return the app notifier, creating and registering it once."""
    notifier = app.get(_APP_KEY)
    if notifier is None:
        notifier = TelegramConnectionNotifier(identity_service=identity_service)
        app[_APP_KEY] = notifier
        ChannelNotifierRegistry().register(notifier)
    return notifier
