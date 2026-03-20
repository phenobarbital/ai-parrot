# TASK-214: InMemorySource

**Feature**: DatasetManager Lazy Data Sources (FEAT-030)
**Spec**: `sdd/specs/datasetmanager-datasources.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-213
**Assigned-to**: claude-sonnet-4-6

---

## Context

> Simplest concrete source type. Wraps an already-loaded `pd.DataFrame` so it fits the
> `DataSource` protocol. Enables `add_dataframe()` to use the new source abstraction while
> remaining fully backward compatible.

---

## Scope

- Implement `InMemorySource` at `parrot/tools/dataset_manager/sources/memory.py`.
- Constructor accepts `df: pd.DataFrame` and `name: str`.
- `prefetch_schema()`: derive column→dtype map from `df.dtypes` (no I/O).
- `fetch(**params)`: return `self._df` as-is (params are ignored).
- `describe()`: return a string like `"In-memory DataFrame ({rows} rows × {cols} columns)"`.
- `cache_key`: `f"mem:{self.name}"`.
- Export `InMemorySource` from `parrot/tools/dataset_manager/sources/__init__.py`.

```python
# parrot/tools/dataset_manager/sources/memory.py
from typing import Dict
import pandas as pd
from .base import DataSource


class InMemorySource(DataSource):
    """Wraps an already-loaded pd.DataFrame as a DataSource."""

    def __init__(self, df: pd.DataFrame, name: str) -> None:
        self._df = df
        self._name = name

    async def prefetch_schema(self) -> Dict[str, str]:
        return {col: str(dtype) for col, dtype in self._df.dtypes.items()}

    async def fetch(self, **params) -> pd.DataFrame:
        return self._df

    def describe(self) -> str:
        rows, cols = self._df.shape
        return f"In-memory DataFrame ({rows} rows × {cols} columns)"

    @property
    def cache_key(self) -> str:
        return f"mem:{self._name}"
```

**NOT in scope**: Changes to `DatasetManager.add_dataframe()` (that happens in TASK-219).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/sources/memory.py` | CREATE | InMemorySource implementation |
| `parrot/tools/dataset_manager/sources/__init__.py` | MODIFY | Export InMemorySource |

---

## Acceptance Criteria

- [ ] `InMemorySource` at `parrot/tools/dataset_manager/sources/memory.py`
- [ ] `prefetch_schema()` returns `{col: dtype_str}` without any I/O
- [ ] `fetch()` returns the wrapped DataFrame unchanged
- [ ] `cache_key` format: `mem:{name}`
- [ ] `from parrot.tools.dataset_manager.sources import InMemorySource` works
- [ ] Unit tests pass: `pytest tests/tools/test_datasources.py::TestInMemorySource -v`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-datasources.spec.md` for full context
2. **Check dependencies** — verify TASK-213 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-214-inmemory-source.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-07
**Notes**: Created `parrot/tools/dataset_manager/sources/memory.py` with `InMemorySource` implementing all required methods. Exported from sources `__init__.py`. Created `tests/tools/test_datasources.py::TestInMemorySource` with 9 tests — all passing.

**Deviations from spec**: None.
