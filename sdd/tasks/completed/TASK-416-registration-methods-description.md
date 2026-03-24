# TASK-416: Add description parameter to all registration methods

**Feature**: add-description-datasetmanager
**Spec**: `sdd/specs/add-description-datasetmanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-415
**Assigned-to**: unassigned

---

## Context

With `DatasetEntry` now supporting a first-class `description` field (TASK-415), all registration methods on `DatasetManager` need to accept and forward this parameter. This is the largest task by surface area — 7 methods need updating.

Implements **Module 2** from the spec.

---

## Scope

- Add `description: Optional[str] = None` parameter to all registration methods:
  - `add_dataset()`
  - `add_dataframe()`
  - `add_query()`
  - `add_table_source()`
  - `add_sql_source()`
  - `add_airtable_source()`
  - `add_smartsheet_source()`
- Pass `description` through to `DatasetEntry` constructor in each method
- Ensure the parameter is keyword-only where the method already uses `*` separator

**NOT in scope**: `DatasetEntry` internals (TASK-415), summary generation (TASK-417), guide/metadata changes (TASK-418).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | Add `description` param to all 7 `add_*` methods |

---

## Implementation Notes

### Pattern to Follow
For each registration method, add `description` as a keyword-only parameter and forward it:

```python
async def add_dataset(
    self,
    name: str,
    *,
    description: Optional[str] = None,  # NEW
    query_slug: Optional[str] = None,
    ...
) -> str:
    ...
    entry = DatasetEntry(
        name=name,
        description=description,  # Forward to entry
        source=source,
        metadata=metadata,
        ...
    )
```

### Key Constraints
- Preserve backward compatibility — `description` defaults to `None`
- Do not change the order of existing parameters
- For methods that don't use `*` separator, add `description` after existing positional args but before keyword-only args

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — all `add_*` methods

---

## Acceptance Criteria

- [ ] All 7 registration methods accept `description: Optional[str] = None`
- [ ] Description is forwarded to `DatasetEntry` in each method
- [ ] Existing callers without `description` continue to work
- [ ] No linting errors

---

## Test Specification

```python
import pytest
import pandas as pd
from parrot.tools.dataset_manager.tool import DatasetManager

@pytest.fixture
def dm():
    return DatasetManager()

@pytest.fixture
def sample_df():
    return pd.DataFrame({"a": [1, 2], "b": [3, 4]})

class TestRegistrationDescription:
    def test_add_dataframe_with_description(self, dm, sample_df):
        """add_dataframe passes description to entry."""
        dm.add_dataframe("test", sample_df, description="Test dataset")
        entry = dm.get_dataset_entry("test")
        assert entry.description == "Test dataset"

    def test_add_dataframe_without_description(self, dm, sample_df):
        """add_dataframe without description defaults to empty."""
        dm.add_dataframe("test", sample_df)
        entry = dm.get_dataset_entry("test")
        assert entry.description == ""

    def test_add_query_with_description(self, dm):
        """add_query passes description to entry."""
        dm.add_query("test", "some_slug", description="Query dataset")
        entry = dm.get_dataset_entry("test")
        assert entry.description == "Query dataset"

    def test_add_sql_source_with_description(self, dm):
        """add_sql_source passes description to entry."""
        dm.add_sql_source("test", "SELECT 1", "pg", description="SQL dataset")
        entry = dm.get_dataset_entry("test")
        assert entry.description == "SQL dataset"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/add-description-datasetmanager.spec.md` for full context
2. **Check dependencies** — verify TASK-415 is completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-416-registration-methods-description.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-03-24
**Notes**: Added `description: Optional[str] = None` to all 7 registration methods: `add_dataset`, `add_dataframe`, `add_query`, `add_table_source`, `add_sql_source`, `add_airtable_source`, `add_smartsheet_source`. All methods forward description to `DatasetEntry`. `add_table_source` and `add_sql_source` now use `*` separator for keyword-only params.

**Deviations from spec**: none
