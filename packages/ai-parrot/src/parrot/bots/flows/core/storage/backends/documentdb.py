"""DocumentDbResultStorage — default backend wrapping DocumentDb (FEAT-147).

Preserves today's behaviour exactly: each ``save()`` opens a fresh
``async with DocumentDb()`` context and calls ``db.write()``.
"""
from __future__ import annotations

from typing import Any

from navconfig.logging import logging

from parrot.interfaces.documentdb import DocumentDb

from .base import ResultStorage


class DocumentDbResultStorage(ResultStorage):
    """Default backend — preserves the legacy DocumentDB write path.

    Each ``save()`` call opens a fresh ``async with DocumentDb()`` context,
    matching the existing fire-and-forget semantics. ``close()`` is a no-op
    because the connection lifecycle is owned per-write.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger("parrot.crew_storage.documentdb")

    async def save(self, collection: str, document: dict[str, Any]) -> None:
        """Persist a document to DocumentDB.

        Args:
            collection: Target MongoDB collection name.
            document: Execution result document.
        """
        async with DocumentDb() as db:
            await db.write(collection, document)

    async def close(self) -> None:
        """No-op — connection lifecycle is per-write in this backend."""
        return None
