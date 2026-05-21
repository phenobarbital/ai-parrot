"""Escalation action that sends a one-way notification.

Dispatches by ``tier.action_metadata["kind"]`` to the appropriate backend.
Supports legacy ``action_metadata["channel"]`` key for backwards compatibility.

FEAT-194 — TASK-1276
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .base import EscalationAction
from .backends import EmailBackend, WebhookBackend, ActionBackendError


class NotifyAction(EscalationAction):
    """Dispatches one-way escalation notifications to Email or Webhook backends.

    The backend is selected by ``tier.action_metadata["kind"]`` (or the legacy
    ``"channel"`` key).  Supported kinds:

    - ``"email"`` → :class:`~parrot.human.actions.backends.EmailBackend`
    - ``"webhook"`` → :class:`~parrot.human.actions.backends.WebhookBackend`

    When a backend fails, the exception is caught and a dict with
    ``error=True`` is returned so the manager can advance to the next tier.

    Args:
        email_cfg: Keyword arguments forwarded to :class:`EmailBackend.__init__`.
        webhook_cfg: Keyword arguments forwarded to :class:`WebhookBackend.__init__`.
    """

    def __init__(
        self,
        *,
        email_cfg: Optional[Dict[str, Any]] = None,
        webhook_cfg: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._email_cfg: Dict[str, Any] = email_cfg or {}
        self._webhook_cfg: Dict[str, Any] = webhook_cfg or {}
        self._cache: Dict[str, Any] = {}
        self.logger = logging.getLogger("parrot.human.actions.notify")

    def _get_backend(self, kind: str):
        """Return a cached backend instance for the given *kind*.

        Args:
            kind: One of ``"email"``, ``"webhook"``.

        Returns:
            The cached backend instance.

        Raises:
            ActionBackendError: When *kind* is unknown.
        """
        if kind in self._cache:
            return self._cache[kind]
        if kind == "email":
            self._cache[kind] = EmailBackend(**self._email_cfg)
        elif kind == "webhook":
            self._cache[kind] = WebhookBackend(**self._webhook_cfg)
        else:
            raise ActionBackendError(f"NotifyAction: unknown kind {kind!r}")
        return self._cache[kind]

    async def execute(self, interaction, tier) -> Dict[str, Any]:
        """Dispatch to the appropriate notification backend.

        Reads ``tier.action_metadata["kind"]`` (or legacy ``"channel"``).
        On backend failure, returns ``{"message": ..., "error": True}``
        so the manager can advance to the next tier.

        Args:
            interaction: The human interaction being escalated.
            tier: The escalation tier providing ``action_metadata``.

        Returns:
            Backend result dict, or ``{"message": ..., "error": True}`` on failure.
        """
        meta = tier.action_metadata
        # Support both the new "kind" key and the legacy "channel" key
        kind: str = meta.get("kind") or meta.get("channel") or "email"

        try:
            backend = self._get_backend(kind)
            return await backend.execute(interaction, tier)
        except ActionBackendError as exc:
            self.logger.warning(
                "NotifyAction backend %r failed for interaction %s: %s",
                kind,
                getattr(interaction, "interaction_id", "?"),
                exc,
            )
            return {
                "message": f"[escalated:{kind}] failed: {exc}",
                "error": True,
            }
