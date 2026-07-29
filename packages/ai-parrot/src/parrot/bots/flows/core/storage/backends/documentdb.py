"""DocumentDbResultStorage — default backend wrapping DocumentDb (FEAT-147).

Preserves today's behaviour exactly: each ``save()`` opens a fresh
``async with DocumentDb()`` context and calls ``db.write()``.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

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

        A ``record_id`` (UUID string) is generated when the document doesn't
        already carry one, so ``get()``/``delete()`` have a stable identifier
        to query on (MongoDB's auto-generated ``_id`` is stripped by
        ``find_documents()`` and never exposed to callers — see FEAT-307).

        Args:
            collection: Target MongoDB collection name.
            document: Execution result document.
        """
        try:
            document.setdefault("record_id", str(uuid.uuid4()))
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

    # ──────────────────────────────────────────────────────────────────
    # Read methods (FEAT-307)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_query(filters: Optional[dict[str, Any]]) -> dict[str, Any]:
        """Build a MongoDB query dict from a plain-dict filter set.

        Args:
            filters: Optional filters: ``tenant``, ``user_id``, ``crew_name``,
                ``method``, ``date_from``, ``date_to``.

        Returns:
            A MongoDB query filter. Empty dict matches every document.
        """
        query: dict[str, Any] = {}
        filters = filters or {}

        if filters.get("tenant"):
            query["tenant"] = filters["tenant"]
        if filters.get("user_id"):
            query["user_id"] = filters["user_id"]
        if filters.get("crew_name"):
            query["crew_name"] = filters["crew_name"]
        if filters.get("method"):
            query["method"] = filters["method"]

        date_from = filters.get("date_from")
        date_to = filters.get("date_to")
        if date_from is not None or date_to is not None:
            ts_range: dict[str, Any] = {}
            if date_from is not None:
                ts_range["$gte"] = date_from
            if date_to is not None:
                ts_range["$lte"] = date_to
            query["timestamp"] = ts_range

        return query

    async def list(
        self,
        collection: str,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List execution documents ordered by ``timestamp DESC``.

        Motor's cursor (via ``find_documents()``) doesn't support ``skip`` in
        this wrapper, so pagination is done by over-fetching ``limit + offset``
        rows and slicing in-memory.

        Args:
            collection: Target MongoDB collection name.
            filters: Optional filters — see :meth:`_build_query`.
            limit: Maximum number of documents to return.
            offset: Number of documents to skip (pagination).

        Returns:
            A list of execution documents, newest first. Empty list on error
            or when no documents match.
        """
        try:
            query = self._build_query(filters)
            async with DocumentDb() as db:
                results = await db.find_documents(
                    collection,
                    query,
                    sort=[("timestamp", -1)],
                    limit=limit + offset,
                )
            return results[offset:offset + limit]
        except Exception as exc:
            self.logger.warning(
                "DocumentDbResultStorage list failed for collection=%s: %s",
                collection,
                exc,
            )
            return []

    async def get(
        self,
        collection: str,
        record_id: str,
    ) -> Optional[dict[str, Any]]:
        """Retrieve a single execution document by its ``record_id``.

        Args:
            collection: Target MongoDB collection name.
            record_id: UUID string assigned to the document during ``save()``.

        Returns:
            The execution document, or ``None`` if not found or on error.
        """
        try:
            async with DocumentDb() as db:
                return await db.read_one(collection, {"record_id": record_id})
        except Exception as exc:
            self.logger.warning(
                "DocumentDbResultStorage get failed for collection=%s, id=%s: %s",
                collection,
                record_id,
                exc,
            )
            return None

    async def delete(
        self,
        collection: str,
        record_id: str,
    ) -> bool:
        """Delete a single execution document by its ``record_id``.

        Args:
            collection: Target MongoDB collection name.
            record_id: UUID string assigned to the document during ``save()``.

        Returns:
            ``True`` if a document was deleted, ``False`` otherwise (including
            on error).
        """
        try:
            async with DocumentDb() as db:
                result = await db.delete_many(collection, {"record_id": record_id})
            return getattr(result, "deleted_count", 0) > 0
        except Exception as exc:
            self.logger.warning(
                "DocumentDbResultStorage delete failed for collection=%s, id=%s: %s",
                collection,
                record_id,
                exc,
            )
            return False

    async def count(
        self,
        collection: str,
        filters: Optional[dict[str, Any]] = None,
    ) -> int:
        """Count execution documents matching the given filters.

        No native count method exists on the ``DocumentDb`` wrapper, so this
        fetches matching documents via ``find_documents()`` (unbounded) and
        counts the result list.

        Args:
            collection: Target MongoDB collection name.
            filters: Optional filters — see :meth:`_build_query`.

        Returns:
            The number of matching documents, or ``0`` on error.
        """
        try:
            query = self._build_query(filters)
            async with DocumentDb() as db:
                results = await db.find_documents(collection, query)
            return len(results)
        except Exception as exc:
            self.logger.warning(
                "DocumentDbResultStorage count failed for collection=%s: %s",
                collection,
                exc,
            )
            return 0
