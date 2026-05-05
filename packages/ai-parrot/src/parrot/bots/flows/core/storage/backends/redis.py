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

    async def close(self) -> None:
        """Release the Redis connection. Safe to call multiple times."""
        if self._conn is not None:
            try:
                await self._conn.close()
            finally:
                self._conn = None
