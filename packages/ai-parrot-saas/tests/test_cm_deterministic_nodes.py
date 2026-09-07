"""The deterministic Community Manager nodes, driven directly.

The flow-path tests prove the graph routes; these prove each node *decides*
correctly, which is where the business rules actually live. No engine, no
scheduler — a plain dict stands in for the shared state, which is what
``CMNode.shared_state`` accepts precisely so a node can be tested alone.
"""
from __future__ import annotations

import pytest

from parrot_saas.flows.community_manager.models import (
    ContactChannel,
    GuardrailStatus,
    PublishResult,
    ReplyDraft,
    ReviewIntake,
)
from parrot_saas.flows.community_manager.nodes.coupon import CaptureContactNode
from parrot_saas.flows.community_manager.nodes.intake import ReviewIntakeNode
from parrot_saas.flows.community_manager.nodes.reply import (
    BLOCKED_PATTERNS,
    GuardrailNode,
    PublishReplyNode,
)
from parrot_saas.flows.community_manager.nodes.terminal import (
    CloseNode,
    FailureNode,
)
from parrot_saas.reviews.models import Guest, ReplyStatus, Review, ReviewStatus
from parrot_saas.reviews.port import ReviewReply, ReviewSourceError

GOOD_REPLY = (
    "We are sorry your visit fell short of what we aim for, and we would "
    "very much like to put it right on your next visit."
)


def _review(**overrides) -> ReviewIntake:
    """Build a normalised review."""
    payload = {
        "review_id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "bar-pepe",
        "source": "mock",
        "external_id": "ext-1",
        "rating": 1,
        "text": "Cold food.",
    }
    payload.update(overrides)
    return ReviewIntake(**payload)


class _Reviews:
    """Recording stand-in for ``ReviewRepository``."""

    def __init__(self, stored: Review | None = None, *, fail: bool = False) -> None:
        self.stored = stored
        self.fail = fail
        self.statuses: list = []
        self.replies: list = []

    async def set_status(self, tenant_id, review_id, status):
        if self.fail:
            raise RuntimeError("database is down")
        self.statuses.append((tenant_id, review_id, getattr(status, "value", status)))
        return self.stored

    async def get(self, tenant_id, review_id):
        return self.stored

    async def record_reply(self, tenant_id, review_id, **kwargs):
        if self.fail:
            raise RuntimeError("database is down")
        self.replies.append((tenant_id, review_id, kwargs))


class _Guests:
    """Recording stand-in for ``GuestRepository``."""

    def __init__(self, guest: Guest | None = None, *, fail: bool = False) -> None:
        self.guest = guest
        self.fail = fail

    async def get(self, tenant_id, guest_id):
        if self.fail:
            raise RuntimeError("database is down")
        return self.guest


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------


async def test_intake_seeds_the_context_for_later_nodes() -> None:
    """Tenant and timezone, without which the rules judge weekends in UTC."""
    node = ReviewIntakeNode(
        node_id="review_intake", tenant_id="bar-pepe", timezone="Europe/Madrid"
    )
    shared = {"review": _review()}

    await node.execute(shared, {})

    assert shared["tenant_id"] == "bar-pepe"
    assert shared["timezone"] == "Europe/Madrid"


async def test_intake_reads_the_guest_back_from_the_row() -> None:
    """The one field worth a round trip.

    Ingest resolves the guest; a stale copy in shared state would send the
    coupon branch hunting for contact details already on file.
    """
    stored = Review(
        review_id="11111111-1111-1111-1111-111111111111",
        tenant_id="bar-pepe",
        guest_id="22222222-2222-2222-2222-222222222222",
        rating=1,
        text="Cold food.",
    )
    node = ReviewIntakeNode(node_id="review_intake", review_repository=_Reviews(stored))
    shared = {"review": _review(guest_id="")}

    intake = await node.execute(shared, {})

    assert intake.guest_id == "22222222-2222-2222-2222-222222222222"


async def test_intake_marks_the_review_in_progress() -> None:
    """So a list of reviews shows what is being worked on."""
    reviews = _Reviews(Review(review_id="r", tenant_id="bar-pepe"))
    node = ReviewIntakeNode(node_id="review_intake", review_repository=reviews)

    await node.execute({"review": _review()}, {})

    assert reviews.statuses[0][2] == ReviewStatus.IN_PROGRESS.value


