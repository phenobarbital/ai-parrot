---
type: Wiki Overview
title: 'TASK-1467: `apply_filters()` Orchestration + Spatial Delegation'
id: doc:sdd-tasks-completed-task-1467-apply-filters-orchestration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 4** — the heart of the feature. Resolves a filter request
relates_to:
- concept: mod:parrot.tools.dataset_manager.filtering
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.filtering.compiler
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.spatial.contracts
  rel: mentions
---

# TASK-1467: `apply_filters()` Orchestration + Spatial Delegation

**Feature**: FEAT-225 — DatasetManager Common-Field Filtering
**Spec**: `sdd/specs/datasetmanager-filtering.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1464, TASK-1465, TASK-1466
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** — the heart of the feature. Resolves a filter request
against the catalog and applies it **recursively** to every dataset that has the
target column(s), choosing the execution path per source type, honoring `required`,
and assembling a `FilterResult`. `kind="spatial"` delegates to the existing
`spatial_filter()`.

---

## Scope

- Implement `async def apply_filters(self, request: Dict[str, Any], *, persist: bool = False) -> FilterResult`:
  - Resolve each request key to a stored `FilterDefinition`; coerce bare
    scalar/list into `FilterCondition(op="eq"|"in")`.
  - For each affected dataset, decide the path:
    - SQL-backed source (table/query) → build WHERE via `FilterCompiler.compile_where`
      and push down (reuse `permanent_filter`/WHERE mechanism, fetch filtered).
    - In-memory DataFrame → `FilterCompiler.compile_pandas` / extended `_apply_filter`.
    - `kind="spatial"` → build a `SpatialFilterSpec` and call `self.spatial_filter(spec)`;
      return the existing `SpatialResult` shape for that filter.
  - Skip datasets lacking the column → record in `result.skipped` when
    `definition.required is False`; raise `ValueError` (naming dataset) when `True`.
  - Return per-dataset filtered data alongside the `FilterResult` (applied/skipped).
  - `persist=True` → register filtered DataFrames as new dataset entries (naming
    policy is an open question — see spec §8; use a documented default for now).
- Unit + integration tests (mixed sources, recursive skip, required-raise,
  spatial delegation, persist).

**NOT in scope**: value catalogs (TASK-1468), schema/suggest (TASK-1469),
tools/handler (TASK-1470), compiler internals (TASK-1466).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | add `apply_filters()` orchestration |
| `packages/ai-parrot/tests/unit/test_apply_filters.py` | CREATE | recursive skip / required / persist / spatial-delegate |
| `packages/ai-parrot/tests/integration/test_apply_filters_mixed.py` | CREATE | end-to-end mixed sources |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.dataset_manager.filtering import FilterDefinition, FilterCondition, FilterResult
from parrot.tools.dataset_manager.filtering.compiler import FilterCompiler   # TASK-1466
from parrot.tools.dataset_manager.spatial.contracts import SpatialFilterSpec, SpatialResult  # spatial/contracts.py:25,266
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                                       # line 500
    self._datasets: Dict[str, DatasetEntry]                                  # line 533
    self._filter_defs: Dict[str, FilterDefinition]                           # added in TASK-1465
    async def materialize(self, name, force_refresh=False, **params) -> pd.DataFrame  # line 3953
    async def spatial_filter(self, spec: "SpatialFilterSpec",
                             cap_per_dataset: int = 1000) -> "SpatialResult"  # line 4186
    @staticmethod
    def _apply_filter(df, filter_dict) -> pd.DataFrame                       # line 829 (extended TASK-1466)
    def _resolve_name(self, name: str) -> str                                # used by get_manifest:4169

class DatasetEntry:                                                          # line 123
    source: <DataSource>                                                     # getattr(source, "driver", None) selects path
    _df: Optional[pd.DataFrame]
    _column_types: Dict[str, str]

# SpatialFilterSpec fields: point: Tuple[float,float]; radius: float;
#   unit: Literal["mi","km","m"]; datasets: List[str]   (spatial/contracts.py:25)
```

### Does NOT Exist
- ~~`DatasetManager.apply_filters`~~ — created here.
- ~~A pre-built mapping of dataset→columns~~ — derive from `_column_types` / df columns;
  may require `materialize()` for not-yet-fetched sources.
- ~~Spatial path through `materialize()`/Redis Parquet cache~~ — FEAT-219 G4 forbids it;
  always route spatial through `spatial_filter()` which owns its execution.

---

## Implementation Notes

### Pattern to Follow
- Source-type routing: inspect the entry's source (e.g. `getattr(source, "driver", None)`
  as `SpatialCompiler` does) — SQL drivers push down, in-memory uses pandas.
- For spatial, build `SpatialFilterSpec(point=..., radius=..., unit=..., datasets=[...])`
  from the `FilterCondition` value and delegate.
- Mirror `get_manifest()` (tool.py:4139) for resolving which registered datasets apply.

### Key Constraints
- Async throughout; `self.logger` at skip/apply/persist points.
- Ephemeral by default — do NOT mutate `self._datasets` unless `persist=True`.
- Empty filtered result is valid (not an error).
- `required=True` + missing column → `ValueError` naming the dataset and filter.

---

## Acceptance Criteria

- [ ] `apply_filters({"region": {"op":"in","value":[...]}}, persist=False)` filters all
      datasets with `region`, skips others, manager untouched.
- [ ] `result.applied` / `result.skipped` correctly populated.
- [ ] `required=True` + missing column raises `ValueError`.
- [ ] `kind="spatial"` request returns a `SpatialResult` via `spatial_filter()`.
- [ ] `persist=True` registers new filtered dataset entries.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_apply_filters.py packages/ai-parrot/tests/integration/test_apply_filters_mixed.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_apply_filters.py
import pytest


async def test_recursive_skip(manager_with_three_datasets):
    dm = manager_with_three_datasets  # stores+sites have region; weather does not
    from parrot.tools.dataset_manager.filtering import FilterDefinition
    dm.define_filters([FilterDefinition(name="region", columns=["region"],
                                        kind="categorical", ops=["in"], required=False)])
    res = await dm.apply_filters({"region": ["North"]})
    assert set(res.applied) >= {"stores", "sites"}
    assert "weather" in res.skipped


async def test_required_missing_raises(manager_with_three_datasets):
    from parrot.tools.dataset_manager.filtering import FilterDefinition
    dm = manager_with_three_datasets
    dm.define_filters([FilterDefinition(name="region", columns=["region"],
                                        kind="categorical", ops=["eq"], required=True)])
    with pytest.raises(ValueError):
        await dm.apply_filters({"region": "North"})
```

---

## Agent Instructions

Standard SDD agent loop. This task edits `tool.py` heavily — locate methods by
symbol, keep edits surgical, and coordinate with FEAT-224.

---

## Completion Note

Implemented as specified. Added `async def apply_filters(request, persist=False)` to
`DatasetManager`. Resolves request keys against `_filter_defs`, coerces bare scalar/list
to `FilterCondition(eq/in)`, routes spatial kind to `spatial_filter()`, applies pandas
filter to in-memory datasets, skips datasets missing target columns (records in
`result.skipped`), raises `ValueError` for `required=True` missing columns. `persist=True`
registers filtered DataFrames as `<name>__filtered` with collision guard. 11 unit tests
and 7 integration tests pass. No linting errors.
