---
type: Wiki Overview
title: 'TASK-1466: Filter Compiler (SQL push-down + pandas) + extend `_apply_filter`'
id: doc:sdd-tasks-completed-task-1466-filter-compiler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 3**. Translates a `FilterCondition` into either a SQL
  `WHERE`
relates_to:
- concept: mod:parrot.tools.dataset_manager.filtering
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.filtering.compiler
  rel: mentions
---

# TASK-1466: Filter Compiler (SQL push-down + pandas) + extend `_apply_filter`

**Feature**: FEAT-225 — DatasetManager Common-Field Filtering
**Spec**: `sdd/specs/datasetmanager-filtering.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1464, TASK-1465
**Assigned-to**: unassigned

---

## Context

Implements **Module 3**. Translates a `FilterCondition` into either a SQL `WHERE`
fragment (for SQL-backed sources) or a pandas mask (for in-memory frames). Also
extends the existing `_apply_filter()` to support the new operators. This is the
execution engine the orchestrator (TASK-1467) calls.

---

## Scope

- Extend `DatasetManager._apply_filter` (static, tool.py:829) to handle:
  - `ne` → `df[col] != value`
  - `not_in` → `~df[col].isin(value)`
  - `range` → `df[col].between(min, max)` (value = `{"min":..,"max":..}` or 2-seq)
  - keep existing `eq` (scalar `==`) and `in` (`isin`) semantics unchanged.
- Implement `filtering/compiler.py` with a `FilterCompiler`:
  - `compile_where(column, condition) -> (sql_fragment, params)` for `eq/ne/in/not_in/range`
    following the existing `permanent_filter` predicate style (scalar → `col = 'v'`,
    list → `col IN (...)`).
  - `compile_pandas(df, column, condition) -> pd.Series` (boolean mask).
  - Keep `compile_*` deterministic / I/O-free where feasible (execution is the
    orchestrator's job in TASK-1467).
- Unit tests for both paths and all operators.

**NOT in scope**: deciding which path per dataset / iterating datasets (TASK-1467),
spatial (`radius` delegates — TASK-1467), value catalogs, schema.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/filtering/compiler.py` | CREATE | `FilterCompiler` (SQL + pandas) |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | extend `_apply_filter` operators |
| `packages/ai-parrot/tests/unit/test_filter_compiler.py` | CREATE | per-op SQL + pandas tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pandas as pd
from parrot.tools.dataset_manager.filtering import FilterCondition, FilterOp  # TASK-1464
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
@staticmethod
def _apply_filter(df: pd.DataFrame, filter_dict: Dict[str, Any]) -> pd.DataFrame:  # line 829
    # current: scalar -> ==, list/tuple/set -> isin(); ANDed; reset_index(drop=True);
    #          ValueError if column missing. EXTEND with ne / not_in / range.

# permanent_filter predicate style to mirror for SQL WHERE building:
#   TableSource WHERE injection .................. tool.py:1388
#   QuerySlug conditions merge ................... tool.py:948
#   scalar -> "col = 'val'" ; list/tuple -> "col IN (...)"
```

### Does NOT Exist
- ~~`ne` / `not_in` / `range` in `_apply_filter` today~~ — only `==` and `isin`.
- ~~A reusable SQL predicate builder class~~ — predicate building is inline in
  TableSource/QuerySlug; this task introduces `FilterCompiler` to centralize it.
- ~~Ibis-based compilation~~ — NO-GO (TASK-1437, see `spatial/compiler.py`); hand-write SQL.

---

## Implementation Notes

### Pattern to Follow
- For pandas, follow the existing `_apply_filter` mask-AND pattern (build a
  boolean Series, AND conditions, `reset_index(drop=True)`).
- For SQL, replicate the scalar/list predicate style already used for
  `permanent_filter` (tool.py:1388 / :948). Parameterize values to avoid injection.

### Key Constraints
- Preserve backward-compatible `_apply_filter(df, {col: scalar|list})` dict form.
- Raise `ValueError` (matching the existing message) when a column is missing —
  the *skip vs error* decision belongs to the orchestrator (TASK-1467), not here.
- `range` value accepts `{"min","max"}` dict or a 2-element sequence.

---

## Acceptance Criteria

- [ ] `_apply_filter` handles `ne`/`not_in`/`range`; existing `eq`/`in` unchanged.
- [ ] `FilterCompiler.compile_where` emits correct fragments for `eq/ne/in/not_in/range`.
- [ ] `FilterCompiler.compile_pandas` returns correct boolean masks.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_filter_compiler.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/dataset_manager/filtering/compiler.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_filter_compiler.py
import pandas as pd
from parrot.tools.dataset_manager.filtering import FilterCondition
from parrot.tools.dataset_manager.filtering.compiler import FilterCompiler


def test_pandas_ne():
    df = pd.DataFrame({"region": ["North", "South", "North"]})
    mask = FilterCompiler().compile_pandas(df, "region", FilterCondition(op="ne", value="North"))
    assert mask.tolist() == [False, True, False]


def test_pandas_range():
    df = pd.DataFrame({"x": [1, 5, 10]})
    mask = FilterCompiler().compile_pandas(df, "x", FilterCondition(op="range", value={"min": 2, "max": 8}))
    assert mask.tolist() == [False, True, False]


def test_sql_in_fragment():
    frag, params = FilterCompiler().compile_where("region", FilterCondition(op="in", value=["A", "B"]))
    assert "IN" in frag.upper()
```

---

## Agent Instructions

Standard SDD agent loop. Locate `_apply_filter` by symbol in `tool.py` (line may
have shifted). Coordinate edits with FEAT-224 if both touch `tool.py`.

---

## Completion Note

Implemented as specified. Created `filtering/compiler.py` with `FilterCompiler`
(stateless, I/O-free) that provides `compile_where(column, condition)` returning
a SQL fragment + params list, and `compile_pandas(df, column, condition)` returning
a boolean Series. Handles eq/ne/in/not_in/range for both paths. Extended
`DatasetManager._apply_filter` to accept `FilterCondition` instances as dict
values (legacy scalar/list semantics preserved). 26 unit tests pass. No linting
errors.
