"""Contact capture, navrules eligibility, issuance and delivery.

These nodes are deterministic by design: an offer's eligibility is a business
rule the tenant edits, not a judgement a model makes. The rules engine is
navrules; see :mod:`parrot_saas.rules` for the ruleset construction.

Two things about this branch are worth stating before reading it.

**The rules see a context these nodes assemble, not the flow's objects.** A
tenant writes ``ctx.rating`` and ``ctx.reply_published``; the flow holds a
``ReviewIntake`` and a ``PublishResult``. :func:`build_eligibility_ctx` is that
translation, and it is the whole reason the published vocabulary means anything
at runtime — a field nobody maps is a field every rule mentioning it silently
fails to match on.

**Nothing here fails the run.** By the time this branch executes, the public
reply is already out. Marking the review failed because a counter query timed
out or an e-mail bounced would be a false report *and* an invitation to retry a
flow that would publish the reply a second time. Every step degrades to a
result with a reason and lets the run close normally.
"""
from __future__ import annotations

from typing import Any, Optional

from parrot.bots.flows.core import FlowContext
from parrot.bots.flows.core.types import DependencyResults

from navconfig.logging import logging

from ..models import (
    ContactCapture,
    ContactChannel,
    CouponDecision,
    CouponIssued,
    DeliveryResult,
    ReviewIntake,
)
from .base import CMNode, register_cm_node

logger = logging.getLogger("parrot_saas.flows.cm.coupon")


def _fingerprint(handle: str) -> str:
    """Return a stable, non-reversible marker for a contact handle.

    Flow results end up in execution rows; a guest's e-mail does not belong
    there. The digest still identifies the same guest across runs.
    """
    from parrot.security.audit_ledger import derive_key_fingerprint

    return derive_key_fingerprint(handle.strip().lower())


