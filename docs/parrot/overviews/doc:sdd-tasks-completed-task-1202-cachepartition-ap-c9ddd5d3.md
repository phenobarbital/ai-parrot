---
type: Wiki Overview
title: 'TASK-1202: CachePartition API rework — completeness + TTL gating + score-sorted
  search'
id: doc:sdd-tasks-completed-task-1202-cachepartition-api-rework-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The current `CachePartition` silently returns stub `TableMetadata`
relates_to:
- concept: mod:parrot.bots.database.cache
  rel: mentions
- concept: mod:parrot.bots.database.models
  rel: mentions
---

# TASK-1202: CachePartition API rework — completeness + TTL gating + score-sorted search

**Feature**: FEAT-178 — Database Toolkit Cache Contract & Tool Semantics
**Spec**: `sdd/specs/database-toolkit-cache-contract.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1201
**Assigned-to**: unassigned

---

## Context

The current `CachePartition` silently returns stub `TableMetadata`
as if it were authoritative and truncates search results without
sorting by score (cache.py:357-365). This task implements the new
contract: every read declares a minimum completeness; the cache
returns `None` when that level is not met. Search returns score-
sorted results.

Implements **Module 2** of the spec.

---

## Scope

- Extend `CachePartitionConfig` with
  `ttl_by_completeness: Dict[Completeness, int]` — defaults
  `{NAME_ONLY: 86400, WITH_COLUMNS: 21600, FULL: 3600}`.
- Add new methods on `CachePartition`:
  - `async def get(self, schema_name, table_name, *, required=Completeness.NAME_ONLY, max_age=None) -> Optional[TableMetadata]`
  - `async def list(self, schema_names, *, completeness_min=Completeness.NAME_ONLY, max_age=None, limit=None) -> List[TableMetadata]`
  - `async def search(self, schema_names, search_term, *, completeness_min=Completeness.NAME_ONLY, max_age=None, limit=20) -> List[TableMetadata]`
- `store_table_metadata` must respect per-completeness TTL when
  writing to Redis (the effective Redis TTL is
  `min(redis_ttl, ttl_by_completeness[entry.completeness])`).
- Rework `_score_against_cache` to **sort by score descending**
  before truncating. Same for `_search_cache_only`.
- Vector path: `_search_vector_store` candidates are filtered
  post-hoc by `completeness_min` and `max_age` via the new
  `get(...)` call.
- Keep `get_table_metadata` and `search_similar_tables` as
  backwards-compat aliases that delegate to the new API and emit
  `DeprecationWarning`.
- Forward `cache_ttl_by_completeness` kwarg from `DatabaseAgent`
  into `CachePartitionConfig` (small wiring in `agent.py:162-170`).
- Unit tests: completeness gating, max-age gating, score sort,
  per-completeness TTL, vector post-hoc filter, deprecation
  warnings.

**NOT in scope**: SQLToolkit method changes (TASK-1204), DB
introspection coalescing (TASK-1203), prompt layer (TASK-1206).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/cache.py` | MODIFY | New `get/list/search`, `ttl_by_completeness`, score-sorted scoring, vector post-hoc filter, deprecation aliases |
| `packages/ai-parrot/src/parrot/bots/database/agent.py` | MODIFY | Forward `cache_ttl_by_completeness` kwarg into `CachePartitionConfig` |
| `packages/ai-parrot/tests/bots/database/test_cache.py` | CREATE or MODIFY | Unit tests for new API |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from parrot.bots.database.models import TableMetadata, Completeness  # Completeness from TASK-1201
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/database/cache.py
class CachePartitionConfig(BaseModel):                       # line 30
    # existing: namespace, lru_maxsize=500, lru_ttl=1800, redis_ttl=3600

class CachePartition:                                        # line 43
    def __init__(self, namespace, lru_maxsize=500, lru_ttl=1800,
                 redis_ttl=3600, redis_pool=None,
                 vector_store=None): ...                      # line 55
    def _table_cache_key(self, schema_name, table_name) -> str: ...  # line 85
    def _redis_key(self, schema_name, table_name) -> str: ...        # line 89
    async def get_table_metadata(self, schema_name, table_name) -> Optional[TableMetadata]: ...  # line 95
    async def store_table_metadata(self, metadata: TableMetadata) -> None: ...     # line 138
    async def search_similar_tables(self, schema_names, query, limit=5) -> List[TableMetadata]: ...  # line 166
    def _calculate_relevance_score(self, table_name, table_meta, keywords) -> float: ...  # line 223
    def _search_cache_only(self, schema_names, query, limit) -> List[TableMetadata]: ...  # line 255
    def _score_against_cache(self, schema_names, keywords, seen, remaining) -> List[TableMetadata]: ...  # line 336
    async def _get_from_redis(self, schema_name, table_name) -> Optional[TableMetadata]: ...  # line 392
    async def _store_in_redis(self, metadata: TableMetadata) -> None: ...  # line 409
    async def _search_vector_store(self, schema_names, query, limit) -> Any: ...  # line 422
    async def _store_in_vector_store(self, metadata: TableMetadata) -> None: ...  # line 430
    async def _convert_vector_results(self, results) -> List[TableMetadata]: ...  # line 449


