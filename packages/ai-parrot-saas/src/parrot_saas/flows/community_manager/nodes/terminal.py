"""Terminal nodes: the success sink and the error fan-in.

``close`` is reached from six different places — a skipped triage, a blocked
guardrail, a guest with no contact channel, an ineligible guest, an exhausted
budget, and a delivered coupon. That OR-join is precisely why the flow runs in
the engine's explicit-edge mode: the definition-driven scheduler uses an
AND-join and would never fire it.
"""
from __future__ import annotations

from typing import Any

from parrot.bots.flows.core import FlowContext
from parrot.bots.flows.core.types import DependencyResults

from ..models import FailureSummary, RunSummary
from .base import CMNode, register_cm_node


@register_cm_node("cm.close")
class CloseNode(CMNode):
    """Summarise a completed run.

    Reached whichever way the run ended, including the paths that
    deliberately did nothing — a skipped review and a blocked reply are
    successful outcomes of the flow, not failures of it.
    """

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> RunSummary:
        """Return a summary of what the run did."""
        shared = self.shared_state(ctx)
        issued = shared.get("issued")
        publish = shared.get("publish")
        summary = RunSummary(
            review_id=getattr(shared.get("review"), "review_id", ""),
            outcome=self._outcome(shared),
            replied=bool(getattr(publish, "published", False)),
            coupon_issued=bool(getattr(issued, "issued", False)),
            coupon_code=getattr(issued, "coupon_code", "") or "",
        )
        shared["summary"] = summary
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
    """

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> FailureSummary:
        """Return a summary of the first failure recorded on the context."""
        shared = self.shared_state(ctx)
        errors = getattr(ctx, "errors", {}) or {}
        node_id, error = next(iter(errors.items()), ("", None))
        summary = FailureSummary(
            review_id=getattr(shared.get("review"), "review_id", ""),
            failed_node=node_id,
            error=f"{type(error).__name__}: {error}" if error else "",
        )
        shared["failure"] = summary
        return summary


__all__ = ("CloseNode", "FailureNode")
