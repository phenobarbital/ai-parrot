"""Redis hot cache for episodic memory.

Caches recent episodes and failures per namespace using Redis data structures:
- ZSET (sorted by timestamp) for recent episodes.
- HASH for full episode data.
- LIST for failure episode IDs.

All operations degrade gracefully when Redis is unavailable.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .models import EpisodicMemory, MemoryNamespace

logger = logging.getLogger(__name__)

# Key suffixes
_RECENT_SUFFIX = ":recent"
_FAILURES_SUFFIX = ":failures"


class EpisodeRedisCache:
    """Redis-based hot cache for episodic memory.

    Stores recent episodes per namespace for fast access without
    hitting the backend. All methods return None on Redis errors,
    allowing the caller to fall back to the backend transparently.

    Args:
        redis_client: An async Redis client (redis.asyncio.Redis).
        default_ttl: TTL in seconds for cached data (default: 1 hour).
        max_recent: Maximum recent episodes per namespace in the ZSET.
        key_prefix: Base prefix for all Redis keys.
    """

    def __init__(
        self,
        redis_client: Any,
        default_ttl: int = 3600,
        max_recent: int = 50,
        key_prefix: str = "episodic",
    ) -> None:
        self._redis = redis_client
        self._default_ttl = default_ttl
        self._max_recent = max_recent
        self._key_prefix = key_prefix

    def _key(self, namespace: MemoryNamespace, suffix: str = "") -> str:
        """Build a Redis key from namespace prefix and suffix."""
        return f"{self._key_prefix}:{namespace.redis_prefix}{suffix}"

    def _episode_key(self, namespace: MemoryNamespace, episode_id: str) -> str:
        """Build a Redis key for a single episode HASH."""
        return f"{self._key_prefix}:{namespace.redis_prefix}:{episode_id}"

    async def cache_episode(
        self, namespace: MemoryNamespace, episode: EpisodicMemory
    ) -> None:
        """Cache an episode in Redis.

        Stores the episode as a HASH, adds it to the recent ZSET,
        and (if it's a failure) prepends its ID to the failures LIST.

        Args:
            namespace: The namespace scope for cache keys.
            episode: The episode to cache.
        """
        try:
            pipe = self._redis.pipeline()

            # Store full episode as JSON string in a HASH key
            episode_key = self._episode_key(namespace, episode.episode_id)
            episode_data = json.dumps(episode.to_dict())
            pipe.set(episode_key, episode_data)
            pipe.expire(episode_key, self._default_ttl)

            # Add to recent ZSET with timestamp score
            recent_key = self._key(namespace, _RECENT_SUFFIX)
            score = episode.created_at.timestamp()
            pipe.zadd(recent_key, {episode.episode_id: score})
            # Trim to max_recent (remove oldest entries beyond cap)
            pipe.zremrangebyrank(recent_key, 0, -(self._max_recent + 1))
            pipe.expire(recent_key, self._default_ttl)

            # Add to failures LIST if applicable
            if episode.is_failure:
                failures_key = self._key(namespace, _FAILURES_SUFFIX)
                pipe.lpush(failures_key, episode.episode_id)
                pipe.ltrim(failures_key, 0, self._max_recent - 1)
                pipe.expire(failures_key, self._default_ttl)

            await pipe.execute()
        except Exception as e:
            logger.warning("Redis cache_episode failed: %s", e)

    async def get_recent(
        self, namespace: MemoryNamespace, limit: int = 10
    ) -> list[EpisodicMemory] | None:
        """Get recent episodes from the cache.

        Args:
            namespace: The namespace scope.
            limit: Maximum number of episodes to return.

        Returns:
            List of episodes ordered by recency, or None on cache miss/error.
        """
        try:
            recent_key = self._key(namespace, _RECENT_SUFFIX)
            # Get most recent episode IDs (highest scores)
            episode_ids = await self._redis.zrevrange(recent_key, 0, limit - 1)
            if not episode_ids:
                return None

            return await self._fetch_episodes(namespace, episode_ids)
        except Exception as e:
            logger.warning("Redis get_recent failed: %s", e)
            return None

    async def get_failures(
        self, namespace: MemoryNamespace, limit: int = 5
    ) -> list[EpisodicMemory] | None:
        """Get cached failure episodes.

        Args:
            namespace: The namespace scope.
            limit: Maximum number of failures to return.

        Returns:
            List of failure episodes, or None on cache miss/error.
        """
        try:
            failures_key = self._key(namespace, _FAILURES_SUFFIX)
            episode_ids = await self._redis.lrange(failures_key, 0, limit - 1)
            if not episode_ids:
                return None

            return await self._fetch_episodes(namespace, episode_ids)
        except Exception as e:
            logger.warning("Redis get_failures failed: %s", e)
            return None

    async def get_episode(
        self, namespace: MemoryNamespace, episode_id: str
    ) -> EpisodicMemory | None:
        """Get a single cached episode.

        Args:
            namespace: The namespace scope.
            episode_id: The episode to retrieve.

        Returns:
            The episode, or None on cache miss/error.
        """
        try:
            episode_key = self._episode_key(namespace, episode_id)
            data = await self._redis.get(episode_key)
            if data is None:
                return None

            if isinstance(data, bytes):
                data = data.decode("utf-8")

            return EpisodicMemory.from_dict(json.loads(data))
        except Exception as e:
            logger.warning("Redis get_episode failed: %s", e)
            return None

    async def invalidate(self, namespace: MemoryNamespace) -> None:
        """Invalidate all cached data for a namespace.

        Deletes the recent ZSET, failures LIST, and all individual
        episode HASHes referenced by the ZSET.

        Args:
            namespace: The namespace to invalidate.
        """
        try:
            recent_key = self._key(namespace, _RECENT_SUFFIX)
            failures_key = self._key(namespace, _FAILURES_SUFFIX)

            # Collect all episode IDs from both structures
            episode_ids = set()
            zset_ids = await self._redis.zrange(recent_key, 0, -1)
            if zset_ids:
                episode_ids.update(
                    eid.decode("utf-8") if isinstance(eid, bytes) else eid
                    for eid in zset_ids
                )
            list_ids = await self._redis.lrange(failures_key, 0, -1)
            if list_ids:
                episode_ids.update(
                    eid.decode("utf-8") if isinstance(eid, bytes) else eid
                    for eid in list_ids
                )

            # Delete all keys
            keys_to_delete = [recent_key, failures_key]
            for eid in episode_ids:
                keys_to_delete.append(self._episode_key(namespace, eid))

            if keys_to_delete:
                await self._redis.delete(*keys_to_delete)
        except Exception as e:
            logger.warning("Redis invalidate failed: %s", e)

    async def _fetch_episodes(
        self, namespace: MemoryNamespace, episode_ids: list[Any]
    ) -> list[EpisodicMemory] | None:
        """Fetch multiple episodes by ID from Redis.

        Returns None if no episodes could be retrieved.
        """
        pipe = self._redis.pipeline()
        for eid in episode_ids:
            eid_str = eid.decode("utf-8") if isinstance(eid, bytes) else eid
            pipe.get(self._episode_key(namespace, eid_str))

        results = await pipe.execute()

        episodes = []
        for data in results:
            if data is not None:
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                try:
                    episodes.append(EpisodicMemory.from_dict(json.loads(data)))
                except (json.JSONDecodeError, Exception) as e:
                    logger.warning("Failed to deserialize cached episode: %s", e)

        return episodes if episodes else None
