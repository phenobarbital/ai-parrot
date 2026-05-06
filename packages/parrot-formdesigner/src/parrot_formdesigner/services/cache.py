"""Form Cache for the forms abstraction layer.

Provides in-memory TTL-based caching for FormSchema objects with optional
Redis backend for distributed caching.

Migrated from parrot/integrations/dialogs/cache.py with:
- FormSchema instead of FormDefinition
- Cleaner async-only API (asyncio.Lock throughout)
- Redis serialization via FormSchema.model_dump_json()
- No watchdog dependency in core (file watching is optional)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from ..core.schema import FormSchema

logger = logging.getLogger(__name__)


@dataclass
class _CacheEntry:
    """Internal cache entry with TTL metadata."""

    form: FormSchema
    loaded_at: datetime
    access_count: int = 0
    last_accessed: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


class FormCache:
    """In-memory TTL cache for FormSchema with optional Redis backend.

    Supports:
    - In-memory cache with per-entry TTL expiration
    - Optional Redis backend for distributed/multi-process caching
    - Async-safe with asyncio.Lock
    - Invalidation callbacks for downstream notification

    Example:
        cache = FormCache(ttl_seconds=3600)
        await cache.set(form_schema)
        form = await cache.get("my-form")

        # With Redis
        cache = FormCache(ttl_seconds=3600, redis_url="redis://localhost:6379")
        await cache.set(form_schema)
    """

    REDIS_KEY_PREFIX = "parrot:form:"

    def __init__(
        self,
        ttl_seconds: int = 3600,
        redis_url: str | None = None,
    ) -> None:
        """Initialize FormCache.

        Args:
            ttl_seconds: Time-to-live in seconds for cached entries.
                Default: 3600 (1 hour).
            redis_url: Optional Redis connection URL. If provided, forms are
                also stored in Redis for distributed access.
        """
        self._memory_cache: dict[str, _CacheEntry] = {}
        self._ttl = timedelta(seconds=ttl_seconds)
        self._redis_url = redis_url
        self._redis: Any | None = None
        self._lock = asyncio.Lock()
        self._on_invalidate: list[Callable[[str], Awaitable[None]]] = []
        self.logger = logging.getLogger(__name__)

    async def _get_redis(self) -> Any | None:
        """Lazily initialize Redis connection (thread-safe).

        Uses the instance lock to prevent duplicate connections from
        concurrent coroutines (double-checked locking pattern).

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
                        "redis not installed — Redis caching unavailable"
                    )
                except Exception as exc:
                    self.logger.warning("Failed to connect to Redis: %s", exc)
        return self._redis

    async def get(self, form_id: str) -> FormSchema | None:
        """Retrieve a form from cache.

        Checks memory cache first, then Redis. Expired entries are evicted.

        Args:
            form_id: Form identifier.

        Returns:
            FormSchema if found and not expired, None otherwise.
        """
        # Memory cache
        async with self._lock:
            entry = self._memory_cache.get(form_id)
            if entry is not None:
                if datetime.now(tz=timezone.utc) - entry.loaded_at > self._ttl:
                    # Expired — evict
                    del self._memory_cache[form_id]
                else:
                    entry.access_count += 1
                    entry.last_accessed = datetime.now(tz=timezone.utc)
                    return entry.form

        # Redis fallback
        redis = await self._get_redis()
        if redis:
            form = await self._redis_get(redis, form_id)
            if form is not None:
                # Populate memory cache from Redis
                await self._set_memory(form)
                return form

        return None

    async def set(self, form: FormSchema) -> None:
        """Store a form in cache.

        Args:
            form: FormSchema to cache.
        """
        await self._set_memory(form)

        redis = await self._get_redis()
        if redis:
            await self._redis_set(redis, form)

    async def _set_memory(self, form: FormSchema) -> None:
        """Store form in the memory cache.

        Args:
            form: FormSchema to store.
        """
        async with self._lock:
            self._memory_cache[form.form_id] = _CacheEntry(
                form=form,
                loaded_at=datetime.now(tz=timezone.utc),
            )

    async def invalidate(self, form_id: str) -> None:
        """Remove a form from cache.

        Args:
            form_id: Identifier of the form to evict.
        """
        async with self._lock:
            self._memory_cache.pop(form_id, None)

        redis = await self._get_redis()
        if redis:
            await self._redis_delete(redis, form_id)

        # Fire callbacks
        for callback in self._on_invalidate:
            try:
                await callback(form_id)
            except Exception as exc:
                self.logger.warning("Invalidate callback failed: %s", exc)

    async def invalidate_all(self) -> None:
        """Clear all forms from cache.

        Note: Per-key ``on_invalidate`` callbacks are NOT fired during bulk
        invalidation. Callers that require per-key notification should use
        ``invalidate()`` individually instead.
        """
        async with self._lock:
            self._memory_cache.clear()

        redis = await self._get_redis()
        if redis:
            await self._redis_clear(redis)

    def on_invalidate(
        self, callback: Callable[[str], Awaitable[None]]
    ) -> None:
        """Register a callback for invalidation events.

        Args:
            callback: Async callable receiving the invalidated form_id.
        """
        self._on_invalidate.append(callback)

    async def size(self) -> int:
        """Return number of currently cached (unexpired) forms.

        Returns:
            Count of valid cache entries.
        """
        now = datetime.now(tz=timezone.utc)
        async with self._lock:
            return sum(
                1
                for entry in self._memory_cache.values()
                if now - entry.loaded_at <= self._ttl
            )

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    def _redis_key(self, form_id: str) -> str:
        """Build a Redis key for a form_id.

        Args:
            form_id: Form identifier.

        Returns:
            Namespaced Redis key string.
        """
        return f"{self.REDIS_KEY_PREFIX}{form_id}"

    async def _redis_get(self, redis: Any, form_id: str) -> FormSchema | None:
        """Fetch and deserialize a form from Redis.

        Args:
            redis: Redis client.
            form_id: Form identifier.

        Returns:
            FormSchema if found, None otherwise.
        """
        try:
            key = self._redis_key(form_id)
            data = await redis.get(key)
            if data:
                return FormSchema.model_validate_json(data)
        except Exception as exc:
            self.logger.warning("Redis get failed for %s: %s", form_id, exc)
        return None

    async def _redis_set(self, redis: Any, form: FormSchema) -> None:
        """Serialize and store a form in Redis with TTL.

        Args:
            redis: Redis client.
            form: FormSchema to store.
        """
        try:
            key = self._redis_key(form.form_id)
            ttl_secs = int(self._ttl.total_seconds())
            await redis.setex(key, ttl_secs, form.model_dump_json())
        except Exception as exc:
            self.logger.warning(
                "Redis set failed for %s: %s", form.form_id, exc
            )

    async def _redis_delete(self, redis: Any, form_id: str) -> None:
        """Delete a form from Redis.

        Args:
            redis: Redis client.
            form_id: Form identifier.
        """
        try:
            await redis.delete(self._redis_key(form_id))
        except Exception as exc:
            self.logger.warning("Redis delete failed for %s: %s", form_id, exc)

    async def _redis_clear(self, redis: Any) -> None:
        """Clear all form entries from Redis.

        Args:
            redis: Redis client.
        """
        try:
            keys = await redis.keys(f"{self.REDIS_KEY_PREFIX}*")
            if keys:
                await redis.delete(*keys)
        except Exception as exc:
            self.logger.warning("Redis clear failed: %s", exc)

    async def close(self) -> None:
        """Close the Redis connection if open."""
        if self._redis is not None:
            try:
                await self._redis.close()
            except Exception as exc:
                self.logger.debug("Error closing Redis connection: %s", exc)
            self._redis = None
