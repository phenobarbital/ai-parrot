# TASK-417: Implement get_datasets_summary() method

**Feature**: add-description-datasetmanager
**Spec**: `sdd/specs/add-description-datasetmanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-415
**Assigned-to**: unassigned

---

## Context

With descriptions available on `DatasetEntry` (TASK-415), we need a method that generates a concise markdown summary of all active datasets. This summary serves two purposes (per owner decision): (1) LLM-callable tool for on-demand summary, and (2) internal use for system prompt injection during agent initialization.

Implements **Module 3** from the spec.

---

## Scope

- Implement `get_datasets_summary() -> str` on `DatasetManager`
- Iterate all active datasets and produce markdown bullet-list:
  ```
  - **us_census_data_2023**: Common integrated metrics for ethnicity and demographics for US Census 2023
  - **sales_q4**: Quarterly sales data by region and product category
  - **raw_logs**: (no description)
  ```
- Exclude inactive datasets
- Expose as a tool (decorated method) so the LLM can call it directly
- Return empty string if no active datasets

**NOT in scope**: Integration into `_generate_dataframe_guide()` or `get_metadata()` (TASK-418).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | Add `get_datasets_summary()` method |

---

## Implementation Notes

### Pattern to Follow
```python
async def get_datasets_summary(self) -> str:
    """Generate a bullet-list summary of all active datasets with descriptions.

    Returns:
        Markdown-formatted bullet list of active datasets.
        Each entry shows the dataset name and its description.
        Used both as an LLM tool and internally for system prompt injection.
    """
    lines = []
    for name, entry in self._datasets.items():
        if not entry.is_active:
            continue
        desc = entry.description or "(no description)"
        lines.append(f"- **{name}**: {desc}")
    return "\n".join(lines) if lines else ""
```

### Key Constraints
- Must be async (toolkit convention)
- Method should be included in the toolkit's exposed tools (not in `exclude_tools`)
- Keep output concise — descriptions are already capped at 300 chars per TASK-415

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — existing tool methods like `list_datasets()`, `get_metadata()`

---

## Acceptance Criteria

- [ ] `get_datasets_summary()` returns markdown bullet-list of active datasets
- [ ] Inactive datasets are excluded
- [ ] Datasets without description show `(no description)`
- [ ] Empty string returned when no active datasets
- [ ] Method is exposed as an LLM-callable tool
- [ ] No linting errors

---

## Test Specification

```python
import pytest
import pandas as pd
from parrot.tools.dataset_manager.tool import DatasetManager

@pytest.fixture
def dm_with_datasets():
    dm = DatasetManager()
    df = pd.DataFrame({"a": [1]})
    dm.add_dataframe("sales", df, description="Q4 sales by region")
    dm.add_dataframe("census", df, description="US Census 2023 demographics")
    dm.add_dataframe("logs", df)  # no description
    return dm

class TestGetDatasetsSummary:
    @pytest.mark.asyncio
    async def test_summary_format(self, dm_with_datasets):
        """Summary contains bullet-list with descriptions."""
        summary = await dm_with_datasets.get_datasets_summary()
        assert "- **sales**: Q4 sales by region" in summary
        assert "- **census**: US Census 2023 demographics" in summary
        assert "- **logs**: (no description)" in summary

    @pytest.mark.asyncio
    async def test_excludes_inactive(self, dm_with_datasets):
        """Inactive datasets are excluded from summary."""
        dm_with_datasets.deactivate("sales")
        summary = await dm_with_datasets.get_datasets_summary()
        assert "sales" not in summary
        assert "census" in summary

    @pytest.mark.asyncio
    async def test_empty_when_no_datasets(self):
        """Returns empty string with no datasets."""
        dm = DatasetManager()
        summary = await dm.get_datasets_summary()
        assert summary == ""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/add-description-datasetmanager.spec.md` for full context
2. **Check dependencies** — verify TASK-415 is completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-417-get-datasets-summary.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-03-24
**Notes**: Implemented `get_datasets_summary()` as an async LLM-callable tool. Also added `_build_datasets_summary_sync()` shared helper used by both the async tool and the sync `_generate_dataframe_guide()`. Excludes inactive datasets, shows "(no description)" for datasets without descriptions, returns "" when no active datasets.

**Deviations from spec**: Extracted sync helper `_build_datasets_summary_sync()` to avoid code duplication (needed by TASK-418's sync guide generation).