@register_cm_node("cm.capture_contact")
class CaptureContactNode(CMNode):
    """Determine whether the guest can lawfully be reached with an offer.

    ``contact_available`` routes, and the answer is deliberately conservative:
    **no recorded marketing consent means unreachable**, even when an address
    is on file. Sending a promotional message to someone who never agreed to
    receive one is a legal problem for the tenant, and the flow closing with a
    published reply and no coupon is a perfectly good outcome.

    The result carries a *fingerprint* of the contact handle rather than the
    handle itself. Flow results are persisted as execution rows, and putting a
    guest's e-mail in one would spread personal data into the audit log for no
    benefit — the fingerprint still lets two runs be recognised as the same
    guest.

    Attributes:
        guest_repository: Repository resolving a guest's contact details.
            Absent, the node reports the guest as unreachable, which keeps the
            graph runnable with no database and errs the safe way.
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
        tenant_id = shared.get("tenant_id") or getattr(review, "tenant_id", "")
        guest_id = getattr(review, "guest_id", "") or ""

        result, visits = await self._resolve(tenant_id, guest_id)
        shared["contact"] = result
        # The eligibility rules read these, and they are computed here because
        # a rule that had to look them up would stop being declarative.
        shared.setdefault("eligibility_ctx", {}).update(
            {
                "has_contact": result.contact_available,
                "contact_channel": result.channel,
                "consent_marketing": result.contact_available,
                "lifetime_visits": visits,
            }
        )
        return result

    async def _resolve(
        self, tenant_id: str, guest_id: str
    ) -> tuple[ContactCapture, int]:
        """Look the guest up and decide whether they may be contacted.

        Args:
            tenant_id: Owning tenant.
            guest_id: The guest resolved at ingest, if any.

        Returns:
            ``(capture, lifetime_visits)``. Any failure resolves to
            unreachable — the safe direction, since the alternative is
            messaging someone the tenant has no record of consenting.
        """
        if self.guest_repository is None or not guest_id:
            return (
                ContactCapture(
                    contact_available=False,
                    channel=ContactChannel.NONE,
                    guest_id=guest_id,
                ),
                0,
            )

        try:
            guest = await self.guest_repository.get(tenant_id, guest_id)
        except Exception as exc:  # noqa: BLE001 - unreachable is the safe answer
            logger.warning(
                "could not resolve guest %s for tenant %s: %s",
                guest_id,
                tenant_id,
                exc,
            )
            return ContactCapture(guest_id=guest_id), 0

        if guest is None:
            return ContactCapture(guest_id=guest_id), 0

        channel, handle = self._channel_for(guest)
        reachable = bool(handle) and bool(guest.consent_marketing)
        if handle and not guest.consent_marketing:
            logger.info(
                "guest %s has a contact handle but no marketing consent; "
                "closing without an offer",
                guest_id,
            )
        return (
            ContactCapture(
                contact_available=reachable,
                channel=channel if reachable else ContactChannel.NONE,
                guest_id=guest_id,
                handle_fingerprint=_fingerprint(handle) if handle else "",
            ),
            int(getattr(guest, "lifetime_visits", 0) or 0),
        )

    @staticmethod
    def _channel_for(guest: Any) -> tuple[ContactChannel, str]:
        """Pick how to reach a guest, preferring e-mail.

        E-mail first because it carries a rendered coupon and costs nothing;
        SMS is the fallback for a guest who only left a number.

        Args:
            guest: The stored guest.

        Returns:
            ``(channel, handle)``, or ``(NONE, "")`` when neither is on file.
        """
        if getattr(guest, "email", ""):
            return ContactChannel.EMAIL, guest.email
        if getattr(guest, "phone", ""):
            return ContactChannel.SMS, guest.phone
        return ContactChannel.NONE, ""


def build_eligibility_ctx(shared: dict[str, Any]) -> dict[str, Any]:
    """Translate the flow's objects into the vocabulary a tenant writes rules in.

    ``ELIGIBILITY_FIELDS`` publishes names like ``ctx.rating`` and
    ``ctx.reply_published``; the flow holds a :class:`ReviewIntake` and a
    ``PublishResult``. Nothing bridged the two before this function existed, so
    every rule reading a review field matched against that field's *default* —
    a one-star review arrived at the rules as ``ctx.rating == 0``, and the
    documented ``recover_detractor`` example could not fire. The path tests did
    not catch it because each of them seeds ``eligibility_ctx`` by hand.

    Values already present in ``shared["eligibility_ctx"]`` win: the contact
    node writes consent and reachability there, and a caller (a dry-run, a
    replay) may pin anything it likes.

    Args:
        shared: The flow's per-run shared state.

    Returns:
        The mapping to hand to ``build_eval_context``, in vocabulary terms.
    """
    review = shared.get("review")
    triage = shared.get("triage")
    publish = shared.get("publish")

    derived: dict[str, Any] = {}
    if isinstance(review, ReviewIntake):
        derived.update(
            {
                "rating": review.rating,
                "language": review.language,
                "source": review.source,
                "location_ref": review.location_ref,
            }
        )
    if triage is not None:
        derived.update(
            {
                "sentiment": _plain(getattr(triage, "sentiment", "")),
                "severity": _plain(getattr(triage, "severity", "")),
                # Triage refines the review's own language guess.
                "language": getattr(triage, "language", "")
                or derived.get("language", "en"),
            }
        )
    if publish is not None:
        derived["reply_published"] = bool(getattr(publish, "published", False))

    # Whatever the contact node (or a caller) already established wins.
    derived.update(shared.get("eligibility_ctx") or {})
    return derived


def _plain(value: Any) -> str:
    """Render an enum-or-string as its plain value, blank for ``None``."""
    return str(getattr(value, "value", value) or "")


@register_cm_node("cm.coupon_eligibility")
class CouponEligibilityNode(CMNode):
    """Evaluate the tenant's navrules ruleset for this guest and review.

    Two jobs, in order. First it assembles the context the rules read — the
    review's own fields, what triage concluded, whether the public reply
    actually went out, and the anti-abuse counters. Then it evaluates.

    **The counters are queried here, never by a rule.** That is what keeps
    every rule a declarative ``ConditionRule``, which is in turn what keeps
    ``evaluate_sync`` legal and the native backend reachable. It also means the
    lookup's failure mode is this node's problem, and the answer is to decline:
    a rule saying "at most one coupon per guest per quarter" that cannot be
    evaluated must not be treated as satisfied. Declining costs a guest one
    offer; guessing costs the tenant an unbounded number of them.

    Attributes:
        ruleset: A compiled navrules ``RuleSet`` under ``Policy.FIRST_MATCH``.
            FIRST_MATCH is required: it is the only policy that returns the
            matching rule's ``result`` payload.
        coupon_repository: Source of the anti-abuse counters. Absent — the
            offline graph, with no coupon domain at all — the counters keep
            their vocabulary defaults, which is different from a repository
            that is present and failing.
        history_window_days: Window the ``coupons_issued_90d`` counter covers.
            Configurable, but the vocabulary name says 90, so moving it is a
            deliberate act rather than a default someone drifts.
    """

    ruleset: Optional[Any] = None
    coupon_repository: Optional[Any] = None
    history_window_days: int = 90

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> CouponDecision:
        """Return the eligibility decision."""
        shared = self.shared_state(ctx)
        decision = shared.get("eligibility")
        if isinstance(decision, CouponDecision):
            return decision

        eligibility_ctx = build_eligibility_ctx(shared)
        counters, available = await self._counters(shared)
        eligibility_ctx.update(counters)
        # Published so a dry-run, an audit row or an operator asking "why did
        # this guest get a coupon?" sees exactly what the rules saw.
        shared["eligibility_ctx"] = eligibility_ctx

        if not available:
            result = CouponDecision(
                eligible=False, reason="eligibility_counters_unavailable"
            )
        elif self.ruleset is None:
            result = CouponDecision(
                eligible=False, reason="no ruleset configured"
            )
        else:
            result = self._evaluate(shared)
        shared["eligibility"] = result
        return result

    async def _counters(
        self, shared: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        """Compute the anti-abuse counters for this guest.

        Args:
            shared: The flow's shared state.

        Returns:
            ``(counters, available)``. ``available`` is ``False`` only when a
            repository was configured and could not answer — the case where
            declining is the safe direction. No repository at all, or an
            anonymous review with no guest, are ordinary situations and leave
            the vocabulary defaults in place.
        """
        from ....rules.context import NEVER_COUPONED_DAYS

        guest_id = getattr(shared.get("contact"), "guest_id", "") or ""
        if self.coupon_repository is None or not guest_id:
            return {}, True

        try:
            history = await self.coupon_repository.guest_history(
                shared.get("tenant_id")
                or getattr(shared.get("review"), "tenant_id", ""),
                guest_id,
                window_days=self.history_window_days,
            )
        except Exception as exc:  # noqa: BLE001 - decline rather than guess
            logger.error(
                "could not read the coupon history of guest %s (%s); "
                "declining rather than assuming they have had none",
                guest_id,
                exc,
            )
            return {}, False

        return {
            "coupons_issued_90d": history.issued_in_window,
            "last_coupon_days_ago": history.days_since_last(
                never=NEVER_COUPONED_DAYS
            ),
        }, True

    def _evaluate(self, shared: dict[str, Any]) -> CouponDecision:
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

        eval_ctx = build_eval_context(shared)
        env = build_environment(shared)
        try:
            outcome = self.ruleset.evaluate_sync(eval_ctx, env)
        except Exception as exc:  # noqa: BLE001 - a bad rule is not a failed run
            # ``evaluate_sync`` raises on a non-declarative rule. The write API
            # rejects those, but a row predating that check — or written
            # straight to the database — must not take down every review this
            # tenant receives.
            logger.error(
                "evaluating the eligibility ruleset failed (%s); "
                "closing without an offer",
                exc,
            )
            return CouponDecision(eligible=False, reason="ruleset_error")

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

    An issuer *exception* is treated the same way, which is the less obvious
    half. The issuance runs in a transaction, so a failure leaves nothing
    behind; what it would leave behind if it propagated is a review marked
    failed even though its public reply went out, and a retry that would
    publish that reply again. Reporting "no coupon, because the issuer failed"
    is both true and safe.

    Attributes:
        issuer: Coupon issuance service. Absent, nothing is issued and the run
            closes with a reason — which is what lets the graph run with no
            coupon domain at all.
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
        offer_code = getattr(decision, "offer_code", "") or ""
        if self.issuer is None:
            result = CouponIssued(
                issued=False,
                offer_code=offer_code,
                reason="no issuer configured",
            )
        elif not offer_code:
            # A rule matched but named no offer. Calling the issuer with a
            # blank code would just be an "unknown_offer" round trip.
            result = CouponIssued(issued=False, reason="no_offer_code")
        else:
            result = await self._issue(shared, offer_code)
        shared["issued"] = result
        return result

    async def _issue(self, shared: dict[str, Any], offer_code: str) -> CouponIssued:
        """Call the issuer, turning a failure into a decision."""
        try:
            return await self.issuer.issue(
                shared.get("tenant_id")
                or getattr(shared.get("review"), "tenant_id", ""),
                offer_code=offer_code,
                guest_id=getattr(shared.get("contact"), "guest_id", ""),
                review_id=getattr(shared.get("review"), "review_id", ""),
            )
        except Exception as exc:  # noqa: BLE001 - see the class docstring
            logger.error(
                "issuing %s failed (%s); the review was still answered",
                offer_code,
                exc,
            )
            return CouponIssued(
                issued=False, offer_code=offer_code, reason="issuer_error"
            )


@register_cm_node("cm.coupon_deliver")
class CouponDeliverNode(CMNode):
    """Deliver the issued coupon over the guest's contact channel.

    The node never sees the guest's address: :class:`ContactCapture` carries
    only a fingerprint, and the delivery service reads the handle from the
    guest repository at send time. That keeps a personal e-mail out of the
    flow's shared state and therefore out of the execution rows it becomes.

    A failed send closes the run rather than failing it. The coupon exists and
    stays ``issued`` with an event saying why it did not go out, so it can be
    resent; failing the run would instead mark an answered review as failed.

    Attributes:
        delivery: Delivery service. Absent, the coupon is issued but not sent.
        business_name: Display name used in the message.
        timeout: Wall-clock budget for the outbound send.
    """

    delivery: Optional[Any] = None
    business_name: str = ""
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
            result = await self._send(shared, contact, issued, channel)
        shared["delivery"] = result
        return result

    async def _send(
        self,
        shared: dict[str, Any],
        contact: Any,
        issued: Any,
        channel: Any,
    ) -> DeliveryResult:
        """Hand the coupon to the delivery service, tolerating a failure."""
        tenant_id = shared.get("tenant_id") or getattr(
            shared.get("review"), "tenant_id", ""
        )
        try:
            receipt = await self.with_timeout(
                self.delivery.send(
                    tenant_id,
                    contact,
                    issued,
                    business=self.business_name or tenant_id,
                ),
                self.timeout,
                "delivering the coupon",
            )
        except Exception as exc:  # noqa: BLE001 - the coupon is already minted
            logger.warning(
                "delivering coupon %s failed: %s",
                getattr(issued, "coupon_code", "?"),
                exc,
            )
            return DeliveryResult(
                delivered=False,
                channel=channel,
                reason=f"delivery_error:{type(exc).__name__}",
            )

        # A service that answers with a bare bool is honoured too, so a tenant
        # deployment can plug in its own sender without importing a receipt.
        delivered = bool(getattr(receipt, "delivered", receipt))
        return DeliveryResult(
            delivered=delivered,
            channel=channel if delivered else ContactChannel.NONE,
            reason=str(getattr(receipt, "reason", "") or ""),
        )


__all__ = (
    "CaptureContactNode",
    "CouponDeliverNode",
    "CouponEligibilityNode",
    "CouponIssueNode",
    "build_eligibility_ctx",
)
