"""PricingPolicy — derived per-seat cost policy (FEAT-783 M9, U4)."""

from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

PolicyKind = Literal["billed", "subscription", "estimate"]
_KINDS: frozenset[str] = frozenset({"billed", "subscription", "estimate"})


class PricingPolicy(BaseModel):
    """Derived per-seat cost policy for billed, subscription, or estimated usage."""

    kind: PolicyKind = "billed"

    @classmethod
    def from_label(cls, label: Optional[str]) -> "PricingPolicy":
        """Parse an event pricing-policy label, defaulting unknown values to billed.

        Args:
            label: Policy label emitted by the usage origin.

        Returns:
            The parsed policy, or the billed policy for missing/unknown labels.
        """
        if label is None:
            return cls()
        if label not in _KINDS:
            logger.debug("unknown pricing_policy %r; treating as billed", label)
            return cls()
        return cls(kind=label)  # type: ignore[arg-type]

    def apply(self, usd: Optional[float]) -> tuple[Optional[float], Optional[float]]:
        """Apply this policy to an already-computed USD value.

        Args:
            usd: The list-price cost computed at the usage origin or subscriber.

        Returns:
            A pair of reported USD and equivalent list-price USD.
        """
        if self.kind == "subscription":
            return 0.0, usd
        return usd, None