async def test_intake_survives_a_database_blip() -> None:
    """The row records the run; it is not the run's input.

    A brief outage must not cost the guest their reply.
    """
    node = ReviewIntakeNode(
        node_id="review_intake", review_repository=_Reviews(fail=True)
    )
    shared = {"review": _review()}

    intake = await node.execute(shared, {})

    assert intake.review_id == "11111111-1111-1111-1111-111111111111"


async def test_intake_without_a_review_is_loud() -> None:
    """A run with nothing to act on is a bug in the runner, not a no-op."""
    node = ReviewIntakeNode(node_id="review_intake")

    with pytest.raises(ValueError, match="no review"):
        await node.execute({}, {})


# ---------------------------------------------------------------------------
# Guardrail
# ---------------------------------------------------------------------------


def _guardrail(**kwargs) -> GuardrailNode:
    """Build a guardrail node."""
    return GuardrailNode(node_id="guardrail", **kwargs)


async def test_a_clean_draft_is_approved() -> None:
    """The happy path, and the text carried forward to publication."""
    node = _guardrail()
    shared = {"draft": ReplyDraft(text=GOOD_REPLY, attempt=1)}

    verdict = await node.execute(shared, {})

    assert verdict.status == GuardrailStatus.APPROVED.value
    assert verdict.text == GOOD_REPLY


@pytest.mark.parametrize(
    "phrase",
    ["discount", "coupon", "refund", "on the house", "as an AI", "[name]"],
)
async def test_a_public_reply_may_not_promise_or_leak(phrase: str) -> None:
    """Each pattern is a specific way a published reply does damage.

    Announcing a discount publicly turns a private recovery gesture into a
    standing promise to anyone who complains; promising a refund commits money
    in public; a model tell embarrasses the customer in front of theirs.
    """
    node = _guardrail(max_revise_rounds=1)
    draft = ReplyDraft(text=f"{GOOD_REPLY} Here is a {phrase}.", attempt=1)

    verdict = await node.execute({"draft": draft}, {})

    assert verdict.status != GuardrailStatus.APPROVED.value
    assert any(phrase.lower() in r.lower() for r in verdict.reasons)


async def test_a_tenant_cannot_switch_off_the_built_in_rules() -> None:
    """Their list is added to the built-in one, never replaces it."""
    node = _guardrail(banned_phrases=("mediocre",), max_revise_rounds=1)

    house = await node.execute(
        {"draft": ReplyDraft(text=f"{GOOD_REPLY} mediocre", attempt=1)}, {}
    )
    builtin = await node.execute(
        {"draft": ReplyDraft(text=f"{GOOD_REPLY} refund", attempt=1)}, {}
    )

    assert house.status != GuardrailStatus.APPROVED.value
    assert builtin.status != GuardrailStatus.APPROVED.value


async def test_a_curt_reply_is_refused() -> None:
    """Three words under a one-star review reads as dismissal."""
    node = _guardrail()

    verdict = await node.execute({"draft": ReplyDraft(text="Sorry.", attempt=1)}, {})

    assert verdict.status != GuardrailStatus.APPROVED.value


async def test_every_violation_is_reported_at_once() -> None:
    """So a revision fixes everything, rather than finding the next problem."""
    node = _guardrail(max_revise_rounds=5)
    draft = ReplyDraft(text="A discount and a refund.", attempt=1)

    verdict = await node.execute({"draft": draft}, {})

    assert len(verdict.reasons) >= 3  # too short, discount, refund


async def test_the_repair_loop_is_bounded_here() -> None:
    """The engine does not bound cycles; this node does.

    Once the budget is spent a failing draft becomes ``blocked``, which is the
    edge that ends the loop.
    """
    node = _guardrail(max_revise_rounds=2)
    bad = f"{GOOD_REPLY} refund"

    first = await node.execute({"draft": ReplyDraft(text=bad, attempt=1)}, {})
    second = await node.execute({"draft": ReplyDraft(text=bad, attempt=2)}, {})

    assert first.status == GuardrailStatus.REVISE.value
    assert second.status == GuardrailStatus.BLOCKED.value
    assert "revision budget exhausted" in second.reasons


async def test_the_guardrail_needs_a_draft() -> None:
    """Reaching it without one is a graph bug worth surfacing."""
    with pytest.raises(ValueError, match="without a draft"):
        await _guardrail().execute({}, {})


def test_the_blocked_patterns_cover_the_three_failure_families() -> None:
    """Money, offers and model tells — stated so a trim is deliberate."""
    joined = " ".join(BLOCKED_PATTERNS)

    assert "refund" in joined
    assert "coupon" in joined
    assert "as an ai" in joined


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


