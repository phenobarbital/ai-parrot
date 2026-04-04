# ============================================================================
# CACHE MANAGER WITH NAMESPACED PARTITIONS
# ============================================================================
"""Multi-database cache with partitioned namespaces.

Replaces the monolithic ``SchemaMetadataCache`` with a ``CacheManager`` that
creates ``CachePartition`` instances per database.  Each partition has its own
LRU sizing and TTL while optionally sharing a Redis connection pool and a
vector store for similarity search.
"""
from __future__ import annotations

import json as _json
import re
from dataclasses import asdict as _asdict
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from cachetools import TTLCache
from navconfig.logging import logging
from pydantic import BaseModel, Field

from .models import SchemaMetadata, TableMetadata

if TYPE_CHECKING:
    from ...stores.abstract import AbstractStore


# ---------------------------------------------------------------------------
# Configuration model
# ---------------------------------------------------------------------------

class CachePartitionConfig(BaseModel):
    """Configuration for a single cache partition."""

    namespace: str = Field(..., description="Unique identifier for this partition")
    lru_maxsize: int = Field(default=500, ge=1, description="Max items in LRU cache")
    lru_ttl: int = Field(default=1800, ge=1, description="LRU TTL in seconds")
    redis_ttl: int = Field(default=3600, ge=1, description="Redis TTL in seconds")


# ---------------------------------------------------------------------------
# CachePartition — drop-in replacement for SchemaMetadataCache
# ---------------------------------------------------------------------------

