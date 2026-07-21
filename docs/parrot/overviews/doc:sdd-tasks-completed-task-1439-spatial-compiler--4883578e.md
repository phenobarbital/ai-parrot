---
type: Wiki Overview
title: 'TASK-1439: SpatialCompiler — Pandas bbox fallback + table.py BETWEEN predicate'
id: doc:sdd-tasks-completed-task-1439-spatial-compiler-pandas-bbox-fallback-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 4. The fallback branch of `SpatialCompiler` for backends without
  spatial
relates_to:
- concept: mod:parrot.tools.dataset_manager
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.tool
  rel: mentions
---

# TASK-1439: SpatialCompiler — Pandas bbox fallback + table.py BETWEEN predicate

**Feature**: FEAT-219 — Spatial Filtering for DatasetManager
**Spec**: `sdd/specs/spatial-dataset-filter.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1436
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. The fallback branch of `SpatialCompiler` for backends without spatial
functions (`mysql`, unknown driver, `InMemorySource`): derive a bounding box from
`(point, radius)`, push it as a cheap `BETWEEN` predicate, fetch only box survivors, then
refine to the exact circle with a vectorized haversine in memory. The bbox is a superset of
the circle — this guarantees we **never pull the full table** (spec G3/G4). Requires
teaching `_build_filter_clause` a range predicate **without disturbing** the existing
equality/`IN` path (spec §8 open question).

---

## Scope

- Implement the fallback branch of `SpatialCompiler.compile()` / `execute()` for non-spatial
  backends: bbox derivation → `BETWEEN` push-down → bounded fetch → haversine refine.
- Extend `TableSource._build_filter_clause` (or add a sibling) with a `BETWEEN`/range
  predicate for the bbox prefilter, without altering the equality/`IN` behavior. Confirm
  injection order relative to `_inject_permanent_filter` (table.py:414).
- Implement the vectorized haversine refine (numpy) over box survivors; reuse the
  in-memory filter machinery (`_apply_filter`, tool.py:821) where it fits.
- Record `geodesic=False` (spherical-approximate) for this path into `geodesic_paths`.
- Write unit tests: `test_bbox_predicate_isolated`, `test_haversine_refine` (spec §4).

**NOT in scope**: the pg/bigquery engine branch (TASK-1438), orchestration (TASK-1440),
contracts (TASK-1436), the HTTP handler (TASK-1441).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/spatial/compiler.py` | MODIFY | add fallback branch (created in TASK-1438) |
| `parrot/tools/dataset_manager/table.py` | MODIFY | `BETWEEN`/range predicate in `_build_filter_clause` |
| `tests/unit/test_spatial_compiler_fallback.py` | CREATE | bbox + haversine tests |

> **Conflict note**: `compiler.py` is also created by TASK-1438 — that is why this task
> depends on TASK-1438's branch existing first in sequence (per-spec worktree). `table.py`
> overlaps in-flight FEAT-218 — see spec Worktree Strategy.

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-03. Paths under `packages/ai-parrot/src/parrot/tools/dataset_manager/`.

### Verified Imports
```python
from parrot.tools.dataset_manager.table import TableSource      # table.py:113
from parrot.tools.dataset_manager.memory import InMemorySource  # memory.py:14
from parrot.tools.dataset_manager.tool import DatasetManager    # tool.py:492  (for _apply_filter)
```

### Existing Signatures to Use
```python
# parrot/tools/dataset_manager/table.py
class TableSource(DataSource):                          # l.113
    def _build_filter_clause(self) -> str: ...          # l.391  (equality / IN — EXTEND with BETWEEN, don't break)
    def _inject_permanent_filter(self, sql: str) -> str: ...  # l.414  (confirm bbox injection order vs this)

# parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                  # l.492
    @staticmethod
    def _apply_filter(df: pd.DataFrame, filter_dict: Dict[str, Any]) -> pd.DataFrame: ...  # l.821

# parrot/tools/dataset_manager/memory.py
class InMemorySource(DataSource): ...                   # l.14  (no driver → this fallback path)
```

### Does NOT Exist
- ~~`_apply_filter` as an instance method~~ — it is a **`@staticmethod`** (tool.py:821). Call as `DatasetManager._apply_filter(df, ...)`.
- ~~an existing `BETWEEN`/range branch in `_build_filter_clause`~~ — only equality/`IN` exist (table.py:391); you are adding the range branch.
- ~~existing haversine / great-circle helper~~ — none; implement with numpy.
- ~~`ibis`~~ — not needed in this fallback path at all.

---

## Implementation Notes

### Key Constraints
- The bbox is a cheap **superset** of the circle — push it down, then refine exactly in
  memory. Never fetch the full table (spec G4).
- `_build_filter_clause` change must be **additive** — the existing equality/`IN` path must
  behave identically (verified by `test_bbox_predicate_isolated`).
- Confirm where the bbox WHERE fragment sits relative to `_inject_permanent_filter`
  (table.py:414) so permanent filters still apply.
- Vectorize haversine with numpy (spec §7 External Dependencies).
- Record `geodesic=False` for this path (spherical-approximate) — declare+verify honesty.

### References in Codebase
- `parrot/tools/dataset_manager/table.py:391` / `:414` — filter clause + permanent filter.
- `parrot/tools/dataset_manager/tool.py:821` — `_apply_filter` staticmethod.

---

## Acceptance Criteria

- [ ] Fallback `compile()`/`execute()` derive bbox, push `BETWEEN`, fetch survivors, refine.
- [ ] `_build_filter_clause` gains a range predicate; equality/`IN` path unchanged.
- [ ] Haversine refine excludes bbox-corner points outside the circle.
- [ ] `geodesic_paths` records `False` for fallback datasets.
- [ ] All tests pass: `pytest tests/unit/test_spatial_compiler_fallback.py -v`
- [ ] No linting errors: `ruff check parrot/tools/dataset_manager/`

---

## Test Specification

```python
# tests/unit/test_spatial_compiler_fallback.py
import pytest


def test_bbox_predicate_isolated():
    """Adding the bbox BETWEEN clause leaves the equality/IN path byte-identical."""
    ...

def test_haversine_refine():
    """Points inside the bbox but outside the radius are dropped by the refine step."""
    ...
```

---

## Agent Instructions

Standard SDD lifecycle. Be conservative editing `_build_filter_clause` — coordinate with
in-flight FEAT-218 (spec Worktree Strategy) and keep the change additive.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Sonnet (sdd-worker)
**Date**: 2026-06-03
**Notes**: Fallback branch (_compile_pandas, _execute_pandas, _build_bbox_sql, _haversine_refine)
was already implemented in TASK-1438's compiler.py. This task added: (1) BETWEEN range predicate
to TableSource._build_filter_clause — uses dict{'min':..., 'max':...} value form; equality/IN
path unchanged byte-identical; (2) confirmed bbox injection order — _build_bbox_sql constructs
the bbox WHERE directly then calls source._inject_permanent_filter on top, so permanent filters
stack on after the bbox predicate. Records geodesic=False for the pandas path.
**Deviations from spec**: none
