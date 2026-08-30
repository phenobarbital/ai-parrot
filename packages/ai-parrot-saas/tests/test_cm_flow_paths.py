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
from parrot_saas.reviews.models import Guest
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
    """Run the flow with ``shared`` seeded, returning (result, executed).

    The seeded dict is updated with the run's final shared state on the way
    out, so a test can assert on what the nodes *wrote* — the eligibility
    context in particular — and not only on what they returned.
    """
    flow = build_community_manager_flow(tenant=tenant, **deps)
    ctx = FlowContext(initial_task="community-manager")
    ctx.shared_data.update(shared)
    result = await flow.run_flow(ctx)
    shared.update(ctx.shared_data)
    # ``completion_order`` rather than ``result.nodes``: the latter reports the
    # graph's final state in no particular order, so it can say *what* ran but
    # never *when*.
    shared["__completion_order__"] = list(ctx.completion_order)
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


async def test_a_rejected_draft_is_repaired_and_published(tenant) -> None:
    """The repair loop converges: round one is rejected, round two publishes.

    The fake drafter answers *from the prompt it is given* — it writes a clean
    reply only once it can see why the previous one was refused. So this test
    fails unless the guardrail's reasons genuinely reach the drafting prompt,
    which is the whole point of the loop and precisely what the node did not do
    before T15: it built its prompt from the review alone, produced the same
    draft twice, and every rejected review ended in ``blocked``.
    """

    class _Drafter:
        """Answers badly until told what was wrong."""

        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def invoke(self, task: str, **kwargs):
            self.prompts.append(task)
            if "banned phrase" in task:
                text = (
                    "We are truly sorry the food was cold and the service "
                    "slow, and we have raised both with the team who were on "
                    "that evening."
                )
            else:
                # Offering a discount in public is exactly what the guardrail
                # exists to catch.
                text = (
                    "Our apologies for the poor experience — here is a "
                    "discount for your next visit with us."
                )
            return type(
                "_Msg", (), {"output": text, "structured_output": text, "usage": None}
            )()

    class _Publisher:
        """Minimal ``ReviewSource.reply`` recording what went out."""

        def __init__(self) -> None:
            self.published: list[str] = []

        async def reply(self, tenant_id: str, external_id: str, text: str):
            self.published.append(text)
            return type("_Reply", (), {"external_reply_id": "ext-reply-1"})()

    drafter, publisher = _Drafter(), _Publisher()
    result, executed = await _run(
        tenant,
        {"review": _review()},
        reply_agent=drafter,
        review_source=publisher,
    )

    assert len(drafter.prompts) == 2
    assert "discount" in drafter.prompts[1]  # the rejected draft came back
    assert topo.PUBLISH_REPLY in executed
    assert result.responses[topo.GUARDRAIL].status == "approved"
    assert result.responses[topo.GUARDRAIL].attempt == 2
    assert len(publisher.published) == 1
    assert "discount" not in publisher.published[0]


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
# The rules engine, wired into the real graph
# ---------------------------------------------------------------------------


async def test_a_wired_ruleset_decides_eligibility(tenant) -> None:
    """The engine has to fit its consumer, not just its own tests.

    Every other path test seeds ``eligibility`` directly, so nothing else would
    notice if the node's call into navrules drifted — or if the context builder
    stopped producing the fields the rules read.
    """
    from parrot_saas.flows.community_manager.models import ContactCapture, ContactChannel
    from parrot_saas.rules.builder import build_ruleset

    ruleset = build_ruleset(
        [
            {
                "name": "recover_detractor",
                "priority": 100,
                "conditions": {"ctx.rating": {"lte": 2}, "ctx.has_contact": True},
                "result": {"offer_code": "RECOVER20", "reason": "detractor"},
            }
        ]
    )
    shared = {
        "review": _review(rating=1),
        "contact": ContactCapture(
            contact_available=True, channel=ContactChannel.EMAIL, guest_id="g-1"
        ),
        "timezone": tenant.timezone,
        "eligibility_ctx": {"rating": 1, "has_contact": True},
    }

    result, executed = await _run(tenant, shared, ruleset=ruleset)

    assert topo.COUPON_ELIGIBILITY in executed
    decision = result.responses[topo.COUPON_ELIGIBILITY]
    assert decision.eligible is True
    assert decision.offer_code == "RECOVER20"
    assert decision.rule_name == "recover_detractor"


