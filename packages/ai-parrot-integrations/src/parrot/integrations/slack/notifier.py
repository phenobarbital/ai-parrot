"""Provider-agnostic Slack connection notifier (FEAT-777 M2, AC-6).

Registered in the process-wide ``ChannelNotifierRegistry`` by ``SlackAgentWrapper``. One notifier per
channel: with several Slack bots the last registered token wins (v1 limitation). Never writes identities.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from parrot.auth.oauth2.events import ConnectionEvent

logger = logging.getLogger(__name__)


class SlackConnectionNotifier:
    """DM a Slack user about connection lifecycle events for any provider."""

    channel = "slack"

    def __init__(self, bot_token: str) -> None:
        from slack_sdk.web.async_client import AsyncWebClient  # lazy, as SlackOAuthNotifier

        self._client = AsyncWebClient(token=bot_token)
        self.logger = logger

    async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:
        """Send the DM for ``completed`` / ``revoked`` / ``refresh_failed``; other kinds are ignored."""
        extra = dict(state_payload.get("extra") or {})
        slack_user_id = str(extra.get("slack_user_id") or state_payload.get("slack_user_id") or "")
        if not slack_user_id:
            self.logger.info("Skipping Slack connection notification without slack_user_id")
            return
        text = self._message(event, self._display_name(event.provider))
        if text is None:
            return
        try:
            await self._client.chat_postMessage(channel=slack_user_id, text=text)
        except Exception:  # noqa: BLE001 - DM failure must never break completion
            self.logger.exception("Failed to DM Slack user for %s %s", event.provider, event.kind)

    @staticmethod
    def _display_name(provider_id: str) -> str:
        from parrot.auth.oauth2.registry import OAuth2ProviderRegistry

        try:
            provider = OAuth2ProviderRegistry().get(provider_id)
        except Exception:  # noqa: BLE001 - unknown provider falls back to its id
            provider = None
        return getattr(provider, "display_name", None) or provider_id

    @staticmethod
    def _message(event: ConnectionEvent, name: str) -> Optional[str]:
        if event.kind == "connection.completed":
            return f"{name} connected as *{event.display_name}*."
        if event.kind == "connection.revoked":
            return f"{name} was disconnected."
        if event.kind == "connection.refresh_failed":
            text = f"{name} needs to be reconnected: use `/connect {event.provider}`."
            if event.reason:
                text += f" ({event.reason})"
            return text
        return None