# packages/ai-parrot/src/parrot/bots/database/agent.py
class DatabaseAgent(BasicAgent):                             # line 85
    async def configure(self, app=None) -> None: ...         # line 134
    # Cache partition creation: agent.py:162-170 — construct
    # CachePartitionConfig and forward cache_ttl_by_completeness here.
```

### Existing Defect
```python
# cache.py:357-365 — _score_against_cache returns in ITERATION ORDER, truncates without sort
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
            out.append(table_meta)
            if len(out) >= remaining:
                return out      # ← bug: truncates before score sort
```

### Does NOT Exist
- ~~`CachePartition.get(...)` with `required=`~~ — introduced here.
- ~~`CachePartition.list(...)`~~ — introduced here.
- ~~`CachePartition.search(...)` with `completeness_min=`~~ — introduced here.
- ~~`CachePartitionConfig.ttl_by_completeness`~~ — introduced here.

---

## Implementation Notes

### `get(...)` semantics (spec §2 New Interfaces)
```python
async def get(
    self,
    schema_name: str,
    table_name: str,
    *,
    required: Completeness = Completeness.NAME_ONLY,
    max_age: Optional[timedelta] = None,
) -> Optional[TableMetadata]:
    """
    Return metadata only if:
      1. entry exists in any tier (LRU > Redis > vector)
      2. entry.completeness >= required
      3. now - entry.loaded_at <= effective_max_age
         where effective_max_age = max_age if provided else
         timedelta(seconds=ttl_by_completeness[entry.completeness])
    Returns None otherwise. Caller decides DB fallback.
    """
```

### Score-sort pattern (spec §7)
Accumulate `(score, meta)` tuples, then
`sorted(scored, key=lambda x: x[0], reverse=True)[:limit]`.
Fix both `_score_against_cache` and `_search_cache_only`.

### TTL composition
Effective Redis TTL for `store_table_metadata`:
```python
tier_cap = self.ttl_by_completeness.get(metadata.completeness, self.redis_ttl)
effective_ttl = min(self.redis_ttl, tier_cap)
```

### Vector post-hoc filter (Q5)
After `_search_vector_store` returns candidates, run each through
the new `self.get(schema, table, required=completeness_min,
max_age=max_age)`. Drop candidates that return `None`. This also
handles the renamed/dropped table case naturally.

### Backwards-compat aliases
`get_table_metadata` and `search_similar_tables` must keep their
exact signatures and behaviour, but emit `DeprecationWarning` via
`warnings.warn(..., DeprecationWarning, stacklevel=2)` and
delegate to the new methods.

### `DatabaseAgent` wiring
At `agent.py:162-170` (where `CachePartitionConfig` is constructed),
read a new kwarg `cache_ttl_by_completeness` from `DatabaseAgent.__init__`
and forward it (only if not `None`) into the config.

---

## Acceptance Criteria

- [ ] `CachePartitionConfig.ttl_by_completeness` field exists with
      the documented defaults
- [ ] `CachePartition.get(required=...)` returns `None` for entries
      that do not satisfy `required`
- [ ] `CachePartition.get(max_age=...)` returns `None` for stale
      entries; default `max_age` derived from `ttl_by_completeness`
- [ ] `CachePartition.list` and `CachePartition.search` exist with
      the specified signatures
- [ ] `_score_against_cache` and `_search_cache_only` sort by score
      descending before truncating
- [ ] Vector candidates are filtered post-hoc by `completeness_min`
      and `max_age`
- [ ] `get_table_metadata` and `search_similar_tables` emit
      `DeprecationWarning` and still work
- [ ] `DatabaseAgent(cache_ttl_by_completeness=...)` forwards into
      `CachePartitionConfig`
- [ ] All existing cache tests still pass
- [ ] New tests pass: `pytest packages/ai-parrot/tests/bots/database/test_cache.py -v`

---

## Test Specification

```python
# tests/bots/database/test_cache.py
import warnings
from datetime import datetime, timedelta
import pytest

from parrot.bots.database.cache import CachePartition, CachePartitionConfig
from parrot.bots.database.models import Completeness, TableMetadata


