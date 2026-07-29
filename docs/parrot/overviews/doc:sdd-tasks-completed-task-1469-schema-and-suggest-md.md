---
type: Wiki Overview
title: 'TASK-1469: `get_filter_schema()` + `suggest_filters()` (opt-in auto-discovery)'
id: doc:sdd-tasks-completed-task-1469-schema-and-suggest-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 6**. `get_filter_schema()` serializes the catalog for
  the
relates_to:
- concept: mod:parrot.tools.dataset_manager.filtering
  rel: mentions
---

# TASK-1469: `get_filter_schema()` + `suggest_filters()` (opt-in auto-discovery)

**Feature**: FEAT-225 — DatasetManager Common-Field Filtering
**Spec**: `sdd/specs/datasetmanager-filtering.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1464, TASK-1465
**Assigned-to**: unassigned

---

## Context

Implements **Module 6**. `get_filter_schema()` serializes the catalog for the
frontend (which controls to render, and which datasets each filter applies to).
`suggest_filters()` is the **opt-in** auto-discovery layer (brainstorm Option C):
it proposes `FilterDefinition`s from existing column introspection — no side effects.

---

## Scope

- Implement `get_filter_schema(self) -> List[Dict[str, Any]]`:
  - One entry per stored `FilterDefinition`: `name`, `kind`, `ops`, `label`,
    `required`, and `datasets` = the registered datasets that have the column(s).
- Implement `suggest_filters(self) -> List[FilterDefinition]`:
  - Use `categorize_columns()` / `DatasetEntry._column_types` to find columns
    present in ≥N datasets and propose definitions:
    - `categorical`/`categorical_text` → `ops=["eq","ne","in"]`
    - `integer`/`float`/`datetime` → `ops=["range"]`, kind `numeric`/`temporal`
    - declared lat/lng pair (or registered spatial profile) → `kind="spatial", ops=["radius"]`
  - Return proposals only — do NOT mutate `self._filter_defs`.
- Unit tests for both methods.

**NOT in scope**: persisting suggestions (caller decides), value catalogs
(TASK-1468), apply (TASK-1467), tools/handler (TASK-1470).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | add `get_filter_schema()` + `suggest_filters()` |
| `packages/ai-parrot/tests/unit/test_filter_schema_suggest.py` | CREATE | schema applicability + suggestion inference |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.dataset_manager.filtering import FilterDefinition  # TASK-1464
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                              # line 500
    self._datasets: Dict[str, DatasetEntry]                        # line 533
    self._filter_defs: Dict[str, FilterDefinition]                 # TASK-1465
    @staticmethod
    def categorize_columns(df: pd.DataFrame) -> Dict[str, str]:    # line 633
        # -> boolean|integer|float|datetime|categorical|categorical_text|text
    def get_manifest(self) -> List[Dict[str, Any]]:                # line 4139 (applicability pattern)

class DatasetEntry:                                                # line 123
    _column_types: Dict[str, str]   # semantic types per column
    _column_metadata: Dict[str, Dict[str, Any]]

# spatial profiles for spatial suggestions:
#   SPATIAL_PROFILE_REGISTRY (spatial/registry.py:29), get_manifest() intersects with self._datasets
```

### Does NOT Exist
- ~~`DatasetManager.get_filter_schema` / `suggest_filters`~~ — created here.
- ~~A column→datasets index~~ — derive on the fly from `_column_types` / df columns.
- ~~An auto-apply mechanism~~ — `suggest_filters` returns proposals only (opt-in).

---

## Implementation Notes

### Pattern to Follow
- Reuse the `get_manifest()` approach (tool.py:4139) to compute which registered
  datasets have a given column.
- Map `categorize_columns` semantic types → `FilterKind` + default `ops`.

### Key Constraints
- `suggest_filters()` has **no side effects** (does not store definitions).
- The "present in ≥N datasets" threshold should be a parameter with a sane default; log choices.
- Respect PBAC: do not surface policy-forbidden columns in schema/suggestions.

---

## Acceptance Criteria

- [ ] `get_filter_schema()` lists each defined filter with its applicable datasets.
- [ ] `suggest_filters()` proposes categorical/numeric/spatial candidates from introspection.
- [ ] `suggest_filters()` does not mutate `_filter_defs`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_filter_schema_suggest.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_filter_schema_suggest.py
import pytest
from parrot.tools.dataset_manager.filtering import FilterDefinition


def test_schema_lists_applicable_datasets(manager_with_three_datasets):
    dm = manager_with_three_datasets
    dm.define_filters([FilterDefinition(name="region", columns=["region"],
                                        kind="categorical", ops=["in"])])
    schema = dm.get_filter_schema()
    entry = next(e for e in schema if e["name"] == "region")
    assert "weather" not in entry["datasets"]  # weather lacks region


def test_suggest_filters_no_side_effects(manager_with_three_datasets):
    dm = manager_with_three_datasets
    before = dict(dm._filter_defs)
    proposals = dm.suggest_filters()
    assert dm._filter_defs == before
    assert any(p.columns == ["region"] for p in proposals)
```

---

## Agent Instructions

Standard SDD agent loop. Locate `categorize_columns` and `get_manifest` by symbol
in `tool.py`. Coordinate with FEAT-224.

---

## Completion Note

Implemented as specified. Added `get_filter_schema()` to DatasetManager — returns one
dict per stored FilterDefinition including per-filter applicable dataset list. Added
`suggest_filters(min_datasets=1)` — proposes FilterDefinitions from column introspection
with no side effects: categorical→eq/ne/in/not_in, numeric→range/eq, temporal→range,
spatial profiles→radius. 14 unit tests pass. No linting errors.
