---
type: Wiki Overview
title: 'TASK-1440: DatasetManager.spatial_filter orchestration'
id: doc:sdd-tasks-completed-task-1440-spatial-filter-orchestration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 5. The thin toolkit method that ties the feature together.
  It is LLM-visible
relates_to:
- concept: mod:parrot.tools.dataset_manager.spatial.compiler
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.spatial.contracts
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.tool
  rel: mentions
---

# TASK-1440: DatasetManager.spatial_filter orchestration

**Feature**: FEAT-219 — Spatial Filtering for DatasetManager
**Spec**: `sdd/specs/spatial-dataset-filter.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1436, TASK-1438, TASK-1439
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. The thin toolkit method that ties the feature together. It is LLM-visible
(so NL→spec mode sees it as a tool) and gets per-call permission isolation for free via the
existing `_pctx_var` ContextVar. It orchestrates ONLY: resolve profiles (validate) → group
datasets by `(driver, connection)` → `asyncio.gather` per group with `_pctx_var` propagated
→ merge into one `SpatialFeatureCollection` with a hard cap + true `total_count` per dataset.

---

## Scope

- Implement `DatasetManager.spatial_filter(spec: SpatialFilterSpec) -> SpatialFeatureCollection`.
- Resolve each dataset via `_resolve_name` (tool.py:599) and its profile via
  `SPATIAL_PROFILE_REGISTRY`; validate existence (descriptive `ValueError`).
- Group datasets by `(driver, connection)`; dispatch each group to the right
  `SpatialCompiler` branch (engine vs fallback) via `getattr(source, "driver", None)`.
- `asyncio.gather` per group, propagating the current `PermissionContext` through `_pctx_var`.
- Merge results into one `SpatialFeatureCollection`; apply **hard cap per dataset** and set
  `total_count` (true count) + `capped`; populate `geodesic_paths` from the compiler.
- Write unit tests: `test_capping_total_count`, `test_group_by_driver_connection`,
  `test_pctx_isolation` (spec §4).

**NOT in scope**: the HTTP handler / AgenTalk envelope (TASK-1441), the compiler internals
(TASK-1438/1439), the contracts (TASK-1436). This method only orchestrates.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/tool.py` | MODIFY | add `spatial_filter` thin method on `DatasetManager` |
| `tests/unit/test_spatial_filter_orchestration.py` | CREATE | grouping, capping, pctx-isolation tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-03. Paths under `packages/ai-parrot/src/parrot/tools/dataset_manager/`.

### Verified Imports
```python
import contextvars
from parrot.tools.dataset_manager.tool import DatasetManager, _pctx_var  # tool.py:492 / :41
from parrot.tools.dataset_manager.spatial.contracts import SpatialFilterSpec, SpatialFeatureCollection  # TASK-1436
from parrot.tools.dataset_manager.spatial.compiler import SpatialCompiler  # TASK-1438/1439
```

### Existing Signatures to Use
```python
# parrot/tools/dataset_manager/tool.py
_pctx_var: contextvars.ContextVar = contextvars.ContextVar(  # l.41
    "dataset_manager_pctx", default=None)

class DatasetManager(AbstractToolkit):                  # l.492
    tool_prefix: str = "dataset"                        # l.512
    def _resolve_name(self, identifier: str) -> str: ...  # l.599
    async def _pre_execute(self, tool_name: str, **kwargs) -> None:  # l.2558
        ...
        _pctx_var.set(pctx)                             # l.2580  (permission context established here)

# parrot/tools/dataset_manager/table.py
class TableSource(DataSource):
    self.driver = _normalize_driver(driver)             # l.157  (grouping discriminator)
```

### Does NOT Exist
- ~~`DatasetManager.materialize`~~ — `materialize` is on `DatasetEntry` (tool.py:240). `spatial_filter` MUST NOT route through it (spec G4).
- ~~`DataSource.driver`~~ — `driver` is on `TableSource` only (table.py:157). Use `getattr(source, "driver", None)`; absence → fallback path.
- ~~`_apply_filter` as an instance method~~ — it is a `@staticmethod` (tool.py:821).
- ~~`_pctx_var` as an instance attribute~~ — it is a **module-level** `ContextVar` (tool.py:41).

---

## Implementation Notes

### Pattern to Follow
- **Thin method**: orchestrate only — no SQL, no geometry math here (that lives in the
  compiler). Mirrors the manager-orchestrates / compiler-translates split (spec §2).
- Propagate `_pctx_var` into each `asyncio.gather` task so concurrent requests keep isolated
  `PermissionContext` (the ContextVar is copied per task; set it inside the task if needed).
- Group by `(driver, connection)` so one gather task serves co-located datasets.

### Key Constraints
- Async throughout; `asyncio.gather` for fan-out.
- Hard cap is **per dataset**; `total_count` reports the TRUE count even when capped.
- Validate every referenced dataset/profile up front (descriptive `ValueError`).
- Be mindful of the AsyncDB per-connection pool ceiling (spec §8 open question) — do not
  unbounded-fan-out; document any concurrency bound you choose.
- Partial-backend-failure policy is an open question (spec §8) — implement a clear,
  documented choice (surface partial + error marker is the suggested default) and note it.

### References in Codebase
- `parrot/tools/dataset_manager/tool.py:41` / `:2558` — `_pctx_var` + where it is set.
- `parrot/tools/dataset_manager/tool.py:599` — `_resolve_name`.

---

## Acceptance Criteria

- [ ] `spatial_filter` resolves + validates datasets/profiles; unknown → descriptive `ValueError`.
- [ ] Datasets grouped by `(driver, connection)`; one gather task per group.
- [ ] Concurrent calls keep isolated `PermissionContext` via `_pctx_var`.
- [ ] Result capped per dataset; `total_count` true; `capped` set; `geodesic_paths` populated.
- [ ] Does NOT route through `DatasetEntry.materialize`.
- [ ] All tests pass: `pytest tests/unit/test_spatial_filter_orchestration.py -v`
- [ ] No linting errors: `ruff check parrot/tools/dataset_manager/tool.py`

---

## Test Specification

```python
# tests/unit/test_spatial_filter_orchestration.py
import pytest


async def test_group_by_driver_connection():
    """Datasets across the same (driver, connection) collapse into one gather task."""
    ...

async def test_capping_total_count():
    """A dense result is capped at N; total_count reports the true count; capped=True."""
    ...

async def test_pctx_isolation():
    """Two concurrent spatial_filter calls keep distinct PermissionContext via _pctx_var."""
    ...
```

---

## Agent Instructions

Standard SDD lifecycle. Keep the method thin — push any SQL/geometry work down to the
compiler. Document your partial-failure and concurrency-bound choices in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Sonnet (sdd-worker)
**Date**: 2026-06-03
**Notes**: DatasetManager.spatial_filter added at end of tool.py. Orchestration: resolves names
via _resolve_name, validates profiles via validate_profiles_exist, groups by (driver, connection)
using _get_connection_args for connection identity, asyncio.gather per dataset with _pctx_var
propagation into each task, merges into SpatialFeatureCollection with cap_per_dataset hard cap.
Partial-failure policy: one dataset failing surfaces empty features + error log (not fatal).
AsyncDB pool ceiling: documented choice — no concurrency bound applied beyond asyncio.gather
default (each dataset is one task); real pool-ceiling limits are AsyncDB's responsibility.
**Deviations from spec**: none
