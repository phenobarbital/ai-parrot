"""Terminal nodes: the success sink and the error fan-in.

``close`` is reached from six different places — a skipped triage, a blocked
guardrail, a guest with no contact channel, an ineligible guest, an exhausted
budget, and a delivered coupon. That OR-join is precisely why the flow runs in
the engine's explicit-edge mode: the definition-driven scheduler uses an
AND-join and would never fire it.
"""
from __future__ import annotations

from typing import Any, Optional

from navconfig.logging import logging
from parrot.bots.flows.core import FlowContext
from parrot.bots.flows.core.types import DependencyResults

from ..models import FailureSummary, RunSummary
from .base import CMNode, register_cm_node

logger = logging.getLogger("parrot_saas.flows.cm.terminal")

#: How a run's outcome maps onto the review's stored status.
#:
#: Only three states matter to someone reading a list of reviews: it was
#: answered, it was deliberately left alone, or something went wrong. The
#: richer ``outcome`` string stays on the run summary, where the detail is
#: useful without cluttering the review list.
_OUTCOME_STATUS = {
    "skipped": "skipped",
    "blocked": "skipped",
}


async def _set_review_status(
    repository: Optional[Any], tenant_id: str, review_id: str, status: str
) -> None:
    """Record where a review ended up.

    Never raises. The run is over by the time this runs, and losing the status
    write is a smaller problem than turning a completed run into a failed one
    — which would also mean the failure handler reporting a database blip as
    though the reply had gone wrong.
    """
    if repository is None or not review_id:
        return
    try:
        from ....reviews.models import ReviewStatus

        await repository.set_status(tenant_id, review_id, ReviewStatus(status))
    except Exception as exc:  # noqa: BLE001 - the run already finished
        logger.warning(
            "could not set review %s to %s: %s", review_id, status, exc
        )


@register_cm_node("cm.close")
class CloseNode(CMNode):
    """Summarise a completed run.

    Reached whichever way the run ended, including the paths that
    deliberately did nothing — a skipped review and a blocked reply are
    successful outcomes of the flow, not failures of it.

    Attributes:
        review_repository: Repository the review's terminal status is written
            to. Absent, the summary is still returned; the status write is
            bookkeeping, not the outcome.
    """

    review_repository: Optional[Any] = None

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> RunSummary:
        """Return a summary of what the run did, and record where it ended."""
        shared = self.shared_state(ctx)
        issued = shared.get("issued")
        publish = shared.get("publish")
        review = shared.get("review")
        outcome = self._outcome(shared)
        summary = RunSummary(
            review_id=getattr(review, "review_id", ""),
            outcome=outcome,
            replied=bool(getattr(publish, "published", False)),
            coupon_issued=bool(getattr(issued, "issued", False)),
            coupon_code=getattr(issued, "coupon_code", "") or "",
        )
        shared["summary"] = summary

        await _set_review_status(
            self.review_repository,
            shared.get("tenant_id") or getattr(review, "tenant_id", ""),
            summary.review_id,
            _OUTCOME_STATUS.get(outcome, "replied"),
        )
        return summary

    @staticmethod
    def _outcome(shared: dict[str, Any]) -> str:
        """Name the terminal outcome, for dashboards and audit rows."""
        triage = shared.get("triage")
        if getattr(triage, "action", None) is not None and (
            getattr(triage.action, "value", triage.action) == "skip"
        ):
            return "skipped"
        guardrail = shared.get("guardrail")
        status = getattr(guardrail, "status", None)
        if status is not None and getattr(status, "value", status) == "blocked":
            return "blocked"
        if getattr(shared.get("delivery"), "delivered", False):
            return "coupon_delivered"
        if getattr(shared.get("issued"), "issued", False):
            return "coupon_issued"
        if not getattr(shared.get("contact"), "contact_available", False):
            return "replied_no_contact"
        if not getattr(shared.get("eligibility"), "eligible", True):
            return "replied_not_eligible"
        return "replied"


@register_cm_node("cm.failure")
class FailureNode(CMNode):
    """Record which node raised and why.

    Every middle node has an ``on_error`` edge here, so this is the single
    place a run's failure is described. It never re-raises: the run has
    already failed, and swallowing here keeps the flow's terminal state
    reportable rather than losing it to a second exception.

    Attributes:
        review_repository: Repository the review is marked failed in, so a
            retry can find it without reading execution rows.
    """

    review_repository: Optional[Any] = None

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> FailureSummary:
        """Return a summary of the first failure recorded on the context."""
        shared = self.shared_state(ctx)
        review = shared.get("review")
        errors = getattr(ctx, "errors", {}) or {}
        node_id, error = next(iter(errors.items()), ("", None))
        summary = FailureSummary(
            review_id=getattr(review, "review_id", ""),
            failed_node=node_id,
            error=f"{type(error).__name__}: {error}" if error else "",
        )
        shared["failure"] = summary

        await _set_review_status(
            self.review_repository,
            shared.get("tenant_id") or getattr(review, "tenant_id", ""),
            summary.review_id,
            "failed",
        )
        return summary


__all__ = ("CloseNode", "FailureNode")
