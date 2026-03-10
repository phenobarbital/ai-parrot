"""Messaging platform hooks — Telegram, WhatsApp, MS Teams.

These hooks register aiohttp routes that receive incoming messages from
messaging platforms and re-emit them as ``HookEvent`` objects.  They
are designed to work alongside (not replace) the full integration
wrappers in ``parrot/integrations/``.

The wrapper classes handle bidirectional communication (receive + respond).
These hooks only handle the *trigger* side — when a message arrives,
they fire a ``HookEvent`` so the orchestrator can route it to an agent.
"""
import re
from typing import Any, List, Optional

from aiohttp import web

from .base import BaseHook
from .models import HookType, MessagingHookConfig


class _MessagingHookBase(BaseHook):
    """Shared logic for messaging platform hooks."""

    def __init__(self, config: MessagingHookConfig, **kwargs) -> None:
        super().__init__(
            name=config.name,
            enabled=config.enabled,
            target_type=config.target_type,
            target_id=config.target_id,
            metadata=config.metadata,
            **kwargs,
        )
        self._config = config
        self._trigger_keywords = config.trigger_keywords
        self._trigger_commands = config.trigger_commands
        self._trigger_re = re.compile(config.trigger_pattern) if config.trigger_pattern else None

    async def start(self) -> None:
        self.logger.info(f"MessagingHook '{self.name}' ({self._config.platform}) started")

    async def stop(self) -> None:
        self.logger.info(f"MessagingHook '{self.name}' ({self._config.platform}) stopped")

    def _matches_filter(self, text: str) -> bool:
        """Return True if the message text passes the configured filters."""
        if not any([self._trigger_keywords, self._trigger_commands, self._trigger_re]):
            return True  # No filters — accept everything

        if self._trigger_keywords:
            lower = text.lower()
            if any(kw.lower() in lower for kw in self._trigger_keywords):
                return True

        if self._trigger_commands:
            first_word = text.strip().split()[0] if text.strip() else ""
            if first_word.lstrip("/") in self._trigger_commands:
                return True

        if self._trigger_re and self._trigger_re.search(text):
            return True

        return False


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


