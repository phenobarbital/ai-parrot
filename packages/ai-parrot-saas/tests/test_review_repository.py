"""Review and guest persistence, against a real PostgreSQL instance.

The behaviour worth proving here is the part a fake connection would fake:
that the uniqueness constraint really collapses a replay into one row, that
partial unique indexes really let contactless guests coexist, and that the
tenant predicate really is on every statement.
"""
from __future__ import annotations

from datetime import timedelta
from typing import AsyncIterator

import pytest
from asyncdb import AsyncDB

from parrot_saas.db.repository import TenantScopeError
from parrot_saas.db.schema import ensure_schema
from parrot_saas.reviews.mock import DEMO_EPOCH, MockReviewSource
from parrot_saas.reviews.models import ReplyStatus, ReviewStatus
from parrot_saas.reviews.port import ReviewEvent
from parrot_saas.reviews.repository import GuestRepository, ReviewRepository

pytestmark = pytest.mark.integration


@pytest.fixture
async def repos(test_dsn: str, unique_schema: str) -> AsyncIterator[tuple]:
    """Review and guest repositories on a throwaway schema with two tenants."""
    conn = AsyncDB("pg", dsn=test_dsn)
    async with await conn.connection():
        await ensure_schema(conn, schema=unique_schema)
        for tenant_id in ("bar-pepe", "hotel-x"):
            await conn.execute(
                f"INSERT INTO {unique_schema}.tenants (tenant_id, name) "
                "VALUES ($1, $2)",
                tenant_id,
                tenant_id.title(),
            )

    reviews = ReviewRepository(test_dsn, schema=unique_schema)
    guests = GuestRepository(test_dsn, schema=unique_schema)
    try:
        yield reviews, guests
    finally:
        await reviews.aclose()
        await guests.aclose()
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


def _event(external_id: str = "mock-1001", **overrides) -> ReviewEvent:
    """Build a review event with sensible defaults."""
    payload = {
        "source": "mock",
        "external_id": external_id,
        "rating": 1,
        "text": "Cold food and a long wait.",
        "author_name": "Marta R.",
        "posted_at": DEMO_EPOCH,
        "raw": {"fixture": "unit"},
    }
    payload.update(overrides)
    return ReviewEvent(**payload)


# ---------------------------------------------------------------------------
# Ingest idempotency
# ---------------------------------------------------------------------------


async def test_ingest_stores_the_review(repos) -> None:
    """A first delivery creates a row and reports it as new."""
    reviews, _ = repos

    review, created = await reviews.ingest("bar-pepe", _event())

    assert created is True
    assert review.external_id == "mock-1001"
    assert review.text == "Cold food and a long wait."
    assert review.status == ReviewStatus.RECEIVED
    assert review.raw == {"fixture": "unit"}
    assert review.posted_at == DEMO_EPOCH


async def test_a_replay_does_not_create_a_second_review(repos) -> None:
    """This is what keeps a webhook retry from replying and couponing twice."""
    reviews, _ = repos

    first, created_first = await reviews.ingest("bar-pepe", _event())
    second, created_second = await reviews.ingest("bar-pepe", _event())

    assert created_first is True
    assert created_second is False
    assert first.review_id == second.review_id
    assert len(await reviews.list_reviews("bar-pepe")) == 1


async def test_a_replay_does_not_overwrite_the_stored_review(repos) -> None:
    """A retry carrying edited text must not silently rewrite history."""
    reviews, _ = repos
    await reviews.ingest("bar-pepe", _event())

    second, created = await reviews.ingest(
        "bar-pepe", _event(text="COMPLETELY DIFFERENT")
    )

    assert created is False
    assert second.text == "Cold food and a long wait."


async def test_the_same_external_id_is_distinct_per_tenant(repos) -> None:
    """Two platforms number from 1; the key is scoped, so that is fine."""
    reviews, _ = repos

    mine, _ = await reviews.ingest("bar-pepe", _event())
    theirs, created = await reviews.ingest("hotel-x", _event())

    assert created is True
    assert mine.review_id != theirs.review_id


async def test_the_same_external_id_is_distinct_per_source(repos) -> None:
    """The key includes the source, so two platforms cannot collide."""
    reviews, _ = repos
    await reviews.ingest("bar-pepe", _event())

    _, created = await reviews.ingest("bar-pepe", _event(source="google"))

    assert created is True


async def test_a_content_hash_can_replace_an_unstable_id(repos) -> None:
    """Sources without stable ids supply their own de-duplication value."""
    reviews, _ = repos

    first, _ = await reviews.ingest(
        "bar-pepe", _event(external_id=""), external_id="sha256:abc"
    )
    second, created = await reviews.ingest(
        "bar-pepe", _event(external_id=""), external_id="sha256:abc"
    )

    assert created is False
    assert first.external_id == second.external_id == "sha256:abc"