async def test_a_wired_ruleset_can_decline(tenant) -> None:
    """"No offer" is a decision the graph routes on, not an error."""
    from parrot_saas.flows.community_manager.models import ContactCapture, ContactChannel
    from parrot_saas.rules.builder import build_ruleset

    ruleset = build_ruleset(
        [
            {
                "name": "recover_detractor",
                "priority": 100,
                "conditions": {"ctx.rating": {"lte": 2}},
                "result": {"offer_code": "RECOVER20"},
            }
        ]
    )
    shared = {
        "review": _review(rating=5),
        "contact": ContactCapture(
            contact_available=True, channel=ContactChannel.EMAIL, guest_id="g-1"
        ),
        "eligibility_ctx": {"rating": 5},
    }

    result, executed = await _run(tenant, shared, ruleset=ruleset)

    decision = result.responses[topo.COUPON_ELIGIBILITY]
    assert decision.eligible is False
    assert decision.reason == "no_rule_matched"
    assert topo.COUPON_ISSUE not in executed
    assert topo.CLOSE in executed


# ---------------------------------------------------------------------------
# The coupon issuer, wired into the real graph
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_wired_issuer_mints_a_real_coupon(
    tenant, test_dsn, unique_schema
) -> None:
    """The issuer has to fit its consumer, not just its own tests.

    Every other path test seeds ``issued`` directly, so nothing would notice if
    the node's call drifted from the issuer's signature — which is exactly the
    mistake that hid in the eligibility node until a ruleset was wired in.
    """
    from asyncdb import AsyncDB

    from parrot_saas.coupons.issuer import CouponIssuer
    from parrot_saas.coupons.models import CouponOfferCreate
    from parrot_saas.coupons.repository import CouponRepository
    from parrot_saas.db.schema import ensure_schema
    from parrot_saas.flows.community_manager.models import (
        ContactCapture,
        ContactChannel,
        CouponDecision,
    )

    conn = AsyncDB("pg", dsn=test_dsn)
    async with await conn.connection():
        await ensure_schema(conn, schema=unique_schema)
        await conn.execute(
            f"INSERT INTO {unique_schema}.tenants (tenant_id, name) "
            "VALUES ('bar-pepe', 'Bar Pepe')"
        )

    coupons = CouponRepository(test_dsn, schema=unique_schema)
    try:
        await coupons.create_offer(
            "bar-pepe",
            CouponOfferCreate(code="RECOVER20", discount_value=20, valid_days=30),
        )
        shared = {
            "review": _review(),
            "tenant_id": "bar-pepe",
            "contact": ContactCapture(
                contact_available=True,
                channel=ContactChannel.EMAIL,
                guest_id="",
            ),
            "eligibility": CouponDecision(
                eligible=True, offer_code="RECOVER20", reason="detractor"
            ),
        }

        result, executed = await _run(
            tenant, shared, issuer=CouponIssuer(coupons)
        )

        assert topo.COUPON_ISSUE in executed
        issued = result.responses[topo.COUPON_ISSUE]
        assert issued.issued is True
        assert issued.coupon_code.startswith("RECOVER20-")
        # The summary is what an operator reads, so the code has to reach it.
        assert result.responses[topo.CLOSE].coupon_code == issued.coupon_code
        assert len(await coupons.list_coupons("bar-pepe")) == 1
    finally:
        await coupons.aclose()
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


