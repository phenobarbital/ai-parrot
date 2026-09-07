"""Entry node: admit a stored review into the flow.

The review is already in the database by the time this runs — the ingest path
verified the webhook, normalised the payload and applied the
``(tenant_id, source, external_id)`` uniqueness constraint, which is what makes
a platform retry a duplicate rather than a second run. So this node does not
store anything. It **reads back** what was stored, which matters for one field
in particular: ``guest_id``. Ingest resolves the guest, and a stale copy of the
review carried in shared state would send the whole coupon branch looking for
contact details that were already on file.

It also seeds the two values every later node reads off the context: the tenant
id, and the tenant's timezone — without which the eligibility rules would judge
"weekend" in UTC.
"""
from __future__ import annotations

from typing import Any, Optional

from navconfig.logging import logging
from parrot.bots.flows.core import FlowContext
from parrot.bots.flows.core.types import DependencyResults

from ..models import ReviewIntake
from .base import CMNode, register_cm_node

logger = logging.getLogger("parrot_saas.flows.cm.intake")


@register_cm_node("cm.review_intake")
class ReviewIntakeNode(CMNode):
    """Load the review this run is about and mark it in progress.

    Attributes:
        review_repository: Repository the stored review is read back from.
            Absent, the node trusts what the runner seeded — which is what
            keeps the graph testable with no database at all.
        tenant_id: Owning tenant, seeded onto the context for later nodes.
        timezone: The tenant's IANA zone, seeded for the eligibility rules.
    """

    review_repository: Optional[Any] = None
    tenant_id: str = ""
    timezone: str = "UTC"

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> ReviewIntake:
        """Return the review that started this run.

        Args:
            ctx: Flow execution context. ``shared_data["review"]`` carries what
                the runner seeded.
            deps: Upstream results (none — this is the entry node).
            **kwargs: Unused.

        Returns:
            The typed review payload.

        Raises:
            ValueError: If the runner did not seed a review.
        """
        shared = self.shared_state(ctx)
        payload = shared.get("review")
        if payload is None:
            raise ValueError(
                "no review in shared_data['review']; the runner must seed the "
                "normalised review before running the flow"
            )
        intake = (
            payload
            if isinstance(payload, ReviewIntake)
            else ReviewIntake(**payload)
        )

        tenant_id = self.tenant_id or intake.tenant_id
        intake = await self._refresh(tenant_id, intake)

        shared["review"] = intake
        shared["tenant_id"] = tenant_id
        shared.setdefault("timezone", self.timezone)
        return intake

    async def _refresh(
        self, tenant_id: str, intake: ReviewIntake
    ) -> ReviewIntake:
        """Read the stored row back and mark the review in progress.

        A failure here is not fatal. The row is a record of the run, not its
        input: if the database is briefly unreachable the reply is still worth
        sending, and taking the whole flow down would turn a blip into an
        unanswered guest.

        Args:
            tenant_id: Owning tenant.
            intake: What the runner seeded.

        Returns:
            The review, with anything the stored row knows better.
        """
        if self.review_repository is None or not intake.review_id:
            return intake

        try:
            from ....reviews.models import ReviewStatus

            stored = await self.review_repository.set_status(
                tenant_id, intake.review_id, ReviewStatus.IN_PROGRESS
            )
            if stored is None:
                stored = await self.review_repository.get(
                    tenant_id, intake.review_id
                )
        except Exception as exc:  # noqa: BLE001 - degrade, never block a reply
            logger.warning(
                "could not read review %s back for tenant %s: %s",
                intake.review_id,
                tenant_id,
                exc,
            )
            return intake

        if stored is None:
            logger.warning(
                "review %s is not stored for tenant %s; running on the "
                "seeded copy",
                intake.review_id,
                tenant_id,
            )
            return intake

        return intake.model_copy(
            update={
                "tenant_id": stored.tenant_id or intake.tenant_id,
                "source": stored.source or intake.source,
                "external_id": stored.external_id or intake.external_id,
                "location_ref": stored.location_ref or intake.location_ref,
                "rating": stored.rating or intake.rating,
                "text": stored.text or intake.text,
                "language": stored.language or intake.language,
                "author_name": stored.author_name or intake.author_name,
                # The one field worth the round trip: ingest resolved it, and
                # a stale copy would send the coupon branch hunting for
                # contact details already on file.
                "guest_id": stored.guest_id or intake.guest_id,
            }
        )


__all__ = ("ReviewIntakeNode",)
