"""Base class for escalation actions."""
from abc import ABC, abstractmethod
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import HumanInteraction, EscalationTier


class EscalationAction(ABC):
    """Abstract base for escalation logic that triggers external systems."""

    @abstractmethod
    async def execute(
        self,
        interaction: "HumanInteraction",
        tier: "EscalationTier",
    ) -> Dict[str, Any]:
        """Execute the escalation action.

        Returns metadata to be attached to the interaction/result.
        """
        ...
