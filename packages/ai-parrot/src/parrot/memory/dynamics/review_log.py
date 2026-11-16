"""Optional durable review capability; baseline episode backends remain valid."""

from typing import Protocol, runtime_checkable

from .models import Grade, MemoryParameters, ReviewCommand, ReviewReceipt

@runtime_checkable
class ReviewBackend(Protocol):
    """Apply scoped dedupe, expected revision, review and state as one transaction."""

    async def apply_review(
        self,
        command: ReviewCommand,
        *,
        grade: Grade | None = None,
        memory_error_signature: str | None = None,
        parameters: MemoryParameters | None = None,
    ) -> ReviewReceipt:
        """Return applied only after commit; pending requires a durable replay record."""
        ...
