# TASK-568: CacheManager with Namespaced Partitions

**Feature**: sqlagent-repair
**Spec**: `sdd/specs/sqlagent-repair.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-082. The `CacheManager` replaces the current monolithic `SchemaMetadataCache` with a partitioned cache that supports multiple databases. Each toolkit will get its own partition with independent LRU sizing and TTL, while sharing a single Redis connection pool and optional vector store. Implements spec Module 1.

---

## Scope

- Implement `CachePartitionConfig` Pydantic model for partition configuration
- Implement `CachePartition` class that wraps the existing `SchemaMetadataCache` API (get/store/search) with a namespace prefix on all keys
- Implement `CacheManager` class that:
  - Creates and manages named `CachePartition` instances
  - Holds a shared optional Redis connection pool (via `redis.asyncio`)
  - Holds a shared optional `AbstractStore` for vector search
  - Provides `search_across_databases()` that queries all partitions
  - Provides `close()` for cleanup
- Each `CachePartition` has its own `TTLCache` (from `cachetools`) with configurable `maxsize` and `ttl`
- Redis tier: when available, store/retrieve table metadata as JSON with namespace-prefixed keys and configurable TTL
- Fallback: when Redis is unavailable, operate in LRU-only mode (no crash)
- Write unit tests for partition isolation, LRU eviction, cross-partition search, Redis fallback

**NOT in scope**: Vector store implementation details (just pass through to `AbstractStore`), toolkit integration, agent changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/database/cache.py` | REWRITE | Replace `SchemaMetadataCache` with `CacheManager` + `CachePartition` + `CachePartitionConfig` |
| `tests/unit/test_cache_manager.py` | CREATE | Unit tests for CacheManager and CachePartition |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Current cache module (to be rewritten)
from parrot.bots.database.cache import SchemaMetadataCache  # cache.py:11

# Models used by cache
from parrot.bots.database.models import SchemaMetadata  # models.py:84
from parrot.bots.database.models import TableMetadata    # models.py:104

# Vector store interface
from parrot.stores.abstract import AbstractStore          # parrot/stores/abstract.py

# External
from cachetools import TTLCache                            # external
from pydantic import BaseModel, Field                      # external
```

### Existing Signatures to Use
```python
# parrot/bots/database/cache.py:11 (current — to be rewritten)
class SchemaMetadataCache:
    def __init__(self, vector_store=None, lru_maxsize=500, lru_ttl=1800):  # line 14
    hot_cache: TTLCache                               # line 21
    schema_cache: Dict[str, SchemaMetadata]            # line 28
    table_access_stats: Dict[str, int]                 # line 29
    async def get_table_metadata(self, schema_name, table_name) -> Optional[TableMetadata]:  # line 44
    async def store_table_metadata(self, metadata: TableMetadata):  # line 80
    async def search_similar_tables(self, schema_names, query, limit=5) -> List[TableMetadata]:  # line 106
    def get_schema_overview(self, schema_name) -> Optional[SchemaMetadata]:  # line 236
    def get_hot_tables(self, schema_names, limit=10) -> List[tuple]:  # line 240
    def _calculate_relevance_score(self, table_name, table_meta, keywords) -> float:  # line 199
    def _extract_search_keywords(self, query) -> List[str]:  # line 185

# parrot/bots/database/models.py:104
class TableMetadata:
    schema: str
    tablename: str
    table_type: str
    full_name: str
    columns: List[Dict[str, Any]]
    def to_yaml_context(self) -> str:  # line 127

# parrot/stores/abstract.py
class AbstractStore(ABC):
    async def similarity_search(self, query, k, filter) -> List: ...
    async def add_documents(self, documents: List[Dict]) -> None: ...
```

### Does NOT Exist
- ~~`SchemaMetadataCache.get_partition()`~~ — no partitioning exists yet
- ~~`SchemaMetadataCache` Redis support~~ — current is LRU + vector only
- ~~`CacheManager`~~ — does not exist yet (this task creates it)
- ~~`CachePartition`~~ — does not exist yet (this task creates it)
- ~~`CachePartitionConfig`~~ — does not exist yet (this task creates it)

---

## Implementation Notes

### Pattern to Follow
```python
# Preserve the existing API surface within CachePartition:
class CachePartition:
    """Drop-in replacement for SchemaMetadataCache with namespace isolation."""
    async def get_table_metadata(self, schema_name, table_name) -> Optional[TableMetadata]: ...
    async def store_table_metadata(self, metadata: TableMetadata): ...
    async def search_similar_tables(self, schema_names, query, limit=5) -> List[TableMetadata]: ...
    def get_schema_overview(self, schema_name) -> Optional[SchemaMetadata]: ...
    def get_hot_tables(self, schema_names, limit=10) -> List[tuple]: ...
