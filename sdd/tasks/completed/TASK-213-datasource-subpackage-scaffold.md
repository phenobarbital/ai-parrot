# TASK-213: DatasetManager Subpackage Scaffold + DataSource ABC

**Feature**: DatasetManager Lazy Data Sources (FEAT-030)
**Spec**: `sdd/specs/datasetmanager-datasources.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: —
**Assigned-to**: claude-sonnet-4-6

---

## Context

> Foundation task. Moves `parrot/tools/dataset_manager.py` into a subpackage and defines the
> `DataSource` ABC that all concrete source types will implement. No logic changes yet — this
> is a pure structural refactor + interface definition.

---

## Scope

- Create `parrot/tools/dataset_manager/` directory with `__init__.py` and `sources/` subdirectory.
- Move `parrot/tools/dataset_manager.py` to `parrot/tools/dataset_manager/tool.py` (keep existing logic intact for now).
- Create `parrot/tools/dataset_manager/__init__.py` re-exporting `DatasetManager`, `DatasetEntry`, `DatasetInfo` so existing imports are unchanged.
- Create `parrot/tools/dataset_manager/sources/__init__.py` (empty, populated by later tasks).
- Define `DataSource` ABC at `parrot/tools/dataset_manager/sources/base.py`:

```python
from abc import ABC, abstractmethod
from typing import Dict
import pandas as pd


class DataSource(ABC):
    """Abstract base for all data sources.

    A DataSource is a reference to data. It knows how to prefetch schema,
    fetch actual data, describe itself to the LLM, and provide a stable
    cache key for Redis.
    """

    async def prefetch_schema(self) -> Dict[str, str]:
        """Return column→type mapping without fetching rows.

        Subclasses override when cheap schema discovery is available.
        Default returns empty dict (schema unknown until fetch).
        """
        return {}

    @abstractmethod
    async def fetch(self, **params) -> pd.DataFrame:
        """Execute and return a DataFrame. Called only on demand."""
        ...

    @abstractmethod
    def describe(self) -> str:
        """Human-readable description for the LLM guide."""
        ...

    @property
    @abstractmethod
    def cache_key(self) -> str:
        """Stable, unique string for Redis keying.

        Shared across agents for the same logical source.
        Format is source-type-specific (e.g. 'qs:{slug}', 'table:{driver}:{table}').
        """
        ...
```

- Verify all existing imports still work after the move (no logic changes).

**NOT in scope**: Any source implementations, changes to DatasetEntry/DatasetInfo, or caching logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/__init__.py` | CREATE | Re-export DatasetManager, DatasetEntry, DatasetInfo |
| `parrot/tools/dataset_manager/tool.py` | CREATE | Move of existing dataset_manager.py (no logic changes) |
| `parrot/tools/dataset_manager/sources/__init__.py` | CREATE | Empty; populated by later tasks |
| `parrot/tools/dataset_manager/sources/base.py` | CREATE | DataSource ABC |
| `parrot/tools/dataset_manager.py` | DELETE | Replaced by subpackage |

---

## Implementation Notes

- The move must be transparent: `from parrot.tools.dataset_manager import DatasetManager` must continue to work.
- Check `parrot/tools/__init__.py` for any direct import of `dataset_manager.py` and update accordingly.
- Do NOT change any logic inside the moved file — only structural changes.

### References in Codebase
- `parrot/tools/dataset_manager.py` — file to move
- `parrot/tools/__init__.py` — may import DatasetManager; check and update
- `parrot/bots/pandas_agent.py` — imports DatasetManager; verify unchanged after move

---

## Acceptance Criteria

- [ ] `parrot/tools/dataset_manager/` subpackage exists with `__init__.py`, `tool.py`, `sources/`
- [ ] `DataSource` ABC defined at `parrot/tools/dataset_manager/sources/base.py` with `prefetch_schema`, `fetch`, `describe`, `cache_key`
- [ ] `from parrot.tools.dataset_manager import DatasetManager` works unchanged
- [ ] `from parrot.tools.dataset_manager import DatasetEntry, DatasetInfo` works unchanged
- [ ] Original `parrot/tools/dataset_manager.py` file removed
- [ ] `pytest tests/tools/test_dataset_manager.py -v` passes (no regressions)

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-datasources.spec.md` for full context
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
3. **Implement** following the scope and notes above
4. **Verify** all acceptance criteria are met
5. **Move this file** to `sdd/tasks/completed/TASK-213-datasource-subpackage-scaffold.md`
6. **Update index** → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-07
**Notes**:
- Moved `parrot/tools/dataset_manager.py` → `parrot/tools/dataset_manager/tool.py`; fixed two relative imports (`from .toolkit` → `from ..toolkit`, `from ..conf` → `from ...conf`)
- Created `parrot/tools/dataset_manager/__init__.py` re-exporting DatasetManager, DatasetEntry, DatasetInfo
- Created `parrot/tools/dataset_manager/sources/__init__.py` exporting DataSource
- Created `parrot/tools/dataset_manager/sources/base.py` with full DataSource ABC (prefetch_schema, fetch, describe, cache_key)
- Deleted old `parrot/tools/dataset_manager.py`
- All existing imports verified: parrot.tools, parrot.bots.data, parrot.handlers.datasets, parrot.tools.pythonpandas all resolve correctly
- DatasetManager functional smoke test passed; DataSource ABC contract verified

**Deviations from spec**: None
