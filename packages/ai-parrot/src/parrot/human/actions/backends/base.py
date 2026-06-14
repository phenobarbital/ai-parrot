"""Abstract base class and exception hierarchy for escalation action backends.

FEAT-194 — TASK-1275
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.human.models import HumanInteraction, EscalationTier


class ActionBackendError(Exception):
    """Base exception raised by any ActionBackend on failure."""


class EmailBackendError(ActionBackendError):
    """Raised when the email backend fails to send a message."""


class NotifyBackendError(ActionBackendError):
    """Raised when the async-notify backend fails to deliver a notification."""


class ZammadBackendError(ActionBackendError):
    """Raised when the Zammad backend fails to create a ticket."""


class WebhookBackendError(ActionBackendError):
    """Raised when the webhook backend fails to post to the endpoint."""


class ActionBackend(ABC):
    """Abstract base class for concrete escalation action backends.

    Each backend receives a :class:`~parrot.human.models.HumanInteraction` and
    the :class:`~parrot.human.models.EscalationTier` whose
    ``action_metadata`` configures the specific backend parameters.

    Backends MUST:
    - Be fully async.
    - Return a dict containing at minimum ``{"message": "<string for LLM>"}``.
    - Raise a typed subclass of :class:`ActionBackendError` on failure (never
      swallow exceptions silently).
    - NOT log credentials or tokens.
    """

    @abstractmethod
    async def execute(
        self,
        interaction: "HumanInteraction",
        tier: "EscalationTier",
    ) -> Dict[str, Any]:
        """Execute the action for the given interaction and tier.

        Args:
            interaction: The ongoing human interaction (provides context,
                question text, interaction_id, severity, etc.).
            tier: The escalation tier being executed (provides
                ``action_metadata`` with backend-specific configuration).

        Returns:
            A dict with at minimum ``{"message": "<string for LLM>"}`` and
            any additional backend-specific keys (e.g. ``ticket_id``, ``url``).

        Raises:
            ActionBackendError: (or a typed subclass) on any failure.
        """
        ...
