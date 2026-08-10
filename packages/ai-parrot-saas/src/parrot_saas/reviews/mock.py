"""An in-memory :class:`ReviewSource` — the one the whole suite runs against.

There is no real review platform behind this feature yet, and the mock is what
makes that survivable: the entire Community Manager flow, its routing, its
coupon decisions and its end-to-end tests all exercise the same port a Google
Business adapter will implement later.

Two properties are load-bearing:

* **Deterministic.** The demo corpus carries fixed timestamps and fixed
  identifiers, and reply ids are a counter rather than a UUID. A test that
  fails does so reproducibly, and a demo tells the same story twice.
* **Offline.** No sockets, no clock dependence in the corpus, no database.
  Persisting is the repository's job — see :mod:`parrot_saas.reviews.port` for
  why an adapter must not write to our tables.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, MutableMapping, Optional, Sequence

from navconfig.logging import logging

from .port import ReviewEvent, ReviewReply, ReviewSource, ReviewSourceError

logger = logging.getLogger("parrot_saas.reviews.mock")

#: Anchor for the demo corpus. Fixed so that relative ordering, "how long ago"
#: rendering and any temporal rule read the same on every run.
DEMO_EPOCH = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def demo_corpus(source: str = "mock") -> tuple[ReviewEvent, ...]:
    """Return a small, deliberately varied set of hospitality reviews.

    The mix is chosen to exercise every branch of the Community Manager graph
    from one corpus: a detractor with contact details (reply, then a coupon), a
    promoter (reply, no coupon), a detractor with no way to reach them (reply,
    no contact), and a bare five-star rating with no text (triage skips it).

    Args:
        source: Adapter name to stamp on each event.

    Returns:
        The corpus, newest first.
    """
    return (
        ReviewEvent(
            source=source,
            external_id="mock-1001",
            location_ref="venue-central",
            rating=1,
            text=(
                "Waited fifty minutes for a table we had booked, and the "
                "starters arrived cold. Nobody apologised."
            ),
            language="en",
            author_name="Marta R.",
            author_email="marta.r@example.com",
            posted_at=DEMO_EPOCH,
            raw={"fixture": "detractor_with_contact"},
        ),
        ReviewEvent(
            source=source,
            external_id="mock-1002",
            location_ref="venue-central",
            rating=5,
            text=(
                "Outstanding evening. The staff remembered our anniversary "
                "and the kitchen sent out something extra."
            ),
            language="en",
            author_name="Tom H.",
            posted_at=DEMO_EPOCH - timedelta(hours=6),
            raw={"fixture": "promoter"},
        ),
        ReviewEvent(
            source=source,
            external_id="mock-1003",
            location_ref="venue-port",
            rating=2,
            text="Room was not ready at check-in and the air conditioning rattled.",
            language="en",
            author_name="Anonymous",
            posted_at=DEMO_EPOCH - timedelta(days=1),
            raw={"fixture": "detractor_without_contact"},
        ),
        ReviewEvent(
            source=source,
            external_id="mock-1004",
            location_ref="venue-port",
            rating=5,
            text="",
            language="en",
            author_name="J.",
            posted_at=DEMO_EPOCH - timedelta(days=2),
            raw={"fixture": "rating_only"},
        ),
    )


class MockReviewSource(ReviewSource):
    """A review source backed by an in-memory corpus.

    Args:
        name: Adapter name stamped on events and stored on review rows.
        seed_demo: Whether new tenants start with :func:`demo_corpus`. On by
            default so a freshly onboarded tenant has something to run against
            without a fixture; turn it off for tests that want an empty source.

    Attributes:
        published: Every reply accepted, in order, as
            ``(tenant_id, external_id, text)``. Test-facing, and the reason
            this class does not need a database to prove a reply happened.
    """

    def __init__(self, *, name: str = "mock", seed_demo: bool = True) -> None:
        self.name = name
        self._seed_demo = seed_demo
        self._by_tenant: MutableMapping[str, list[ReviewEvent]] = {}
        self._replies: MutableMapping[tuple[str, str], ReviewReply] = {}
        self.published: list[tuple[str, str, str]] = []
        self._reply_counter = 0

    # -- corpus management -------------------------------------------------

    def _corpus(self, tenant_id: str) -> list[ReviewEvent]:
        """Return a tenant's corpus, seeding it on first access."""
        if tenant_id not in self._by_tenant:
            self._by_tenant[tenant_id] = (
                list(demo_corpus(self.name)) if self._seed_demo else []
            )
        return self._by_tenant[tenant_id]

    def seed(self, tenant_id: str, *events: ReviewEvent) -> None:
        """Add events to a tenant's corpus.

        Args:
            tenant_id: Tenant to seed.
            *events: Events to add, in any order.
        """
        self._corpus(tenant_id).extend(events)

    def clear(self, tenant_id: Optional[str] = None) -> None:
        """Empty one tenant's corpus, or every tenant's.

        Args:
            tenant_id: Tenant to clear. ``None`` clears everything, replies
                included.
        """
        if tenant_id is None:
            self._by_tenant.clear()
            self._replies.clear()
            self.published.clear()
            self._reply_counter = 0
        else:
            self._by_tenant[tenant_id] = []

    # -- the port ----------------------------------------------------------

    async def fetch(
        self,
        tenant_id: str,
        *,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> Sequence[ReviewEvent]:
        """Return a tenant's reviews, newest first."""
        events = sorted(
            self._corpus(tenant_id), key=lambda e: e.posted_at, reverse=True
        )
        if since is not None:
            events = [e for e in events if e.posted_at > since]
        return events[: max(limit, 0)]

    async def reply(
        self, tenant_id: str, external_id: str, text: str
    ) -> ReviewReply:
        """Record a public reply and return a synthetic identifier.

        Raises:
            ReviewSourceError: If the review is not in this tenant's corpus, or
                the reply is empty. Both are refused because the real platforms
                refuse them, and a mock that accepts anything hides the
                handling the flow will need.
        """
        if not text or not text.strip():
            raise ReviewSourceError("refusing to publish an empty reply")
        known = {event.external_id for event in self._corpus(tenant_id)}
        if external_id not in known:
            raise ReviewSourceError(
                f"tenant {tenant_id!r} has no review {external_id!r} on "
                f"source {self.name!r}"
            )

        self._reply_counter += 1
        published = ReviewReply(
            external_reply_id=f"{self.name}-reply-{self._reply_counter}",
            source=self.name,
        )
        self._replies[(tenant_id, external_id)] = published
        self.published.append((tenant_id, external_id, text))
        logger.debug(
            "mock review source published a reply to %s for tenant %s",
            external_id,
            tenant_id,
        )
        return published

    def normalize(self, payload: Mapping[str, Any]) -> ReviewEvent:
        """Convert a loose payload into an event.

        Accepts the field names this source emits plus the two aliases a
        hand-written demo request is likely to use (``id``, ``comment``), so
        the simulate endpoint can take something a person would actually type.

        Args:
            payload: The raw payload.

        Returns:
            The normalised event, with ``tenant_id`` unset — the ingest path
            assigns it from the authenticated request.

        Raises:
            ValueError: If no external identifier can be determined. Without
                one there is no de-duplication key, and a retried delivery
                would create a second review, a second reply and a second
                coupon.
        """
        data = dict(payload)
        external_id = str(
            data.get("external_id") or data.get("id") or ""
        ).strip()
        if not external_id:
            raise ValueError(
                "a review payload needs an 'external_id' to be de-duplicated"
            )
        posted_at = data.get("posted_at")
        if isinstance(posted_at, str):
            posted_at = datetime.fromisoformat(posted_at)
        return ReviewEvent(
            source=self.name,
            external_id=external_id,
            location_ref=str(data.get("location_ref") or ""),
            rating=int(data.get("rating") or 0),
            text=str(data.get("text") or data.get("comment") or ""),
            language=str(data.get("language") or "en"),
            author_name=str(data.get("author_name") or ""),
            author_email=str(data.get("author_email") or ""),
            author_phone=str(data.get("author_phone") or ""),
            **({"posted_at": posted_at} if posted_at else {}),
            raw=data,
        )

    def verify_webhook(
        self, headers: Mapping[str, str], body: bytes, secret: str
    ) -> bool:
        """Always ``False``.

        Inherited behaviour, restated so it is not mistaken for an oversight:
        this source has no signature scheme, so it must never authenticate a
        webhook. Reaching it from the network is the signed adapter's job; the
        mock is driven by the authenticated simulate endpoint instead.
        """
        return False


__all__ = ("DEMO_EPOCH", "MockReviewSource", "demo_corpus")
