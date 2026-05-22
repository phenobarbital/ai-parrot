"""Escalation action that opens a ticket in an external system.

Dispatches by ``tier.action_metadata["kind"]`` (or legacy ``"platform"``).
Supports Zammad in V1.

FEAT-194 — TASK-1276
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .base import EscalationAction
from .backends import ZammadBackend, ActionBackendError


class TicketAction(EscalationAction):
    """Dispatches ticket-creation escalation actions to Zammad (V1).

    The backend is selected by ``tier.action_metadata["kind"]`` (or the legacy
    ``"platform"`` key).  Supported kinds:

    - ``"zammad"`` → :class:`~parrot.human.actions.backends.ZammadBackend`

    Legacy ``platform="jira"`` is treated as ``"zammad"`` with a warning
    (Jira is not in V1).

    When a backend fails, the exception is caught and a dict with
    ``error=True`` is returned so the manager can advance to the next tier.

    Args:
        zammad_cfg: Keyword arguments forwarded to :class:`ZammadBackend.__init__`.
    """

    def __init__(
        self,
        *,
        zammad_cfg: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._zammad_cfg: Dict[str, Any] = zammad_cfg or {}
        self._cache: Dict[str, Any] = {}
        self.logger = logging.getLogger("parrot.human.actions.ticket")

    def _get_backend(self, kind: str):
        """Return a cached backend instance for the given *kind*.

        Args:
            kind: One of ``"zammad"``.

        Returns:
            The cached backend instance.

        Raises:
            ActionBackendError: When *kind* is unknown.
        """
        if kind in self._cache:
            return self._cache[kind]
        if kind == "zammad":
            self._cache[kind] = ZammadBackend(**self._zammad_cfg)
        else:
            raise ActionBackendError(f"TicketAction: unknown kind {kind!r}")
        return self._cache[kind]

    async def execute(self, interaction, tier) -> Dict[str, Any]:
        """Dispatch to the appropriate ticket backend.

        Reads ``tier.action_metadata["kind"]`` (or legacy ``"platform"``).
        The legacy ``platform="jira"`` case logs a warning and falls back
        to Zammad (Jira is deferred to V2).

        On backend failure, re-raises :class:`ActionBackendError` so the
        manager's ``_escalate_to_next_tier`` can advance the chain.

        Args:
            interaction: The human interaction being escalated.
            tier: The escalation tier providing ``action_metadata``.

        Returns:
            Backend result dict on success.

        Raises:
            ActionBackendError: When the backend fails, so the manager
                can advance to the next tier.
        """
        meta = tier.action_metadata
        # Support new "kind" key and legacy "platform" key
        kind: str = meta.get("kind") or meta.get("platform") or "zammad"

        # Legacy Jira mapping — V1 ships Zammad only
        if kind == "jira":
            self.logger.warning(
                "TicketAction: 'platform=jira' is not supported in V1; "
                "treating as 'zammad'. Migrate to kind='zammad' or wait for V2."
            )
            kind = "zammad"

        backend = self._get_backend(kind)
        try:
            return await backend.execute(interaction, tier)
        except ActionBackendError as exc:
            self.logger.error(
                "TicketAction backend failed (kind=%s): %s",
                kind,
                exc,
            )
            raise  # re-raise so manager._escalate_to_next_tier can advance the chain
