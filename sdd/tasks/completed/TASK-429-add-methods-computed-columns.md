# TASK-429: DatasetManager add_* Methods Computed Columns

**Feature**: composite-datasets
**Spec**: `sdd/specs/composite-datasets.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-428
**Assigned-to**: unassigned

---

## Context

All `add_*` registration methods on DatasetManager must gain an optional `computed_columns` parameter that flows through to `DatasetEntry`.

Implements **Module 3** from the spec (Section 3).

---

## Scope

- Add `computed_columns: Optional[List[ComputedColumnDef]] = None` parameter to:
  - `add_dataframe()`
  - `add_query()`
  - `add_table_source()`
  - `add_sql_source()`
  - `add_airtable_source()`
  - `add_smartsheet_source()`
  - `add_iceberg_source()`
  - `add_mongo_source()`
  - `add_deltatable_source()`
  - `add_dataset()`
- Pass `computed_columns=computed_columns` through to `DatasetEntry(...)` constructor in each method
- Write unit tests verifying the parameter flows through

**NOT in scope**: LLM runtime tools (TASK-430), CompositeDataSource (TASK-431), add_composite_dataset (TASK-432)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | Add computed_columns param to all add_* methods |
| `tests/tools/dataset_manager/test_add_computed_columns.py` | CREATE | Unit tests for parameter passthrough |

---

## Implementation Notes

### Pattern to Follow

The pattern is identical across all methods. Example for `add_dataframe`:

```python
def add_dataframe(
    self,
    name: str,
    df: pd.DataFrame,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    is_active: bool = True,
    computed_columns: Optional[List[ComputedColumnDef]] = None,  # ← NEW
) -> str:
    ...
    entry = DatasetEntry(
        name=name,
        source=source,
        ...,
        computed_columns=computed_columns,  # ← pass through
    )
```

### Key Constraints
- The `computed_columns` parameter must be **optional with default None** to avoid breaking existing callers
- Add the import for `ComputedColumnDef` at the top of the file (use TYPE_CHECKING if preferred for performance)
- Do not change any existing behavior — this is purely additive

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — all add_* methods
- Spec Section 2.6 for the list of methods

---

## Acceptance Criteria

- [ ] All 10 `add_*` methods accept `computed_columns` parameter
- [ ] Parameter defaults to `None` (backward compatible)
- [ ] Parameter is passed through to `DatasetEntry` constructor
- [ ] No breaking changes to existing method signatures
- [ ] All tests pass: `pytest tests/tools/dataset_manager/test_add_computed_columns.py -v`

---

## Test Specification

```python
# tests/tools/dataset_manager/test_add_computed_columns.py
import pytest
import pandas as pd
from parrot.tools.dataset_manager.tool import DatasetManager
from parrot.tools.dataset_manager.computed import ComputedColumnDef


@pytest.fixture
def dm():
    return DatasetManager(generate_guide=False)


@pytest.fixture
def computed_cols():
    return [
        ComputedColumnDef(
            name="total", func="math_operation",
            columns=["a", "b"], kwargs={"operation": "add"},
        ),
    ]


class TestAddMethodsComputedColumns:
    def test_add_dataframe_with_computed(self, dm, computed_cols):
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        dm.add_dataframe("test", df, computed_columns=computed_cols)
        entry = dm._datasets["test"]
        assert len(entry._computed_columns) == 1
        assert "total" in entry._df.columns

    def test_add_dataframe_without_computed(self, dm):
        """Backward compatibility: no computed_columns param."""
        df = pd.DataFrame({"a": [1]})
        dm.add_dataframe("test", df)
        entry = dm._datasets["test"]
        assert entry._computed_columns == []

    def test_add_query_with_computed(self, dm, computed_cols):
        dm.add_query("test", "some_slug", computed_columns=computed_cols)
        entry = dm._datasets["test"]
        assert len(entry._computed_columns) == 1

    def test_add_sql_source_with_computed(self, dm, computed_cols):
        dm.add_sql_source(
            "test", sql="SELECT 1", driver="postgresql",
            computed_columns=computed_cols,
        )
        entry = dm._datasets["test"]
        assert len(entry._computed_columns) == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/composite-datasets.spec.md` for full context
2. **Check dependencies** — verify TASK-428 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-429-add-methods-computed-columns.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
