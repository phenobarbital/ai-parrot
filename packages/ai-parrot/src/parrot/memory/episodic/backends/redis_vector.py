"""Redis Stack (RediSearch) vector backend for episodic memory.

Implements AbstractEpisodeBackend using Redis Stack with HNSW vector index
and RediSearch FT.SEARCH for namespace-filtered vector similarity search.

Requires Redis Stack with the RediSearch module installed.
"""
from __future__ import annotations

import json
import logging
import struct
from datetime import datetime, timezone
from typing import Any

from ..models import (
    EpisodeCategory,
    EpisodeOutcome,
    EpisodeSearchResult,
    EpisodicMemory,
)

logger = logging.getLogger(__name__)

# Redis key prefix for episode hashes
_KEY_PREFIX = "ep:"

# RediSearch index name default
_DEFAULT_INDEX = "idx:episodes"


def _embedding_to_bytes(embedding: list[float]) -> bytes:
    """Convert a float list embedding to bytes (IEEE 754 float32).

    Args:
        embedding: List of float values.

    Returns:
        Bytes representation as FLOAT32 array.
    """
    return struct.pack(f"{len(embedding)}f", *embedding)


def _bytes_to_embedding(data: bytes) -> list[float]:
    """Convert bytes back to a float list embedding.

    Args:
        data: Bytes from Redis HASH field.

    Returns:
        List of float values.
    """
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))


def _episode_to_hash(episode: EpisodicMemory) -> dict[str, Any]:
    """Convert an EpisodicMemory to a flat Redis HASH mapping.

    Args:
        episode: The episode to serialize.

    Returns:
        Dict of field_name -> value suitable for Redis HSET.
    """
    return {
        "episode_id": episode.episode_id,
        "created_at": episode.created_at.timestamp(),
        "updated_at": episode.updated_at.timestamp(),
        "expires_at": episode.expires_at.timestamp() if episode.expires_at else -1.0,
        "tenant_id": episode.tenant_id,
        "agent_id": episode.agent_id,
        "user_id": episode.user_id or "",
        "session_id": episode.session_id or "",
        "room_id": episode.room_id or "",
        "crew_id": episode.crew_id or "",
        "situation": episode.situation,
        "action_taken": episode.action_taken,
        "outcome": episode.outcome.value,
        "outcome_details": episode.outcome_details or "",
        "error_type": episode.error_type or "",
        "error_message": episode.error_message or "",
        "reflection": episode.reflection or "",
        "lesson_learned": episode.lesson_learned or "",
        "suggested_action": episode.suggested_action or "",
        "category": episode.category.value,
        "importance": episode.importance,
        "is_failure": 1 if episode.is_failure else 0,
        "related_tools": json.dumps(episode.related_tools),
        "related_entities": json.dumps(episode.related_entities),
        "metadata": json.dumps(episode.metadata),
        "embedding": _embedding_to_bytes(episode.embedding) if episode.embedding else b"",
    }


def _hash_to_episode(data: dict[str, Any]) -> EpisodicMemory:
    """Convert a Redis HASH mapping back to an EpisodicMemory.

    Args:
        data: Dict from Redis HGETALL or HSET response.

    Returns:
        EpisodicMemory instance.
    """
    expires_ts = float(data.get("expires_at", -1))
    expires_at = (
        datetime.fromtimestamp(expires_ts, tz=timezone.utc)
        if expires_ts > 0
        else None
    )

    embedding_bytes = data.get("embedding", b"")
    embedding = _bytes_to_embedding(embedding_bytes) if embedding_bytes else None

    return EpisodicMemory(
        episode_id=str(data["episode_id"]),
        created_at=datetime.fromtimestamp(float(data["created_at"]), tz=timezone.utc),
        updated_at=datetime.fromtimestamp(float(data["updated_at"]), tz=timezone.utc),
        expires_at=expires_at,
        tenant_id=str(data["tenant_id"]),
        agent_id=str(data["agent_id"]),
        user_id=str(data["user_id"]) or None,
        session_id=str(data["session_id"]) or None,
        room_id=str(data["room_id"]) or None,
        crew_id=str(data["crew_id"]) or None,
        situation=str(data["situation"]),
        action_taken=str(data["action_taken"]),
        outcome=EpisodeOutcome(str(data["outcome"])),
        outcome_details=str(data.get("outcome_details", "")) or None,
        error_type=str(data.get("error_type", "")) or None,
        error_message=str(data.get("error_message", "")) or None,
        reflection=str(data.get("reflection", "")) or None,
        lesson_learned=str(data.get("lesson_learned", "")) or None,
        suggested_action=str(data.get("suggested_action", "")) or None,
        category=EpisodeCategory(str(data.get("category", "tool_execution"))),
        importance=int(data.get("importance", 5)),
        is_failure=bool(int(data.get("is_failure", 0))),
        related_tools=json.loads(data.get("related_tools", "[]")),
        related_entities=json.loads(data.get("related_entities", "[]")),
        metadata=json.loads(data.get("metadata", "{}")),
        embedding=embedding,
    )


