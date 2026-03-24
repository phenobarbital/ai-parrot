# TASK-418: Surface description in get_metadata() and guide generation

**Feature**: add-description-datasetmanager
**Spec**: `sdd/specs/add-description-datasetmanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-415, TASK-417
**Assigned-to**: unassigned

---

## Context

With descriptions stored in `DatasetEntry` (TASK-415) and `get_datasets_summary()` available (TASK-417), this task wires them into the two main output channels: the `get_metadata()` tool response and the `_generate_dataframe_guide()` system prompt injection.

Implements **Module 4** from the spec.

---

## Scope

- **`get_metadata()`**: Ensure the response dict includes `"description"` as a top-level key, populated from `DatasetEntry.description`
- **`_generate_dataframe_guide()`**: Prepend an "## Available Datasets" section at the top of the guide containing the output of `get_datasets_summary()`, before the existing per-dataset detailed info
- Ensure the summary section is only added when there are active datasets with descriptions

**NOT in scope**: Changes to `DatasetEntry` (TASK-415), registration methods (TASK-416), or `get_datasets_summary()` logic (TASK-417).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | Update `get_metadata()` and `_generate_dataframe_guide()` |

---

## Implementation Notes

### get_metadata() changes
```python
async def get_metadata(self, name: str, ...) -> Dict[str, Any]:
    entry = self.get_dataset_entry(name)
    ...
    result = {
        "name": name,
        "description": entry.description,  # NEW — top-level
        ...
    }
    return result
```

### _generate_dataframe_guide() changes
```python
def _generate_dataframe_guide(self) -> str:
    parts = []

    # NEW: Prepend dataset summary
    summary = self._get_datasets_summary_sync()  # or build inline
    if summary:
        parts.append("## Available Datasets\n")
        parts.append(summary)
        parts.append("\n---\n")

    # Existing guide content follows...
    ...
```

Note: `_generate_dataframe_guide()` is synchronous. Since `get_datasets_summary()` is async, either: (a) build the bullet-list inline (iterate `self._datasets` directly), or (b) create a sync helper that the async tool also calls.

### Key Constraints
- `_generate_dataframe_guide()` is called during initialization — it must remain synchronous
- Don't duplicate the iteration logic — extract a shared sync helper if needed
- Keep the summary section compact to avoid bloating the system prompt

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — `get_metadata()` and `_generate_dataframe_guide()`
- `packages/ai-parrot/src/parrot/bots/data.py` — PandasAgent consumes `$df_info`

---

## Acceptance Criteria

- [ ] `get_metadata()` returns `description` as a top-level key
- [ ] `_generate_dataframe_guide()` prepends dataset summary section
- [ ] Summary section only appears when active datasets exist
- [ ] Guide remains synchronous — no async calls
- [ ] No linting errors

---

## Test Specification

```python
import pytest
import pandas as pd
from parrot.tools.dataset_manager.tool import DatasetManager

@pytest.fixture
def dm_with_described_datasets():
    dm = DatasetManager()
    df = pd.DataFrame({"region": ["East"], "sales": [100]})
    dm.add_dataframe("sales", df, description="Q4 sales by region")
    return dm

class TestMetadataDescription:
    @pytest.mark.asyncio
    async def test_get_metadata_has_description(self, dm_with_described_datasets):
        """get_metadata() includes description at top level."""
        meta = await dm_with_described_datasets.get_metadata("sales")
        assert meta["description"] == "Q4 sales by region"

    @pytest.mark.asyncio
    async def test_get_metadata_empty_description(self):
        """get_metadata() returns empty description when none set."""
        dm = DatasetManager()
        dm.add_dataframe("test", pd.DataFrame({"a": [1]}))
        meta = await dm.get_metadata("test")
        assert meta["description"] == ""

class TestGuideDescription:
    def test_guide_includes_summary(self, dm_with_described_datasets):
        """Guide contains Available Datasets section."""
        guide = dm_with_described_datasets.get_guide()
        assert "Available Datasets" in guide
        assert "**sales**: Q4 sales by region" in guide

    def test_guide_no_summary_when_empty(self):
        """Guide omits summary section when no datasets."""
        dm = DatasetManager()
        guide = dm.get_guide()
        assert "Available Datasets" not in guide
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/add-description-datasetmanager.spec.md` for full context
2. **Check dependencies** — verify TASK-415 and TASK-417 are completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-418-surface-description-metadata-guide.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-03-24
**Notes**: `get_metadata()` now returns `entry.description` (not `entry.metadata.get("description", "")`). `_generate_dataframe_guide()` prepends "## Available Datasets" section using `_build_datasets_summary_sync()`. Section only appears when active datasets exist. Guide remains fully synchronous.

**Deviations from spec**: none
