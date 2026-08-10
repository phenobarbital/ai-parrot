"""Persistence for reviews, their replies, and the guests behind them.

Both repositories inherit :class:`~parrot_saas.db.repository.BaseRepository`,
so every statement here goes through helpers that bind ``tenant_id`` as ``$1``
and refuse SQL that does not mention it.

The interesting method is :meth:`ReviewRepository.ingest`. Everything else is
ordinary CRUD; that one carries the guarantee the whole ingest path rests on —
that a platform delivering the same review twice produces one row, one run,
one reply and one coupon.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any, Optional, Sequence

from ..db.repository import BaseRepository
from .models import Guest, ReplyStatus, Review, ReviewReplyRecord, ReviewStatus
from .port import ReviewEvent

#: Columns selected for a review, mapped by ``Review.from_row``.
_REVIEW_COLUMNS = (
    "review_id, tenant_id, source, external_id, location_ref, guest_id, "
    "rating, body, language, author_name, status, posted_at, received_at, raw"
)

_GUEST_COLUMNS = (
    "guest_id, tenant_id, email, phone, display_name, consent_marketing, "
    "lifetime_visits, created_at, updated_at"
)

_REPLY_COLUMNS = (
    "reply_id, tenant_id, review_id, body, status, external_reply_id, "
    "attempt, reason, created_at"
)


def as_uuid(value: Any) -> Optional[_uuid.UUID]:
    """Convert a surrogate key to a UUID, or ``None`` if it is not one.

    Two reasons this exists rather than interpolating ``$n::uuid`` and passing
    a string. asyncpg infers the parameter type from that cast and then rejects
    a ``str`` outright ("bytes is not a 16-char string"), so the cast has to
    happen on this side. And these ids arrive from URL paths: a malformed one
    should read as "no such row", not as a 500 from the driver.

    Args:
        value: A UUID, a string, or anything else.

    Returns:
        The UUID, or ``None`` when the value is empty or malformed.
    """
    if isinstance(value, _uuid.UUID):
        return value
    if not value:
        return None
    try:
        return _uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _normalise_email(email: str) -> str:
    """Lowercase and strip an e-mail for matching.

    Args:
        email: Raw address.

    Returns:
        The comparable form, or an empty string.
    """
    return (email or "").strip().lower()


class GuestRepository(BaseRepository):
    """Guests, matched by whichever contact detail the source supplied.

    Matching is exact on a normalised e-mail or on the phone as stored. Phone
    numbers are **not** normalised to E.164 — that needs a region per tenant
    and a phone-number library to do correctly, and a half-normalisation
    (stripping spaces, guessing a prefix) merges people who are not the same
    person. Exact matching under-merges instead, which is the safer error when
    the consequence is sending someone else's guest a coupon.
    """

    async def get(self, tenant_id: str, guest_id: str) -> Optional[Guest]:
        """Return one guest.

        Args:
            tenant_id: Owning tenant.
            guest_id: Surrogate key.

        Returns:
            The guest, or ``None``.
        """
        key = as_uuid(guest_id)
        if key is None:
            return None
        row = await self.fetch_one(
            tenant_id,
            f"SELECT {_GUEST_COLUMNS} FROM {self.table('guests')} "
            "WHERE tenant_id = $1 AND guest_id = $2",
            key,
        )
        return Guest.from_row(row) if row else None

    async def find(
        self, tenant_id: str, *, email: str = "", phone: str = ""
    ) -> Optional[Guest]:
        """Find a guest by e-mail or phone.

        Args:
            tenant_id: Owning tenant.
            email: Address to match, case-insensitively.
            phone: Phone to match exactly.

        Returns:
            The first match, or ``None`` when neither detail was supplied or
            neither matched.
        """
        email = _normalise_email(email)
        phone = (phone or "").strip()
        if not email and not phone:
            return None
        row = await self.fetch_one(
            tenant_id,
            f"SELECT {_GUEST_COLUMNS} FROM {self.table('guests')} "
            "WHERE tenant_id = $1 "
            "  AND ( ($2 <> '' AND email = $2) OR ($3 <> '' AND phone = $3) ) "
            "ORDER BY created_at LIMIT 1",
            email,
            phone,
        )
        return Guest.from_row(row) if row else None

    async def upsert(
        self,
        tenant_id: str,
        *,
        email: str = "",
        phone: str = "",
        display_name: str = "",
        consent_marketing: Optional[bool] = None,
    ) -> Optional[Guest]:
        """Find a guest by contact detail, or create one.

        Args:
            tenant_id: Owning tenant.
            email: Contact e-mail.
            phone: Contact phone.
            display_name: Name to address them by.
            consent_marketing: Marketing consent. ``None`` leaves an existing
                value alone — consent is granted by the guest, so an ingest
                that happens not to carry it must never revoke it.

        Returns:
            The guest, or ``None`` when no contact detail was supplied (an
            anonymous review has no one to match).
        """
        email = _normalise_email(email)
        phone = (phone or "").strip()
        if not email and not phone:
            return None

        existing = await self.find(tenant_id, email=email, phone=phone)
        if existing is not None:
            return await self._amend(
                tenant_id,
                existing,
                email=email,
                phone=phone,
                display_name=display_name,
                consent_marketing=consent_marketing,
            )

        row = await self.fetch_one(
            tenant_id,
            f"INSERT INTO {self.table('guests')} "
            "(tenant_id, email, phone, display_name, consent_marketing) "
            "VALUES ($1, $2, $3, $4, $5) "
            f"RETURNING {_GUEST_COLUMNS}",
            email,
            phone,
            display_name,
            bool(consent_marketing),
        )
        return Guest.from_row(row) if row else None

    async def _amend(
        self,
        tenant_id: str,
        guest: Guest,
        *,
        email: str,
        phone: str,
        display_name: str,
        consent_marketing: Optional[bool],
    ) -> Guest:
        """Fill in details a later sighting supplied, without erasing any.

        Only empty fields are filled: a guest matched by phone who now arrives
        with an e-mail gains it, but a name already on file is not replaced by
        a different rendering of the same person from another platform.
        """
        updates: dict[str, Any] = {}
        if email and not guest.email:
            updates["email"] = email
        if phone and not guest.phone:
            updates["phone"] = phone
        if display_name and not guest.display_name:
            updates["display_name"] = display_name
        if consent_marketing is not None and consent_marketing != guest.consent_marketing:
            updates["consent_marketing"] = consent_marketing
        if not updates:
            return guest

        columns = list(updates)
        assignments = ", ".join(
            f"{name} = ${index + 3}" for index, name in enumerate(columns)
        )
        row = await self.fetch_one(
            tenant_id,
            f"UPDATE {self.table('guests')} SET {assignments}, updated_at = now() "
            "WHERE tenant_id = $1 AND guest_id = $2 "
            f"RETURNING {_GUEST_COLUMNS}",
            as_uuid(guest.guest_id),
            *(updates[name] for name in columns),
        )
        return Guest.from_row(row) if row else guest

    async def set_consent(
        self, tenant_id: str, guest_id: str, consent: bool
    ) -> Optional[Guest]:
        """Record a guest's marketing consent decision.

        Args:
            tenant_id: Owning tenant.
            guest_id: Surrogate key.
            consent: Whether they agreed to be contacted with offers.

        Returns:
            The updated guest, or ``None`` if there is no such guest.
        """
        key = as_uuid(guest_id)
        if key is None:
            return None
        row = await self.fetch_one(
            tenant_id,
            f"UPDATE {self.table('guests')} "
            "SET consent_marketing = $3, updated_at = now() "
            "WHERE tenant_id = $1 AND guest_id = $2 "
            f"RETURNING {_GUEST_COLUMNS}",
            key,
            consent,
        )
        return Guest.from_row(row) if row else None


class ReviewRepository(BaseRepository):
    """Reviews and the replies drafted for them."""

    async def ingest(
        self,
        tenant_id: str,
        event: ReviewEvent,
        *,
        external_id: Optional[str] = None,
        guest_id: str = "",
    ) -> tuple[Review, bool]:
        """Store a review, or return the one already stored.

        Idempotent on ``(tenant_id, source, external_id)``. A platform that
        delivers the same review twice — a webhook retry, an overlapping poll
        window — must not produce a second run, a second public reply and a
        second coupon, and this constraint is what prevents it.

        ``tenant_id`` is a parameter rather than read from ``event.tenant_id``
        deliberately: the tenant comes from the authenticated request, and
        letting a payload nominate its own owner is how an ingest endpoint
        becomes a cross-tenant writer.

        Args:
            tenant_id: Owning tenant.
            event: The normalised review.
            external_id: De-duplication value. Defaults to the event's own
                ``external_id``; a source whose ids are unstable supplies a
                content hash from ``ReviewSource.dedupe_key`` instead.
            guest_id: Resolved guest, when one was matched.

        Returns:
            ``(review, created)`` — ``created`` is ``False`` for a replay.
        """
        import json

        key = external_id or event.external_id
        row = await self.fetch_one(
            tenant_id,
            f"INSERT INTO {self.table('reviews')} "
            "(tenant_id, source, external_id, location_ref, guest_id, rating, "
            " body, language, author_name, posted_at, raw) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb) "
            "ON CONFLICT (tenant_id, source, external_id) DO NOTHING "
            f"RETURNING {_REVIEW_COLUMNS}",
            event.source,
            key,
            event.location_ref,
            as_uuid(guest_id),
            event.rating,
            event.text,
            event.language,
            event.author_name,
            event.posted_at,
            json.dumps(event.raw or {}),
        )
        if row is not None:
            return Review.from_row(row), True

        existing = await self.get_by_external_id(tenant_id, event.source, key)
        if existing is None:  # pragma: no cover - lost to a concurrent delete
            raise RuntimeError(
                f"review {event.source}:{key} for tenant {tenant_id!r} "
                "conflicted on insert but could not be read back"
            )
        return existing, False

    async def get(self, tenant_id: str, review_id: str) -> Optional[Review]:
        """Return one review by surrogate key."""
        key = as_uuid(review_id)
        if key is None:
            return None
        row = await self.fetch_one(
            tenant_id,
            f"SELECT {_REVIEW_COLUMNS} FROM {self.table('reviews')} "
            "WHERE tenant_id = $1 AND review_id = $2",
            key,
        )
        return Review.from_row(row) if row else None

    async def get_by_external_id(
        self, tenant_id: str, source: str, external_id: str
    ) -> Optional[Review]:
        """Return one review by its source identity."""
        row = await self.fetch_one(
            tenant_id,
            f"SELECT {_REVIEW_COLUMNS} FROM {self.table('reviews')} "
            "WHERE tenant_id = $1 AND source = $2 AND external_id = $3",
            source,
            external_id,
        )
        return Review.from_row(row) if row else None

    async def list_reviews(
        self,
        tenant_id: str,
        *,
        status: Optional[ReviewStatus] = None,
        since: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Review]:
        """List a tenant's reviews, newest first.

        Args:
            tenant_id: Owning tenant.
            status: Optional pipeline filter.
            since: Only reviews posted strictly after this instant.
            limit: Maximum rows.
            offset: Rows to skip.

        Returns:
            The matching reviews.
        """
        rows = await self.fetch_all(
            tenant_id,
            f"SELECT {_REVIEW_COLUMNS} FROM {self.table('reviews')} "
            "WHERE tenant_id = $1 "
            "  AND ($2::text IS NULL OR status = $2) "
            "  AND ($3::timestamptz IS NULL OR posted_at > $3) "
            "ORDER BY posted_at DESC, review_id "
            "LIMIT $4 OFFSET $5",
            status.value if isinstance(status, ReviewStatus) else status,
            since,
            limit,
            offset,
        )
        return [Review.from_row(row) for row in rows]

    async def set_status(
        self, tenant_id: str, review_id: str, status: ReviewStatus
    ) -> Optional[Review]:
        """Move a review to a new pipeline state."""
        key = as_uuid(review_id)
        if key is None:
            return None
        row = await self.fetch_one(
            tenant_id,
            f"UPDATE {self.table('reviews')} SET status = $3 "
            "WHERE tenant_id = $1 AND review_id = $2 "
            f"RETURNING {_REVIEW_COLUMNS}",
            key,
            status.value if isinstance(status, ReviewStatus) else status,
        )
        return Review.from_row(row) if row else None

    async def attach_guest(
        self, tenant_id: str, review_id: str, guest_id: str
    ) -> Optional[Review]:
        """Link a review to a guest resolved after ingest.

        Contact details usually arrive later than the review itself — public
        review platforms rarely expose them — so this is the normal path, not
        a correction.
        """
        key = as_uuid(review_id)
        if key is None:
            return None
        row = await self.fetch_one(
            tenant_id,
            f"UPDATE {self.table('reviews')} SET guest_id = $3 "
            "WHERE tenant_id = $1 AND review_id = $2 "
            f"RETURNING {_REVIEW_COLUMNS}",
            key,
            as_uuid(guest_id),
        )
        return Review.from_row(row) if row else None

    # -- replies -----------------------------------------------------------

    async def record_reply(
        self,
        tenant_id: str,
        review_id: str,
        *,
        text: str,
        status: ReplyStatus = ReplyStatus.DRAFT,
        external_reply_id: str = "",
        attempt: int = 1,
        reason: str = "",
    ) -> ReviewReplyRecord:
        """Store one drafting attempt and its outcome.

        Args:
            tenant_id: Owning tenant.
            review_id: The review being answered.
            text: The drafted reply.
            status: Whether it reached the platform.
            external_reply_id: The platform's identifier, once published.
            attempt: Drafting round, starting at 1.
            reason: Why it failed or was withheld.

        Returns:
            The stored record.

        Raises:
            ValueError: If ``review_id`` is not a valid surrogate key. Unlike
                a read, an unstorable reply must be loud — losing the record of
                a published reply is worse than failing the call.
        """
        key = as_uuid(review_id)
        if key is None:
            raise ValueError(f"not a valid review id: {review_id!r}")
        row = await self.fetch_one(
            tenant_id,
            f"INSERT INTO {self.table('review_replies')} "
            "(tenant_id, review_id, body, status, external_reply_id, attempt, "
            " reason) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7) "
            f"RETURNING {_REPLY_COLUMNS}",
            key,
            text,
            status.value if isinstance(status, ReplyStatus) else status,
            external_reply_id,
            attempt,
            reason,
        )
        return ReviewReplyRecord.from_row(row)

    async def list_replies(
        self, tenant_id: str, review_id: str
    ) -> Sequence[ReviewReplyRecord]:
        """Return every drafting attempt for a review, newest first."""
        key = as_uuid(review_id)
        if key is None:
            return []
        rows = await self.fetch_all(
            tenant_id,
            f"SELECT {_REPLY_COLUMNS} FROM {self.table('review_replies')} "
            "WHERE tenant_id = $1 AND review_id = $2 "
            "ORDER BY created_at DESC, reply_id",
            key,
        )
        return [ReviewReplyRecord.from_row(row) for row in rows]


__all__ = ("GuestRepository", "ReviewRepository", "as_uuid")
