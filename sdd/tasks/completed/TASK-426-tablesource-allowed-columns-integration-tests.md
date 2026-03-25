# TASK-426: Integration tests for allowed_columns (guide + metadata)

**Feature**: datasetmanager-tablesource-column-list
**Spec**: `sdd/specs/datasetmanager-tablesource-column-list.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-422, TASK-423, TASK-424, TASK-425
**Assigned-to**: unassigned

---

## Context

With all implementation and unit tests complete, this task adds integration-level tests verifying that the `allowed_columns` restriction flows through the full DatasetManager pipeline: registration → guide generation → metadata retrieval. These tests verify that the LLM-facing interfaces (guide text, metadata dict) only expose allowed columns.

Implements Spec Module 4 (integration tests).

---

## Scope

- Add integration tests to the test file created in TASK-425 (or a separate file if cleaner).
- Test the full flow: `add_table_source(allowed_columns=[...])` → `get_guide()` → verify only allowed columns appear.
- Test `get_metadata(name)` → verify `columns` list contains only allowed columns.
- Tests mock the database layer (`_run_query`) but exercise the real DatasetManager + TableSource + DatasetEntry chain.

**NOT in scope**: Tests with real database connections (would require CI infrastructure).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/tools/test_tablesource_allowed_columns.py` | MODIFY | Add integration test class |

---

## Implementation Notes

### Test approach

Mock `TableSource._run_query` to return controlled DataFrames, but let the real `DatasetManager.add_table_source()` → `TableSource.prefetch_schema()` → `DatasetEntry` → `get_guide()` pipeline run.

```python
class TestIntegrationGuideAndMetadata:
    async def test_guide_shows_only_allowed_columns(self):
        """Full registration + guide: only allowed columns appear."""
        dm = DatasetManager()
        # Mock _run_query for schema prefetch
        with patch.object(TableSource, '_run_query', new_callable=AsyncMock) as mock_query:
            # Return schema with extra columns
            schema_df = pd.DataFrame({
                'column_name': ['id', 'name', 'department', 'salary', 'ssn'],
                'data_type': ['integer', 'varchar', 'varchar', 'numeric', 'varchar'],
            })
            count_df = pd.DataFrame({'cnt': [100]})
            mock_query.side_effect = [schema_df, count_df]

            await dm.add_table_source(
                "employees", "public.employees", "pg",
                allowed_columns=["id", "name", "department"],
            )

        guide = dm.get_guide()
        assert "id" in guide
        assert "name" in guide
        assert "department" in guide
        assert "salary" not in guide
        assert "ssn" not in guide

    async def test_metadata_shows_only_allowed_columns(self):
        """get_metadata returns only allowed columns."""
        # Similar setup, verify metadata['columns'] is filtered
        ...
```

### Key Constraints
- Must not require a running database
- Must exercise real DatasetManager/DatasetEntry code paths (not mocked)
- Only mock the lowest-level database call (`_run_query`)

### References in Codebase
- `DatasetManager.get_guide()` — generates the LLM system prompt guide
- `DatasetManager.get_metadata()` — returns metadata dict with `columns` key
- `DatasetEntry.columns` property — reads from `source._schema`

---

## Acceptance Criteria

- [ ] Integration test for guide generation: only allowed columns appear
- [ ] Integration test for metadata: `columns` list filtered
- [ ] Tests pass without real database
- [ ] Tests exercise real DatasetManager → TableSource → DatasetEntry pipeline

---

## Test Specification

```python
class TestIntegrationGuideAndMetadata:
    async def test_guide_shows_only_allowed_columns(self): ...
    async def test_metadata_shows_only_allowed_columns(self): ...
    async def test_guide_unrestricted_shows_all_columns(self): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-tablesource-column-list.spec.md`
2. **Check dependencies** — TASK-422 through TASK-425 must be completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Read** existing test file from TASK-425 and the DatasetManager code
5. **Add** integration tests
6. **Run all tests**: `source .venv/bin/activate && pytest packages/ai-parrot/tests/tools/test_tablesource_allowed_columns.py -v`
7. **Move this file** to `sdd/tasks/completed/TASK-426-tablesource-allowed-columns-integration-tests.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