async def test_the_rules_see_the_real_review_with_nothing_seeded(tenant) -> None:
    """The vocabulary a tenant writes rules in must be filled by the flow.

    Every other rules test in this file hands ``eligibility_ctx`` to the graph
    ready-made, so none of them could notice that nothing populated it. This
    one seeds only the review and lets the flow do the rest — the same
    ``recover_detractor`` rule the documentation shows, matching a real
    one-star review because the intake, triage and publish results were
    translated into ``ctx.rating``, ``ctx.sentiment`` and
    ``ctx.reply_published``.
    """
    from parrot_saas.reviews.mock import MockReviewSource
    from parrot_saas.reviews.port import ReviewEvent
    from parrot_saas.rules.builder import DEFAULT_ELIGIBILITY_RULES, build_ruleset

    class _Guests:
        """A guest who consented, so the run reaches eligibility."""

        async def get(self, tenant_id, guest_id):
            return Guest(
                guest_id=guest_id,
                tenant_id=tenant_id,
                email="guest@example.com",
                consent_marketing=True,
                lifetime_visits=3,
            )

    source = MockReviewSource(seed_demo=False)
    source.seed("bar-pepe", ReviewEvent(source="mock", external_id="ext-1"))

    shared = {
        "review": _review(rating=1, guest_id="g-1"),
        "tenant_id": "bar-pepe",
        "timezone": tenant.timezone,
    }

    result, executed = await _run(
        tenant,
        shared,
        review_source=source,
        guest_repository=_Guests(),
        ruleset=build_ruleset(DEFAULT_ELIGIBILITY_RULES),
    )

    assert topo.COUPON_ELIGIBILITY in executed
    decision = result.responses[topo.COUPON_ELIGIBILITY]
    assert decision.eligible is True, shared.get("eligibility_ctx")
    assert decision.rule_name == "recover_detractor"

    # And the context the rules saw is published for whoever asks why.
    seen = shared["eligibility_ctx"]
    assert seen["rating"] == 1
    assert seen["reply_published"] is True
    assert seen["consent_marketing"] is True
    assert seen["lifetime_visits"] == 3


async def test_a_promoter_is_not_offered_the_detractor_coupon(tenant) -> None:
    """The mirror of the case above: the same rule must *not* fire."""
    from parrot_saas.reviews.mock import MockReviewSource
    from parrot_saas.reviews.port import ReviewEvent
    from parrot_saas.rules.builder import DEFAULT_ELIGIBILITY_RULES, build_ruleset

    class _Guests:
        async def get(self, tenant_id, guest_id):
            return Guest(
                guest_id=guest_id,
                tenant_id=tenant_id,
                email="guest@example.com",
                consent_marketing=True,
            )

    source = MockReviewSource(seed_demo=False)
    source.seed("bar-pepe", ReviewEvent(source="mock", external_id="ext-1"))

    result, executed = await _run(
        tenant,
        {
            "review": _review(rating=5, text="Wonderful evening.", guest_id="g-1"),
            "tenant_id": "bar-pepe",
        },
        review_source=source,
        guest_repository=_Guests(),
        ruleset=build_ruleset(DEFAULT_ELIGIBILITY_RULES),
    )

    assert result.responses[topo.COUPON_ELIGIBILITY].eligible is False
    assert topo.COUPON_ISSUE not in executed
    assert result.responses[topo.CLOSE].outcome == "replied_not_eligible"


