"""Per-channel A2UI deep-link resume helper (Module 8, channel half).

Deep links on baked surfaces resume the ORIGINATING channel/session. TASK-1735 shipped
:class:`~parrot.outputs.a2ui.deeplink.DeepLinkService` and the web route; this helper
encapsulates the shared per-channel resume flow (consume → structured user message →
inject → friendly failure) used by the Telegram and MS Teams wrappers, so each wrapper
only needs a thin detection hook.

The action is injected as a **structured user message** (not dispatched) — action
dispatch / ActionRouter is FEAT-B.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Optional

from parrot.outputs.a2ui.deeplink import DeepLinkExpiredError, DeepLinkService

__all__ = ["ChannelDeepLinkResume", "build_structured_message"]

#: Friendly, payload-free landing message for expired/replayed tokens.
EXPIRED_MESSAGE = "This link has expired or was already used. Please request a new one."

#: Injector: (session_id, user_id, agent_id, query) -> Awaitable[Any].
Injector = Callable[..., Awaitable[Any]]


def build_structured_message(action_payload: dict[str, Any]) -> str:
    """Serialize a resumed action into a structured user-message query string.

    Mirrors the web route (TASK-1735): tagged so downstream recognizes it as an A2UI
    action resume rather than free-form user text.
    """
    return json.dumps(
        {"type": "a2ui_action_resume", "action": action_payload}, sort_keys=True
    )


class ChannelDeepLinkResume:
    """Shared per-channel deep-link resume flow for Telegram / MS Teams."""

    def __init__(
        self,
        service: DeepLinkService,
        *,
        channel: str,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.service = service
        self.channel = channel
        self.logger = logger or logging.getLogger(__name__)

    async def resume(self, token: str, *, inject: Injector) -> dict[str, Any]:
        """Consume ``token`` and inject the action into the original session.

        Args:
            token: The opaque deep-link token from the inbound channel event.
            inject: Async callable that injects the structured message into the
                originating session (``session_id``/``user_id``/``agent_id``/``query``).

        Returns:
            ``{"ok": True, "session_id": ..., "result": ...}`` on success, or
            ``{"ok": False, "reply": <friendly message>}`` on expired/replayed tokens.
        """
        if not token:
            return {"ok": False, "reply": EXPIRED_MESSAGE}
        try:
            payload = await self.service.consume(token)
        except DeepLinkExpiredError:
            self.logger.info(
                "A2UI %s deep-link resume rejected (expired/replayed token).", self.channel
            )
            return {"ok": False, "reply": EXPIRED_MESSAGE}

        query = build_structured_message(payload.action_payload)
        result = await inject(
            session_id=payload.session_id,
            user_id=payload.user_id,
            agent_id=payload.agent_id,
            query=query,
        )
        self.logger.info(
            "A2UI %s deep-link resumed session %s.", self.channel, payload.session_id
        )
        return {"ok": True, "session_id": payload.session_id, "result": result}
