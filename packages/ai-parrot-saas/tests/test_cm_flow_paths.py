"""End-to-end routing of the Community Manager flow.

The topology tests prove the graph is well-formed; these prove it *routes*.
Each case seeds the flow's shared state, runs the real scheduler, and asserts
which nodes executed — which is the only way to catch an OR-join that never
fires or a skip that fails to propagate.

No LLM, no database, no review platform: the nodes fall back to deterministic
behaviour when their dependencies are absent, which is exactly what makes the
whole graph testable offline.
"""
from __future__ import annotations

import pytest

from parrot.bots.flows.core import FlowContext
from parrot_saas.flows.community_manager import definition as topo
from parrot_saas.flows.community_manager.flow import build_community_manager_flow
from parrot_saas.flows.community_manager.models import (
    ContactCapture,
    ContactChannel,
    CouponDecision,
    CouponIssued,
    ReviewIntake,
)
from parrot_saas.tenancy.context import TenantContext


@pytest.fixture
def tenant() -> TenantContext:
    """A tenant allowing two drafting attempts."""
    return TenantContext(
        tenant_id="bar-pepe",
        name="Bar Pepe",
        settings={"max_revise_rounds": 2},
    )


def _review(**overrides) -> ReviewIntake:
    """Build a review, defaulting to a one-star detractor."""
    payload = {
        "review_id": "rev-1",
        "tenant_id": "bar-pepe",
        "source": "mock",
        "external_id": "ext-1",
        "rating": 1,
        "text": "Cold food and slow service.",
    }
    payload.update(overrides)
    return ReviewIntake(**payload)


async def _run(tenant: TenantContext, shared: dict, **deps):
    """Run the flow with ``shared`` seeded, returning (result, executed)."""
    flow = build_community_manager_flow(tenant=tenant, **deps)
    ctx = FlowContext(initial_task="community-manager")
    ctx.shared_data.update(shared)
    result = await flow.run_flow(ctx)
    return result, [n.node_id for n in result.nodes]


# ---------------------------------------------------------------------------
# Branch coverage
# ---------------------------------------------------------------------------


async def test_skipped_at_triage_closes_without_replying(tenant) -> None:
    """A review with nothing to act on closes without drafting."""
    review = _review(rating=0, text="")

    result, executed = await _run(tenant, {"review": review})

    assert topo.REPLY_DRAFT not in executed
    assert topo.CLOSE in executed
    assert result.responses[topo.CLOSE].outcome == "skipped"


async def test_reply_path_reaches_contact_capture(tenant) -> None:
    """A detractor is drafted, approved and published, then contact-checked."""
    result, executed = await _run(tenant, {"review": _review()})

    for node in (topo.REPLY_DRAFT, topo.GUARDRAIL, topo.PUBLISH_REPLY,
                 topo.CAPTURE_CONTACT, topo.CLOSE):
        assert node in executed, node


async def test_no_contact_closes_before_coupons(tenant) -> None:
    """Without a reachable guest the coupon branch must not run.

    Conservative by design: issuing an offer the platform cannot lawfully
    deliver is worse than issuing none.
    """
    _, executed = await _run(tenant, {"review": _review()})

    assert topo.COUPON_ELIGIBILITY not in executed
    assert topo.CLOSE in executed


async def test_contact_available_reaches_eligibility(tenant) -> None:
    """A reachable guest is evaluated against the coupon ruleset."""
    shared = {
        "review": _review(),
        "contact": ContactCapture(
            contact_available=True,
            channel=ContactChannel.EMAIL,
            guest_id="guest-1",
        ),
    }

    _, executed = await _run(tenant, shared)

    assert topo.COUPON_ELIGIBILITY in executed
    assert topo.COUPON_ISSUE not in executed  # no ruleset configured


async def test_ineligible_guest_closes_without_issuing(tenant) -> None:
    """An ineligible guest closes the run normally."""
    shared = {
        "review": _review(),
        "contact": ContactCapture(contact_available=True, guest_id="g"),
        "eligibility": CouponDecision(eligible=False, reason="cooldown"),
    }

    result, executed = await _run(tenant, shared)

    assert topo.COUPON_ISSUE not in executed
    assert result.responses[topo.CLOSE].outcome == "replied_not_eligible"


