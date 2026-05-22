"""Generic webhook backend using aiohttp.

FEAT-194 — TASK-1275
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

import aiohttp

from .base import ActionBackend, WebhookBackendError

if TYPE_CHECKING:
    from parrot.human.models import HumanInteraction, EscalationTier


class WebhookBackend(ActionBackend):
    """Posts an escalation payload to a configurable webhook endpoint.

    The webhook is expected to return a JSON body containing a ``deep_link``
    field pointing to the live-chat or external system session.

    Args:
        default_url: Fallback URL when ``action_metadata`` does not provide one.
        timeout_seconds: HTTP request timeout (default 10s).

    Payload POSTed to the webhook::

        {
            "interaction_id": "<uuid>",
            "question": "<question text>",
            "severity": "<low|normal|high|critical>",
            "user_id": "<source_agent or None>"
        }

    Expected response::

        {"deep_link": "https://livechat.example.com/sessions/abc123"}
    """

    def __init__(
        self,
        *,
        default_url: str = "",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._default_url = default_url
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.logger = logging.getLogger("parrot.human.actions.backends.webhook")

    async def execute(
        self,
        interaction: "HumanInteraction",
        tier: "EscalationTier",
    ) -> Dict[str, Any]:
        """POST escalation payload to the configured webhook.

        Args:
            interaction: The human interaction being escalated.
            tier: The escalation tier (reads ``action_metadata`` for ``url``).

        Returns:
            Dict with ``message`` containing the deep_link, and ``deep_link``.

        Raises:
            WebhookBackendError: On HTTP errors, non-2xx responses, or missing
                ``deep_link`` in the response body.
        """
        meta = tier.action_metadata
        url = meta.get("url") or self._default_url
        if not url:
            raise WebhookBackendError(
                "WebhookBackend: no 'url' provided in action_metadata and no "
                "default_url configured."
            )

        severity = getattr(interaction, "severity", None)
        payload: Dict[str, Any] = {
            "interaction_id": interaction.interaction_id,
            "question": interaction.question,
            "severity": str(severity) if severity is not None else "normal",
            "user_id": interaction.source_agent,
        }

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status not in range(200, 300):
                        body_text = await resp.text()
                        raise WebhookBackendError(
                            f"WebhookBackend: HTTP {resp.status} from {url}: "
                            f"{body_text[:200]}"
                        )
                    data = await resp.json()

        except aiohttp.ClientError as exc:
            raise WebhookBackendError(
                f"WebhookBackend: network error contacting {url}: {exc}"
            ) from exc

        deep_link: Optional[str] = data.get("deep_link")
        if not deep_link:
            raise WebhookBackendError(
                f"WebhookBackend: response from {url} did not contain 'deep_link'. "
                f"Got: {str(data)[:200]}"
            )

        self.logger.info(
            "WebhookBackend: live-chat deep_link obtained for interaction %s",
            interaction.interaction_id,
        )
        return {
            "message": f"[escalated:live_chat] {deep_link}",
            "deep_link": deep_link,
        }