class CachePartition:
    """Namespaced cache partition with the same API as ``SchemaMetadataCache``.

    Each partition owns:
    * An independent ``TTLCache`` (LRU tier)
    * A schema-level cache (``Dict[str, SchemaMetadata]``)
    * Access statistics for hot-table tracking

    Optionally uses a shared Redis pool and vector store passed by the
    ``CacheManager``.
    """

    def __init__(
        self,
        namespace: str,
        lru_maxsize: int = 500,
        lru_ttl: int = 1800,
        redis_ttl: int = 3600,
        redis_pool: Any = None,
        vector_store: Optional["AbstractStore"] = None,
    ):
        self.namespace = namespace
        self.redis_ttl = redis_ttl

        # Tier 1: LRU
        self.hot_cache: TTLCache = TTLCache(maxsize=lru_maxsize, ttl=lru_ttl)

        # Tier 2: Redis (optional, shared)
        self._redis = redis_pool

        # Tier 3: Vector store (optional, shared)
        self.vector_store = vector_store
        self.vector_enabled = vector_store is not None

        # Schema-level caches
        self.schema_cache: Dict[str, SchemaMetadata] = {}
        self.table_access_stats: Dict[str, int] = {}

        self.logger = logging.getLogger(f"Parrot.Cache.{namespace}")

    # -- Key helpers --------------------------------------------------------

    def _table_cache_key(self, schema_name: str, table_name: str) -> str:
        """Generate cache key for table metadata."""
        return f"table:{schema_name}:{table_name}"

    def _redis_key(self, schema_name: str, table_name: str) -> str:
        """Generate namespace-prefixed Redis key."""
        return f"{self.namespace}:table:{schema_name}:{table_name}"

    # -- Public API (mirrors SchemaMetadataCache) ---------------------------

    async def get_table_metadata(
        self,
        schema_name: str,
        table_name: str,
    ) -> Optional[TableMetadata]:
        """Get table metadata with access tracking.

        Resolution order: LRU → schema cache → Redis → vector store.
        """
        cache_key = self._table_cache_key(schema_name, table_name)

        # Tier 1: LRU
        if cache_key in self.hot_cache:
            self._track_access(cache_key)
            return self.hot_cache[cache_key]

        # Tier 1b: schema cache
        if schema_name in self.schema_cache:
            schema_meta = self.schema_cache[schema_name]
            all_objects = schema_meta.get_all_objects()
            if table_name in all_objects:
                metadata = all_objects[table_name]
                self.hot_cache[cache_key] = metadata
                self._track_access(cache_key)
                return metadata

        # Tier 2: Redis
        metadata = await self._get_from_redis(schema_name, table_name)
        if metadata is not None:
            self.hot_cache[cache_key] = metadata
            self._track_access(cache_key)
            return metadata

        # Tier 3: Vector store
        if self.vector_enabled:
            metadata = await self._search_vector_store(schema_name, table_name)
            if metadata is not None:
                self.hot_cache[cache_key] = metadata
                self._track_access(cache_key)
                return metadata

        return None

    async def store_table_metadata(self, metadata: TableMetadata) -> None:
        """Store table metadata across all available tiers."""
        cache_key = self._table_cache_key(metadata.schema, metadata.tablename)

        # Tier 1: LRU
        self.hot_cache[cache_key] = metadata

        # Schema cache
        if metadata.schema not in self.schema_cache:
            self.schema_cache[metadata.schema] = SchemaMetadata(
                schema=metadata.schema,
                database_name="navigator",
                table_count=0,
                view_count=0,
            )
        schema_meta = self.schema_cache[metadata.schema]
        if metadata.table_type == "BASE TABLE":
            schema_meta.tables[metadata.tablename] = metadata
        else:
            schema_meta.views[metadata.tablename] = metadata

        # Tier 2: Redis
        await self._store_in_redis(metadata)

        # Tier 3: Vector store
        if self.vector_enabled:
            await self._store_in_vector_store(metadata)

    async def search_similar_tables(
        self,
        schema_names: List[str],
        query: str,
        limit: int = 5,
    ) -> List[TableMetadata]:
        """Search for similar tables within allowed schemas."""
        if self.vector_enabled:
            search_query = f"schemas:{','.join(schema_names)} {query}"
            try:
                results = await self.vector_store.similarity_search(
                    search_query,
                    k=limit,
                    filter={"schema_name": {"$in": schema_names}},
                )
                converted = await self._convert_vector_results(results)
                if converted:
                    return converted
            except Exception as exc:
                self.logger.debug("Vector similarity search failed: %s", exc)
        return self._search_cache_only(schema_names, query, limit)

    def get_schema_overview(self, schema_name: str) -> Optional[SchemaMetadata]:
        """Get complete schema overview."""
        return self.schema_cache.get(schema_name)

    def get_hot_tables(
        self,
        schema_names: List[str],
        limit: int = 10,
    ) -> List[tuple[str, str, int]]:
        """Get most frequently accessed tables across allowed schemas."""
        schema_access: list[tuple[str, str, int]] = []
        for schema_name in schema_names:
            schema_prefix = f"table:{schema_name}:"
            for key, count in self.table_access_stats.items():
                if key.startswith(schema_prefix):
                    table_name = key.replace(schema_prefix, "")
                    schema_access.append((schema_name, table_name, count))
        return sorted(schema_access, key=lambda x: x[2], reverse=True)[:limit]

    # -- Internal helpers ---------------------------------------------------

    def _track_access(self, cache_key: str) -> None:
        """Track table access for hot table identification."""
        self.table_access_stats[cache_key] = self.table_access_stats.get(cache_key, 0) + 1

    def _extract_search_keywords(self, query: str) -> List[str]:
        """Extract meaningful keywords from a natural language query."""
        stop_words = {
            "get", "show", "find", "list", "select", "by", "from", "the",
            "a", "an", "and", "or", "of", "to", "in", "on", "at", "for",
            "with", "top", "all",
        }
        words = re.findall(r"\b[a-zA-Z]+\b", query.lower())
        return [w for w in words if w not in stop_words and len(w) > 2]

    def _calculate_relevance_score(
        self,
        table_name: str,
        table_meta: TableMetadata,
        keywords: List[str],
    ) -> float:
        """Calculate relevance score for a table based on keywords."""
        score = 0.0
        table_name_lower = table_name.lower()
        column_names = [col["name"].lower() for col in table_meta.columns]

        for keyword in keywords:
            kw = keyword.lower()
            if kw == table_name_lower:
                score += 10.0
            elif kw in table_name_lower:
                score += 5.0
            elif kw in column_names:
                score += 8.0
            elif any(kw in cn for cn in column_names):
                score += 3.0
            elif table_meta.comment and kw in table_meta.comment.lower():
                score += 2.0
        return score

    def _search_cache_only(
        self,
        schema_names: List[str],
        query: str,
        limit: int,
    ) -> List[TableMetadata]:
        """Fallback search using only cache when vector store unavailable."""
        results: List[TableMetadata] = []
        keywords = self._extract_search_keywords(query.lower())

        for schema_name in schema_names:
            if schema_name not in self.schema_cache:
                continue
            all_objects = self.schema_cache[schema_name].get_all_objects()
            for table_name, table_meta in all_objects.items():
                score = self._calculate_relevance_score(table_name, table_meta, keywords)
                if score > 0:
                    results.append(table_meta)
                    if len(results) >= limit:
                        break
            if len(results) >= limit:
                break
        return results[:limit]

    # -- Redis helpers ------------------------------------------------------

    async def _get_from_redis(
        self, schema_name: str, table_name: str
    ) -> Optional[TableMetadata]:
        """Retrieve metadata from Redis if available."""
        if self._redis is None:
            return None
        try:
            key = self._redis_key(schema_name, table_name)
            raw = await self._redis.get(key)
            if raw is None:
                return None
            data = _json.loads(raw)
            return TableMetadata(**data)
        except Exception as exc:
            self.logger.debug("Redis get failed for %s.%s: %s", schema_name, table_name, exc)
            return None

    async def _store_in_redis(self, metadata: TableMetadata) -> None:
        """Store metadata in Redis if available."""
        if self._redis is None:
            return
        try:
            key = self._redis_key(metadata.schema, metadata.tablename)
            data = _json.dumps(_asdict(metadata), default=str)
            await self._redis.set(key, data, ex=self.redis_ttl)
        except Exception as exc:
            self.logger.debug("Redis store failed for %s: %s", metadata.full_name, exc)

    # -- Vector store helpers -----------------------------------------------

    async def _search_vector_store(
        self, schema_name: str, table_name: str
    ) -> Optional[TableMetadata]:
        """Search vector store for a specific table."""
        if not self.vector_enabled:
            return None
        return None  # basic impl; actual results come from search_similar_tables

    async def _store_in_vector_store(self, metadata: TableMetadata) -> None:
        """Store metadata in vector store."""
        if not self.vector_enabled:
            return
        try:
            document = {
                "content": metadata.to_yaml_context(),
                "metadata": {
                    "type": "table_metadata",
                    "schema": metadata.schema,
                    "tablename": metadata.tablename,
                    "table_type": metadata.table_type,
                    "full_name": metadata.full_name,
                },
            }
            await self.vector_store.add_documents([document])
        except Exception as exc:
            self.logger.debug("Vector store write failed for %s: %s", metadata.full_name, exc)

    async def _convert_vector_results(self, results: Any) -> List[TableMetadata]:
        """Convert vector store results to TableMetadata objects."""
        return []


