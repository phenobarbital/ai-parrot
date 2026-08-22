"""Contact capture, navrules eligibility, issuance and delivery.

These nodes are deterministic by design: an offer's eligibility is a business
rule the tenant edits, not a judgement a model makes. The rules engine is
navrules; see :mod:`parrot_saas.rules` for the ruleset construction.
"""
from __future__ import annotations

from typing import Any, Optional

from parrot.bots.flows.core import FlowContext
from parrot.bots.flows.core.types import DependencyResults

from ..models import (
    ContactCapture,
    ContactChannel,
    CouponDecision,
    CouponIssued,
    DeliveryResult,
)
from .base import CMNode, register_cm_node


@register_cm_node("cm.capture_contact")
class CaptureContactNode(CMNode):
    """Determine whether the guest can be reached with an offer.

    ``contact_available`` routes. It is deliberately conservative: a guest
    with no recorded marketing consent counts as unreachable, so the flow
    closes rather than issuing a coupon it may not lawfully deliver.

    Attributes:
        guest_repository: Optional repository resolving a guest's contact
            details. Absent in the skeleton.
    """

    guest_repository: Optional[Any] = None

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> ContactCapture:
        """Return what is known about reaching the guest."""
        shared = self.shared_state(ctx)
        contact = shared.get("contact")
        if isinstance(contact, ContactCapture):
            return contact

        review = shared.get("review")
        guest_id = getattr(review, "guest_id", "") or ""
        result = ContactCapture(
            contact_available=False,
            channel=ContactChannel.NONE,
            guest_id=guest_id,
        )
        shared["contact"] = result
        return result


@register_cm_node("cm.coupon_eligibility")
class CouponEligibilityNode(CMNode):
    """Evaluate the tenant's navrules ruleset for this guest and review.

    The counters a rule reads (``coupons_issued_90d`` and friends) are
    computed here, before evaluation, rather than inside a rule. That is what
    keeps every rule declarative — and therefore what keeps ``evaluate_sync``
    legal and the Rust backend usable.

    Attributes:
        ruleset: A compiled navrules ``RuleSet`` under ``Policy.FIRST_MATCH``.
            FIRST_MATCH is required: it is the only policy that returns the
            matching rule's ``result`` payload.
    """

    ruleset: Optional[Any] = None

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> CouponDecision:
        """Return the eligibility decision."""
        shared = self.shared_state(ctx)
        decision = shared.get("eligibility")
        if isinstance(decision, CouponDecision):
            return decision

        if self.ruleset is None:
            result = CouponDecision(
                eligible=False, reason="no ruleset configured"
            )
        else:
            result = self._evaluate(ctx)
        shared["eligibility"] = result
        return result

    def _evaluate(self, ctx: FlowContext) -> CouponDecision:
        """Run the ruleset and map its payload onto a decision.

        navrules has no concept of an action: a matching rule yields a
        ``result`` payload and the side effect is the caller's job. That
        separation is why issuance lives in the next node.
        """
        # Four dots: this module is parrot_saas.flows.community_manager.nodes,
        # so three would resolve to parrot_saas.flows.rules, which does not
        # exist. The mistake stayed invisible while the ruleset was always
        # None and this branch never ran.
        from ....rules.context import build_environment, build_eval_context

        shared = self.shared_state(ctx)
        eval_ctx = build_eval_context(shared)
        env = build_environment(shared)
        outcome = self.ruleset.evaluate_sync(eval_ctx, env)
        if not outcome.matched or not outcome.value:
            return CouponDecision(eligible=False, reason="no_rule_matched")
        payload = outcome.value
        rule = getattr(outcome, "rule", None)
        return CouponDecision(
            eligible=True,
            offer_code=str(payload.get("offer_code", "")),
            reason=str(payload.get("reason", "rule_matched")),
            rule_name=getattr(rule, "name", "") or "",
        )


@register_cm_node("cm.coupon_issue")
class CouponIssueNode(CMNode):
    """Issue a coupon for the decided offer.

    ``issued`` routes. An exhausted budget or a per-guest cap sets ``issued``
    to ``False`` with a reason and closes the run normally — that is a
    business outcome, not an error, so it must not reach the failure handler.

    Attributes:
        issuer: Optional coupon issuer service. Absent in the skeleton.
    """

    issuer: Optional[Any] = None

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> CouponIssued:
        """Issue a coupon, or explain why none was issued."""
        shared = self.shared_state(ctx)
        preset = shared.get("issued")
        if isinstance(preset, CouponIssued):
            return preset

        decision = shared.get("eligibility")
        if self.issuer is None:
            result = CouponIssued(
                issued=False,
                offer_code=getattr(decision, "offer_code", ""),
                reason="no issuer configured",
            )
        else:
            result = await self.issuer.issue(
                shared["tenant_id"],
                offer_code=decision.offer_code,
                guest_id=getattr(shared.get("contact"), "guest_id", ""),
                review_id=getattr(shared.get("review"), "review_id", ""),
            )
        shared["issued"] = result
        return result


@register_cm_node("cm.coupon_deliver")
class CouponDeliverNode(CMNode):
    """Deliver the issued coupon over the guest's contact channel.

    Attributes:
        delivery: Optional delivery service (async-notify backed).
        timeout: Wall-clock budget for the outbound send.
    """

    delivery: Optional[Any] = None
    timeout: float = 30.0

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> DeliveryResult:
        """Send the coupon and return the outcome."""
        shared = self.shared_state(ctx)
        issued = shared.get("issued")
        contact = shared.get("contact")
        channel = getattr(contact, "channel", ContactChannel.NONE)

        if self.delivery is None:
            result = DeliveryResult(
                delivered=False,
                channel=channel,
                reason="no delivery backend configured",
            )
        else:
            await self.with_timeout(
                self.delivery.send(shared["tenant_id"], contact, issued),
                self.timeout,
                "delivering the coupon",
            )
            result = DeliveryResult(delivered=True, channel=channel)
        shared["delivery"] = result
        return result


__all__ = (
    "CaptureContactNode",
    "CouponDeliverNode",
    "CouponEligibilityNode",
    "CouponIssueNode",
)
