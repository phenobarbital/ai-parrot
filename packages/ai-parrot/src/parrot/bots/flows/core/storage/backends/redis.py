"""RedisResultStorage — Redis backend for crew/flow execution results (FEAT-147).

One key per execution: ``{collection}:{crew_name}:{ts_ms}``, JSON value, optional TTL.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from navconfig.logging import logging
from asyncdb import AsyncDB

from parrot.conf import (
    CREW_RESULT_STORAGE_REDIS_URL,
    CREW_RESULT_STORAGE_REDIS_TTL,
)
from .base import ResultStorage


class RedisResultStorage(ResultStorage):
    """Persist crew/flow execution results to Redis (one key per execution).

    Key shape: ``{collection}:{crew_name}:{timestamp_ms}``
    Value: JSON-encoded document (with ``default=str`` for non-serialisable fields).
    TTL: configurable via constructor or ``CREW_RESULT_STORAGE_REDIS_TTL`` (default 7 days).
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> None:
        """Initialise the Redis backend.

        Args:
            dsn: Redis DSN; defaults to ``CREW_RESULT_STORAGE_REDIS_URL``.
            ttl: Key TTL in seconds; ``0`` disables TTL. Defaults to
                ``CREW_RESULT_STORAGE_REDIS_TTL`` (604 800 s = 7 days).
        """
        self._dsn = dsn or CREW_RESULT_STORAGE_REDIS_URL
        self._ttl: int = CREW_RESULT_STORAGE_REDIS_TTL if ttl is None else ttl
        self._conn: Optional[AsyncDB] = None
        self.logger = logging.getLogger("parrot.crew_storage.redis")

    async def _ensure(self) -> AsyncDB:
        """Lazily open the Redis connection on first use."""
        if self._conn is None:
            self._conn = AsyncDB("redis", dsn=self._dsn)
            await self._conn.connection()
        return self._conn

    async def save(self, collection: str, document: dict[str, Any]) -> None:
        """Write one execution record to Redis.

        Args:
            collection: Logical collection name used as key prefix.
            document: Execution result document.
        """
        try:
            conn = await self._ensure()
            execution_id = document.get("execution_id")
            if execution_id:
                suffix = document.get("node_execution_id") or "crew"
                key = f"{collection}:{execution_id}:{suffix}"
            else:
                crew_name = document.get("crew_name", "unknown")
                ts_ms = int(time.time() * 1000)
                # NOTE: Millisecond precision means two concurrent runs of the same crew
                # in the same millisecond produce the same key. The second write overwrites
                # the first. This is acceptable under the fire-and-forget semantics.
                key = f"{collection}:{crew_name}:{ts_ms}"
            value = json.dumps(document, default=str)
            if self._ttl > 0:
                await conn.execute("SET", key, value, "EX", str(self._ttl))
            else:
                await conn.execute("SET", key, value)
        except Exception as exc:
            self.logger.warning(
                "RedisResultStorage save failed for collection=%s: %s",
                collection,
                exc,
            )

    async def fetch(self, collection: str, execution_id: str) -> list[dict[str, Any]]:
        """Return all documents written under *execution_id* in *collection*.

        Uses cursor-based ``SCAN`` (never ``KEYS``) with pattern
        ``{collection}:{execution_id}:*``, iterating until the cursor
        returns ``0``, then ``GET``s each matched key.

        Args:
            collection: Logical collection name used as key prefix.
            execution_id: Crew-level execution id to match keys against.

        Returns:
            List of parsed documents; empty list when nothing matches.

        Raises:
            Exception: Connection errors are logged then re-raised — unlike
                ``save()``, read failures must not be silently swallowed.
        """
        try:
            conn = await self._ensure()
            pattern = f"{collection}:{execution_id}:*"
            documents: list[dict[str, Any]] = []
            cursor = 0
            while True:
                cursor, keys = await conn.execute("SCAN", cursor, "MATCH", pattern)
                cursor = int(cursor)
                for key in keys:
                    value = await conn.execute("GET", key)
                    if value:
                        documents.append(json.loads(value))
                if cursor == 0:
                    break
            return documents
        except Exception as exc:
            self.logger.warning(
                "RedisResultStorage fetch failed for collection=%s, execution_id=%s: %s",
                collection,
                execution_id,
                exc,
            )
            raise

    async def close(self) -> None:
        """Release the Redis connection. Safe to call multiple times."""
        if self._conn is not None:
            try:
                await self._conn.close()
            finally:
                self._conn = None

    # ──────────────────────────────────────────────────────────────────
    # Read methods (FEAT-307)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _matches_filters(doc: dict[str, Any], filters: Optional[dict[str, Any]]) -> bool:
        """Check whether *doc* matches the given plain-dict filters.

        Legacy documents without a ``tenant`` field are treated as
        ``"global"`` (matching the Postgres backend's ``COALESCE`` behaviour).

        Args:
            doc: Parsed execution document.
            filters: Optional filters: ``tenant``, ``user_id``, ``crew_name``,
                ``method``, ``date_from``, ``date_to``.

        Returns:
            ``True`` if the document matches all provided filters.
        """
        if not filters:
            return True
        if filters.get("tenant") and doc.get("tenant", "global") != filters["tenant"]:
            return False
        if filters.get("user_id") and doc.get("user_id") != filters["user_id"]:
            return False
        if filters.get("crew_name") and doc.get("crew_name") != filters["crew_name"]:
            return False
        if filters.get("method") and doc.get("method") != filters["method"]:
            return False

        ts = doc.get("timestamp")
        date_from = filters.get("date_from")
        if date_from is not None and ts is not None:
            threshold = date_from.timestamp() if hasattr(date_from, "timestamp") else date_from
            if ts < threshold:
                return False
        date_to = filters.get("date_to")
        if date_to is not None and ts is not None:
            threshold = date_to.timestamp() if hasattr(date_to, "timestamp") else date_to
            if ts > threshold:
                return False
        return True

    async def _scan_documents(self, collection: str) -> list[dict[str, Any]]:
        """SCAN every key under ``{collection}:*`` and return parsed documents.

        Each returned document has an ``"id"`` key set to its Redis key
        (Redis documents have no natural id — the key itself identifies them).

        Args:
            collection: Logical collection name used as key prefix.

        Returns:
            All parsed documents found under the collection's key prefix.
        """
        conn = await self._ensure()
        pattern = f"{collection}:*"
        cursor = "0"
        docs: list[dict[str, Any]] = []

        while True:
            result = await conn.execute("SCAN", cursor, "MATCH", pattern, "COUNT", "100")
            cursor, keys = result[0], result[1]
            if keys:
                values = await conn.execute("MGET", *keys)
                for key, val in zip(keys, values):
                    if val:
                        doc = json.loads(val)
                        doc["id"] = key
                        docs.append(doc)
            if str(cursor) == "0":
                break

        return docs

    async def list(
        self,
        collection: str,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List execution documents ordered by ``timestamp DESC``.

        Uses SCAN + MGET to fetch all keys under the collection prefix, then
        filters and paginates in-memory (Redis is not the recommended backend
        for high-volume reads — see spec Known Risks).

        Args:
            collection: Logical collection name used as key prefix.
            filters: Optional in-memory filters — see :meth:`_matches_filters`.
            limit: Maximum number of documents to return.
            offset: Number of documents to skip (pagination), applied after filtering.

        Returns:
            A list of execution documents, newest first. Empty list on error
            or when no documents match.
        """
        try:
            docs = await self._scan_documents(collection)
            matched = [d for d in docs if self._matches_filters(d, filters)]
            matched.sort(key=lambda d: d.get("timestamp", 0), reverse=True)
            return matched[offset:offset + limit]
        except Exception as exc:
            self.logger.warning(
                "RedisResultStorage list failed for collection=%s: %s",
                collection,
                exc,
            )
            return []

    async def get(
        self,
        collection: str,
        record_id: str,
    ) -> Optional[dict[str, Any]]:
        """Retrieve a single execution document by its Redis key.

        Args:
            collection: Logical collection name used as key prefix.
            record_id: The Redis key identifying the document (as returned
                by ``list()``'s ``"id"`` field).

        Returns:
            The execution document, or ``None`` if not found, on error, or
            when ``record_id`` doesn't belong to ``collection`` (security:
            without this check a caller could GET an arbitrary Redis key
            outside this collection's namespace).
        """
        if not record_id.startswith(f"{collection}:"):
            self.logger.warning(
                "RedisResultStorage get refused: id=%s does not belong to "
                "collection=%s",
                record_id,
                collection,
            )
            return None
        try:
            conn = await self._ensure()
            value = await conn.execute("GET", record_id)
            if not value:
                return None
            doc = json.loads(value)
            doc["id"] = record_id
            return doc
        except Exception as exc:
            self.logger.warning(
                "RedisResultStorage get failed for collection=%s, id=%s: %s",
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
        """Delete a single execution document by its Redis key.

        Args:
            collection: Logical collection name used as key prefix.
            record_id: The Redis key identifying the document.

        Returns:
            ``True`` if a key was deleted, ``False`` otherwise (including on
            error, or when ``record_id`` doesn't belong to ``collection`` —
            see :meth:`get` for why this check exists).
        """
        if not record_id.startswith(f"{collection}:"):
            self.logger.warning(
                "RedisResultStorage delete refused: id=%s does not belong to "
                "collection=%s",
                record_id,
                collection,
            )
            return False
        try:
            conn = await self._ensure()
            result = await conn.execute("DEL", record_id)
            return int(result) > 0
        except Exception as exc:
            self.logger.warning(
                "RedisResultStorage delete failed for collection=%s, id=%s: %s",
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

        Args:
            collection: Logical collection name used as key prefix.
            filters: Optional in-memory filters — see :meth:`_matches_filters`.

        Returns:
            The number of matching documents, or ``0`` on error.
        """
        try:
            docs = await self._scan_documents(collection)
            return sum(1 for d in docs if self._matches_filters(d, filters))
        except Exception as exc:
            self.logger.warning(
                "RedisResultStorage count failed for collection=%s: %s",
                collection,
                exc,
            )
            return 0
