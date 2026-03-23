"""Event deduplication for Slack integration.

Slack retries event delivery if it doesn't receive HTTP 200 within ~3 seconds.
Without deduplication, the same message can be processed multiple times,
causing duplicate agent responses. This module provides both in-memory
and Redis-backed deduplication strategies.
"""
import time
import asyncio
import logging
from typing import Dict, Optional, Protocol, Union

logger = logging.getLogger("SlackDedup")


class EventDeduplicatorProtocol(Protocol):
    """Protocol for event deduplication backends.

    Both in-memory and Redis-backed implementations follow this interface.
    """

    def is_duplicate(self, event_id: str) -> bool:
        """Check if an event has been seen before.

        Args:
            event_id: The Slack event ID to check.

        Returns:
            True if the event was already processed, False otherwise.
        """
        ...

    async def start(self) -> None:
        """Start the deduplicator (e.g., cleanup tasks)."""
        ...

    async def stop(self) -> None:
        """Stop the deduplicator and clean up resources."""
        ...


class EventDeduplicator:
    """In-memory event deduplication with TTL.

    For single-instance deployments. Use RedisEventDeduplicator
    for multi-instance production environments.

    Args:
        ttl_seconds: Time-to-live for seen events (default: 300 seconds / 5 minutes).
        cleanup_interval: How often to run cleanup (default: 60 seconds).

    Example:
        >>> dedup = EventDeduplicator(ttl_seconds=300)
        >>> await dedup.start()
        >>> if not dedup.is_duplicate("evt_123"):
        ...     # Process the event
        ...     pass
        >>> await dedup.stop()
    """

    def __init__(self, ttl_seconds: int = 300, cleanup_interval: int = 60):
        self._seen: Dict[str, float] = {}
        self._ttl = ttl_seconds
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the background cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.debug("Deduplication cleanup task started")

    async def stop(self) -> None:
        """Stop the cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.debug("Deduplication cleanup task stopped")

    def is_duplicate(self, event_id: Optional[str]) -> bool:
        """Check if event was already seen. Thread-safe for sync contexts.

        Args:
            event_id: The Slack event ID to check.

        Returns:
            True if the event was already processed, False if new or empty.
        """
        if not event_id:
            return False
        now = time.time()
        if event_id in self._seen:
            logger.debug("Duplicate event detected: %s", event_id)
            return True
        self._seen[event_id] = now
        return False

    async def _cleanup_loop(self) -> None:
        """Periodically remove expired entries."""
        while True:
            await asyncio.sleep(self._cleanup_interval)
            cutoff = time.time() - self._ttl
            expired = [k for k, v in self._seen.items() if v < cutoff]
            for k in expired:
                del self._seen[k]
            if expired:
                logger.debug("Cleaned up %d expired events", len(expired))

    @property
    def seen_count(self) -> int:
        """Return the number of events currently tracked."""
        return len(self._seen)

    def clear(self) -> None:
        """Clear all tracked events. Useful for testing."""
        self._seen.clear()


class RedisEventDeduplicator:
    """Redis-backed deduplication for multi-instance deployments.

    Uses Redis SET NX with TTL for atomic deduplication across
    multiple application instances.

    Args:
        redis_pool: An async Redis client/pool (aioredis or redis-py async).
        prefix: Key prefix for deduplication keys (default: "slack:dedup:").
        ttl: Time-to-live in seconds (default: 300).

    Example:
        >>> import redis.asyncio as redis
        >>> pool = redis.from_url("redis://localhost")
        >>> dedup = RedisEventDeduplicator(pool)
        >>> await dedup.start()
        >>> if not await dedup.is_duplicate("evt_123"):
        ...     # Process the event
        ...     pass
        >>> await dedup.stop()
    """

    def __init__(
        self,
        redis_pool,  # aioredis/redis-py async pool
        prefix: str = "slack:dedup:",
        ttl: int = 300
    ):
        self._redis = redis_pool
        self._prefix = prefix
        self._ttl = ttl

    async def is_duplicate(self, event_id: Optional[str]) -> bool:
        """Check if event was seen using Redis SETNX.

        Args:
            event_id: The Slack event ID to check.

        Returns:
            True if the event was already processed, False if new or empty.
        """
        if not event_id:
            return False
        key = f"{self._prefix}{event_id}"
        # SET NX returns True if key was set (new), None/False if exists
        was_set = await self._redis.set(key, "1", nx=True, ex=self._ttl)
        if not was_set:
            logger.debug("Duplicate event detected (Redis): %s", event_id)
            return True
        return False

    async def start(self) -> None:
        """No-op for Redis (connection managed externally)."""
        logger.debug("RedisEventDeduplicator ready")

    async def stop(self) -> None:
        """No-op for Redis (connection managed externally)."""
        pass


# Type alias for deduplicator backends
DeduplicatorType = Union[EventDeduplicator, RedisEventDeduplicator]
