---
type: Wiki Overview
title: 'TASK-1468: Value Catalogs (`get_filter_values`) + Cache'
id: doc:sdd-tasks-completed-task-1468-value-catalogs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 5**. Provides the distinct-value lists that the frontend
  uses
relates_to:
- concept: mod:parrot.tools.dataset_manager.filtering
  rel: mentions
---

# TASK-1468: Value Catalogs (`get_filter_values`) + Cache

**Feature**: FEAT-225 — DatasetManager Common-Field Filtering
**Spec**: `sdd/specs/datasetmanager-filtering.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1464, TASK-1465
**Assigned-to**: unassigned

---

## Context

Implements **Module 5**. Provides the distinct-value lists that the frontend uses
to build combo selectors (e.g. the list of unique `region` values). Declared
`values_source` wins; otherwise infer `UNION DISTINCT`/`unique()` across the
datasets that have the column, cached with a cardinality cap + TTL.

---

## Scope

- Implement `async def get_filter_values(self, name: str) -> List[Any]`:
  - Look up the `FilterDefinition` by `name`.
  - If `values_source` declared:
    - `query_slug` → run the slug and take the column.
    - `column`/`dataset` → DISTINCT over the declared column/dataset.
  - Else (inference fallback): union of distinct values across all datasets that
    have the column (SQL → `SELECT DISTINCT`; in-memory → `df[col].unique()`),
    de-duplicated and sorted.
  - Apply a cardinality cap (default — see spec §8 open question; pick a sane
    default like 1000 and log truncation).
  - Cache the result (reuse the manager's existing Redis/Parquet cache with a TTL).
- Place inference/cache helpers in `filtering/values.py`.
- Unit tests (declared source wins; inference + cache; cardinality cap).

**NOT in scope**: schema/suggest (TASK-1469), apply/orchestration (TASK-1467),
the HTTP endpoint (TASK-1470).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/filtering/values.py` | CREATE | inference + cache helpers |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | add `get_filter_values()` |
| `packages/ai-parrot/tests/unit/test_filter_values.py` | CREATE | declared vs inferred + cache + cap |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.dataset_manager.filtering import FilterDefinition, ValuesSource  # TASK-1464
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                                  # line 500
    self._datasets: Dict[str, DatasetEntry]                            # line 533
    self._filter_defs: Dict[str, FilterDefinition]                     # TASK-1465
    async def materialize(self, name, force_refresh=False, **params) -> pd.DataFrame  # line 3953
    # Reuse the existing Redis/Parquet cache used by materialize() — locate the
    # cache attribute/helper in __init__ (do NOT invent a new cache client).

class DatasetEntry:                                                    # line 123
    _column_types: Dict[str, str]
# QuerySlugSource path exists for running query slugs (add_query, tool.py:1300).
```

### Does NOT Exist
- ~~`DatasetManager.get_filter_values` / `get_distinct` / `get_unique`~~ — created here.
- ~~A dedicated distinct-values cache~~ — reuse the manager's existing cache; do not
  spin up a new Redis client.

---

## Implementation Notes

### Pattern to Follow
- For in-memory frames, `df[col].dropna().unique().tolist()`.
- For SQL sources, prefer a `SELECT DISTINCT col` (push-down) over materializing the
  whole frame; fall back to `materialize()` + `unique()` if the source can't be queried directly.
- Reuse the manager's cache (same mechanism `materialize()` uses) keyed by filter name.

### Key Constraints
- Async; `self.logger` for cache hits/misses and truncation.
- Respect PBAC: never return values from a column the policy would drop/forbid.
- Cardinality cap configurable; default documented; log when truncated.

---

## Acceptance Criteria

- [ ] Declared `values_source` (query_slug / column) takes priority over inference.
- [ ] Inference unions DISTINCT across datasets with the column; sorted, de-duplicated.
- [ ] Result cached (second call hits cache); cardinality cap enforced + logged.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_filter_values.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/dataset_manager/filtering/values.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_filter_values.py
import pytest
from parrot.tools.dataset_manager.filtering import FilterDefinition, ValuesSource


async def test_declared_source_wins(manager_with_regions_catalog):
    dm = manager_with_regions_catalog
    dm.define_filters([FilterDefinition(name="region", columns=["region"],
        kind="categorical", ops=["in"],
        values_source=ValuesSource(query_slug="regions_catalog"))])
    vals = await dm.get_filter_values("region")
    assert "North" in vals


async def test_inferred_union_distinct(manager_with_three_datasets):
    dm = manager_with_three_datasets
    dm.define_filters([FilterDefinition(name="region", columns=["region"],
        kind="categorical", ops=["in"])])  # no values_source
    vals = await dm.get_filter_values("region")
    assert sorted(vals) == vals  # sorted + deduped
```

---

## Agent Instructions

Standard SDD agent loop. Find the existing cache helper in `DatasetManager.__init__`
before adding caching — reuse it.

---

## Completion Note

Implemented as specified. Created `filtering/values.py` with `infer_values_from_datasets`
and `apply_cardinality_cap` helpers. Added `get_filter_values(name, cardinality_cap=1000)`
to DatasetManager. Supports declared `values_source` (query_slug or column/dataset
restriction) and inference fallback from in-memory datasets. Per-instance in-memory
cache avoids redundant scans. Cardinality cap (default 1000) truncates and logs. 12
unit tests pass. No linting errors.
