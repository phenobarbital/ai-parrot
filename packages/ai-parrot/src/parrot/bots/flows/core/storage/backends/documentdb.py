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
        try:
            async with DocumentDb() as db:
                await db.write(collection, document)
        except Exception as exc:
            self.logger.warning(
                "DocumentDbResultStorage save failed for collection=%s: %s",
                collection,
                exc,
            )

    async def fetch(self, collection: str, execution_id: str) -> list[dict[str, Any]]:
        """Return all documents in *collection* whose ``execution_id`` matches.

        Args:
            collection: Target MongoDB collection name.
            execution_id: Crew-level execution id to filter by.

        Returns:
            List of matching documents; empty list when nothing matches.

        Raises:
            Exception: Connection/query errors are logged then re-raised —
                unlike ``save()``, read failures must not be silently
                swallowed into an empty result.
        """
        try:
            async with DocumentDb() as db:
                return await db.read(collection, {"execution_id": execution_id})
        except Exception as exc:
            self.logger.warning(
                "DocumentDbResultStorage fetch failed for collection=%s: %s",
                collection,
                exc,
            )
            raise

    async def close(self) -> None:
        """No-op — connection lifecycle is per-write in this backend."""
        return None