class RedisVectorBackend:
    """Redis Stack (RediSearch) backend for episodic memory vector search.

    Stores episodes as Redis HASHes with a RediSearch index for
    vector similarity (HNSW) and tag-based namespace filtering.

    Requires Redis Stack with the RediSearch module enabled.
    Use ``configure()`` to create the index before performing any operations.

    Graceful degradation: all methods return empty results (or None) on
    connection failure, logging a warning rather than raising.

    Args:
        redis_url: Redis connection URL (e.g., ``redis://localhost:6379``).
        index_name: RediSearch index name. Default ``idx:episodes``.
        embedding_dim: Dimension of the embedding vectors. Default 384.
        hnsw_m: HNSW graph connectivity parameter. Default 16.
        hnsw_ef_construction: HNSW build-time search depth. Default 200.

    Example:
        backend = RedisVectorBackend(redis_url="redis://localhost:6379")
        await backend.configure()
        await backend.store(episode)
        results = await backend.search_similar(embedding=[...], namespace_filter={...})
        await backend.cleanup()
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        index_name: str = _DEFAULT_INDEX,
        embedding_dim: int = 384,
        hnsw_m: int = 16,
        hnsw_ef_construction: int = 200,
    ) -> None:
        self._redis_url = redis_url
        self._index_name = index_name
        self._embedding_dim = embedding_dim
        self._hnsw_m = hnsw_m
        self._hnsw_ef_construction = hnsw_ef_construction
        self._redis: Any = None

    async def configure(self) -> None:
        """Connect to Redis and create the RediSearch index.

        Creates the index if it does not exist. Raises a RuntimeError if
        Redis Stack / RediSearch is not available.

        Raises:
            RuntimeError: If RediSearch module is not loaded on the server.
            ImportError: If the redis package is not installed.
        """
        try:
            import redis.asyncio as aioredis
        except ImportError as e:
            raise ImportError(
                "redis[hiredis] package is required for RedisVectorBackend. "
                "Install with: pip install 'redis[hiredis]'"
            ) from e

        self._redis = aioredis.from_url(self._redis_url, decode_responses=False)

        # Verify RediSearch is available
        try:
            modules = await self._redis.execute_command("MODULE LIST")
            has_search = any(
                b"search" in (m[1] if isinstance(m, list) else m).lower()
                for m in (modules or [])
                if m
            )
            if not has_search:
                raise RuntimeError(
                    "RediSearch module not found on Redis server. "
                    "RedisVectorBackend requires Redis Stack or RediSearch module. "
                    "See: https://redis.io/docs/stack/search/"
                )
        except RuntimeError:
            raise
        except Exception as e:
            logger.warning("Could not verify RediSearch module: %s", e)

        # Create index (ignore if already exists)
        try:
            await self._redis.execute_command(
                "FT.CREATE", self._index_name,
                "ON", "HASH",
                "PREFIX", "1", _KEY_PREFIX,
                "SCHEMA",
                "embedding", "VECTOR", "HNSW", "6",
                "TYPE", "FLOAT32",
                "DIM", str(self._embedding_dim),
                "DISTANCE_METRIC", "COSINE",
                "tenant_id", "TAG",
                "agent_id", "TAG",
                "user_id", "TAG",
                "session_id", "TAG",
                "room_id", "TAG",
                "crew_id", "TAG",
                "is_failure", "TAG",
                "category", "TAG",
                "importance", "NUMERIC", "SORTABLE",
                "created_at", "NUMERIC", "SORTABLE",
                "expires_at", "NUMERIC", "SORTABLE",
                "situation", "TEXT",
                "action_taken", "TEXT",
                "lesson_learned", "TEXT",
            )
            logger.info("RediSearch index created: %s", self._index_name)
        except Exception as e:
            error_msg = str(e).lower()
            if "index already exists" in error_msg or "already exists" in error_msg:
                logger.debug("RediSearch index already exists: %s", self._index_name)
            else:
                logger.warning("Failed to create RediSearch index: %s", e)

    async def cleanup(self) -> None:
        """Close the Redis connection pool.

        Safe to call even if configure() was not called.
        """
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception as e:
                logger.warning("Error closing Redis connection: %s", e)
            finally:
                self._redis = None

    async def store(self, episode: EpisodicMemory) -> str:
        """Store an episode as a Redis HASH.

        Args:
            episode: The episode to store.

        Returns:
            The episode_id of the stored episode, or the episode_id on failure.
        """
        if self._redis is None:
            logger.warning("RedisVectorBackend not configured; store() is a no-op")
            return episode.episode_id

        try:
            key = f"{_KEY_PREFIX}{episode.episode_id}"
            hash_data = _episode_to_hash(episode)
            await self._redis.hset(key, mapping=hash_data)
            logger.debug("Stored episode %s", episode.episode_id)
            return episode.episode_id
        except Exception as e:
            logger.warning("RedisVectorBackend.store() failed: %s", e)
            return episode.episode_id

    async def search_similar(
        self,
        embedding: list[float],
        namespace_filter: dict[str, Any],
        top_k: int = 5,
        score_threshold: float = 0.3,
        include_failures_only: bool = False,
    ) -> list[EpisodeSearchResult]:
        """Search episodes by KNN vector similarity with namespace pre-filtering.

        Builds a RediSearch FT.SEARCH query with TAG pre-filters and KNN
        vector search on the embedding field.

        Args:
            embedding: Query embedding vector (must match embedding_dim).
            namespace_filter: Dict of field_name -> value for TAG pre-filtering.
            top_k: Maximum results to return.
            score_threshold: Minimum cosine similarity score (0-1).
            include_failures_only: If True, only return is_failure=1 episodes.

        Returns:
            List of EpisodeSearchResult ranked by similarity (highest first).
        """
        if self._redis is None:
            logger.warning("RedisVectorBackend not configured; search_similar() returns []")
            return []

        try:
            # Build pre-filter string for TAG fields
            filter_parts = []
            for field, value in namespace_filter.items():
                if value:
                    # Escape special chars in tag values
                    safe_val = str(value).replace("-", r"\-")
                    filter_parts.append(f"@{field}:{{{safe_val}}}")

            if include_failures_only:
                filter_parts.append("@is_failure:{1}")

            pre_filter = " ".join(filter_parts) if filter_parts else "*"

            # KNN query
            query = f"({pre_filter})=>[KNN {top_k} @embedding $vec AS vector_score]"

            embedding_bytes = _embedding_to_bytes(embedding)

            raw = await self._redis.execute_command(
                "FT.SEARCH", self._index_name,
                query,
                "PARAMS", "2", "vec", embedding_bytes,
                "SORTBY", "vector_score",
                "LIMIT", "0", str(top_k),
                "RETURN", "0",
                "DIALECT", "2",
            )

            if not raw or len(raw) < 2:
                return []

            results: list[EpisodeSearchResult] = []
            # FT.SEARCH returns [total, key1, [fields...], key2, [fields...], ...]
            # With RETURN 0, it returns keys only: [total, key1, [], key2, [], ...]
            total = raw[0]
            idx = 1
            while idx < len(raw):
                key = raw[idx].decode() if isinstance(raw[idx], bytes) else raw[idx]
                idx += 2  # skip key and empty field list

                # Fetch the full hash
                hash_data = await self._redis.hgetall(key)
                if not hash_data:
                    continue

                # Decode bytes keys/values
                decoded = {}
                for k, v in hash_data.items():
                    dk = k.decode() if isinstance(k, bytes) else k
                    if dk == "embedding":
                        decoded[dk] = v  # keep as bytes for conversion
                    else:
                        decoded[dk] = v.decode() if isinstance(v, bytes) else v

                episode = _hash_to_episode(decoded)

                # Compute semantic similarity score (cosine)
                if episode.embedding and embedding:
                    dot = sum(a * b for a, b in zip(embedding, episode.embedding))
                    norm_a = sum(x * x for x in embedding) ** 0.5
                    norm_b = sum(x * x for x in episode.embedding) ** 0.5
                    score = dot / (norm_a * norm_b) if norm_a and norm_b else 0.0
                    score = max(0.0, min(1.0, score))
                else:
                    score = 0.0

                if score >= score_threshold:
                    results.append(
                        EpisodeSearchResult(
                            **episode.model_dump(),
                            embedding=episode.embedding,
                            score=score,
                        )
                    )

            results.sort(key=lambda r: r.score, reverse=True)
            return results

        except Exception as e:
            logger.warning("RedisVectorBackend.search_similar() failed: %s", e)
            return []

    async def get_recent(
        self,
        namespace_filter: dict[str, Any],
        limit: int = 10,
        since: datetime | None = None,
    ) -> list[EpisodicMemory]:
        """Get recent episodes by namespace, ordered by created_at DESC.

        Args:
            namespace_filter: Dict of field_name -> value for TAG filtering.
            limit: Maximum results to return.
            since: Only return episodes created after this datetime.

        Returns:
            List of recent episodes.
        """
        if self._redis is None:
            logger.warning("RedisVectorBackend not configured; get_recent() returns []")
            return []

        try:
            filter_parts = []
            for field, value in namespace_filter.items():
                if value:
                    safe_val = str(value).replace("-", r"\-")
                    filter_parts.append(f"@{field}:{{{safe_val}}}")

            if since is not None:
                filter_parts.append(f"@created_at:[{since.timestamp()} +inf]")

            query_filter = " ".join(filter_parts) if filter_parts else "*"

            raw = await self._redis.execute_command(
                "FT.SEARCH", self._index_name,
                query_filter,
                "SORTBY", "created_at", "DESC",
                "LIMIT", "0", str(limit),
                "RETURN", "0",
                "DIALECT", "2",
            )

            if not raw or len(raw) < 2:
                return []

            episodes = []
            idx = 1
            while idx < len(raw):
                key = raw[idx].decode() if isinstance(raw[idx], bytes) else raw[idx]
                idx += 2

                hash_data = await self._redis.hgetall(key)
                if not hash_data:
                    continue

                decoded = {}
                for k, v in hash_data.items():
                    dk = k.decode() if isinstance(k, bytes) else k
                    if dk == "embedding":
                        decoded[dk] = v
                    else:
                        decoded[dk] = v.decode() if isinstance(v, bytes) else v

                episodes.append(_hash_to_episode(decoded))

            return episodes

        except Exception as e:
            logger.warning("RedisVectorBackend.get_recent() failed: %s", e)
            return []

    async def get_failures(
        self,
        agent_id: str,
        tenant_id: str = "default",
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        """Get recent failure episodes for an agent.

        Args:
            agent_id: Agent identifier.
            tenant_id: Tenant identifier.
            limit: Maximum results to return.

        Returns:
            List of failure episodes, most recent first.
        """
        return await self.get_recent(
            namespace_filter={
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "is_failure": "1",
            },
            limit=limit,
        )

    async def delete_expired(self) -> int:
        """Delete episodes that have passed their expires_at timestamp.

        Scans all episodes and deletes those with expires_at < now.

        Returns:
            Number of episodes deleted.
        """
        if self._redis is None:
            logger.warning("RedisVectorBackend not configured; delete_expired() returns 0")
            return 0

        try:
            now = datetime.now(timezone.utc).timestamp()
            # Find expired episodes via RediSearch
            raw = await self._redis.execute_command(
                "FT.SEARCH", self._index_name,
                f"@expires_at:[-inf ({now}]",
                "LIMIT", "0", "1000",
                "RETURN", "0",
                "DIALECT", "2",
            )

            if not raw or len(raw) < 2:
                return 0

            keys = []
            idx = 1
            while idx < len(raw):
                key = raw[idx].decode() if isinstance(raw[idx], bytes) else raw[idx]
                keys.append(key)
                idx += 2

            if keys:
                await self._redis.delete(*keys)
                logger.info("Deleted %d expired episodes from Redis", len(keys))

            return len(keys)

        except Exception as e:
            logger.warning("RedisVectorBackend.delete_expired() failed: %s", e)
            return 0

    async def count(self, namespace_filter: dict[str, Any]) -> int:
        """Count episodes matching a namespace filter.

        Args:
            namespace_filter: Dict of field_name -> value for TAG filtering.

        Returns:
            Number of matching episodes.
        """
        if self._redis is None:
            logger.warning("RedisVectorBackend not configured; count() returns 0")
            return 0

        try:
            filter_parts = []
            for field, value in namespace_filter.items():
                if value:
                    safe_val = str(value).replace("-", r"\-")
                    filter_parts.append(f"@{field}:{{{safe_val}}}")

            query_filter = " ".join(filter_parts) if filter_parts else "*"

            raw = await self._redis.execute_command(
                "FT.SEARCH", self._index_name,
                query_filter,
                "LIMIT", "0", "0",
                "DIALECT", "2",
            )

            # FT.SEARCH with LIMIT 0 0 returns [total_count]
            return int(raw[0]) if raw else 0

        except Exception as e:
            logger.warning("RedisVectorBackend.count() failed: %s", e)
            return 0
