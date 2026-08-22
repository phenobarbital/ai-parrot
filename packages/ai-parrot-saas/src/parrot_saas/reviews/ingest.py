"""The common ingest path: verify, normalise, store once, enqueue a run.

Both entry points — the signed webhook and the authenticated simulate
endpoint — funnel through :class:`ReviewIngestService`. Keeping one path means
the de-duplication guarantee is stated once, and a demo exercises the same code
a platform does.

This module is deliberately **flow-agnostic**: it imports nothing from
``parrot_saas.flows``. Ingest is about admitting a review into the system; what
happens next is the launcher's business, and coupling the two would tie the
generic ingest to one vertical flow.
"""
from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable, Mapping, Optional, Protocol

from navconfig.logging import logging

from ..tenancy.context import TenantContext
from .models import Review
from .port import ReviewEvent, ReviewSource

logger = logging.getLogger("parrot_saas.reviews.ingest")

#: Outcome when a review was admitted and a run was queued.
STATUS_QUEUED = "queued"

#: Outcome when the platform delivered a review we already hold.
STATUS_DUPLICATE = "duplicate"


class RunLauncher(Protocol):
    """Starts the flow for a newly admitted review.

    Implemented by the runner. Kept as a callable rather than an import so
    ingest does not depend on any particular flow.
    """

    async def __call__(
        self, tenant: TenantContext, review: Review, run_id: str
    ) -> Any:
        """Run whatever this deployment does with a new review."""


async def null_run_launcher(
    tenant: TenantContext, review: Review, run_id: str
) -> dict:
    """Record that nothing ran, loudly.

    The default when no runner is wired in. It warns rather than failing
    silently: the review really was stored, so a silent no-op would look like
    success while every review piled up unanswered.

    Args:
        tenant: Tenant the review belongs to.
        review: The stored review.
        run_id: Identifier reserved for the run.

    Returns:
        A record of the non-event.
    """
    logger.warning(
        "review %s stored for tenant %s but no run launcher is configured; "
        "no flow was started (run_id=%s)",
        review.review_id,
        tenant.tenant_id,
        run_id,
    )
    return {"status": "not_started", "run_id": run_id}


class IngestResult:
    """What an ingest attempt produced.

    Attributes:
        review: The stored review, new or pre-existing.
        created: Whether this call admitted it.
        run_id: The queued run, or an empty string for a duplicate.
        status: :data:`STATUS_QUEUED` or :data:`STATUS_DUPLICATE`.
    """

    __slots__ = ("review", "created", "run_id", "status")

    def __init__(
        self, review: Review, created: bool, run_id: str = ""
    ) -> None:
        self.review = review
        self.created = created
        self.run_id = run_id
        self.status = STATUS_QUEUED if created else STATUS_DUPLICATE

    def to_json(self) -> dict:
        """Render for an HTTP response."""
        payload = {
            "status": self.status,
            "review_id": self.review.review_id,
            "external_id": self.review.external_id,
            "source": self.review.source,
        }
        if self.run_id:
            payload["run_id"] = self.run_id
        return payload


class ReviewIngestService:
    """Admits reviews and queues a run for the ones that are new.

    Args:
        reviews: Repository storing reviews and replies.
        guests: Repository resolving contact details to a guest.
        job_manager: The application's ``JobManager``. Optional — without one
            the launcher is awaited inline, which is what tests want and what a
            deployment without the jobs subsystem gets.
        run_launcher: Coroutine started for each newly admitted review.
            Defaults to :func:`null_run_launcher`.
    """

    def __init__(
        self,
        *,
        reviews: Any,
        guests: Any,
        job_manager: Optional[Any] = None,
        run_launcher: Optional[Callable[..., Awaitable[Any]]] = None,
    ) -> None:
        self._reviews = reviews
        self._guests = guests
        self._jobs = job_manager
        self._launcher = run_launcher or null_run_launcher

    async def ingest_payload(
        self,
        tenant: TenantContext,
        source: ReviewSource,
        payload: Mapping[str, Any],
    ) -> IngestResult:
        """Normalise a raw payload and admit it.

        Args:
            tenant: The verified tenant. Never taken from the payload.
            source: Adapter that produced the payload.
            payload: The platform's own representation.

        Returns:
            The outcome.

        Raises:
            ValueError: If the payload is not a review this source recognises.
        """
        return await self.ingest_event(tenant, source, source.normalize(payload))

    async def ingest_event(
        self,
        tenant: TenantContext,
        source: ReviewSource,
        event: ReviewEvent,
    ) -> IngestResult:
        """Admit an already-normalised event.

        A duplicate returns early and queues nothing. That is the point of the
        whole de-duplication design: a webhook retry must not produce a second
        run, a second public reply and a second coupon.

        Args:
            tenant: The verified tenant.
            source: Adapter that produced the event.
            event: The normalised review.

        Returns:
            The outcome.
        """
        guest_id = await self._resolve_guest(tenant.tenant_id, event)
        review, created = await self._reviews.ingest(
            tenant.tenant_id,
            event,
            external_id=source.dedupe_key(event),
            guest_id=guest_id,
        )
        if not created:
            logger.info(
                "tenant %s re-delivered review %s:%s; no run queued",
                tenant.tenant_id,
                review.source,
                review.external_id,
            )
            return IngestResult(review, created=False)

        run_id = await self._queue_run(tenant, review)
        return IngestResult(review, created=True, run_id=run_id)

    async def _resolve_guest(self, tenant_id: str, event: ReviewEvent) -> str:
        """Match or create the guest behind a review, when it names one.

        Public review platforms rarely expose contact details, so an empty
        result is the normal case rather than a failure — the flow has a
        contact-capture step precisely because of it.
        """
        guest = await self._guests.upsert(
            tenant_id,
            email=event.author_email,
            phone=event.author_phone,
            display_name=event.author_name,
        )
        return guest.guest_id if guest is not None else ""

    async def _queue_run(self, tenant: TenantContext, review: Review) -> str:
        """Start the run for a newly admitted review.

        The run id doubles as the job id so that one identifier follows the
        work from the 202 response through the job record and into the flow's
        checkpoint key.
        """
        run_id = str(uuid.uuid4())

        async def _work() -> Any:
            return await self._launcher(tenant, review, run_id)

        if self._jobs is None:
            await _work()
            return run_id

        self._jobs.create_job(
            job_id=run_id,
            obj_id=f"cm:{tenant.tenant_id}",
            query={
                "tenant_id": tenant.tenant_id,
                "review_id": review.review_id,
                "source": review.source,
                "external_id": review.external_id,
            },
            session_id=review.review_id,
            execution_mode="community_manager",
        )
        await self._jobs.execute_job(run_id, _work)
        return run_id


__all__ = (
    "STATUS_DUPLICATE",
    "STATUS_QUEUED",
    "IngestResult",
    "ReviewIngestService",
    "RunLauncher",
    "null_run_launcher",
)