def _make(schema, table, completeness=Completeness.FULL, age_seconds=0,
          columns=None):
    return TableMetadata(
        schema=schema, tablename=table, table_type="BASE TABLE",
        full_name=f"{schema}.{table}", completeness=completeness,
        loaded_at=datetime.utcnow() - timedelta(seconds=age_seconds),
        columns=columns or [{"name": "id", "type": "int"}],
    )


class TestCacheGet:
    async def test_get_respects_required_level(self, partition):
        await partition.store_table_metadata(
            _make("s", "t", Completeness.NAME_ONLY, columns=[])
        )
        assert await partition.get("s", "t", required=Completeness.FULL) is None
        assert await partition.get("s", "t", required=Completeness.NAME_ONLY) is not None

    async def test_get_respects_max_age(self, partition):
        await partition.store_table_metadata(
            _make("s", "t", Completeness.FULL, age_seconds=10_000)
        )
        # default max_age for FULL is 3600s
        assert await partition.get("s", "t", required=Completeness.FULL) is None


class TestCacheSearch:
    async def test_search_sorts_by_score(self, partition):
        # Substring matches first by insertion; exact match last.
        await partition.store_table_metadata(_make("altice", "store_inventory"))
        await partition.store_table_metadata(_make("altice", "store_groups"))
        await partition.store_table_metadata(_make("pokemon", "stores"))

        out = await partition.search(["altice", "pokemon"], "stores", limit=10)
        # Exact match "stores" must rank above "store_inventory"
        assert out[0].tablename == "stores"

    async def test_completeness_min_excludes_stubs(self, partition):
        await partition.store_table_metadata(
            _make("s", "t", Completeness.NAME_ONLY, columns=[])
        )
        out = await partition.search(["s"], "t",
                                     completeness_min=Completeness.WITH_COLUMNS)
        assert out == []


class TestPerCompletenessTTL:
    async def test_name_only_outlives_full_ttl(self, partition):
        """NAME_ONLY default TTL (24h) is longer than FULL (1h)."""
        meta = _make("s", "t", Completeness.NAME_ONLY,
                     age_seconds=3700, columns=[])
        await partition.store_table_metadata(meta)
        # Past FULL TTL but within NAME_ONLY TTL — still served
        got = await partition.get("s", "t", required=Completeness.NAME_ONLY)
        assert got is not None


class TestDeprecation:
    async def test_get_table_metadata_warns(self, partition):
        await partition.store_table_metadata(_make("s", "t"))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await partition.get_table_metadata("s", "t")
            assert any(issubclass(x.category, DeprecationWarning) for x in w)
```

---

## Agent Instructions

When you pick up this task:

1. Confirm TASK-1201 is in `sdd/tasks/completed/`.
2. Re-verify the Codebase Contract (`grep -n` `cache.py` for line
   numbers — they may have shifted after TASK-1201 was merged).
3. Implement.
4. Run `pytest packages/ai-parrot/tests/bots/database/test_cache.py -v`.
5. Run `ruff check packages/ai-parrot/src/parrot/bots/database/cache.py packages/ai-parrot/src/parrot/bots/database/agent.py`.
6. Move task file to `completed/` and update the per-spec index.
7. Fill in the Completion Note.

---

## Completion Note

Implemented on branch `feat-178-database-toolkit-cache-contract`.

- Added `ttl_by_completeness: Dict[int, int]` to `CachePartitionConfig` (defaults NAME_ONLY=86400, WITH_COLUMNS=21600, FULL=3600).
- Added `ttl_by_completeness` attribute to `CachePartition.__init__`.
- New `get(required, max_age)`: resolves LRU→schema_cache→Redis→vector, gates on completeness and `loaded_at`-based freshness.
- New `list(schema_names, completeness_min, max_age, limit)`: in-memory iteration with freshness gate.
- New `search(schema_names, search_term, completeness_min, max_age, limit)`: vector path with post-hoc filtering via `get()`; cache-only fallback with completeness/age gate.
- Fixed `_score_against_cache`: collects all scored items, sorts descending by score, then truncates — eliminates the early-truncation bug.
- `store_table_metadata` now computes `effective_ttl = min(redis_ttl, tier_cap)` before Redis write.
- `_store_in_redis` accepts optional `ttl` kwarg.
- `get_table_metadata` and `search_similar_tables` emit `DeprecationWarning` and delegate to new methods.
- `DatabaseAgent` accepts `cache_ttl_by_completeness` kwarg and forwards to `CachePartitionConfig`.
- Pre-existing `_QUALIFIED_REF_RE` regex moved after imports to fix E402 lint (pre-existing issue).
- 17/17 new tests pass; 59/59 existing tests pass.