async def test_eligible_guest_issues_and_delivers(tenant) -> None:
    """The happy path runs through issuance and delivery to close."""
    shared = {
        "review": _review(),
        "contact": ContactCapture(
            contact_available=True,
            channel=ContactChannel.EMAIL,
            guest_id="guest-1",
        ),
        "eligibility": CouponDecision(
            eligible=True, offer_code="RECOVER20", reason="detractor_recovery"
        ),
        "issued": CouponIssued(
            issued=True, coupon_code="RC-ABC123", offer_code="RECOVER20"
        ),
    }

    result, executed = await _run(tenant, shared)

    assert topo.COUPON_ISSUE in executed
    assert topo.COUPON_DELIVER in executed
    summary = result.responses[topo.CLOSE]
    assert summary.coupon_issued is True
    assert summary.coupon_code == "RC-ABC123"


async def test_exhausted_budget_closes_instead_of_failing(tenant) -> None:
    """A budget refusal is a business outcome, not an error.

    It must close normally rather than routing to the failure handler, or
    every sold-out offer would look like an incident.
    """
    shared = {
        "review": _review(),
        "contact": ContactCapture(contact_available=True, guest_id="g"),
        "eligibility": CouponDecision(eligible=True, offer_code="RECOVER20"),
        "issued": CouponIssued(issued=False, reason="budget_exhausted"),
    }

    _, executed = await _run(tenant, shared)

    assert topo.COUPON_DELIVER not in executed
    assert topo.FAILURE not in executed
    assert topo.CLOSE in executed


# ---------------------------------------------------------------------------
# The bounded repair loop
# ---------------------------------------------------------------------------


async def test_guardrail_blocks_and_loop_terminates(tenant) -> None:
    """A draft that can never pass must not loop forever.

    The engine does not bound cycles; the guardrail node downgrades ``revise``
    to ``blocked`` once the attempt budget is spent. Without that rule this
    test would hang rather than fail, which is why the bound lives in the node
    and not on the edge.
    """
    strict = TenantContext(
        tenant_id="bar-pepe",
        name="Bar Pepe",
        settings={"max_revise_rounds": 2, "banned_phrases": ["thank you", "sorry"]},
    )

    result, executed = await _run(strict, {"review": _review()})

    assert topo.PUBLISH_REPLY not in executed
    assert topo.CLOSE in executed
    assert result.responses[topo.CLOSE].outcome == "blocked"


async def test_repair_loop_reenters_drafting(tenant) -> None:
    """The back-edge really does re-execute the drafting node."""
    strict = TenantContext(
        tenant_id="bar-pepe",
        name="Bar Pepe",
        settings={"max_revise_rounds": 3, "banned_phrases": ["thank you", "sorry"]},
    )

    result, _ = await _run(strict, {"review": _review()})

    assert result.responses[topo.GUARDRAIL].attempt == 3


# ---------------------------------------------------------------------------
# Failure fan-in
# ---------------------------------------------------------------------------


async def test_node_error_routes_to_failure_handler(tenant) -> None:
    """A raising node reaches the failure handler, not an unhandled crash."""
    result, executed = await _run(tenant, {})  # no review seeded -> intake raises

    assert topo.FAILURE in executed
    assert topo.CLOSE not in executed
    summary = result.responses[topo.FAILURE]
    assert summary.failed_node == topo.REVIEW_INTAKE
    assert "no review in shared_data" in summary.error


# ---------------------------------------------------------------------------
# The review source port, wired into the real graph
# ---------------------------------------------------------------------------


async def test_a_wired_review_source_actually_publishes(tenant) -> None:
    """The port has to fit its consumer, not just its own tests.

    Every other path test runs with ``review_source=None`` and the publish
    node's no-op fallback, so nothing else would notice if the adapter's
    ``reply`` signature drifted from the call the node makes.
    """
    from parrot_saas.reviews.mock import MockReviewSource
    from parrot_saas.reviews.port import ReviewEvent

    source = MockReviewSource(seed_demo=False)
    source.seed("bar-pepe", ReviewEvent(source="mock", external_id="ext-1"))

    result, executed = await _run(
        tenant, {"review": _review()}, review_source=source
    )

    assert topo.PUBLISH_REPLY in executed
    published = result.responses[topo.PUBLISH_REPLY]
    assert published.published is True
    assert published.external_reply_id == "mock-reply-1"
    assert source.published[0][:2] == ("bar-pepe", "ext-1")


# ---------------------------------------------------------------------------
# Checkpointing stays available
# ---------------------------------------------------------------------------


async def test_flow_with_checkpointing_enabled_still_builds(tenant) -> None:
    """``checkpoint=True`` must not fail at build time.

    ``_ensure_checkpointer`` exports the flow, so a callable predicate would
    raise here before any node ran. Building successfully is the proof that
    the CEL-only rule is being honoured.
    """
    flow = build_community_manager_flow(
        tenant=tenant, checkpoint=True, run_id="run-1"
    )

    assert flow.to_definition().flow == "cm.bar-pepe"
    assert flow.flow_id == "run-1"