async def test_a_delivered_coupon_closes_the_run(tenant) -> None:
    """The last edge of the branch, with a delivery service wired in."""
    from parrot_saas.flows.community_manager.models import (
        ContactCapture,
        ContactChannel,
        CouponDecision,
        CouponIssued,
    )

    class _Delivery:
        def __init__(self) -> None:
            self.calls: list = []

        async def send(self, tenant_id, contact, issued, *, business=""):
            self.calls.append((tenant_id, issued.coupon_code, business))
            return type("_R", (), {"delivered": True, "reason": ""})()

    delivery = _Delivery()
    shared = {
        "review": _review(),
        "tenant_id": "bar-pepe",
        "contact": ContactCapture(
            contact_available=True,
            channel=ContactChannel.EMAIL,
            guest_id="g-1",
        ),
        "eligibility": CouponDecision(eligible=True, offer_code="RECOVER20"),
        "issued": CouponIssued(
            issued=True, coupon_code="RECOVER20-7KQF9M", offer_code="RECOVER20"
        ),
    }

    result, executed = await _run(tenant, shared, delivery=delivery)

    assert topo.COUPON_DELIVER in executed
    assert result.responses[topo.COUPON_DELIVER].delivered is True
    assert result.responses[topo.CLOSE].outcome == "coupon_delivered"
    # The tenant's display name, not its slug, is what a guest reads.
    assert delivery.calls[0][2] == "Bar Pepe"


# ---------------------------------------------------------------------------
# The deterministic nodes against real repositories
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_deterministic_nodes_persist_what_they_did(
    tenant, test_dsn, unique_schema
) -> None:
    """One run, and everything it should leave behind.

    The unit tests drive each node alone; this proves they still line up when
    the engine dispatches them — the review moves to ``replied``, the reply
    attempt is on file with its text, and the guest resolved at ingest is the
    one the contact step found.
    """
    from asyncdb import AsyncDB

    from parrot_saas.db.schema import ensure_schema
    from parrot_saas.reviews.mock import MockReviewSource
    from parrot_saas.reviews.models import ReplyStatus, ReviewStatus
    from parrot_saas.reviews.port import ReviewEvent
    from parrot_saas.reviews.repository import GuestRepository, ReviewRepository

    conn = AsyncDB("pg", dsn=test_dsn)
    async with await conn.connection():
        await ensure_schema(conn, schema=unique_schema)
        await conn.execute(
            f"INSERT INTO {unique_schema}.tenants (tenant_id, name) "
            "VALUES ('bar-pepe', 'Bar Pepe')"
        )

    reviews = ReviewRepository(test_dsn, schema=unique_schema)
    guests = GuestRepository(test_dsn, schema=unique_schema)
    source = MockReviewSource(seed_demo=False)
    try:
        guest = await guests.upsert(
            "bar-pepe", email="marta@example.com", display_name="Marta"
        )
        await guests.set_consent("bar-pepe", guest.guest_id, True)
        event = ReviewEvent(
            source="mock",
            external_id="ext-1",
            rating=1,
            text="Cold food and a long wait.",
        )
        source.seed("bar-pepe", event)
        stored, _ = await reviews.ingest(
            "bar-pepe", event, guest_id=guest.guest_id
        )

        shared = {"review": _review(review_id=stored.review_id)}
        result, executed = await _run(
            tenant,
            shared,
            review_source=source,
            review_repository=reviews,
            guest_repository=guests,
        )

        # Published, and recorded with the text that went out.
        assert topo.PUBLISH_REPLY in executed
        replies = await reviews.list_replies("bar-pepe", stored.review_id)
        assert len(replies) == 1
        assert replies[0].status == ReplyStatus.PUBLISHED
        assert replies[0].text == source.published[0][2]

        # The guest ingest resolved is the one contact capture found.
        contact = result.responses[topo.CAPTURE_CONTACT]
        assert contact.guest_id == guest.guest_id
        assert contact.contact_available is True
        assert "marta@example.com" not in contact.model_dump_json()

        # And the review ends up where an operator can see it.
        assert (
            await reviews.get("bar-pepe", stored.review_id)
        ).status == ReviewStatus.REPLIED
    finally:
        await reviews.aclose()
        await guests.aclose()
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


