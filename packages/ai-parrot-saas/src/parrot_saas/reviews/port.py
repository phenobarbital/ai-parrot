"""The :class:`ReviewSource` port — where reviews come from and replies go.

A tenant's reviews may arrive from Google Business, a booking platform, a
generic signed webhook, or a seeded corpus in a demo. The flow must not know
which. This port is the seam: it carries a normalised :class:`ReviewEvent` in
and a :class:`ReviewReply` out, and every adapter behind it is interchangeable.

Two of its choices are deliberate and worth stating, because both fail quietly
if reversed:

* **The port does not touch the database.** Adapters normalise and talk to
  their platform; persisting a review or a reply is the repository's job,
  driven by the flow. A real adapter (Google Business, Meta) has no business
  writing to our tables, so the mock must not either — otherwise the mock
  teaches a shape the real ones cannot follow.
* **:meth:`ReviewSource.verify_webhook` denies by default.** A source that has
  not implemented signature verification must not accept an unauthenticated
  webhook because it forgot to say no.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ReviewEvent(BaseModel):
    """A review as it arrives from a source, normalised but not yet stored.

    Attributes:
        source: Adapter name that produced this event.
        external_id: The source's own identifier for the review. Combined with
            ``source`` and the tenant it forms the de-duplication key.
        tenant_id: Owning tenant. Set by the ingest path, not by the adapter —
            an adapter has no authority to decide whose review this is.
        location_ref: The source's identifier for the venue. Deliberately a
            free string, not a foreign key: a review can arrive for a location
            the tenant has not configured yet, and dropping it would be worse
            than storing it unresolved.
        rating: Star rating, ``0`` when the source has none.
        text: Review body.
        language: BCP-47-ish language tag.
        author_name: Display name, when the source exposes one.
        author_email: Contact e-mail, when the source exposes one. Usually
            absent on public review platforms — which is exactly why the flow
            has a contact-capture step.
        author_phone: Contact phone, when the source exposes one.
        posted_at: When the guest published it.
        raw: The original payload, kept for audit and replay.
    """

    model_config = ConfigDict(use_enum_values=True, validate_default=True)

    source: str
    external_id: str
    tenant_id: str = ""
    location_ref: str = ""
    rating: int = 0
    text: str = ""
    language: str = "en"
    author_name: str = ""
    author_email: str = ""
    author_phone: str = ""
    posted_at: datetime = Field(default_factory=_utcnow)
    raw: dict[str, Any] = Field(default_factory=dict)


class ReviewReply(BaseModel):
    """The outcome of publishing a reply on the source platform.

    Attributes:
        external_reply_id: The platform's identifier for the published reply.
        source: Adapter that published it.
        published_at: When the platform accepted it.
    """

    model_config = ConfigDict(validate_default=True)

    external_reply_id: str
    source: str = ""
    published_at: datetime = Field(default_factory=_utcnow)


class ReviewSourceError(RuntimeError):
    """A source could not be reached, or refused an operation."""


class ReviewSource(ABC):
    """Adapter over one platform that publishes reviews and accepts replies.

    Implementations are constructed once per deployment (not per tenant) and
    receive ``tenant_id`` on every call, because one adapter serves every
    tenant that uses that platform.

    Attributes:
        name: Stable adapter name. Stored on every review row and used as part
            of the de-duplication key, so changing it orphans existing rows.
    """

    name: str = "review-source"

    @abstractmethod
    async def fetch(
        self,
        tenant_id: str,
        *,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> Sequence[ReviewEvent]:
        """Return recent reviews for a tenant.

        Args:
            tenant_id: Tenant whose reviews to read.
            since: Only reviews posted strictly after this instant.
            limit: Maximum number to return.

        Returns:
            Normalised events, newest first.

        Raises:
            ReviewSourceError: If the platform could not be reached.
        """

    @abstractmethod
    async def reply(
        self, tenant_id: str, external_id: str, text: str
    ) -> ReviewReply:
        """Publish a public reply to a review.

        Args:
            tenant_id: Tenant on whose behalf to reply.
            external_id: The source's identifier for the review.
            text: The reply body.

        Returns:
            The published reply.

        Raises:
            ReviewSourceError: If the platform rejected the reply.
        """

    @abstractmethod
    def normalize(self, payload: Mapping[str, Any]) -> ReviewEvent:
        """Convert a raw platform payload into a :class:`ReviewEvent`.

        Args:
            payload: The platform's own representation.

        Returns:
            The normalised event, with ``tenant_id`` left unset — the ingest
            path assigns it from the authenticated request, never the payload.

        Raises:
            ValueError: If the payload is not a review this source recognises.
        """

    def verify_webhook(
        self, headers: Mapping[str, str], body: bytes, secret: str
    ) -> bool:
        """Whether an inbound webhook is authentic.

        Denies by default. A source that cannot verify a signature must not
        accept webhooks at all, and inheriting a permissive default is how
        that turns into an open ingest endpoint.

        Args:
            headers: Request headers.
            body: The **raw** request body. Signatures cover bytes, so a body
                that has been parsed and re-serialised will not verify.
            secret: The tenant's shared secret for this source.

        Returns:
            ``True`` only when the signature is present and correct.
        """
        return False

    def dedupe_key(self, event: ReviewEvent) -> str:
        """Return the value used to recognise a repeat of this review.

        Defaults to the source's own identifier, which is what a platform with
        stable ids should use. A source whose ids are not stable — or absent —
        must override this with a content hash, or replays will create
        duplicate rows and duplicate replies.

        Args:
            event: The normalised event.

        Returns:
            The de-duplication value, stored as ``reviews.external_id``.
        """
        return event.external_id


__all__ = (
    "ReviewEvent",
    "ReviewReply",
    "ReviewSource",
    "ReviewSourceError",
)