class _Source:
    """Recording stand-in for a ``ReviewSource``."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published: list = []

    async def reply(self, tenant_id, external_id, text):
        if self.fail:
            raise ReviewSourceError("the platform refused the reply")
        self.published.append((tenant_id, external_id, text))
        return ReviewReply(external_reply_id="mock-reply-1", source="mock")


async def test_publishing_records_the_attempt() -> None:
    """The published text is the first thing anyone asks to see."""
    reviews, source = _Reviews(), _Source()
    node = PublishReplyNode(
        node_id="publish_reply", review_source=source, review_repository=reviews
    )
    shared = {
        "review": _review(),
        "tenant_id": "bar-pepe",
        "guardrail": type("V", (), {"text": GOOD_REPLY})(),
        "draft": ReplyDraft(text=GOOD_REPLY, attempt=2),
    }

    result = await node.execute(shared, {})

    assert result.published is True
    assert result.external_reply_id == "mock-reply-1"
    _, _, kwargs = reviews.replies[0]
    assert kwargs["status"] == ReplyStatus.PUBLISHED
    assert kwargs["attempt"] == 2
    assert kwargs["text"] == GOOD_REPLY


async def test_a_refused_publication_is_recorded_then_raised() -> None:
    """The run failed and should be retried — but the attempt is evidence.

    Recording before re-raising matters because the failure handler summarises
    the run without knowing what text was attempted.
    """
    reviews, source = _Reviews(), _Source(fail=True)
    node = PublishReplyNode(
        node_id="publish_reply", review_source=source, review_repository=reviews
    )
    shared = {
        "review": _review(),
        "tenant_id": "bar-pepe",
        "draft": ReplyDraft(text=GOOD_REPLY, attempt=1),
    }

    with pytest.raises(ReviewSourceError):
        await node.execute(shared, {})

    _, _, kwargs = reviews.replies[0]
    assert kwargs["status"] == ReplyStatus.FAILED
    assert "refused" in kwargs["reason"]


async def test_a_failed_recording_does_not_undo_a_published_reply() -> None:
    """The guest already has it; losing the audit row is the smaller problem."""
    node = PublishReplyNode(
        node_id="publish_reply",
        review_source=_Source(),
        review_repository=_Reviews(fail=True),
    )
    shared = {
        "review": _review(),
        "tenant_id": "bar-pepe",
        "draft": ReplyDraft(text=GOOD_REPLY, attempt=1),
    }

    result = await node.execute(shared, {})

    assert result.published is True


async def test_no_source_configured_records_but_does_not_publish() -> None:
    """What keeps the whole graph runnable with no review platform."""
    reviews = _Reviews()
    node = PublishReplyNode(node_id="publish_reply", review_repository=reviews)
    shared = {
        "review": _review(),
        "tenant_id": "bar-pepe",
        "draft": ReplyDraft(text=GOOD_REPLY, attempt=1),
    }

    result = await node.execute(shared, {})

    assert result.published is False
    assert reviews.replies[0][2]["status"] == ReplyStatus.FAILED


# ---------------------------------------------------------------------------
# Contact capture
# ---------------------------------------------------------------------------


def _capture(guests=None) -> CaptureContactNode:
    """Build a contact-capture node."""
    return CaptureContactNode(node_id="capture_contact", guest_repository=guests)


async def test_a_consenting_guest_with_an_email_is_reachable() -> None:
    """E-mail first: it carries a rendered coupon and costs nothing."""
    guest = Guest(
        guest_id="g1", email="marta@example.com", consent_marketing=True
    )
    shared = {"review": _review(guest_id="g1"), "tenant_id": "bar-pepe"}

    result = await _capture(_Guests(guest)).execute(shared, {})

    assert result.contact_available is True
    assert result.channel == ContactChannel.EMAIL.value


async def test_a_phone_only_guest_falls_back_to_sms() -> None:
    """The fallback for someone who only left a number."""
    guest = Guest(guest_id="g1", phone="+34600111222", consent_marketing=True)
    shared = {"review": _review(guest_id="g1"), "tenant_id": "bar-pepe"}

    result = await _capture(_Guests(guest)).execute(shared, {})

    assert result.channel == ContactChannel.SMS.value


async def test_no_consent_means_unreachable_even_with_an_address() -> None:
    """The rule this node exists to enforce.

    Messaging someone who never agreed is a legal problem for the tenant, and
    closing with a published reply and no coupon is a fine outcome.
    """
    guest = Guest(
        guest_id="g1", email="marta@example.com", consent_marketing=False
    )
    shared = {"review": _review(guest_id="g1"), "tenant_id": "bar-pepe"}

    result = await _capture(_Guests(guest)).execute(shared, {})

    assert result.contact_available is False
    assert result.channel == ContactChannel.NONE.value


async def test_the_contact_handle_is_never_carried_in_the_result() -> None:
    """Flow results become execution rows; an e-mail does not belong there."""
    guest = Guest(
        guest_id="g1", email="marta@example.com", consent_marketing=True
    )
    shared = {"review": _review(guest_id="g1"), "tenant_id": "bar-pepe"}

    result = await _capture(_Guests(guest)).execute(shared, {})

    assert "marta@example.com" not in result.model_dump_json()
    assert len(result.handle_fingerprint) == 64


async def test_the_same_handle_fingerprints_the_same() -> None:
    """Two runs for one guest have to be recognisable as the same guest."""
    guest = Guest(guest_id="g1", email="Marta@Example.com", consent_marketing=True)
    shared = {"review": _review(guest_id="g1"), "tenant_id": "bar-pepe"}
    first = await _capture(_Guests(guest)).execute(dict(shared), {})

    guest2 = Guest(guest_id="g1", email="marta@example.com", consent_marketing=True)
    second = await _capture(_Guests(guest2)).execute(dict(shared), {})

    assert first.handle_fingerprint == second.handle_fingerprint


async def test_capture_publishes_what_the_rules_will_read() -> None:
    """Computed here so an eligibility rule stays declarative."""
    guest = Guest(guest_id="g1", email="a@b.c", consent_marketing=True)
    shared = {"review": _review(guest_id="g1"), "tenant_id": "bar-pepe"}

    await _capture(_Guests(guest)).execute(shared, {})

    assert shared["eligibility_ctx"]["has_contact"] is True
    assert shared["eligibility_ctx"]["consent_marketing"] is True


@pytest.mark.parametrize(
    "guests", [None, _Guests(None), _Guests(fail=True)], ids=["absent", "missing", "down"]
)
async def test_anything_unknown_resolves_to_unreachable(guests) -> None:
    """Every uncertain path errs the same way, which is the safe way."""
    shared = {"review": _review(guest_id="g1"), "tenant_id": "bar-pepe"}

    result = await _capture(guests).execute(shared, {})

    assert result.contact_available is False


# ---------------------------------------------------------------------------
# Terminal nodes
# ---------------------------------------------------------------------------


async def test_close_records_that_the_review_was_answered() -> None:
    """So a list of reviews shows what happened without reading run rows."""
    reviews = _Reviews()
    node = CloseNode(node_id="close", review_repository=reviews)
    shared = {
        "review": _review(),
        "tenant_id": "bar-pepe",
        "publish": PublishResult(published=True),
    }

    summary = await node.execute(shared, {})

    assert summary.replied is True
    assert reviews.statuses[0][2] == ReviewStatus.REPLIED.value


@pytest.mark.parametrize(
    ("outcome_key", "value", "expected"),
    [("triage", "skip", ReviewStatus.SKIPPED.value)],
)
async def test_a_deliberate_non_reply_is_skipped_not_failed(
    outcome_key, value, expected
) -> None:
    """A review the flow chose to leave alone is a success, not an incident."""
    reviews = _Reviews()
    shared = {
        "review": _review(),
        "tenant_id": "bar-pepe",
        outcome_key: type("T", (), {"action": value})(),
    }

    await CloseNode(node_id="close", review_repository=reviews).execute(shared, {})

    assert reviews.statuses[0][2] == expected


async def test_failure_marks_the_review_failed() -> None:
    """A retry can then find it without reading execution rows."""
    from parrot.bots.flows.core import FlowContext

    reviews = _Reviews()
    node = FailureNode(node_id="failure_handler", review_repository=reviews)
    ctx = FlowContext(initial_task="community-manager")
    ctx.shared_data.update({"review": _review(), "tenant_id": "bar-pepe"})
    ctx.errors["publish_reply"] = RuntimeError("boom")

    summary = await node.execute(ctx, {})

    assert summary.failed_node == "publish_reply"
    assert "boom" in summary.error
    assert reviews.statuses[0][2] == ReviewStatus.FAILED.value


async def test_a_status_write_failure_does_not_fail_the_run() -> None:
    """The run is over; a database blip must not rewrite its outcome."""
    node = CloseNode(node_id="close", review_repository=_Reviews(fail=True))
    shared = {"review": _review(), "tenant_id": "bar-pepe"}

    summary = await node.execute(shared, {})

    assert summary.review_id == "11111111-1111-1111-1111-111111111111"
