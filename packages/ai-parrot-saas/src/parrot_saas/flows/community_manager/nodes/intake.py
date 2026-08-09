"""Entry node: admit a normalised review into the flow.

Skeleton stage (T13): the review is read from the flow's shared state, where
the ingest handler places it after normalising and de-duplicating. Persisting
the row and resolving the guest arrive with the review repository (T14).
"""
from __future__ import annotations

from typing import Any

from parrot.bots.flows.core import FlowContext
from parrot.bots.flows.core.types import DependencyResults

from ..models import ReviewIntake
from .base import CMNode, register_cm_node


@register_cm_node("cm.review_intake")
class ReviewIntakeNode(CMNode):
    """Normalise the inbound review into a :class:`ReviewIntake`.

    The ingest handler has already verified the webhook signature and applied
    the ``(tenant_id, source, external_id)`` uniqueness constraint, so a
    duplicate never reaches the flow; this node only builds the typed payload
    the rest of the graph reads.
    """

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> ReviewIntake:
        """Return the review that started this run.

        Args:
            ctx: Flow execution context. ``shared_data["review"]`` carries the
                normalised payload placed there by the runner.
            deps: Upstream results (none — this is the entry node).
            **kwargs: Unused.

        Returns:
            The typed review payload.

        Raises:
            ValueError: If the runner did not seed a review.
        """
        shared = self.shared_state(ctx)
        payload = shared.get("review")
        if payload is None:
            raise ValueError(
                "no review in shared_data['review']; the runner must seed the "
                "normalised review before running the flow"
            )
        intake = (
            payload
            if isinstance(payload, ReviewIntake)
            else ReviewIntake(**payload)
        )
        shared["review"] = intake
        shared.setdefault("tenant_id", intake.tenant_id)
        return intake


__all__ = ("ReviewIntakeNode",)
