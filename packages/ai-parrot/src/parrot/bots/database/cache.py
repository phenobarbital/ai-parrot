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

import asyncio
import json as _json
import re
import warnings
from dataclasses import asdict as _asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from cachetools import TTLCache
from navconfig.logging import logging
from pydantic import BaseModel, Field
from .models import Completeness, SchemaMetadata, TableMetadata

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
    ttl_by_completeness: Dict[int, int] = Field(
        default_factory=lambda: {
            int(Completeness.NAME_ONLY): 86400,
            int(Completeness.WITH_COLUMNS): 21600,
            int(Completeness.FULL): 3600,
        },
        description="Per-completeness TTL cap in seconds (keyed by Completeness int value)",
    )


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
        ttl_by_completeness: Optional[Dict[int, int]] = None,
    ):
        self.namespace = namespace
        self.redis_ttl = redis_ttl
        self.ttl_by_completeness: Dict[int, int] = ttl_by_completeness or {
            int(Completeness.NAME_ONLY): 86400,
            int(Completeness.WITH_COLUMNS): 21600,
            int(Completeness.FULL): 3600,
        }

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

    # -- Public API ---------------------------------------------------------

    async def get(
        self,
        schema_name: str,
        table_name: str,
        *,
        required: Completeness = Completeness.NAME_ONLY,
        max_age: Optional[timedelta] = None,
    ) -> Optional[TableMetadata]:
        """Return metadata only when completeness and freshness requirements are met.

        Resolution order: LRU → schema cache → Redis → vector store.
        Returns None when:
          * entry not found in any tier
          * entry.completeness < required
          * now - entry.loaded_at > effective_max_age
            (effective_max_age = max_age if provided else ttl_by_completeness[completeness])
        """
        cache_key = self._table_cache_key(schema_name, table_name)
        metadata: Optional[TableMetadata] = None

        # Tier 1: LRU
        if cache_key in self.hot_cache:
            metadata = self.hot_cache[cache_key]

        # Tier 1b: schema cache
        if metadata is None and schema_name in self.schema_cache:
            all_objects = self.schema_cache[schema_name].get_all_objects()
            if table_name in all_objects:
                metadata = all_objects[table_name]
                self.hot_cache[cache_key] = metadata

        # Tier 2: Redis
        if metadata is None:
            metadata = await self._get_from_redis(schema_name, table_name)
            if metadata is not None:
                self.hot_cache[cache_key] = metadata

        # Tier 3: Vector store (point lookup)
        if metadata is None and self.vector_enabled:
            metadata = await self._search_vector_store(schema_name, table_name)
            if metadata is not None:
                self.hot_cache[cache_key] = metadata

        if metadata is None:
            return None

        # Completeness gate
        if not metadata.satisfies(required):
            return None

        # Age gate
        effective_max_age = max_age if max_age is not None else timedelta(
            seconds=self.ttl_by_completeness.get(int(metadata.completeness), self.redis_ttl)
        )
        if datetime.utcnow() - metadata.loaded_at > effective_max_age:
            return None

        self._track_access(cache_key)
        return metadata

    async def get_table_metadata(
        self,
        schema_name: str,
        table_name: str,
    ) -> Optional[TableMetadata]:
        """Deprecated — use get() instead."""
        warnings.warn(
            "get_table_metadata is deprecated; use get() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.get(schema_name, table_name)

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

        # Tier 2: Redis — cap TTL by completeness level
        tier_cap = self.ttl_by_completeness.get(int(metadata.completeness), self.redis_ttl)
        effective_ttl = min(self.redis_ttl, tier_cap)
        await self._store_in_redis(metadata, ttl=effective_ttl)

        # Tier 3: Vector store
        if self.vector_enabled:
            await self._store_in_vector_store(metadata)

    async def list(
        self,
        schema_names: List[str],
        *,
        completeness_min: Completeness = Completeness.NAME_ONLY,
        max_age: Optional[timedelta] = None,
        limit: Optional[int] = None,
    ) -> List[TableMetadata]:
        """Return all cached tables in *schema_names* filtered by completeness and age."""
        results: List[TableMetadata] = []
        now = datetime.utcnow()
        for schema_name in schema_names:
            if schema_name not in self.schema_cache:
                continue
            for meta in self.schema_cache[schema_name].get_all_objects().values():
                if not meta.satisfies(completeness_min):
                    continue
                effective_max_age = max_age if max_age is not None else timedelta(
                    seconds=self.ttl_by_completeness.get(int(meta.completeness), self.redis_ttl)
                )
                if now - meta.loaded_at > effective_max_age:
                    continue
                results.append(meta)
                if limit is not None and len(results) >= limit:
                    return results
        return results

    async def search(
        self,
        schema_names: List[str],
        search_term: str,
        *,
        completeness_min: Completeness = Completeness.NAME_ONLY,
        max_age: Optional[timedelta] = None,
        limit: int = 20,
    ) -> List[TableMetadata]:
        """Search for tables within *schema_names* filtered by completeness and age.

        Vector candidates are filtered post-hoc via get().  Cache-only path
        applies the same gates directly from schema_cache to avoid Redis RTTs.
        """
        if self.vector_enabled:
            search_query = f"schemas:{','.join(schema_names)} {search_term}"
            try:
                raw = await self.vector_store.similarity_search(
                    search_query,
                    k=limit,
                    filter={"schema_name": {"$in": schema_names}},
                )
                converted = await self._convert_vector_results(raw)
                filtered: List[TableMetadata] = []
                for meta in converted:
                    validated = await self.get(
                        meta.schema, meta.tablename,
                        required=completeness_min, max_age=max_age,
                    )
                    if validated is not None:
                        filtered.append(validated)
                if filtered:
                    return filtered[:limit]
            except Exception as exc:
                self.logger.debug("Vector similarity search failed: %s", exc)

        # Cache-only fallback — fetch a larger pool then filter
        candidates = self._search_cache_only(schema_names, search_term, limit * 3)
        now = datetime.utcnow()
        results: List[TableMetadata] = []
        for meta in candidates:
            if not meta.satisfies(completeness_min):
                continue
            effective_max_age = max_age if max_age is not None else timedelta(
                seconds=self.ttl_by_completeness.get(int(meta.completeness), self.redis_ttl)
            )
            if now - meta.loaded_at > effective_max_age:
                continue
            results.append(meta)
            if len(results) >= limit:
                break
        return results

    async def search_similar_tables(
        self,
        schema_names: List[str],
        query: str,
        limit: int = 5,
    ) -> List[TableMetadata]:
        """Deprecated — use search() instead."""
        warnings.warn(
            "search_similar_tables is deprecated; use search() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.search(schema_names, query, limit=limit)

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

    # Match qualified ``schema.table`` references. ASCII identifiers only —
    # Postgres identifiers can include other chars when quoted, but every
    # cached table we see in practice uses snake_case ASCII.
    _QUALIFIED_REF_RE = re.compile(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b"
    )

    def _search_cache_only(
        self,
        schema_names: List[str],
        query: str,
        limit: int,
    ) -> List[TableMetadata]:
        """Cache-only fallback search, layered by precision.

        Three passes, each consulted only if the previous one left room
        under ``limit``. DB fallback (in the caller) only fires when all
        three return empty.

        1. **Qualified refs** — ``schema.table`` tokens in ``query`` are
           looked up directly in the cache. Guarantees that a prompt
           mentioning ``pokemon.products`` returns that exact row before
           alphabetically-earlier ``products`` tables steal the slot
           (the 144-schema warehouse has dozens of ``products`` tables).

        2. **Keyword scoring** — fuzzy match the original tokens
           against table names / columns.

        3. **Stem-aware keyword scoring** — when (2) returns nothing,
           retry with stems of the longer keywords (drop 1-2 trailing
           chars on tokens ≥6 chars). Catches plural/singular drift like
           ``category`` vs ``categories`` where exact substring match
           fails (the ``y`` → ``ies`` swap breaks ILIKE-style ``%term%``).
        """
        results: List[TableMetadata] = []
        seen: set = set()
        allowed = set(schema_names)

        # Pass 1 — exact lookups for qualified refs in the query.
        for match in self._QUALIFIED_REF_RE.finditer(query):
            schema, table = match.group(1), match.group(2)
            if schema not in allowed or schema not in self.schema_cache:
                continue
            schema_meta = self.schema_cache[schema]
            meta = schema_meta.tables.get(table) or schema_meta.views.get(table)
            key = (schema, table)
            if meta is not None and key not in seen:
                results.append(meta)
                seen.add(key)
                if len(results) >= limit:
                    return results

        # Pass 2 — keyword scoring with the original tokens.
        keywords = self._extract_search_keywords(query.lower())
        if not keywords:
            return results

        scored = self._score_against_cache(schema_names, keywords, seen, limit - len(results))
        for meta in scored:
            key = (meta.schema, meta.tablename)
            results.append(meta)
            seen.add(key)
        if len(results) >= limit:
            return results[:limit]

        # Pass 3 — stem-aware retry. Only fires when (2) found nothing —
        # otherwise the original keywords already had hits and stem
        # variants would just produce noisier scores. Returning even one
        # extra row here is much cheaper than the DB roundtrip the
        # caller would otherwise make.
        if not scored:
            stem_keywords = self._stem_keywords(keywords)
            if stem_keywords:
                stem_scored = self._score_against_cache(
                    schema_names, stem_keywords, seen, limit - len(results)
                )
                for meta in stem_scored:
                    key = (meta.schema, meta.tablename)
                    results.append(meta)
                    seen.add(key)
                if stem_scored:
                    self.logger.debug(
                        "cache stem-aware hit: keywords=%s stems=%s",
                        keywords, stem_keywords,
                    )

        return results[:limit]

    def _score_against_cache(
        self,
        schema_names: List[str],
        keywords: List[str],
        seen: set,
        remaining: int,
    ) -> List[TableMetadata]:
        """Score every cached table in ``schema_names`` against ``keywords``.

        Used by ``_search_cache_only`` for both the exact and stem-aware
        passes — extracted so the two passes share scoring logic.
        Returns up to ``remaining`` matches in iteration order; the
        caller controls dedup via ``seen``.
        """
        if remaining <= 0 or not keywords:
            return []
        scored: list[tuple[float, TableMetadata]] = []
        for schema_name in schema_names:
            if schema_name not in self.schema_cache:
                continue
            all_objects = self.schema_cache[schema_name].get_all_objects()
            for table_name, table_meta in all_objects.items():
                key = (schema_name, table_name)
                if key in seen:
                    continue
                score = self._calculate_relevance_score(table_name, table_meta, keywords)
                if score > 0:
                    scored.append((score, table_meta))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [meta for _, meta in scored[:remaining]]

    @staticmethod
    def _stem_keywords(keywords: List[str]) -> List[str]:
        """Generate stem variants of ``keywords`` for the cache pass-3 retry.

        For every keyword of length ≥6, emit the keyword with 1 trailing
        character dropped, and (when the result is still ≥4 chars) the
        keyword with 2 trailing characters dropped. Stems shorter than 4
        chars are skipped — they would match nearly every table name and
        only add noise.

        Deduped, preserves the order of first occurrence.
        """
        out: List[str] = []
        for kw in keywords:
            if len(kw) < 6:
                continue
            for trim in (1, 2):
                stem = kw[:-trim]
                if len(stem) >= 4 and stem not in out and stem not in keywords:
                    out.append(stem)
        return out

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

    async def _store_in_redis(self, metadata: TableMetadata, ttl: Optional[int] = None) -> None:
        """Store metadata in Redis if available."""
        if self._redis is None:
            return
        try:
            key = self._redis_key(metadata.schema, metadata.tablename)
            data = _json.dumps(_asdict(metadata), default=str)
            effective_ttl = ttl if ttl is not None else self.redis_ttl
            await self._redis.set(key, data, ex=effective_ttl)
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
        owns_vector_store: When ``True`` (default) :meth:`close` disposes the
            ``vector_store`` (releasing its connection pool / SQLAlchemy engine).
            Set to ``False`` when the store is shared and its lifecycle is
            managed elsewhere.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        vector_store: Optional["AbstractStore"] = None,
        owns_vector_store: bool = True,
    ):
        self._redis_url = redis_url
        self._redis_pool: Any = None
        self.vector_store = vector_store
        self._owns_vector_store = owns_vector_store
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
            ttl_by_completeness=config.ttl_by_completeness,
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
        """Close shared resources (Redis pool + owned vector store).

        Disposing the ``vector_store`` here is what prevents its SQLAlchemy
        async engine (e.g. ``PgvectorStore``) from lingering until interpreter
        teardown, where the event loop is already closing and the pool's
        ``connection.close()`` raises ``CancelledError``. Skipped when
        ``owns_vector_store`` is ``False``.
        """
        if self._redis_pool is not None:
            try:
                await self._redis_pool.close()
            except Exception as exc:
                self.logger.debug("Error closing Redis pool: %s", exc)
            self._redis_pool = None
        self._partitions.clear()
        if self._owns_vector_store and self.vector_store is not None:
            disconnect = getattr(self.vector_store, "disconnect", None) or getattr(
                self.vector_store, "close", None
            )
            if callable(disconnect):
                try:
                    result = disconnect()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as exc:
                    self.logger.debug("Error disposing vector store: %s", exc)
            self.vector_store = None
        self.logger.info("CacheManager closed")