@pytest.mark.integration
async def test_a_guest_without_consent_gets_a_reply_and_no_coupon(
    tenant, test_dsn, unique_schema
) -> None:
    """The whole point of the contact step, end to end.

    An address on file is not permission to use it, so the run answers the
    review publicly and stops before the coupon branch.
    """
    from asyncdb import AsyncDB

    from parrot_saas.db.schema import ensure_schema
    from parrot_saas.reviews.mock import MockReviewSource
    from parrot_saas.reviews.port import ReviewEvent
    from parrot_saas.reviews.repository import GuestRepository, ReviewRepository

    conn = AsyncDB("pg", dsn=test_dsn)
    async with await conn.connection():
        await ensure_schema(conn, schema=unique_schema)
        await conn.execute(
            f"INSERT INTO {unique_schema}.tenants (tenant_id, name) "
            "VALUES ('bar-pepe', 'Bar Pepe')"
        )

    reviews = ReviewRepository(test_dsn, schema=unique_schema)
    guests = GuestRepository(test_dsn, schema=unique_schema)
    source = MockReviewSource(seed_demo=False)
    try:
        guest = await guests.upsert("bar-pepe", email="silent@example.com")
        event = ReviewEvent(source="mock", external_id="ext-2", rating=1, text="Bad.")
        source.seed("bar-pepe", event)
        stored, _ = await reviews.ingest(
            "bar-pepe", event, guest_id=guest.guest_id
        )

        result, executed = await _run(
            tenant,
            {"review": _review(review_id=stored.review_id)},
            review_source=source,
            review_repository=reviews,
            guest_repository=guests,
        )

        assert topo.PUBLISH_REPLY in executed
        assert topo.COUPON_ELIGIBILITY not in executed
        assert result.responses[topo.CLOSE].outcome == "replied_no_contact"
    finally:
        await reviews.aclose()
        await guests.aclose()
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


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


# ---------------------------------------------------------------------------
# The eight scenarios, as an ordered table
# ---------------------------------------------------------------------------
#
# The tests above each prove one branch, asserting membership: "close ran",
# "coupon_issue did not". This table asserts the *exact sequence* of every
# scenario in one place, which does two things membership cannot:
#
#   * an extra node — a coupon_issue that fires when it should not — shows up,
#     because the sequence is compared whole rather than probed;
#   * the file gains a readable specification of what the graph does, which is
#     the thing a person actually wants when asking "what happens to a
#     one-star review from a guest with no contact details?".
#
# The order is the completion order the scheduler produced, so it also pins
# the OR-join and skip-propagation behaviour: `close` appears once, after
# whichever branch reached it.


def _detractor_with_contact() -> dict:
    """Shared state for a one-star review from a reachable, consenting guest."""
    from parrot_saas.flows.community_manager.models import (
        ContactCapture,
        ContactChannel,
    )

    return {
        "review": _review(rating=1),
        "tenant_id": "bar-pepe",
        "contact": ContactCapture(
            contact_available=True,
            channel=ContactChannel.EMAIL,
            guest_id="g-1",
        ),
    }


