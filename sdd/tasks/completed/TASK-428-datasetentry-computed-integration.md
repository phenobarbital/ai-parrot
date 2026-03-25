# TASK-428: DatasetEntry Computed Column Integration

**Feature**: composite-datasets
**Spec**: `sdd/specs/composite-datasets.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-427
**Assigned-to**: unassigned

---

## Context

Integrates computed columns into `DatasetEntry` so they are applied post-materialization and appear as regular columns in all metadata surfaces.

Implements **Module 2** from the spec (Section 3).

---

## Scope

- Add `computed_columns: Optional[List[ComputedColumnDef]]` parameter to `DatasetEntry.__init__`
- Store as `self._computed_columns: List[ComputedColumnDef]`
- If `df` is provided directly AND computed columns exist, apply them in `__init__`
- Implement `_apply_computed_columns()` method:
  - Iterate computed columns in list order
  - Look up function via `get_computed_function(col_def.func)`
  - Log warning and skip if function unknown
  - Log error and continue if function raises
  - Apply: `self._df = fn(self._df, col_def.name, col_def.columns, **col_def.kwargs)`
- Modify `materialize()`:
  - Apply computed columns AFTER fetch, BEFORE `categorize_columns()`
- Modify `columns` property:
  - When `_df` is None, append computed column names to schema-based columns
- Modify `_column_metadata` property:
  - Inject `description` from `ComputedColumnDef` for computed columns
- Write unit tests

**NOT in scope**: Changes to add_* methods (TASK-429), LLM tools (TASK-430), CompositeDataSource (TASK-431)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | DatasetEntry class changes |
| `tests/tools/dataset_manager/test_computed_integration.py` | CREATE | Unit tests for DatasetEntry computed column flow |

---

## Implementation Notes

### Pattern to Follow

```python
# In DatasetEntry.__init__, add parameter and storage:
def __init__(self, ..., computed_columns: Optional[List[ComputedColumnDef]] = None):
    ...
    self._computed_columns: List[ComputedColumnDef] = computed_columns or []
    # Apply to existing df if provided
    if df is not None and self._computed_columns:
        self._apply_computed_columns()

# In materialize(), after fetch and before categorize:
async def materialize(self, force=False, **params):
    if self._df is None or force:
        self._df = await self.source.fetch(**params)
        if self._df is not None and self._computed_columns:
            self._apply_computed_columns()
        if self.auto_detect_types and self._df is not None:
            self._column_types = DatasetManager.categorize_columns(self._df)
    return self._df
```

### Key Constraints
- Computed columns must be applied BEFORE `categorize_columns()` so they get proper type classification
- Failure in one computed column must NOT abort the others — log and continue
- The import of `computed.py` should use relative import: `from .computed import get_computed_function, list_computed_functions`
- Ordering matters: if column B depends on computed column A, A must come first in the list

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` lines 88–349 — DatasetEntry class
- Spec Sections 2.5 and 2.8 for exact integration points

---

## Acceptance Criteria

- [ ] `DatasetEntry` accepts `computed_columns` parameter (optional, default None)
- [ ] Computed columns applied on `__init__` when `df` is provided
- [ ] Computed columns applied in `materialize()` post-fetch, pre-categorization
- [ ] `columns` property includes computed column names in prefetch state
- [ ] `_column_metadata` injects computed column descriptions
- [ ] Failures logged but don't abort (resilience)
- [ ] Column ordering respected (A before B if B depends on A)
- [ ] All tests pass: `pytest tests/tools/dataset_manager/test_computed_integration.py -v`
- [ ] No breaking changes to existing DatasetEntry constructor

---

## Test Specification

```python
# tests/tools/dataset_manager/test_computed_integration.py
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock
from parrot.tools.dataset_manager.tool import DatasetEntry
from parrot.tools.dataset_manager.computed import ComputedColumnDef


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "revenue": [100.0, 200.0],
        "expenses": [60.0, 80.0],
        "first": ["John", "Jane"],
        "last": ["Doe", "Smith"],
    })


@pytest.fixture
def computed_cols():
    return [
        ComputedColumnDef(
            name="ebitda", func="math_operation",
            columns=["revenue", "expenses"],
            kwargs={"operation": "subtract"},
            description="Earnings metric",
        ),
        ComputedColumnDef(
            name="full_name", func="concatenate",
            columns=["first", "last"],
            kwargs={"sep": " "},
            description="Display name",
        ),
    ]


class TestDatasetEntryComputed:
    def test_init_with_df_applies_computed(self, sample_df, computed_cols):
        """Computed columns applied immediately when df provided."""
        entry = DatasetEntry(
            name="test", df=sample_df, computed_columns=computed_cols
        )
        assert "ebitda" in entry._df.columns
        assert "full_name" in entry._df.columns

    def test_init_without_computed_unchanged(self, sample_df):
        """Existing behavior preserved when no computed columns."""
        entry = DatasetEntry(name="test", df=sample_df)
        assert entry._computed_columns == []

    @pytest.mark.asyncio
    async def test_materialize_applies_computed(self, computed_cols):
        """Computed columns applied after materialize fetch."""
        source = MagicMock()
        source.fetch = AsyncMock(return_value=pd.DataFrame({
            "revenue": [100.0], "expenses": [60.0],
            "first": ["John"], "last": ["Doe"],
        }))
        source.has_builtin_cache = False
        entry = DatasetEntry(
            name="test", source=source, computed_columns=computed_cols,
        )
        df = await entry.materialize()
        assert "ebitda" in df.columns
        assert df["ebitda"].iloc[0] == 40.0

    def test_columns_includes_computed_prefetch(self, computed_cols):
        """columns property includes computed names even before load."""
        source = MagicMock()
        source._schema = {"revenue": "float", "expenses": "float"}
        entry = DatasetEntry(
            name="test", source=source, computed_columns=computed_cols,
        )
        cols = entry.columns
        assert "ebitda" in cols
        assert "full_name" in cols

    def test_failure_resilience(self, sample_df):
        """One failing computed column doesn't abort others."""
        cols = [
            ComputedColumnDef(
                name="bad", func="nonexistent_func", columns=["revenue"],
            ),
            ComputedColumnDef(
                name="ebitda", func="math_operation",
                columns=["revenue", "expenses"],
                kwargs={"operation": "subtract"},
            ),
        ]
        entry = DatasetEntry(name="test", df=sample_df, computed_columns=cols)
        assert "ebitda" in entry._df.columns
        assert "bad" not in entry._df.columns

    def test_column_ordering(self):
        """Computed column B can depend on computed column A if A is listed first."""
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        cols = [
            ComputedColumnDef(
                name="c", func="math_operation",
                columns=["a", "b"], kwargs={"operation": "add"},
            ),
            ComputedColumnDef(
                name="d", func="math_operation",
                columns=["c", "a"], kwargs={"operation": "subtract"},
            ),
        ]
        entry = DatasetEntry(name="test", df=df, computed_columns=cols)
        assert list(entry._df["c"]) == [4, 6]
        assert list(entry._df["d"]) == [3, 4]  # c - a
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/composite-datasets.spec.md` for full context
2. **Check dependencies** — verify TASK-427 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-428-datasetentry-computed-integration.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
