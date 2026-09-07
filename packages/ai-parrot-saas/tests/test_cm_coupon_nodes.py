"""The coupon branch of the Community Manager flow, driven node by node.

The path tests prove the graph routes through this branch; these prove the
branch *decides* correctly. Two properties carry most of the weight:

* **The rules see the real review.** ``ELIGIBILITY_FIELDS`` publishes a
  vocabulary a tenant writes rules in, and until T16 nothing mapped the flow's
  objects onto it — a one-star review reached the engine as ``ctx.rating == 0``
  and the documented ``recover_detractor`` example could not fire. Every path
  test seeds ``eligibility_ctx`` by hand, which is exactly why none of them
  noticed.
* **Nothing in this branch fails the run.** The public reply is already out by
  the time any of it executes. A counter query that times out, a ruleset with
  a bad row, an issuer that raises, an e-mail that bounces — each closes the
  run with a reason rather than marking an answered review failed and inviting
  a retry that would publish the reply a second time.
"""
from __future__ import annotations

import logging

import pytest

from parrot_saas.flows.community_manager.models import (
    ContactCapture,
    ContactChannel,
    CouponDecision,
    CouponIssued,
    PublishResult,
    ReviewIntake,
    ReviewTriage,
    Sentiment,
    Severity,
    TriageAction,
)
from parrot_saas.flows.community_manager.nodes.coupon import (
    CaptureContactNode,
    CouponDeliverNode,
    CouponEligibilityNode,
    CouponIssueNode,
    build_eligibility_ctx,
)
from parrot_saas.rules.builder import build_ruleset
from parrot_saas.rules.context import NEVER_COUPONED_DAYS, build_eval_context


def _review(**overrides) -> ReviewIntake:
    """Build a normalised review."""
    payload = {
        "review_id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "bar-pepe",
        "source": "google",
        "external_id": "ext-1",
        "location_ref": "loc-7",
        "rating": 1,
        "text": "Cold food.",
        "language": "es",
    }
    payload.update(overrides)
    return ReviewIntake(**payload)


def _replied_shared(**extra) -> dict:
    """Shared state as it stands when the coupon branch begins."""
    shared = {
        "tenant_id": "bar-pepe",
        "review": _review(),
        "triage": ReviewTriage(
            action=TriageAction.REPLY,
            sentiment=Sentiment.NEGATIVE,
            severity=Severity.HIGH,
            language="es",
        ),
        "publish": PublishResult(published=True, external_reply_id="r-1"),
        "contact": ContactCapture(
            contact_available=True,
            channel=ContactChannel.EMAIL,
            guest_id="22222222-2222-2222-2222-222222222222",
        ),
    }
    shared.update(extra)
    return shared


class _History:
    """Stand-in for ``CouponRepository.guest_history``."""

    def __init__(self, issued: int = 0, days: int | None = None, *, fail=None):
        self.issued = issued
        self.days = days
        self.fail = fail
        self.calls: list = []

    async def guest_history(self, tenant_id, guest_id, *, window_days=90):
        self.calls.append((tenant_id, guest_id, window_days))
        if self.fail is not None:
            raise self.fail
        days, issued = self.days, self.issued

        class _H:
            issued_in_window = issued

            @staticmethod
            def days_since_last(*, never):
                return never if days is None else days

        return _H()


class _Guests:
    """Stand-in for ``GuestRepository``."""

    def __init__(self, guest=None, *, fail=None):
        self.guest = guest
        self.fail = fail

    async def get(self, tenant_id, guest_id):
        if self.fail is not None:
            raise self.fail
        return self.guest


class _Guest:
    """A stored guest."""

    def __init__(self, **kw):
        self.email = kw.get("email", "")
        self.phone = kw.get("phone", "")
        self.consent_marketing = kw.get("consent_marketing", False)
        self.lifetime_visits = kw.get("lifetime_visits", 0)


# ---------------------------------------------------------------------------
# The vocabulary the rules actually see
# ---------------------------------------------------------------------------


