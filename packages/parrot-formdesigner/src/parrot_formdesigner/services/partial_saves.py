"""Redis-backed ephemeral storage for partial form answers.

Provides ``PartialSaveStore`` — a service that stores work-in-progress form
answers in Redis under the key namespace ``parrot:partial:{form_id}:{session_id}``.

Design mirrors ``FormCache`` (services/cache.py) with these differences:
- No in-memory cache tier: partial saves are per-session ephemeral data that
  is not worth local caching across requests.
- Key includes ``session_id`` for isolation between concurrent users.
- ``save()`` implements merge-on-write: new answers are merged over cached
  answers (last-write-wins), and the TTL is refreshed on every write.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ..core.partial import PartialFormData


class PartialSaveStore:
    """Redis-backed ephemeral storage for partial form answers.

    Each save merges the new answers over any cached answers (last-write-wins)
    and refreshes the TTL for the entire entry.  Different ``session_id`` values
    produce independent cache entries, ensuring session isolation.

    If no ``redis_url`` is provided (or Redis is unavailable), the service
    operates in a no-op mode: ``save()`` returns the merged state without
    persisting it, ``get()`` returns ``None``, and ``delete()`` returns
    ``False``.  This allows callers to handle graceful degradation.

    Args:
        ttl_seconds: Time-to-live in seconds for cached entries. Default: 3600
            (1 hour). Each ``save()`` call refreshes the TTL.
        redis_url: Optional Redis connection URL, e.g.
            ``"redis://localhost:6379"``.  If ``None``, Redis is not used.

    Example:
        store = PartialSaveStore(ttl_seconds=3600, redis_url="redis://localhost")
        partial = await store.save("my-form", "session-abc", {"name": "Alice"})
        cached = await store.get("my-form", "session-abc")
        await store.delete("my-form", "session-abc")
        await store.close()
    """

    REDIS_KEY_PREFIX = "parrot:partial:"

    def __init__(
        self,
        ttl_seconds: int = 3600,
        redis_url: str | None = None,
    ) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._redis_url = redis_url
        self._redis: Any | None = None
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def save(
        self,
        form_id: str,
        session_id: str,
        answers: dict[str, Any],
    ) -> PartialFormData:
        """Merge answers into the cached partial and return the updated state.

        New values override existing cached values (last-write-wins).  The TTL
        for the entire cache entry is refreshed on every call.

        If Redis is unavailable, the merged state is returned without persisting
        (in-process only — survives the current request but not across requests).

        Args:
            form_id: Form identifier.
            session_id: Session identifier (uniquely scopes the cache entry).
            answers: Mapping of field_id to new values.  Merged over any
                existing cached data.

        Returns:
            PartialFormData representing the full merged state after the save.
        """
        existing = await self.get(form_id, session_id)
        merged_data: dict[str, Any] = {
            **(existing.data if existing else {}),
            **answers,
        }

        now = datetime.now(tz=timezone.utc)
        partial = PartialFormData(
            form_id=form_id,
            session_id=session_id,
            data=merged_data,
            field_errors={},  # populated by handler, not store
            saved_at=now,
            expires_at=now + self._ttl,
        )

        redis = await self._get_redis()
        if redis is not None:
            await self._redis_set(redis, partial)

        return partial

    async def get(
        self,
        form_id: str,
        session_id: str,
    ) -> PartialFormData | None:
        """Retrieve cached partial answers.

        Returns ``None`` if the entry is absent or has expired.  Redis handles
        TTL expiry natively — no client-side TTL check is needed.

        Args:
            form_id: Form identifier.
            session_id: Session identifier.

        Returns:
            PartialFormData if cached, None otherwise.
        """
        redis = await self._get_redis()
        if redis is None:
            return None
        return await self._redis_get(redis, form_id, session_id)

    async def delete(
        self,
        form_id: str,
        session_id: str,
    ) -> bool:
        """Remove cached partial answers.

        Args:
            form_id: Form identifier.
            session_id: Session identifier.

        Returns:
            True if the key existed (and was deleted), False if no entry was
            cached or Redis is unavailable.
        """
        redis = await self._get_redis()
        if redis is None:
            return False
        return await self._redis_delete(redis, form_id, session_id)

    async def close(self) -> None:
        """Close the Redis connection if open."""
        if self._redis is not None:
            try:
                await self._redis.close()
            except Exception as exc:
                self.logger.debug("Error closing Redis connection: %s", exc)
            self._redis = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _redis_key(self, form_id: str, session_id: str) -> str:
        """Build the namespaced Redis key for a form+session pair.

        Args:
            form_id: Form identifier.
            session_id: Session identifier.

        Returns:
            Key string of the form ``parrot:partial:{form_id}:{session_id}``.
        """
        return f"{self.REDIS_KEY_PREFIX}{form_id}:{session_id}"

    async def _get_redis(self) -> Any | None:
        """Lazily initialize Redis connection using double-checked locking.

        Mirrors the pattern in ``FormCache._get_redis()`` (services/cache.py:80).

        Returns:
            Redis client if available, None otherwise.
        """
        async with self._lock:
            if self._redis is None and self._redis_url:
                try:
                    from redis.asyncio import Redis  # type: ignore[import]
                    self._redis = await Redis.from_url(self._redis_url)
                except ImportError:
                    self.logger.warning(
                        "redis package not installed — PartialSaveStore unavailable"
                    )
                except Exception as exc:
                    self.logger.warning(
                        "PartialSaveStore: failed to connect to Redis: %s", exc
                    )
        return self._redis

    async def _redis_set(self, redis: Any, partial: PartialFormData) -> None:
        """Serialize and store a PartialFormData entry in Redis with TTL.

        Args:
            redis: Redis client.
            partial: PartialFormData to store.
        """
        try:
            key = self._redis_key(partial.form_id, partial.session_id)
            ttl_secs = int(self._ttl.total_seconds())
            await redis.setex(key, ttl_secs, partial.model_dump_json())
        except Exception as exc:
            self.logger.warning(
                "PartialSaveStore: Redis set failed for %s/%s: %s",
                partial.form_id,
                partial.session_id,
                exc,
            )

    async def _redis_get(
        self, redis: Any, form_id: str, session_id: str
    ) -> PartialFormData | None:
        """Fetch and deserialize a PartialFormData entry from Redis.

        Args:
            redis: Redis client.
            form_id: Form identifier.
            session_id: Session identifier.

        Returns:
            PartialFormData if found, None otherwise.
        """
        try:
            key = self._redis_key(form_id, session_id)
            data = await redis.get(key)
            if data:
                return PartialFormData.model_validate_json(data)
        except Exception as exc:
            self.logger.warning(
                "PartialSaveStore: Redis get failed for %s/%s: %s",
                form_id,
                session_id,
                exc,
            )
        return None

    async def _redis_delete(
        self, redis: Any, form_id: str, session_id: str
    ) -> bool:
        """Delete a PartialFormData entry from Redis.

        Args:
            redis: Redis client.
            form_id: Form identifier.
            session_id: Session identifier.

        Returns:
            True if the key existed, False otherwise.
        """
        try:
            key = self._redis_key(form_id, session_id)
            deleted_count = await redis.delete(key)
            return bool(deleted_count)
        except Exception as exc:
            self.logger.warning(
                "PartialSaveStore: Redis delete failed for %s/%s: %s",
                form_id,
                session_id,
                exc,
            )
            return False