class TelegramHook(_MessagingHookBase):
    """Receives Telegram messages via webhook and fires HookEvents.

    Works alongside ``TelegramAgentWrapper``.  When a message matches
    the configured filters, a ``HookEvent`` is emitted so the
    orchestrator can route it to an agent or crew.
    """

    hook_type = HookType.TELEGRAM

    def setup_routes(self, app: Any) -> None:
        url = self._config.url or f"/api/v1/hooks/telegram/{self.name}"
        app.router.add_post(url, self._handle_telegram)
        self.logger.info(f"Telegram hook route: POST {url}")

    async def _handle_telegram(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            message = data.get("message") or data.get("channel_post") or {}
            text = message.get("text", "")
            chat = message.get("chat", {})
            user = message.get("from", {})

            if not text or not self._matches_filter(text):
                return web.json_response({"ok": True, "filtered": True})

            event = self._make_event(
                event_type="telegram.message",
                payload={
                    "text": text,
                    "chat_id": chat.get("id"),
                    "chat_type": chat.get("type"),
                    "user_id": user.get("id"),
                    "username": user.get("username"),
                    "first_name": user.get("first_name"),
                    "message_id": message.get("message_id"),
                },
                task=text,
            )
            await self.on_event(event)
            return web.json_response({"ok": True})
        except Exception as exc:
            self.logger.error(f"Telegram hook error: {exc}")
            return web.json_response({"ok": False, "error": str(exc)}, status=500)


# ---------------------------------------------------------------------------
# WhatsApp
# ---------------------------------------------------------------------------


class WhatsAppHook(_MessagingHookBase):
    """Receives WhatsApp webhook POSTs from Meta Cloud API.

    Handles both the verification challenge (GET) and incoming
    message notifications (POST).
    """

    hook_type = HookType.WHATSAPP

    def __init__(self, config: MessagingHookConfig, **kwargs) -> None:
        super().__init__(config, **kwargs)
        self._verify_token = config.metadata.get("verify_token", "parrot_verify")

    def setup_routes(self, app: Any) -> None:
        url = self._config.url or f"/api/v1/hooks/whatsapp/{self.name}"
        app.router.add_get(url, self._handle_verify)
        app.router.add_post(url, self._handle_whatsapp)
        self.logger.info(f"WhatsApp hook routes: GET/POST {url}")

    async def _handle_verify(self, request: web.Request) -> web.Response:
        """Meta webhook verification challenge."""
        mode = request.query.get("hub.mode")
        token = request.query.get("hub.verify_token")
        challenge = request.query.get("hub.challenge")
        if mode == "subscribe" and token == self._verify_token:
            return web.Response(text=challenge, content_type="text/plain")
        return web.Response(status=403, text="Verification failed")

    async def _handle_whatsapp(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            entries = data.get("entry", [])
            for entry in entries:
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    messages = value.get("messages", [])
                    for msg in messages:
                        text = msg.get("text", {}).get("body", "")
                        if not text or not self._matches_filter(text):
                            continue
                        contact = (value.get("contacts") or [{}])[0]
                        event = self._make_event(
                            event_type="whatsapp.message",
                            payload={
                                "text": text,
                                "wa_id": msg.get("from"),
                                "message_id": msg.get("id"),
                                "timestamp": msg.get("timestamp"),
                                "contact_name": contact.get("profile", {}).get("name"),
                                "phone_number_id": value.get("metadata", {}).get("phone_number_id"),
                            },
                            task=text,
                        )
                        await self.on_event(event)
            return web.json_response({"ok": True})
        except Exception as exc:
            self.logger.error(f"WhatsApp hook error: {exc}")
            return web.json_response({"ok": False}, status=500)


# ---------------------------------------------------------------------------
# MS Teams
# ---------------------------------------------------------------------------


class MSTeamsHook(_MessagingHookBase):
    """Receives MS Teams Activity POSTs via Bot Framework webhook.

    Parses the incoming Activity JSON, extracts the message text,
    applies filters, and emits a HookEvent.  For full bidirectional
    Teams integration, use ``MSTeamsAgentWrapper`` instead.
    """

    hook_type = HookType.MSTEAMS

    def setup_routes(self, app: Any) -> None:
        url = self._config.url or f"/api/v1/hooks/msteams/{self.name}"
        app.router.add_post(url, self._handle_teams)
        self.logger.info(f"MS Teams hook route: POST {url}")

    async def _handle_teams(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            activity_type = data.get("type", "")
            text = data.get("text", "")

            # Only process message activities
            if activity_type != "message":
                return web.json_response({"ok": True, "skipped": True})

            # Strip @mention tags
            entities = data.get("entities", [])
            for entity in entities:
                if entity.get("type") == "mention":
                    mention_text = entity.get("text", "")
                    text = text.replace(mention_text, "").strip()

            if not text or not self._matches_filter(text):
                return web.json_response({"ok": True, "filtered": True})

            from_user = data.get("from", {})
            conversation = data.get("conversation", {})

            event = self._make_event(
                event_type="msteams.message",
                payload={
                    "text": text,
                    "activity_id": data.get("id"),
                    "user_id": from_user.get("id"),
                    "user_name": from_user.get("name"),
                    "conversation_id": conversation.get("id"),
                    "conversation_type": conversation.get("conversationType"),
                    "channel_id": data.get("channelId"),
                    "service_url": data.get("serviceUrl"),
                },
                task=text,
            )
            await self.on_event(event)
            return web.json_response({"ok": True})
        except Exception as exc:
            self.logger.error(f"MS Teams hook error: {exc}")
            return web.json_response({"ok": False}, status=500)
