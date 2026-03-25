# TASK-433: DatasetInfo, Guide & Fetch Integration

**Feature**: composite-datasets
**Spec**: `sdd/specs/composite-datasets.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-432
**Assigned-to**: unassigned

---

## Context

Final integration task: composite datasets must appear correctly in all DatasetManager surfaces — DatasetInfo model, LLM guide, fetch_dataset routing, list_datasets, and get_metadata.

Implements **Module 7** from the spec (Section 3).

---

## Scope

- Add `"composite"` to `DatasetInfo.source_type` Literal
- Add `CompositeDataSource` to `DatasetEntry.to_info()._source_type_map`
- Add composite branch to `_generate_dataframe_guide()`:
  - Show components and join descriptions
  - Show usage hint with conditions example
- Add composite branch to `fetch_dataset()`:
  - Pass `conditions` as `filter` parameter to `CompositeDataSource.fetch()`
  - Set `force_refresh = True` (composites always re-fetch)
- Add composite branch to `list_datasets()`:
  - `action_required` guidance for unloaded composites
- Add composite branch to `get_metadata()`:
  - Not-loaded guidance specific to composites
- Write unit tests for all integration points

**NOT in scope**: Changes to CompositeDataSource itself (TASK-431)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | DatasetInfo, to_info, guide, fetch_dataset, list_datasets, get_metadata |
| `tests/tools/dataset_manager/test_composite_integration.py` | CREATE | Integration tests |

---

## Implementation Notes

### DatasetInfo Changes

```python
class DatasetInfo(BaseModel):
    source_type: Literal[
        "dataframe", "query_slug", "sql", "table", "airtable", "smartsheet",
        "iceberg", "mongo", "deltatable", "composite",  # ← ADD
    ]
```

### to_info() Changes

```python
from .sources.composite import CompositeDataSource

# Add to _source_type_map:
CompositeDataSource: "composite",
```

### fetch_dataset() Changes

```python
from .sources.composite import CompositeDataSource

# In the source-type dispatch block:
if isinstance(entry.source, CompositeDataSource):
    if conditions:
        params['filter'] = conditions
    force_refresh = True
```

### _generate_dataframe_guide() Changes

Add a block for composite source_type (when not loaded):
```python
elif info.source_type == "composite":
    source = entry.source
    if isinstance(source, CompositeDataSource):
        guide_parts.append(f"- **Components**: {', '.join(source.component_names)}")
        for j in source.joins:
            guide_parts.append(f"  - {j.left} {j.how.upper()} JOIN {j.right} ON {j.on}")
    guide_parts.append(
        f'\n- **To use**: `fetch_dataset("{ds_name}")` or '
        f'`fetch_dataset("{ds_name}", conditions={{"column": "value"}})` '
        f'to filter components before joining.'
    )
```

### Key Constraints
- Import `CompositeDataSource` at function level to avoid circular imports
- Composites always force_refresh because components may have changed
- The guide block for composites should show join topology even before loading
- `list_datasets` action_required should tell the LLM to call `fetch_dataset`

### References in Codebase
- Spec Sections 3.5–3.7 for exact integration points
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — DatasetInfo (lines 34–86), to_info (lines 278–349), guide (lines 2562–2718), fetch_dataset (lines 2220–2440)

---

## Acceptance Criteria

- [ ] `DatasetInfo.source_type` accepts `"composite"`
- [ ] `to_info()` returns `source_type="composite"` for composite datasets
- [ ] `_generate_dataframe_guide()` shows join topology for composites
- [ ] `fetch_dataset()` routes composites correctly with filter propagation
- [ ] `fetch_dataset()` sets force_refresh=True for composites
- [ ] `list_datasets()` shows correct action_required for composites
- [ ] `get_metadata()` shows appropriate guidance for unloaded composites
- [ ] End-to-end: register composite → fetch → verify joined result with computed columns
- [ ] All tests pass: `pytest tests/tools/dataset_manager/test_composite_integration.py -v`
- [ ] No breaking changes to existing source types

---

## Test Specification

```python
# tests/tools/dataset_manager/test_composite_integration.py
import pytest
import pandas as pd
from parrot.tools.dataset_manager.tool import DatasetManager, DatasetInfo
from parrot.tools.dataset_manager.computed import ComputedColumnDef


@pytest.fixture
def dm():
    dm = DatasetManager(generate_guide=True)
    dm.add_dataframe("sales", pd.DataFrame({
        "id": [1, 2, 3], "year": [2025, 2025, 2024],
        "revenue": [100, 200, 150], "expenses": [60, 80, 90],
    }))
    dm.add_dataframe("regions", pd.DataFrame({
        "id": [1, 2, 3], "region": ["East", "West", "South"],
    }))
    return dm


class TestDatasetInfoComposite:
    def test_source_type_literal(self):
        info = DatasetInfo(
            name="test", source_type="composite", source_description="test",
        )
        assert info.source_type == "composite"


class TestToInfoComposite:
    def test_to_info_returns_composite(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        entry = dm._datasets["combined"]
        info = entry.to_info()
        assert info.source_type == "composite"


class TestGuideComposite:
    def test_guide_includes_join_info(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        guide = dm._generate_dataframe_guide()
        assert "combined" in guide
        assert "INNER JOIN" in guide or "inner" in guide.lower()


class TestFetchDatasetComposite:
    @pytest.mark.asyncio
    async def test_fetch_basic(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        result = await dm.fetch_dataset("combined")
        # Result should contain data or confirmation
        assert "combined" in str(result).lower() or isinstance(result, str)

    @pytest.mark.asyncio
    async def test_fetch_with_filter(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        result = await dm.fetch_dataset("combined", conditions={"year": 2025})
        assert isinstance(result, str)


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_composite_with_computed(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
            computed_columns=[
                ComputedColumnDef(
                    name="ebitda", func="math_operation",
                    columns=["revenue", "expenses"],
                    kwargs={"operation": "subtract"},
                    description="EBITDA",
                ),
            ],
        )
        result = await dm.fetch_dataset("combined")
        entry = dm._datasets["combined"]
        assert entry.loaded
        assert "ebitda" in entry._df.columns
        assert "region" in entry._df.columns
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/composite-datasets.spec.md` for full context
2. **Check dependencies** — verify TASK-432 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-433-datasetinfo-guide-fetch-integration.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
