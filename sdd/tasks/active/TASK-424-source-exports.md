# TASK-424: Source Exports and __init__.py Updates

**Feature**: datasetmanager-sources
**Spec**: `sdd/specs/datasetmanager-sources.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-420, TASK-421, TASK-422
**Assigned-to**: unassigned

---

## Context

> This task implements Module 5 from the spec: updating `__init__.py` files to export
> the three new source classes so they are importable from the public API.

---

## Scope

- Update `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/__init__.py`:
  - Add imports for `IcebergSource`, `MongoSource`, `DeltaTableSource`
  - Add to `__all__` list
  - Update module docstring
- Update `packages/ai-parrot/src/parrot/tools/dataset_manager/__init__.py`:
  - Add imports for `IcebergSource`, `MongoSource`, `DeltaTableSource`
  - Add to `__all__` list
- Verify imports work correctly

**NOT in scope**: Source implementations, registration methods

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/__init__.py` | MODIFY | Add new source exports |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/__init__.py` | MODIFY | Add new source exports |

---

## Implementation Notes

### Expected Result for `sources/__init__.py`
```python
"""
DataSource implementations for DatasetManager.

Available source types:
- DataSource: Abstract base class (ABC)
- InMemorySource: Wraps an already-loaded pd.DataFrame
- QuerySlugSource: Wraps QuerySource slug (lazy, no schema prefetch by default)
- MultiQuerySlugSource: Wraps multiple QuerySource slugs
- SQLQuerySource: User-provided SQL with {param} interpolation
- TableSource: Table reference with INFORMATION_SCHEMA schema prefetch
- AirtableSource: Airtable base table reference
- SmartsheetSource: Smartsheet sheet reference
- IcebergSource: Apache Iceberg table via asyncdb iceberg driver
- MongoSource: MongoDB/DocumentDB collection (read-only, filter-required)
- DeltaTableSource: Delta Lake table via asyncdb delta driver
"""
from .base import DataSource
from .memory import InMemorySource
from .query_slug import MultiQuerySlugSource, QuerySlugSource
from .sql import SQLQuerySource
from .table import TableSource
from .airtable import AirtableSource
from .smartsheet import SmartsheetSource
from .iceberg import IcebergSource
from .mongo import MongoSource
from .deltatable import DeltaTableSource

__all__ = [
    "DataSource",
    "InMemorySource",
    "MultiQuerySlugSource",
    "QuerySlugSource",
    "SQLQuerySource",
    "TableSource",
    "AirtableSource",
    "SmartsheetSource",
    "IcebergSource",
    "MongoSource",
    "DeltaTableSource",
]
```

### Key Constraints
- Use lazy imports if the asyncdb extras (iceberg, mongo, delta) are optional dependencies
- If import fails due to missing optional deps, log a warning but don't break the package

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/__init__.py` — current exports
- `packages/ai-parrot/src/parrot/tools/dataset_manager/__init__.py` — main package exports

---

## Acceptance Criteria

- [ ] `from parrot.tools.dataset_manager.sources import IcebergSource` works
- [ ] `from parrot.tools.dataset_manager.sources import MongoSource` works
- [ ] `from parrot.tools.dataset_manager.sources import DeltaTableSource` works
- [ ] `from parrot.tools.dataset_manager import IcebergSource` works
- [ ] `from parrot.tools.dataset_manager import MongoSource` works
- [ ] `from parrot.tools.dataset_manager import DeltaTableSource` works
- [ ] All three classes listed in `__all__` in both `__init__.py` files
- [ ] Module docstrings updated

---

## Test Specification

```python
def test_import_iceberg_source():
    from parrot.tools.dataset_manager.sources import IcebergSource
    assert IcebergSource is not None

def test_import_mongo_source():
    from parrot.tools.dataset_manager.sources import MongoSource
    assert MongoSource is not None

def test_import_deltatable_source():
    from parrot.tools.dataset_manager.sources import DeltaTableSource
    assert DeltaTableSource is not None

def test_import_from_main_package():
    from parrot.tools.dataset_manager import IcebergSource, MongoSource, DeltaTableSource
    assert all(cls is not None for cls in [IcebergSource, MongoSource, DeltaTableSource])
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-sources.spec.md` for full context
2. **Check dependencies** — verify TASK-420, TASK-421, TASK-422 are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-424-source-exports.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