SCENARIOS: dict[str, tuple[dict, tuple[str, ...]]] = {
    # 1. Nothing worth answering: triage skips straight to the terminal.
    "skipped_at_triage": (
        {"review": _review(rating=0, text="")},
        (topo.REVIEW_INTAKE, topo.TRIAGE, topo.CLOSE),
    ),
    # 2. A guest we cannot reach is answered publicly and nothing more.
    "replied_no_contact": (
        {"review": _review()},
        (
            topo.REVIEW_INTAKE,
            topo.TRIAGE,
            topo.REPLY_DRAFT,
            topo.GUARDRAIL,
            topo.PUBLISH_REPLY,
            topo.CAPTURE_CONTACT,
            topo.CLOSE,
        ),
    ),
    # 3. Reachable, but no rule matches: a reply and no offer.
    "replied_not_eligible": (
        {
            **_detractor_with_contact(),
            "eligibility": CouponDecision(eligible=False, reason="no_rule_matched"),
        },
        (
            topo.REVIEW_INTAKE,
            topo.TRIAGE,
            topo.REPLY_DRAFT,
            topo.GUARDRAIL,
            topo.PUBLISH_REPLY,
            topo.CAPTURE_CONTACT,
            topo.COUPON_ELIGIBILITY,
            topo.CLOSE,
        ),
    ),
    # 4. Eligible and issued, but the budget is spent — a decision, not a
    #    failure, so the run closes normally without reaching delivery.
    "budget_exhausted": (
        {
            **_detractor_with_contact(),
            "eligibility": CouponDecision(eligible=True, offer_code="RECOVER20"),
            "issued": CouponIssued(issued=False, reason="budget_exhausted"),
        },
        (
            topo.REVIEW_INTAKE,
            topo.TRIAGE,
            topo.REPLY_DRAFT,
            topo.GUARDRAIL,
            topo.PUBLISH_REPLY,
            topo.CAPTURE_CONTACT,
            topo.COUPON_ELIGIBILITY,
            topo.COUPON_ISSUE,
            topo.CLOSE,
        ),
    ),
    # 5. The whole happy path, delivery included.
    "coupon_delivered": (
        {
            **_detractor_with_contact(),
            "eligibility": CouponDecision(eligible=True, offer_code="RECOVER20"),
            "issued": CouponIssued(issued=True, coupon_code="RECOVER20-7KQF9M"),
        },
        (
            topo.REVIEW_INTAKE,
            topo.TRIAGE,
            topo.REPLY_DRAFT,
            topo.GUARDRAIL,
            topo.PUBLISH_REPLY,
            topo.CAPTURE_CONTACT,
            topo.COUPON_ELIGIBILITY,
            topo.COUPON_ISSUE,
            topo.COUPON_DELIVER,
            topo.CLOSE,
        ),
    ),
}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
async def test_the_flow_takes_exactly_the_expected_path(tenant, scenario) -> None:
    """Each scenario's completion order, whole rather than probed."""
    seed, expected = SCENARIOS[scenario]
    shared = dict(seed)

    await _run(tenant, shared)

    assert tuple(shared["__completion_order__"]) == expected


async def test_the_repair_loop_is_visible_in_the_completion_order(tenant) -> None:
    """The cycle is the one path that is not a flat sequence.

    ``completion_order`` records one entry per *completion*, not per node, so
    a bounded back-edge shows up as the pair repeating — which makes it the
    only place the loop can be observed directly rather than inferred from the
    guardrail's attempt counter. Three rounds here, then the bound converts
    ``revise`` into ``blocked`` and the run closes without publishing.
    """
    strict = TenantContext(
        tenant_id="bar-pepe",
        name="Bar Pepe",
        settings={"max_revise_rounds": 3, "banned_phrases": ["thank you", "sorry"]},
    )

    shared = {"review": _review()}
    result, _ = await _run(strict, shared)
    order = shared["__completion_order__"]

    assert result.responses[topo.GUARDRAIL].attempt == 3
    assert order.count(topo.REPLY_DRAFT) == 3
    assert order.count(topo.GUARDRAIL) == 3
    # Drafting and judging alternate; neither runs twice in a row.
    loop = [n for n in order if n in (topo.REPLY_DRAFT, topo.GUARDRAIL)]
    assert loop == [topo.REPLY_DRAFT, topo.GUARDRAIL] * 3
    assert topo.PUBLISH_REPLY not in order
    assert order[-1] == topo.CLOSE


async def test_a_failure_replaces_the_terminal_rather_than_joining_it(
    tenant,
) -> None:
    """``close`` and ``failure_handler`` are alternatives, never both.

    Worth pinning as an ordering fact: the run summary and the failure summary
    are read by different consumers, and a run that produced both would make
    "did this succeed?" unanswerable.
    """
    shared: dict = {}
    await _run(tenant, shared)

    assert shared["__completion_order__"] == [topo.FAILURE]