def test_the_review_reaches_the_rules_vocabulary():
    """A tenant writing ``ctx.rating`` must see the review's rating.

    This is the regression the whole task exists for: without the mapping,
    every review-derived field sits at its default and each rule mentioning
    one silently never matches.
    """
    ctx = build_eligibility_ctx(_replied_shared())

    assert ctx["rating"] == 1
    assert ctx["source"] == "google"
    assert ctx["location_ref"] == "loc-7"
    assert ctx["sentiment"] == "negative"
    assert ctx["severity"] == "high"
    assert ctx["language"] == "es"
    assert ctx["reply_published"] is True


def test_the_assembled_context_survives_flattening():
    """Assembling is only half of it — the values must reach the engine.

    ``EvalContext.flatten`` drops anything ``_as_scalar`` cannot flatten, so a
    field can be assembled correctly and still be invisible to a rule.
    """
    flat = build_eval_context(
        {"eligibility_ctx": build_eligibility_ctx(_replied_shared())}
    ).flatten(None)

    assert flat["ctx.rating"] == 1
    assert flat["ctx.sentiment"] == "negative"
    assert flat["ctx.reply_published"] is True


def test_an_unpublished_reply_is_visible_as_such():
    """"Reply went out" is a fact a rule gates the offer on."""
    shared = _replied_shared(publish=PublishResult(published=False))

    assert build_eligibility_ctx(shared)["reply_published"] is False


def test_the_contact_node_keeps_precedence_over_derived_values():
    """Consent is established by the contact node and must not be recomputed."""
    shared = _replied_shared(
        eligibility_ctx={"consent_marketing": True, "rating": 5}
    )

    ctx = build_eligibility_ctx(shared)

    assert ctx["consent_marketing"] is True
    assert ctx["rating"] == 5  # a caller pinning a value wins


@pytest.mark.asyncio
async def test_capture_contact_publishes_lifetime_visits():
    """``ctx.lifetime_visits`` has to come from somewhere."""
    node = CaptureContactNode(
        node_id="capture_contact",
        guest_repository=_Guests(
            _Guest(email="a@b.c", consent_marketing=True, lifetime_visits=7)
        ),
    )
    shared = {"tenant_id": "bar-pepe", "review": _review(guest_id="g-1")}

    result = await node.execute(shared, {})

    assert result.contact_available is True
    assert shared["eligibility_ctx"]["lifetime_visits"] == 7
    # The address itself never enters shared state.
    assert "a@b.c" not in str(shared)


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eligibility_matches_a_rule_on_the_real_review():
    """End to end through the node: no hand-seeded context anywhere."""
    ruleset = build_ruleset(
        [
            {
                "name": "recover_detractor",
                "priority": 100,
                "conditions": {
                    "ctx.rating": {"lte": 2},
                    "ctx.reply_published": True,
                    "ctx.coupons_issued_90d": {"lt": 1},
                },
                "result": {"offer_code": "RECOVER20", "reason": "detractor"},
            }
        ]
    )
    history = _History(issued=0)
    node = CouponEligibilityNode(
        node_id="coupon_eligibility", ruleset=ruleset, coupon_repository=history
    )
    shared = _replied_shared()

    decision = await node.execute(shared, {})

    assert decision.eligible is True
    assert decision.offer_code == "RECOVER20"
    assert decision.rule_name == "recover_detractor"
    assert history.calls[0][2] == 90


@pytest.mark.asyncio
async def test_the_anti_abuse_counter_declines_a_repeat_guest():
    """The counters are the point of precomputing them."""
    ruleset = build_ruleset(
        [
            {
                "name": "recover_detractor",
                "priority": 100,
                "conditions": {
                    "ctx.rating": {"lte": 2},
                    "ctx.coupons_issued_90d": {"lt": 1},
                },
                "result": {"offer_code": "RECOVER20"},
            }
        ]
    )
    node = CouponEligibilityNode(
        node_id="coupon_eligibility",
        ruleset=ruleset,
        coupon_repository=_History(issued=2, days=10),
    )
    shared = _replied_shared()

    decision = await node.execute(shared, {})

    assert decision.eligible is False
    assert decision.reason == "no_rule_matched"
    assert shared["eligibility_ctx"]["coupons_issued_90d"] == 2
    assert shared["eligibility_ctx"]["last_coupon_days_ago"] == 10


