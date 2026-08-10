"""Review ingest: the source port, its adapters, and persistence.

Exports are resolved lazily (PEP 562), matching the parent package: the
repositories pull in ``asyncdb``, which is a heavy import to pay for naming an
event type.
"""
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from .mock import DEMO_EPOCH, MockReviewSource, demo_corpus
    from .models import (
        Guest,
        ReplyStatus,
        Review,
        ReviewReplyRecord,
        ReviewStatus,
    )
    from .port import ReviewEvent, ReviewReply, ReviewSource, ReviewSourceError
    from .repository import GuestRepository, ReviewRepository

__all__ = (
    "DEMO_EPOCH",
    "Guest",
    "GuestRepository",
    "MockReviewSource",
    "ReplyStatus",
    "Review",
    "ReviewEvent",
    "ReviewReply",
    "ReviewReplyRecord",
    "ReviewRepository",
    "ReviewSource",
    "ReviewSourceError",
    "ReviewStatus",
    "demo_corpus",
)

_LAZY_EXPORTS = {
    "DEMO_EPOCH": ("parrot_saas.reviews.mock", "DEMO_EPOCH"),
    "MockReviewSource": ("parrot_saas.reviews.mock", "MockReviewSource"),
    "demo_corpus": ("parrot_saas.reviews.mock", "demo_corpus"),
    "Guest": ("parrot_saas.reviews.models", "Guest"),
    "ReplyStatus": ("parrot_saas.reviews.models", "ReplyStatus"),
    "Review": ("parrot_saas.reviews.models", "Review"),
    "ReviewReplyRecord": ("parrot_saas.reviews.models", "ReviewReplyRecord"),
    "ReviewStatus": ("parrot_saas.reviews.models", "ReviewStatus"),
    "ReviewEvent": ("parrot_saas.reviews.port", "ReviewEvent"),
    "ReviewReply": ("parrot_saas.reviews.port", "ReviewReply"),
    "ReviewSource": ("parrot_saas.reviews.port", "ReviewSource"),
    "ReviewSourceError": ("parrot_saas.reviews.port", "ReviewSourceError"),
    "GuestRepository": ("parrot_saas.reviews.repository", "GuestRepository"),
    "ReviewRepository": ("parrot_saas.reviews.repository", "ReviewRepository"),
}


def __getattr__(name: str) -> Any:
    """Resolve lazily-exported names on first access (PEP 562).

    Args:
        name: Attribute being looked up on the package.

    Returns:
        The resolved object.

    Raises:
        AttributeError: If ``name`` is not a known lazy export.
    """
    try:
        module_path, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
    from importlib import import_module

    return getattr(import_module(module_path), attr)


def __dir__() -> list[str]:
    """Expose lazy exports to ``dir()`` and tab-completion."""
    return sorted(__all__)
