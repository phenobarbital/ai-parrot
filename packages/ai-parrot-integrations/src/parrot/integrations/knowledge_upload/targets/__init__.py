"""Target factory for knowledge uploads (lazy: no knowledge imports when disabled)."""

from __future__ import annotations

from ..models import KnowledgeUploadConfig, UploadTargetKind
from .base import IngestTarget


def build_targets(config: KnowledgeUploadConfig) -> dict[UploadTargetKind, IngestTarget]:
    """Instantiate the configured targets; availability is checked by the service."""
    targets: dict[UploadTargetKind, IngestTarget] = {}
    if config.bookstore is not None:
        from .bookstore import BookstoreTarget

        targets[UploadTargetKind.BOOKSTORE] = BookstoreTarget(config.bookstore)
    if config.wiki is not None:
        from .wiki import WikiTarget

        targets[UploadTargetKind.WIKI] = WikiTarget(config.wiki)
    return targets


__all__ = ["IngestTarget", "build_targets"]