@pytest.mark.asyncio
async def test_a_guest_who_never_had_a_coupon_reads_as_never():
    """``None`` would vanish from the context; the sentinel does not."""
    node = CouponEligibilityNode(
        node_id="coupon_eligibility", coupon_repository=_History()
    )
    shared = _replied_shared()

    await node.execute(shared, {})

    assert shared["eligibility_ctx"]["last_coupon_days_ago"] == NEVER_COUPONED_DAYS


@pytest.mark.asyncio
async def test_an_unreadable_history_declines_instead_of_guessing(caplog):
    """A limit that cannot be checked must not be treated as satisfied.

    Assuming zero would let a database blip hand a repeat guest an unbounded
    number of offers. Declining costs one guest one coupon.
    """
    node = CouponEligibilityNode(
        node_id="coupon_eligibility",
        ruleset=build_ruleset(
            [
                {
                    "name": "always",
                    "priority": 1,
                    "conditions": {"ctx.rating": {"lte": 5}},
                    "result": {"offer_code": "ANY"},
                }
            ]
        ),
        coupon_repository=_History(fail=TimeoutError("pool exhausted")),
    )

    with caplog.at_level(logging.ERROR):
        decision = await node.execute(_replied_shared(), {})

    assert decision.eligible is False
    assert decision.reason == "eligibility_counters_unavailable"
    assert "declining rather than assuming" in caplog.text


@pytest.mark.asyncio
async def test_no_coupon_repository_is_not_an_unreadable_history():
    """The offline graph has no coupon domain at all; that is not a failure."""
    node = CouponEligibilityNode(
        node_id="coupon_eligibility",
        ruleset=build_ruleset(
            [
                {
                    "name": "always",
                    "priority": 1,
                    "conditions": {"ctx.rating": {"lte": 5}},
                    "result": {"offer_code": "ANY"},
                }
            ]
        ),
    )

    decision = await node.execute(_replied_shared(), {})

    assert decision.eligible is True


@pytest.mark.asyncio
async def test_a_broken_ruleset_closes_the_run_rather_than_failing_it(caplog):
    """A tenant's bad rule must not break every review they receive."""

    class _Broken:
        def evaluate_sync(self, ctx, env):
            raise RuntimeError("non-declarative rule in ruleset")

    node = CouponEligibilityNode(node_id="coupon_eligibility", ruleset=_Broken())

    with caplog.at_level(logging.ERROR):
        decision = await node.execute(_replied_shared(), {})

    assert decision.eligible is False
    assert decision.reason == "ruleset_error"


# ---------------------------------------------------------------------------
# Issuance
# ---------------------------------------------------------------------------


class _Issuer:
    """Stand-in for ``CouponIssuer``."""

    def __init__(self, result=None, *, fail=None):
        self.result = result or CouponIssued(issued=True, coupon_code="X-1")
        self.fail = fail
        self.calls: list = []

    async def issue(self, tenant_id, *, offer_code, guest_id="", review_id=""):
        self.calls.append((tenant_id, offer_code, guest_id, review_id))
        if self.fail is not None:
            raise self.fail
        return self.result


@pytest.mark.asyncio
async def test_issue_passes_the_decision_through_to_the_issuer():
    """The node's call has to match the issuer's signature."""
    issuer = _Issuer()
    node = CouponIssueNode(node_id="coupon_issue", issuer=issuer)
    shared = _replied_shared(
        eligibility=CouponDecision(eligible=True, offer_code="RECOVER20")
    )

    result = await node.execute(shared, {})

    assert result.issued is True
    tenant_id, offer_code, guest_id, review_id = issuer.calls[0]
    assert tenant_id == "bar-pepe"
    assert offer_code == "RECOVER20"
    assert guest_id == shared["contact"].guest_id
    assert review_id == shared["review"].review_id


