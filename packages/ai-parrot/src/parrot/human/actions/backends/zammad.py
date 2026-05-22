"""Zammad ticket backend using aiohttp.

FEAT-194 — TASK-1275
"""
from __future__ import annotations

import logging
from typing import Any, Dict, TYPE_CHECKING

import aiohttp

from .base import ActionBackend, ZammadBackendError

if TYPE_CHECKING:
    from parrot.human.models import HumanInteraction, EscalationTier


class ZammadBackend(ActionBackend):
    """Creates a support ticket in a Zammad instance.

    Args:
        base_url: The base URL of the Zammad instance,
            e.g. ``"https://support.example.com"``.
        api_token: Zammad API token for ``Authorization: Token token=...`` auth.
        default_group: Fallback group/queue name when ``action_metadata`` does
            not specify one.
        timeout_seconds: HTTP request timeout (default 10s).

    Example ``action_metadata`` consumed by this backend::

        {
            "kind": "zammad",
            "queue": "Support",
            "title_template": "HITL Escalation: {interaction.question[:60]}",
        }
    """

    def __init__(
        self,
        *,
        base_url: str = "",
        api_token: str = "",
        default_group: str = "Support",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token
        self._default_group = default_group
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.logger = logging.getLogger("parrot.human.actions.backends.zammad")

    async def execute(
        self,
        interaction: "HumanInteraction",
        tier: "EscalationTier",
    ) -> Dict[str, Any]:
        """Create a Zammad ticket for the given interaction.

        Args:
            interaction: The human interaction being escalated.
            tier: The escalation tier (reads ``action_metadata`` for ``queue``,
                ``title_template``).

        Returns:
            Dict with ``message``, ``ticket_id``, and ``url``.

        Raises:
            ZammadBackendError: On HTTP errors or non-2xx responses.
        """
        meta = tier.action_metadata
        group = meta.get("queue") or self._default_group
        title_template = meta.get(
            "title_template",
            "HITL Escalation: {question}",
        )
        question_snippet = (interaction.question or "")[:80]
        try:
            title = title_template.format(
                interaction=interaction,
                tier=tier,
                question=question_snippet,
            )
        except (KeyError, AttributeError):
            title = f"HITL Escalation: {question_snippet}"

        body_lines = [
            f"Interaction ID: {interaction.interaction_id}",
            f"Question: {interaction.question}",
        ]
        if interaction.context:
            body_lines.append(f"Context: {interaction.context}")
        severity = getattr(interaction, "severity", None)
        if severity is not None:
            body_lines.append(f"Severity: {severity}")
        body = "\n".join(body_lines)

        payload: Dict[str, Any] = {
            "title": title,
            "group": group,
            "customer": interaction.source_agent or "parrot-hitl",
            "article": {
                "subject": title,
                "body": body,
                "type": "note",
                "internal": False,
            },
        }

        headers = {
            "Authorization": f"Token token={self._api_token}",
            "Content-Type": "application/json",
        }

        endpoint = f"{self._base_url}/api/v1/tickets"

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(
                    endpoint, json=payload, headers=headers
                ) as resp:
                    if resp.status not in range(200, 300):
                        body_text = await resp.text()
                        raise ZammadBackendError(
                            f"ZammadBackend: HTTP {resp.status} from {endpoint}: "
                            f"{body_text[:200]}"
                        )
                    data = await resp.json()

        except aiohttp.ClientError as exc:
            raise ZammadBackendError(
                f"ZammadBackend: network error contacting {endpoint}: {exc}"
            ) from exc

        ticket_id = data.get("id", "unknown")
        ticket_url = f"{self._base_url}/#ticket/zoom/{ticket_id}"

        self.logger.info(
            "ZammadBackend: ticket %s created for interaction %s",
            ticket_id,
            interaction.interaction_id,
        )
        return {
            "message": (
                f"[escalated:ticket:zammad] Ticket #{ticket_id} opened. {ticket_url}"
            ),
            "ticket_id": ticket_id,
            "url": ticket_url,
        }
