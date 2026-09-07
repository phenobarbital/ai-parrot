"""The review source port and its in-memory adapter. No database, no network."""
from __future__ import annotations

from datetime import timedelta

import pytest

from parrot_saas.reviews.mock import DEMO_EPOCH, MockReviewSource, demo_corpus
from parrot_saas.reviews.port import ReviewEvent, ReviewSource, ReviewSourceError


@pytest.fixture
def source() -> MockReviewSource:
    """A mock source seeded with the demo corpus."""
    return MockReviewSource()


# ---------------------------------------------------------------------------
# The port's defaults
# ---------------------------------------------------------------------------


def test_webhook_verification_denies_by_default() -> None:
    """A source that cannot verify a signature must not accept webhooks.

    Inheriting a permissive default is how a source that simply never got
    round to signatures ends up with an open ingest endpoint.
    """

    class _Bare(ReviewSource):
        async def fetch(self, tenant_id, *, since=None, limit=50):
            return []

        async def reply(self, tenant_id, external_id, text):
            raise NotImplementedError

        def normalize(self, payload):
            raise NotImplementedError

    assert _Bare().verify_webhook({}, b"{}", "secret") is False


def test_dedupe_key_defaults_to_the_external_id(source: MockReviewSource) -> None:
    """Sources with stable platform ids need no content hash."""
    event = ReviewEvent(source="mock", external_id="mock-1001")

    assert source.dedupe_key(event) == "mock-1001"


def test_the_port_cannot_be_instantiated_incomplete() -> None:
    """fetch/reply/normalize are the contract; a partial adapter must fail."""

    class _Partial(ReviewSource):
        async def fetch(self, tenant_id, *, since=None, limit=50):
            return []

    with pytest.raises(TypeError):
        _Partial()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


async def test_fetch_returns_the_demo_corpus_newest_first(
    source: MockReviewSource,
) -> None:
    """A freshly onboarded tenant has something to run against."""
    events = await source.fetch("bar-pepe")

    assert [e.external_id for e in events] == [
        "mock-1001",
        "mock-1002",
        "mock-1003",
        "mock-1004",
    ]


async def test_the_corpus_covers_every_branch_of_the_flow() -> None:
    """The mix is the point: one corpus exercises the whole graph.

    A detractor who can be contacted, a promoter, a detractor who cannot be
    contacted, and a bare rating that triage should skip.
    """
    corpus = demo_corpus()

    assert any(e.rating <= 2 and e.author_email for e in corpus)
    assert any(e.rating >= 4 and e.text for e in corpus)
    assert any(e.rating <= 2 and not e.author_email for e in corpus)
    assert any(not e.text for e in corpus)


async def test_the_corpus_is_deterministic() -> None:
    """Fixed timestamps and ids, so a failure reproduces and a demo repeats."""
    first, second = demo_corpus(), demo_corpus()

    assert [e.posted_at for e in first] == [e.posted_at for e in second]
    assert first[0].posted_at == DEMO_EPOCH


async def test_fetch_filters_by_since_and_limit(source: MockReviewSource) -> None:
    """Incremental polling reads only what is new."""
    recent = await source.fetch("bar-pepe", since=DEMO_EPOCH - timedelta(hours=12))
    capped = await source.fetch("bar-pepe", limit=2)

    assert [e.external_id for e in recent] == ["mock-1001", "mock-1002"]
    assert len(capped) == 2


async def test_tenants_have_separate_corpora(source: MockReviewSource) -> None:
    """Seeding one tenant must not be visible to another."""
    source.seed(
        "bar-pepe", ReviewEvent(source="mock", external_id="extra-1", rating=3)
    )

    mine = await source.fetch("bar-pepe")
    theirs = await source.fetch("hotel-x")

    assert "extra-1" in {e.external_id for e in mine}
    assert "extra-1" not in {e.external_id for e in theirs}


async def test_an_empty_source_can_be_requested() -> None:
    """Tests that want no corpus should not have to delete one."""
    source = MockReviewSource(seed_demo=False)

    assert await source.fetch("bar-pepe") == []


# ---------------------------------------------------------------------------
# Replying
# ---------------------------------------------------------------------------


async def test_reply_returns_a_deterministic_identifier(
    source: MockReviewSource,
) -> None:
    """A counter rather than a UUID, so assertions can name the value."""
    first = await source.reply("bar-pepe", "mock-1001", "Thank you, we are sorry.")
    second = await source.reply("bar-pepe", "mock-1002", "Glad you enjoyed it!")

    assert first.external_reply_id == "mock-reply-1"
    assert second.external_reply_id == "mock-reply-2"
    assert first.source == "mock"


async def test_published_replies_are_observable(source: MockReviewSource) -> None:
    """Proving a reply happened must not require a database."""
    await source.reply("bar-pepe", "mock-1001", "We are sorry about the wait.")

    assert source.published == [
        ("bar-pepe", "mock-1001", "We are sorry about the wait.")
    ]


async def test_replying_to_an_unknown_review_is_refused(
    source: MockReviewSource,
) -> None:
    """Real platforms refuse this; a mock that accepts it hides the handling."""
    with pytest.raises(ReviewSourceError, match="no review"):
        await source.reply("bar-pepe", "does-not-exist", "Hello")


async def test_an_empty_reply_is_refused(source: MockReviewSource) -> None:
    """A blank public reply is worse than none."""
    with pytest.raises(ReviewSourceError, match="empty reply"):
        await source.reply("bar-pepe", "mock-1001", "   ")


async def test_a_reply_cannot_reach_another_tenants_review() -> None:
    """The corpus is per tenant, so the identifier does not carry across."""
    source = MockReviewSource(seed_demo=False)
    source.seed("bar-pepe", ReviewEvent(source="mock", external_id="only-mine"))

    with pytest.raises(ReviewSourceError):
        await source.reply("hotel-x", "only-mine", "Hello")


# ---------------------------------------------------------------------------
# Normalising
# ---------------------------------------------------------------------------


def test_normalize_accepts_a_hand_written_payload(source: MockReviewSource) -> None:
    """The simulate endpoint should take what a person would actually type."""
    event = source.normalize(
        {"id": "typed-1", "rating": 2, "comment": "Slow service", "language": "es"}
    )

    assert event.external_id == "typed-1"
    assert event.text == "Slow service"
    assert event.language == "es"
    assert event.raw["comment"] == "Slow service"


def test_normalize_requires_an_external_id(source: MockReviewSource) -> None:
    """Without one there is no de-duplication key, so a retry would double up."""
    with pytest.raises(ValueError, match="external_id"):
        source.normalize({"rating": 5, "text": "Lovely"})


def test_normalize_never_assigns_the_tenant(source: MockReviewSource) -> None:
    """A payload must not be able to nominate whose review it is."""
    event = source.normalize({"id": "x-1", "tenant_id": "hotel-x"})

    assert event.tenant_id == ""


def test_normalize_parses_an_iso_timestamp(source: MockReviewSource) -> None:
    """Ordering depends on posted_at, so a string date must not be dropped."""
    event = source.normalize({"id": "x-1", "posted_at": "2026-05-04T10:00:00+00:00"})

    assert event.posted_at.year == 2026
    assert event.posted_at.month == 5


def test_the_mock_never_authenticates_a_webhook(source: MockReviewSource) -> None:
    """It has no signature scheme; the simulate endpoint drives it instead."""
    assert source.verify_webhook({"X-Signature": "anything"}, b"{}", "s") is False
