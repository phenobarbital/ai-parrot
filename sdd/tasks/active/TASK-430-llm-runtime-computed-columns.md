# TASK-430: LLM Runtime Computed Columns

**Feature**: composite-datasets
**Spec**: `sdd/specs/composite-datasets.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-428
**Assigned-to**: unassigned

---

## Context

The LLM should be able to add computed columns at runtime (restricted to the function registry) and list available functions. These are new tool methods on DatasetManager.

Implements **Module 4** from the spec (Section 3).

---

## Scope

- Implement `async add_computed_column()` on DatasetManager:
  - Validate function exists in registry
  - Resolve dataset name
  - Validate source columns exist (if dataset loaded or has schema)
  - Create `ComputedColumnDef` and append to entry
  - Apply immediately if dataset loaded
  - Re-categorize types and regenerate guide
  - Return confirmation or error message
- Implement `async list_available_functions()` on DatasetManager:
  - Return sorted list of registered function names
- Write unit tests

**NOT in scope**: Creating new built-in functions (TASK-427), CompositeDataSource (TASK-431)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | Add add_computed_column() and list_available_functions() methods |
| `tests/tools/dataset_manager/test_llm_computed_columns.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

Follow the existing LLM tool method pattern (e.g., `fetch_dataset`, `get_metadata`):
- Async method
- Returns a string message for the LLM
- Validates inputs before acting
- Updates guide after changes

```python
async def add_computed_column(
    self, dataset_name: str, column_name: str, func: str,
    columns: List[str], description: str = "", **kwargs,
) -> str:
    from .computed import get_computed_function, list_computed_functions, ComputedColumnDef
    # Validate, create, apply, return message
```

### Key Constraints
- Function must exist in the registry (return friendly error if not)
- Column validation only when dataset has schema info (don't error if no schema known)
- Computed columns added to existing `entry._computed_columns` list
- Already-defined computed columns are valid source references
- Guide must be regenerated after adding a computed column

### References in Codebase
- Spec Section 2.7 for exact method signatures and behavior
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — existing LLM tool methods

---

## Acceptance Criteria

- [ ] `add_computed_column()` validates function exists
- [ ] `add_computed_column()` validates source columns when schema available
- [ ] `add_computed_column()` applies immediately when dataset loaded
- [ ] `add_computed_column()` regenerates guide
- [ ] `add_computed_column()` returns confirmation string
- [ ] `add_computed_column()` returns friendly error for unknown function/dataset
- [ ] `list_available_functions()` returns sorted list
- [ ] All tests pass: `pytest tests/tools/dataset_manager/test_llm_computed_columns.py -v`

---

## Test Specification

```python
# tests/tools/dataset_manager/test_llm_computed_columns.py
import pytest
import pandas as pd
from parrot.tools.dataset_manager.tool import DatasetManager


@pytest.fixture
def dm():
    dm = DatasetManager(generate_guide=False)
    df = pd.DataFrame({"revenue": [100.0, 200.0], "expenses": [60.0, 80.0]})
    dm.add_dataframe("sales", df)
    return dm


class TestAddComputedColumn:
    @pytest.mark.asyncio
    async def test_add_valid_column(self, dm):
        result = await dm.add_computed_column(
            "sales", "ebitda", "math_operation",
            ["revenue", "expenses"], operation="subtract",
        )
        assert "ebitda" in result
        assert "added" in result.lower()
        assert "ebitda" in dm._datasets["sales"]._df.columns

    @pytest.mark.asyncio
    async def test_unknown_function(self, dm):
        result = await dm.add_computed_column(
            "sales", "x", "nonexistent", ["revenue"],
        )
        assert "Unknown function" in result

    @pytest.mark.asyncio
    async def test_unknown_dataset(self, dm):
        result = await dm.add_computed_column(
            "missing", "x", "math_operation", ["a", "b"],
        )
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_missing_columns(self, dm):
        result = await dm.add_computed_column(
            "sales", "x", "math_operation",
            ["revenue", "nonexistent"], operation="add",
        )
        assert "not found" in result


class TestListAvailableFunctions:
    @pytest.mark.asyncio
    async def test_returns_sorted_list(self, dm):
        fns = await dm.list_available_functions()
        assert isinstance(fns, list)
        assert fns == sorted(fns)
        assert "math_operation" in fns
        assert "concatenate" in fns
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/composite-datasets.spec.md` for full context
2. **Check dependencies** — verify TASK-428 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-430-llm-runtime-computed-columns.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