@pytest.mark.asyncio
async def test_an_issuer_failure_closes_the_run_rather_than_failing_it(caplog):
    """The reply is already out; the review is not failed.

    Propagating would mark an answered review failed and invite a retry that
    republishes the reply.
    """
    node = CouponIssueNode(
        node_id="coupon_issue", issuer=_Issuer(fail=RuntimeError("db down"))
    )
    shared = _replied_shared(
        eligibility=CouponDecision(eligible=True, offer_code="RECOVER20")
    )

    with caplog.at_level(logging.ERROR):
        result = await node.execute(shared, {})

    assert result.issued is False
    assert result.reason == "issuer_error"
    assert result.offer_code == "RECOVER20"


@pytest.mark.asyncio
async def test_a_matched_rule_naming_no_offer_does_not_call_the_issuer():
    """A blank code is a round trip to a guaranteed 'unknown_offer'."""
    issuer = _Issuer()
    node = CouponIssueNode(node_id="coupon_issue", issuer=issuer)
    shared = _replied_shared(eligibility=CouponDecision(eligible=True))

    result = await node.execute(shared, {})

    assert result.issued is False
    assert result.reason == "no_offer_code"
    assert issuer.calls == []


@pytest.mark.asyncio
async def test_issue_works_without_an_explicit_tenant_id():
    """``tenant_id`` used to be a bare subscript, so its absence was a KeyError."""
    issuer = _Issuer()
    node = CouponIssueNode(node_id="coupon_issue", issuer=issuer)
    shared = _replied_shared(
        eligibility=CouponDecision(eligible=True, offer_code="X")
    )
    del shared["tenant_id"]

    await node.execute(shared, {})

    assert issuer.calls[0][0] == "bar-pepe"  # from the review


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


class _Delivery:
    """Stand-in for ``CouponDelivery``."""

    def __init__(self, receipt=None, *, fail=None):
        self.receipt = receipt
        self.fail = fail
        self.calls: list = []

    async def send(self, tenant_id, contact, issued, *, business=""):
        self.calls.append((tenant_id, contact, issued, business))
        if self.fail is not None:
            raise self.fail
        return self.receipt


class _Receipt:
    def __init__(self, delivered=True, reason=""):
        self.delivered = delivered
        self.reason = reason


@pytest.mark.asyncio
async def test_deliver_reports_the_receipt():
    """A successful send carries the channel through to the summary."""
    delivery = _Delivery(_Receipt())
    node = CouponDeliverNode(
        node_id="coupon_deliver", delivery=delivery, business_name="Bar Pepe"
    )
    shared = _replied_shared(issued=CouponIssued(issued=True, coupon_code="X-1"))

    result = await node.execute(shared, {})

    assert result.delivered is True
    assert result.channel == ContactChannel.EMAIL.value
    assert delivery.calls[0][3] == "Bar Pepe"


@pytest.mark.asyncio
async def test_a_refused_send_is_reported_with_its_reason():
    """A refusal is a decision the run closes on, carrying why."""
    node = CouponDeliverNode(
        node_id="coupon_deliver",
        delivery=_Delivery(_Receipt(False, "unsupported_channel:whatsapp")),
    )
    shared = _replied_shared(issued=CouponIssued(issued=True, coupon_code="X-1"))

    result = await node.execute(shared, {})

    assert result.delivered is False
    assert result.reason == "unsupported_channel:whatsapp"


@pytest.mark.asyncio
async def test_a_raising_delivery_service_does_not_fail_the_run():
    """The coupon exists and stays resendable; the review is not failed."""
    node = CouponDeliverNode(
        node_id="coupon_deliver", delivery=_Delivery(fail=OSError("smtp down"))
    )
    shared = _replied_shared(issued=CouponIssued(issued=True, coupon_code="X-1"))

    result = await node.execute(shared, {})

    assert result.delivered is False
    assert result.reason == "delivery_error:OSError"


@pytest.mark.asyncio
async def test_a_slow_delivery_is_bounded_by_the_node():
    """The scheduler enforces no timeout, so the node must."""
    import asyncio

    class _Slow:
        async def send(self, *a, **kw):
            await asyncio.sleep(0.5)

    node = CouponDeliverNode(
        node_id="coupon_deliver", delivery=_Slow(), timeout=0.05
    )
    shared = _replied_shared(issued=CouponIssued(issued=True, coupon_code="X-1"))

    result = await node.execute(shared, {})

    assert result.delivered is False
    assert result.reason.startswith("delivery_error:")
