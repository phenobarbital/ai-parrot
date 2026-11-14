"""Optional durable review capability; baseline episode backends remain valid."""

from typing import Protocol, runtime_checkable

from .models import ReviewCommand, ReviewReceipt


@runtime_checkable
class ReviewBackend(Protocol):
    """Apply scoped dedupe, expected revision, review and state as one transaction."""

    async def apply_review(self, command: ReviewCommand) -> ReviewReceipt:
        """Return applied only after commit; pending requires a durable replay record."""
        ...