```

### Key Constraints
- Redis must be optional — `CacheManager(redis_url=None)` must work
- Preserve `_calculate_relevance_score()` and `_extract_search_keywords()` logic from current cache
- Use `redis.asyncio` (not `aioredis`) for Redis connections
- Each partition's Redis keys must be prefixed with namespace: `{namespace}:table:{schema}:{table}`
- JSON serialization for Redis values using `datamodel.parsers.json.json_encoder`

### References in Codebase
- `parrot/bots/database/cache.py` — current implementation (rewrite source)
- `parrot/bots/db/cache.py` — Redis-based cache from old package (reference for Redis patterns)

---

## Acceptance Criteria

- [ ] `CacheManager` creates partitions with independent LRU sizes and TTLs
- [ ] Two partitions don't interfere with each other's entries
- [ ] `search_across_databases()` returns results from all partitions
- [ ] Redis fallback: works in LRU-only mode when Redis is unavailable
- [ ] All tests pass: `pytest tests/unit/test_cache_manager.py -v`
- [ ] Imports work: `from parrot.bots.database.cache import CacheManager, CachePartition, CachePartitionConfig`

---

## Test Specification

```python
# tests/unit/test_cache_manager.py
import pytest
from parrot.bots.database.cache import CacheManager, CachePartition, CachePartitionConfig
from parrot.bots.database.models import TableMetadata


@pytest.fixture
def cache_manager():
    return CacheManager(redis_url=None, vector_store=None)


@pytest.fixture
def sample_table():
    return TableMetadata(
        schema="public", tablename="orders", table_type="BASE TABLE",
        full_name='"public"."orders"',
        columns=[{"name": "id", "type": "integer", "nullable": False}],
        primary_keys=["id"], foreign_keys=[], indexes=[], row_count=1000
    )


class TestCachePartitionIsolation:
    async def test_partitions_independent(self, cache_manager, sample_table):
        """Two partitions don't share entries."""
        p1 = cache_manager.create_partition(CachePartitionConfig(namespace="db1"))
        p2 = cache_manager.create_partition(CachePartitionConfig(namespace="db2"))
        await p1.store_table_metadata(sample_table)
        result = await p2.get_table_metadata("public", "orders")
        assert result is None

    async def test_partition_lru_eviction(self, cache_manager, sample_table):
        """Partition respects its own maxsize."""
        p = cache_manager.create_partition(
            CachePartitionConfig(namespace="small", lru_maxsize=2)
        )
        # Store 3 items, first should be evicted
        for i in range(3):
            t = TableMetadata(
                schema="public", tablename=f"table_{i}", table_type="BASE TABLE",
                full_name=f'"public"."table_{i}"', columns=[], primary_keys=[]
            )
            await p.store_table_metadata(t)
        result = await p.get_table_metadata("public", "table_0")
        assert result is None  # evicted

    async def test_search_across_databases(self, cache_manager, sample_table):
        """Cross-partition search returns results from all partitions."""
        p1 = cache_manager.create_partition(CachePartitionConfig(namespace="db1"))
        p2 = cache_manager.create_partition(CachePartitionConfig(namespace="db2"))
        await p1.store_table_metadata(sample_table)
        t2 = TableMetadata(
            schema="analytics", tablename="orders_bq", table_type="BASE TABLE",
            full_name='"analytics"."orders_bq"', columns=[], primary_keys=[]
        )
        await p2.store_table_metadata(t2)
        results = await cache_manager.search_across_databases("orders", limit=10)
        assert len(results) >= 2


class TestCacheManagerFallback:
    def test_no_redis(self):
        """CacheManager works without Redis."""
        cm = CacheManager(redis_url=None, vector_store=None)
        assert cm is not None

    async def test_close_without_redis(self):
        """close() doesn't crash without Redis."""
        cm = CacheManager(redis_url=None, vector_store=None)
        await cm.close()  # should not raise
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sqlagent-repair.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists
   - Confirm `SchemaMetadataCache` still has the listed methods
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-568-cache-manager.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