async def test_the_payload_cannot_choose_the_tenant(repos) -> None:
    """``tenant_id`` is a parameter, not something the event nominates."""
    reviews, _ = repos

    review, _ = await reviews.ingest("bar-pepe", _event(tenant_id="hotel-x"))

    assert review.tenant_id == "bar-pepe"
    assert await reviews.list_reviews("hotel-x") == []


# ---------------------------------------------------------------------------
# Reading and status
# ---------------------------------------------------------------------------


async def test_get_and_unknown(repos) -> None:
    """Reading by surrogate key, and a clean miss."""
    reviews, _ = repos
    stored, _ = await reviews.ingest("bar-pepe", _event())

    found = await reviews.get("bar-pepe", stored.review_id)
    missing = await reviews.get(
        "bar-pepe", "00000000-0000-0000-0000-000000000000"
    )

    assert found.external_id == "mock-1001"
    assert missing is None


async def test_a_tenant_cannot_read_another_tenants_review(repos) -> None:
    """The isolation that the whole BaseRepository design exists to enforce."""
    reviews, _ = repos
    stored, _ = await reviews.ingest("bar-pepe", _event())

    assert await reviews.get("hotel-x", stored.review_id) is None


async def test_listing_filters_and_orders(repos) -> None:
    """Newest first, with a status and a watermark filter."""
    reviews, _ = repos
    old, _ = await reviews.ingest(
        "bar-pepe", _event("old", posted_at=DEMO_EPOCH - timedelta(days=3))
    )
    new, _ = await reviews.ingest("bar-pepe", _event("new"))
    await reviews.set_status("bar-pepe", old.review_id, ReviewStatus.SKIPPED)

    everything = await reviews.list_reviews("bar-pepe")
    skipped = await reviews.list_reviews("bar-pepe", status=ReviewStatus.SKIPPED)
    recent = await reviews.list_reviews(
        "bar-pepe", since=DEMO_EPOCH - timedelta(days=1)
    )

    assert [r.external_id for r in everything] == ["new", "old"]
    assert [r.external_id for r in skipped] == ["old"]
    assert [r.external_id for r in recent] == ["new"]
    assert new.review_id != old.review_id


async def test_set_status_moves_the_review(repos) -> None:
    """Advisory state, but it must actually persist."""
    reviews, _ = repos
    stored, _ = await reviews.ingest("bar-pepe", _event())

    updated = await reviews.set_status(
        "bar-pepe", stored.review_id, ReviewStatus.REPLIED
    )

    assert updated.status == ReviewStatus.REPLIED
    assert (await reviews.get("bar-pepe", stored.review_id)).status == (
        ReviewStatus.REPLIED
    )


# ---------------------------------------------------------------------------
# Replies
# ---------------------------------------------------------------------------


async def test_every_drafting_attempt_is_kept(repos) -> None:
    """The repair loop produces several drafts; the rejected ones are evidence."""
    reviews, _ = repos
    stored, _ = await reviews.ingest("bar-pepe", _event())

    await reviews.record_reply(
        "bar-pepe",
        stored.review_id,
        text="We'll comp your meal!",
        status=ReplyStatus.FAILED,
        attempt=1,
        reason="guardrail: promises compensation",
    )
    await reviews.record_reply(
        "bar-pepe",
        stored.review_id,
        text="We are sorry about the wait.",
        status=ReplyStatus.PUBLISHED,
        external_reply_id="mock-reply-1",
        attempt=2,
    )

    replies = await reviews.list_replies("bar-pepe", stored.review_id)
    assert len(replies) == 2
    assert {r.attempt for r in replies} == {1, 2}
    published = [r for r in replies if r.status == ReplyStatus.PUBLISHED]
    assert published[0].external_reply_id == "mock-reply-1"


async def test_replies_are_tenant_scoped(repos) -> None:
    """``tenant_id`` is denormalised onto the reply so the filter is direct."""
    reviews, _ = repos
    stored, _ = await reviews.ingest("bar-pepe", _event())
    await reviews.record_reply("bar-pepe", stored.review_id, text="Thanks")

    assert await reviews.list_replies("hotel-x", stored.review_id) == []


# ---------------------------------------------------------------------------
# Guests
# ---------------------------------------------------------------------------


async def test_a_guest_is_created_then_matched_by_email(repos) -> None:
    """The second sighting of the same address is the same person."""
    _, guests = repos

    first = await guests.upsert("bar-pepe", email="Marta.R@Example.com")
    second = await guests.upsert("bar-pepe", email="marta.r@example.com")

    assert first.guest_id == second.guest_id
    assert first.email == "marta.r@example.com"


async def test_a_guest_is_matched_by_phone(repos) -> None:
    """Phones match exactly — see the repository docstring on why."""
    _, guests = repos

    first = await guests.upsert("bar-pepe", phone="+34600111222")
    second = await guests.upsert("bar-pepe", phone="+34600111222")

    assert first.guest_id == second.guest_id


