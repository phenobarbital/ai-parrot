# TASK-432: DatasetManager.add_composite_dataset

**Feature**: composite-datasets
**Spec**: `sdd/specs/composite-datasets.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-431, TASK-428
**Assigned-to**: unassigned

---

## Context

Adds the `add_composite_dataset()` registration method to DatasetManager, creating a `CompositeDataSource` and wrapping it in a `DatasetEntry` with optional computed columns.

Implements **Module 6** from the spec (Section 3).

---

## Scope

- Implement `add_composite_dataset()` on DatasetManager:
  - Accept `name`, `joins` (list of dicts), `description`, `computed_columns`, `is_active`, `metadata`
  - Parse joins dicts into `JoinSpec` models
  - Validate all component datasets exist in `_datasets`
  - Create `CompositeDataSource` with back-reference to self
  - Create `DatasetEntry` with source and optional computed_columns
  - Register in `_datasets`
  - Regenerate guide if enabled
  - Return confirmation message with join description
- Write unit tests

**NOT in scope**: DatasetInfo/guide integration (TASK-433), fetch_dataset routing (TASK-433)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | Add add_composite_dataset() method |
| `tests/tools/dataset_manager/test_add_composite.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

Follow existing `add_*` method pattern:
```python
def add_composite_dataset(
    self, name: str, joins: List[Dict[str, Any]], *,
    description: str = "", computed_columns=None,
    is_active: bool = True, metadata=None,
) -> str:
    from .sources.composite import JoinSpec, CompositeDataSource
    join_specs = [JoinSpec(**j) for j in joins]
    # validate components, create source, create entry, register
```

### Key Constraints
- All component datasets must already be registered before creating the composite
- Validation error message must list missing and available datasets
- The method is synchronous (no async needed — no I/O at registration time)
- Return a descriptive confirmation message for the LLM

### References in Codebase
- Spec Section 3.4 for exact method signature and behavior
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — existing add_* methods

---

## Acceptance Criteria

- [ ] `add_composite_dataset()` creates and registers composite dataset
- [ ] Component existence validation raises ValueError for missing datasets
- [ ] JoinSpec models parsed correctly from dicts
- [ ] `computed_columns` passed through to DatasetEntry
- [ ] Guide regenerated after registration
- [ ] Returns descriptive confirmation message
- [ ] All tests pass: `pytest tests/tools/dataset_manager/test_add_composite.py -v`

---

## Test Specification

```python
# tests/tools/dataset_manager/test_add_composite.py
import pytest
import pandas as pd
from parrot.tools.dataset_manager.tool import DatasetManager
from parrot.tools.dataset_manager.computed import ComputedColumnDef


@pytest.fixture
def dm():
    dm = DatasetManager(generate_guide=False)
    dm.add_dataframe("sales", pd.DataFrame({
        "id": [1, 2], "revenue": [100, 200], "expenses": [60, 80],
    }))
    dm.add_dataframe("regions", pd.DataFrame({
        "id": [1, 2], "region": ["East", "West"],
    }))
    return dm


class TestAddCompositeDataset:
    def test_basic_registration(self, dm):
        result = dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
            description="Sales with regions",
        )
        assert "combined" in result
        assert "combined" in dm._datasets

    def test_missing_component_raises(self, dm):
        with pytest.raises(ValueError, match="not registered"):
            dm.add_composite_dataset(
                "bad",
                joins=[{"left": "sales", "right": "nonexistent", "on": "id"}],
            )

    def test_with_computed_columns(self, dm):
        cols = [ComputedColumnDef(
            name="ebitda", func="math_operation",
            columns=["revenue", "expenses"],
            kwargs={"operation": "subtract"},
        )]
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
            computed_columns=cols,
        )
        entry = dm._datasets["combined"]
        assert len(entry._computed_columns) == 1

    def test_multiple_joins(self, dm):
        dm.add_dataframe("extra", pd.DataFrame({
            "id": [1, 2], "score": [9.5, 8.0],
        }))
        result = dm.add_composite_dataset(
            "full",
            joins=[
                {"left": "sales", "right": "regions", "on": "id"},
                {"left": "regions", "right": "extra", "on": "id"},
            ],
        )
        assert "2 join(s)" in result

    def test_confirmation_message(self, dm):
        result = dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id", "how": "left"}],
        )
        assert "LEFT JOIN" in result
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/composite-datasets.spec.md` for full context
2. **Check dependencies** — verify TASK-431 and TASK-428 are in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-432-add-composite-dataset.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
