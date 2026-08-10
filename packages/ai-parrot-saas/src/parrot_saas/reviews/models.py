"""Persisted review-side records: reviews, their replies, and guests.

:class:`~parrot_saas.reviews.port.ReviewEvent` is what a source hands over;
these are what the database holds afterwards. The split matters because the
two differ in exactly the places that carry authority: a stored review has a
``review_id`` we minted, a ``tenant_id`` the ingest path assigned, and a
``guest_id`` we resolved — none of which an adapter is allowed to decide.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field


class ReviewStatus(str, Enum):
    """Where a review is in the Community Manager pipeline.

    Advisory rather than a state machine: the flow's own routing is the
    authority, and this exists so an operator listing reviews can see what
    happened without reading run records.
    """

    RECEIVED = "received"
    IN_PROGRESS = "in_progress"
    REPLIED = "replied"
    SKIPPED = "skipped"
    FAILED = "failed"


class ReplyStatus(str, Enum):
    """Whether a drafted reply made it to the platform."""

    DRAFT = "draft"
    PUBLISHED = "published"
    FAILED = "failed"


class Guest(BaseModel):
    """A person a tenant can contact with an offer.

    Attributes:
        guest_id: Surrogate key.
        tenant_id: Owning tenant.
        email: Normalised to lowercase; empty when unknown.
        phone: Stored as supplied. **Not** normalised to E.164 — doing that
            properly needs a region per tenant and a phone library, so matching
            is exact and the limitation is explicit rather than half-done.
        display_name: Name to address them by.
        consent_marketing: Whether they agreed to be contacted with offers.
            Read directly by the coupon eligibility rules, so it is a stored
            fact rather than something inferred at decision time.
        lifetime_visits: Visit count, fed by the tenant's own systems.
        created_at: Row creation time.
        updated_at: Last modification time.
    """

    model_config = ConfigDict(use_enum_values=True, validate_default=True)

    guest_id: str = ""
    tenant_id: str = ""
    email: str = ""
    phone: str = ""
    display_name: str = ""
    consent_marketing: bool = False
    lifetime_visits: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Guest":
        """Build a guest from a database row."""
        data = dict(row)
        if data.get("guest_id") is not None:
            data["guest_id"] = str(data["guest_id"])
        return cls(**data)


class Review(BaseModel):
    """A review as stored in ``saas.reviews``.

    Attributes:
        review_id: Surrogate key, minted by the database.
        tenant_id: Owning tenant, assigned by the ingest path.
        source: Adapter that produced it.
        external_id: The source's identifier, unique per tenant and source.
        location_ref: The source's venue identifier, unresolved by design.
        guest_id: Resolved guest, when one could be matched.
        rating: Star rating, ``0`` when the source has none.
        text: Review body.
        language: Language tag.
        author_name: Display name as published.
        status: Pipeline state.
        posted_at: When the guest published it.
        received_at: When we ingested it.
        raw: The original payload.
    """

    model_config = ConfigDict(use_enum_values=True, validate_default=True)

    review_id: str = ""
    tenant_id: str = ""
    source: str = ""
    external_id: str = ""
    location_ref: str = ""
    guest_id: str = ""
    rating: int = 0
    text: str = ""
    language: str = "en"
    author_name: str = ""
    status: ReviewStatus = ReviewStatus.RECEIVED
    posted_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Review":
        """Build a review from a database row.

        The column is ``body`` rather than ``text``: ``text`` is a type name
        in Postgres and reads badly in a select list. The model keeps ``text``
        because that is what the flow's ``ReviewIntake`` calls it.

        Args:
            row: A record from ``saas.reviews``. ``raw`` may arrive as a JSON
                string or a mapping depending on driver codecs.

        Returns:
            The parsed review.
        """
        data = dict(row)
        data["text"] = data.pop("body", "") or ""
        for key in ("review_id", "guest_id"):
            data[key] = str(data[key]) if data.get(key) is not None else ""
        raw = data.get("raw")
        if isinstance(raw, str):
            import json

            data["raw"] = json.loads(raw or "{}")
        elif raw is None:
            data["raw"] = {}
        return cls(**data)


class ReviewReplyRecord(BaseModel):
    """A reply we drafted, and what became of it.

    Every attempt is a row, including the ones that were never published: the
    repair loop can produce several drafts for one review, and losing the
    rejected ones would erase the evidence of why the published text looks the
    way it does.

    Attributes:
        reply_id: Surrogate key.
        tenant_id: Owning tenant.
        review_id: The review this answers.
        text: The reply body.
        status: Whether it reached the platform.
        external_reply_id: The platform's identifier, once published.
        attempt: Which drafting round produced it, starting at 1.
        reason: Why it failed or was withheld, when it was.
        created_at: Row creation time.
    """

    model_config = ConfigDict(use_enum_values=True, validate_default=True)

    reply_id: str = ""
    tenant_id: str = ""
    review_id: str = ""
    text: str = ""
    status: ReplyStatus = ReplyStatus.DRAFT
    external_reply_id: str = ""
    attempt: int = 1
    reason: str = ""
    created_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "ReviewReplyRecord":
        """Build a reply record from a database row."""
        data = dict(row)
        data["text"] = data.pop("body", "") or ""
        for key in ("reply_id", "review_id"):
            data[key] = str(data[key]) if data.get(key) is not None else ""
        return cls(**data)


__all__ = (
    "Guest",
    "ReplyStatus",
    "Review",
    "ReviewReplyRecord",
    "ReviewStatus",
)
