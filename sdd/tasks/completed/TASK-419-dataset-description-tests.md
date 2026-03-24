# TASK-419: Unit tests for dataset description feature

**Feature**: add-description-datasetmanager
**Spec**: `sdd/specs/add-description-datasetmanager.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-415, TASK-416, TASK-417, TASK-418
**Assigned-to**: unassigned

---

## Context

Final task for FEAT-059. Consolidates all test cases from the spec into a dedicated test file. Individual tasks may have added inline tests; this task ensures comprehensive coverage including edge cases and integration scenarios.

Implements **Module 5** from the spec.

---

## Scope

- Create `packages/ai-parrot/tests/tools/test_dataset_description.py`
- Cover all test cases from Section 4 of the spec:
  - Description propagation through all registration methods
  - Priority resolution (explicit > metadata > empty)
  - 300-character truncation
  - `get_datasets_summary()` format and filtering
  - `get_metadata()` description field
  - Guide generation with summary section
  - Backward compatibility (no description param)
- Run full test suite to ensure no regressions

**NOT in scope**: Implementation changes — tests only.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/tools/test_dataset_description.py` | CREATE | Comprehensive test file |

---

## Implementation Notes

### Key Constraints
- Use `pytest` and `pytest-asyncio`
- Use fixtures for `DatasetManager` and sample DataFrames
- Mock external dependencies (database connections) where needed for `add_table_source` tests
- All async tests must be marked with `@pytest.mark.asyncio`

### References in Codebase
- `packages/ai-parrot/tests/tools/` — existing test patterns
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — classes under test

---

## Acceptance Criteria

- [ ] Test file created at `packages/ai-parrot/tests/tools/test_dataset_description.py`
- [ ] All 10 test cases from spec Section 4 are covered
- [ ] Tests pass: `pytest packages/ai-parrot/tests/tools/test_dataset_description.py -v`
- [ ] No regressions in existing tests

---

## Test Specification

```python
import pytest
import pandas as pd
from parrot.tools.dataset_manager.tool import DatasetManager, DatasetEntry

@pytest.fixture
def dm():
    return DatasetManager()

@pytest.fixture
def sample_df():
    return pd.DataFrame({"region": ["East", "West", "North"], "sales": [100, 200, 150]})

class TestDatasetEntryDescription:
    def test_explicit_description(self):
        entry = DatasetEntry(name="test", description="My dataset")
        assert entry.description == "My dataset"

    def test_metadata_fallback(self):
        entry = DatasetEntry(name="test", metadata={"description": "From metadata"})
        assert entry.description == "From metadata"

    def test_explicit_overrides_metadata(self):
        entry = DatasetEntry(
            name="test", description="Explicit",
            metadata={"description": "From metadata"},
        )
        assert entry.description == "Explicit"

    def test_no_description_defaults_empty(self):
        entry = DatasetEntry(name="test")
        assert entry.description == ""

    def test_truncation_at_300(self):
        entry = DatasetEntry(name="test", description="x" * 500)
        assert len(entry.description) == 300

class TestRegistrationMethods:
    def test_add_dataframe_with_description(self, dm, sample_df):
        dm.add_dataframe("sales", sample_df, description="Sales data")
        assert dm.get_dataset_entry("sales").description == "Sales data"

    def test_add_dataframe_without_description(self, dm, sample_df):
        dm.add_dataframe("sales", sample_df)
        assert dm.get_dataset_entry("sales").description == ""

    def test_add_query_with_description(self, dm):
        dm.add_query("test", "slug", description="Query data")
        assert dm.get_dataset_entry("test").description == "Query data"

    def test_add_sql_source_with_description(self, dm):
        dm.add_sql_source("test", "SELECT 1", "pg", description="SQL data")
        assert dm.get_dataset_entry("test").description == "SQL data"

class TestGetDatasetsSummary:
    @pytest.mark.asyncio
    async def test_summary_format(self, dm, sample_df):
        dm.add_dataframe("sales", sample_df, description="Q4 sales")
        dm.add_dataframe("logs", sample_df)
        summary = await dm.get_datasets_summary()
        assert "- **sales**: Q4 sales" in summary
        assert "- **logs**: (no description)" in summary

    @pytest.mark.asyncio
    async def test_excludes_inactive(self, dm, sample_df):
        dm.add_dataframe("sales", sample_df, description="Q4 sales")
        dm.deactivate("sales")
        summary = await dm.get_datasets_summary()
        assert "sales" not in summary

    @pytest.mark.asyncio
    async def test_empty_when_no_datasets(self, dm):
        summary = await dm.get_datasets_summary()
        assert summary == ""

class TestMetadataAndGuide:
    @pytest.mark.asyncio
    async def test_get_metadata_includes_description(self, dm, sample_df):
        dm.add_dataframe("sales", sample_df, description="Q4 sales")
        meta = await dm.get_metadata("sales")
        assert meta["description"] == "Q4 sales"

    def test_guide_includes_summary(self, dm, sample_df):
        dm.add_dataframe("sales", sample_df, description="Q4 sales")
        guide = dm.get_guide()
        assert "Available Datasets" in guide
        assert "**sales**: Q4 sales" in guide

    def test_backward_compat_no_description(self, dm, sample_df):
        dm.add_dataframe("test", sample_df)
        entry = dm.get_dataset_entry("test")
        assert entry.description == ""
        assert entry is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/add-description-datasetmanager.spec.md` for full context
2. **Check dependencies** — verify TASK-415 through TASK-418 are completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Run tests**: `pytest packages/ai-parrot/tests/tools/test_dataset_description.py -v`
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-419-dataset-description-tests.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-03-24
**Notes**: Created `packages/ai-parrot/tests/tools/test_dataset_description.py` with 28 test cases covering all spec acceptance criteria. All 28 tests pass. Tests use `df=pd.DataFrame(...)` as DatasetEntry source (spec test stubs omitted this required kwarg). Also created `tests/__init__.py` and `tests/tools/__init__.py`.

**Deviations from spec**: Test fixtures use `df=pd.DataFrame(...)` since `DatasetEntry` requires at least one data source. The spec's inline test stubs omitted this required argument.