async def test_contactless_guests_do_not_collide(repos) -> None:
    """A guest with no contact detail is not a guest we can create.

    The partial unique indexes make this safe rather than an error: empty
    contact fields are excluded from the index, so they cannot collide.
    """
    _, guests = repos

    assert await guests.upsert("bar-pepe", display_name="Anonymous") is None


async def test_a_later_sighting_fills_gaps_without_overwriting(repos) -> None:
    """Adding an e-mail to a phone-matched guest must not rewrite their name."""
    _, guests = repos
    await guests.upsert("bar-pepe", phone="+34600111222", display_name="Marta R.")

    updated = await guests.upsert(
        "bar-pepe",
        phone="+34600111222",
        email="marta@example.com",
        display_name="M. Ruiz",
    )

    assert updated.email == "marta@example.com"
    assert updated.display_name == "Marta R."


async def test_an_ingest_without_consent_never_revokes_it(repos) -> None:
    """Consent is granted by the guest; a silent payload must not take it away."""
    _, guests = repos
    guest = await guests.upsert("bar-pepe", email="marta@example.com")
    await guests.set_consent("bar-pepe", guest.guest_id, True)

    again = await guests.upsert("bar-pepe", email="marta@example.com")

    assert again.consent_marketing is True


async def test_guests_are_tenant_scoped(repos) -> None:
    """The same address at two tenants is two guests."""
    _, guests = repos

    mine = await guests.upsert("bar-pepe", email="marta@example.com")
    theirs = await guests.upsert("hotel-x", email="marta@example.com")

    assert mine.guest_id != theirs.guest_id
    assert await guests.find("hotel-x", email="marta@example.com") == theirs
    assert await guests.get("hotel-x", mine.guest_id) is None


async def test_find_needs_something_to_match_on(repos) -> None:
    """An empty lookup must not return an arbitrary guest."""
    _, guests = repos
    await guests.upsert("bar-pepe", email="marta@example.com")

    assert await guests.find("bar-pepe") is None


# ---------------------------------------------------------------------------
# Wiring a review to a guest
# ---------------------------------------------------------------------------


async def test_a_guest_can_be_attached_after_ingest(repos) -> None:
    """Contact details usually arrive later than the review itself."""
    reviews, guests = repos
    stored, _ = await reviews.ingest("bar-pepe", _event())
    guest = await guests.upsert("bar-pepe", email="marta@example.com")

    updated = await reviews.attach_guest(
        "bar-pepe", stored.review_id, guest.guest_id
    )

    assert updated.guest_id == guest.guest_id


async def test_a_guest_can_be_supplied_at_ingest(repos) -> None:
    """Sources that expose contact details resolve the guest up front."""
    reviews, guests = repos
    guest = await guests.upsert("bar-pepe", email="marta@example.com")

    stored, _ = await reviews.ingest("bar-pepe", _event(), guest_id=guest.guest_id)

    assert stored.guest_id == guest.guest_id


async def test_an_anonymous_review_stores_no_guest(repos) -> None:
    """An empty guest id must become NULL, not a cast failure."""
    reviews, _ = repos

    stored, _ = await reviews.ingest("bar-pepe", _event())

    assert stored.guest_id == ""


# ---------------------------------------------------------------------------
# The isolation guard
# ---------------------------------------------------------------------------


async def test_a_query_without_a_tenant_predicate_is_refused(repos) -> None:
    """The guard that makes the logical boundary hard to get wrong."""
    reviews, _ = repos

    with pytest.raises(TenantScopeError):
        await reviews.fetch_all(
            "bar-pepe", f"SELECT * FROM {reviews.table('reviews')}"
        )


async def test_a_malformed_id_reads_as_a_miss(repos) -> None:
    """These ids arrive from URL paths.

    A garbage path segment should read as "no such row" rather than surfacing
    a driver error as a 500 — and it must not reach the database at all.
    """
    reviews, guests = repos

    assert await reviews.get("bar-pepe", "not-a-uuid") is None
    assert await reviews.set_status("bar-pepe", "../etc", ReviewStatus.REPLIED) is None
    assert await reviews.list_replies("bar-pepe", "nope") == []
    assert await guests.get("bar-pepe", "nope") is None


async def test_a_malformed_id_on_a_write_is_loud(repos) -> None:
    """Losing the record of a published reply is worse than failing the call."""
    reviews, _ = repos

    with pytest.raises(ValueError, match="not a valid review id"):
        await reviews.record_reply("bar-pepe", "nope", text="Thanks")


async def test_the_mock_source_round_trips_through_the_repository(repos) -> None:
    """The port and the persistence layer actually fit together."""
    reviews, _ = repos
    source = MockReviewSource()

    for event in await source.fetch("bar-pepe"):
        await reviews.ingest(
            "bar-pepe", event, external_id=source.dedupe_key(event)
        )

    stored = await reviews.list_reviews("bar-pepe")
    assert len(stored) == 4
    assert [r.external_id for r in stored][0] == "mock-1001"