# ---------------------------------------------------------------------------
# CacheManager — orchestrates partitions
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Backward-compatible wrapper
# ---------------------------------------------------------------------------

class SchemaMetadataCache(CachePartition):
    """Backward-compatible wrapper around ``CachePartition``.

    Preserves the old constructor signature::

        SchemaMetadataCache(vector_store=None, lru_maxsize=500, lru_ttl=1800)

    so that existing code (e.g. ``abstract.py``) continues to work until the
    cleanup task (TASK-579) removes it.
    """

    def __init__(
        self,
        vector_store: Optional["AbstractStore"] = None,
        lru_maxsize: int = 500,
        lru_ttl: int = 1800,
    ):
        super().__init__(
            namespace="default",
            lru_maxsize=lru_maxsize,
            lru_ttl=lru_ttl,
            vector_store=vector_store,
        )


# ---------------------------------------------------------------------------
# CacheManager — orchestrates partitions
# ---------------------------------------------------------------------------

class CacheManager:
    """Manages namespaced cache partitions with shared Redis + vector store.

    Args:
        redis_url: Optional Redis connection string.  ``None`` for LRU-only mode.
        vector_store: Optional ``AbstractStore`` for similarity search.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        vector_store: Optional["AbstractStore"] = None,
    ):
        self._redis_url = redis_url
        self._redis_pool: Any = None
        self.vector_store = vector_store
        self._partitions: Dict[str, CachePartition] = {}
        self.logger = logging.getLogger("Parrot.CacheManager")

        # Eagerly connect to Redis (non-blocking; actual IO happens lazily)
        if redis_url:
            self._init_redis(redis_url)

    def _init_redis(self, redis_url: str) -> None:
        """Initialise a shared async Redis connection pool."""
        try:
            import redis.asyncio as aioredis  # noqa: F811

            self._redis_pool = aioredis.from_url(
                redis_url, decode_responses=True
            )
            self.logger.info("Redis pool initialised: %s", redis_url)
        except Exception as exc:
            self.logger.warning("Redis unavailable (%s) — LRU-only mode", exc)
            self._redis_pool = None

    # -- Partition management -----------------------------------------------

    def create_partition(self, config: CachePartitionConfig) -> CachePartition:
        """Create a new cache partition with the given configuration.

        Args:
            config: Partition configuration.

        Returns:
            The newly created ``CachePartition``.

        Raises:
            ValueError: If a partition with the same namespace already exists.
        """
        if config.namespace in self._partitions:
            raise ValueError(
                f"Partition '{config.namespace}' already exists"
            )
        partition = CachePartition(
            namespace=config.namespace,
            lru_maxsize=config.lru_maxsize,
            lru_ttl=config.lru_ttl,
            redis_ttl=config.redis_ttl,
            redis_pool=self._redis_pool,
            vector_store=self.vector_store,
        )
        self._partitions[config.namespace] = partition
        self.logger.info(
            "Created cache partition '%s' (LRU maxsize=%d, ttl=%ds)",
            config.namespace,
            config.lru_maxsize,
            config.lru_ttl,
        )
        return partition

    def get_partition(self, namespace: str) -> Optional[CachePartition]:
        """Return the partition for *namespace*, or ``None``."""
        return self._partitions.get(namespace)

    # -- Cross-partition search ---------------------------------------------

    async def search_across_databases(
        self,
        query: str,
        limit: int = 5,
    ) -> List[TableMetadata]:
        """Search for tables across all partitions.

        Args:
            query: Natural-language search string.
            limit: Maximum total results.

        Returns:
            Merged list of ``TableMetadata`` from every partition.
        """
        results: List[TableMetadata] = []
        for partition in self._partitions.values():
            # Collect all known schema names in this partition
            schema_names = list(partition.schema_cache.keys())
            if not schema_names:
                continue
            found = await partition.search_similar_tables(schema_names, query, limit=limit)
            results.extend(found)
        return results[:limit]

    # -- Lifecycle ----------------------------------------------------------

    async def close(self) -> None:
        """Close shared resources (Redis pool)."""
        if self._redis_pool is not None:
            try:
                await self._redis_pool.close()
            except Exception as exc:
                self.logger.debug("Error closing Redis pool: %s", exc)
            self._redis_pool = None
        self._partitions.clear()
        self.logger.info("CacheManager closed")
