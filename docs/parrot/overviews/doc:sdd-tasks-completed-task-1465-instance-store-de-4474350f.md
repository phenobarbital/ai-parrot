---
type: Wiki Overview
title: 'TASK-1465: Instance Store + `define_filters()` Validation'
id: doc:sdd-tasks-completed-task-1465-instance-store-define-filters-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2**. Adds the instance-scoped filter store (`self._filter_defs`)
relates_to:
- concept: mod:parrot.tools.dataset_manager.filtering
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.spatial.registry
  rel: mentions
---

# TASK-1465: Instance Store + `define_filters()` Validation

**Feature**: FEAT-225 — DatasetManager Common-Field Filtering
**Spec**: `sdd/specs/datasetmanager-filtering.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1464
**Assigned-to**: unassigned

---

## Context

Implements **Module 2**. Adds the instance-scoped filter store (`self._filter_defs`)
and the `define_filters()` entry point that validates definitions against the
datasets registered in *this* `DatasetManager` instance. No global registry
(spec Non-Goals / Option A rejected).

---

## Scope

- Initialize `self._filter_defs: Dict[str, FilterDefinition] = {}` in
  `DatasetManager.__init__` (find the existing init that sets `self._datasets`).
- Implement `DatasetManager.define_filters(self, definitions: List[FilterDefinition]) -> None`:
  - Validate each `FilterDefinition` against registered datasets:
    - At least one registered dataset must contain the column(s) (warn/log if none).
    - `kind="spatial"` requires a registered `DatasetSpatialProfile` for the
      relevant dataset(s) — validate via `validate_profiles_exist` / `get_spatial_profile`.
  - Store by `definition.name` (replace on duplicate name; log at debug).
- Optionally factor pure validation helpers into `filtering/store.py`.
- Unit tests.

**NOT in scope**: applying filters (TASK-1467), compiling SQL/pandas (TASK-1466),
value catalogs (TASK-1468), schema/suggest (TASK-1469), tools/handler (TASK-1470).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | add `_filter_defs` init + `define_filters()` |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/filtering/store.py` | CREATE | (optional) pure validation helpers |
| `packages/ai-parrot/tests/unit/test_define_filters.py` | CREATE | store + validation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.dataset_manager.filtering import FilterDefinition  # created in TASK-1464
from parrot.tools.dataset_manager.spatial.registry import (
    get_spatial_profile,        # spatial/registry.py:54
    validate_profiles_exist,    # spatial/registry.py:79
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                 # line 500
    self._datasets: Dict[str, DatasetEntry]            # line 533
    def _resolve_name(self, name: str) -> str          # (alias resolution; used by get_manifest:4169)
    def get_manifest(self) -> List[Dict[str, Any]]     # line 4139 — pattern: intersect registry w/ self._datasets

class DatasetEntry:                                    # line 123
    _column_types: Dict[str, str]                      # column -> semantic type
    _column_metadata: Dict[str, Dict[str, Any]]
    # NOTE: a DatasetEntry may not be materialized; column presence may need
    #       _column_types (populated on fetch/prefetch) — handle the not-yet-known case.

# packages/ai-parrot/src/parrot/tools/dataset_manager/spatial/registry.py
def get_spatial_profile(dataset_name: str) -> DatasetSpatialProfile     # line 54 (raises ValueError if absent)
def validate_profiles_exist(dataset_names: List[str]) -> None           # line 79 (raises listing missing)
```

### Does NOT Exist
- ~~A global filter registry~~ — definitions are instance-scoped (`self._filter_defs`).
- ~~`DatasetManager.define_filters`~~ — created here.
- ~~A guaranteed column list before materialization~~ — `_column_types` may be empty
  until a dataset is fetched; do not assume columns are always known.

---

## Implementation Notes

### Pattern to Follow
Mirror `get_manifest()` (tool.py:4139) for resolving registered datasets and
intersecting with `self._datasets`. Use descriptive `ValueError` messages like
`validate_profiles_exist` does.

### Key Constraints
- Instance-scoped store only — never write to module-level globals.
- `self.logger` for warnings (e.g. "no registered dataset has column X").
- Replacing a same-named definition is allowed (debug-log it).

---

## Acceptance Criteria

- [ ] `_filter_defs` initialized on every `DatasetManager` instance independently.
- [ ] `define_filters([...])` stores definitions keyed by name.
- [ ] `kind="spatial"` without a registered profile raises `ValueError`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_define_filters.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/dataset_manager/`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_define_filters.py
import pytest
from parrot.tools.dataset_manager.filtering import FilterDefinition


def test_define_filters_stores_on_instance(manager_with_three_datasets):
    dm = manager_with_three_datasets
    dm.define_filters([FilterDefinition(name="region", columns=["region"],
                                        kind="categorical", ops=["eq", "in"])])
    assert "region" in dm._filter_defs


def test_two_managers_do_not_share_defs(manager_with_three_datasets, another_manager):
    manager_with_three_datasets.define_filters(
        [FilterDefinition(name="region", columns=["region"], kind="categorical", ops=["eq"])])
    assert "region" not in another_manager._filter_defs


def test_spatial_kind_requires_profile(manager_without_spatial_profile):
    with pytest.raises(ValueError):
        manager_without_spatial_profile.define_filters(
            [FilterDefinition(name="geo", columns=["lat", "lng"], kind="spatial", ops=["radius"])])
```

---

## Agent Instructions

Standard SDD agent loop. Re-verify line numbers in `tool.py` before editing — the
file is large and shared with FEAT-224; locate `self._datasets` and `__init__`
by symbol, not by absolute line.

---

## Completion Note

Implemented as specified. Added `self._filter_defs: Dict[str, FilterDefinition] = {}`
to `DatasetManager.__init__`. Added `define_filters()` method that validates column
coverage (warns for non-spatial if no dataset exposes the column) and raises
`ValueError` for spatial kind when no dataset has a registered spatial profile.
Created `filtering/store.py` with `columns_present_in_any` and `warn_if_no_coverage`
helpers. 9 unit tests pass. No linting errors.
