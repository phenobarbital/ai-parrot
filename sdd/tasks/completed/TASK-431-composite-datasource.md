# TASK-431: CompositeDataSource

**Feature**: composite-datasets
**Spec**: `sdd/specs/composite-datasets.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-427
**Assigned-to**: unassigned

---

## Context

Creates the `CompositeDataSource` — a virtual `DataSource` that JOINs existing datasets on demand with per-component filter propagation.

Implements **Module 5** from the spec (Section 3).

---

## Scope

- Create `sources/composite.py` with:
  - `JoinSpec` Pydantic model (left, right, on, how, suffixes)
  - `CompositeDataSource(DataSource)` class:
    - `__init__(name, joins, dataset_manager, description)`
    - `component_names` property — all unique dataset names in joins
    - `_get_component_columns(ds_name)` — known columns for a component
    - `async prefetch_schema()` — merged schema from component schemas
    - `async fetch(filter=None, **params)` — materialize components, apply per-component filters, execute sequential JOINs
    - `describe()` — human-readable description
    - `has_builtin_cache` property — returns True
    - `cache_key` property — stable key for interface compliance
  - Filter propagation: each filter key applied only to components that have it
  - MergeError captured as ValueError with descriptive message
  - Validate join columns exist in both sides
- Export from `sources/__init__.py`
- Write unit tests

**NOT in scope**: DatasetManager.add_composite_dataset (TASK-432), DatasetInfo integration (TASK-433)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/composite.py` | CREATE | JoinSpec, CompositeDataSource |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/__init__.py` | MODIFY | Add CompositeDataSource export |
| `tests/tools/dataset_manager/test_composite_source.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

Follow the existing `DataSource` ABC pattern:
```python
class CompositeDataSource(DataSource):
    async def prefetch_schema(self) -> Dict[str, str]: ...
    async def fetch(self, **params) -> pd.DataFrame: ...
    def describe(self) -> str: ...
    @property
    def has_builtin_cache(self) -> bool: return True
    @property
    def cache_key(self) -> str: ...
```

### Key Constraints
- `DatasetManager` reference uses `TYPE_CHECKING` to avoid circular imports
- `fetch()` accepts `filter` as a keyword arg (dict of equality filters)
- Filter values: scalar → equality, list/tuple/set → isin
- Use `self._dm._apply_filter(df, applicable)` for filter application
- Use `self._dm.materialize(ds_name, **params)` for component materialization
- JOINs execute sequentially: result = first left, then merge each right
- `has_builtin_cache = True` so DatasetManager skips Redis for the composite itself
- Missing component → ValueError with available datasets listed
- Missing join column → ValueError with available columns listed
- `pd.errors.MergeError` → ValueError with descriptive message

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py` — DataSource ABC
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py` — most complex existing source
- Spec Section 3.3 for exact class design

---

## Acceptance Criteria

- [ ] `JoinSpec` model validates correctly
- [ ] `CompositeDataSource` implements full `DataSource` interface
- [ ] Single JOIN produces correct merge result
- [ ] Chained JOINs (A → B → C) work correctly
- [ ] Filter propagation: filter applied only to components with matching column
- [ ] Filter skipped for components without the column (no error)
- [ ] Missing component dataset raises ValueError
- [ ] Missing join column raises ValueError
- [ ] `pd.errors.MergeError` captured as descriptive ValueError
- [ ] `has_builtin_cache` returns True
- [ ] `describe()` returns human-readable join description
- [ ] Exported from `sources/__init__.py`
- [ ] All tests pass: `pytest tests/tools/dataset_manager/test_composite_source.py -v`

---

## Test Specification

```python
# tests/tools/dataset_manager/test_composite_source.py
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.tools.dataset_manager.sources.composite import (
    JoinSpec, CompositeDataSource,
)


@pytest.fixture
def mock_dm():
    """Mock DatasetManager with two datasets."""
    dm = MagicMock()

    df_history = pd.DataFrame({
        "kiosk_id": [1, 2, 3],
        "year": [2025, 2025, 2024],
        "revenue": [100.0, 200.0, 150.0],
    })
    df_locations = pd.DataFrame({
        "kiosk_id": [1, 2, 3],
        "city": ["Miami", "NYC", "LA"],
    })

    dm.materialize = AsyncMock(side_effect=lambda name, **kw: {
        "history": df_history.copy(),
        "locations": df_locations.copy(),
    }[name])

    # Mock _apply_filter
    def apply_filter(df, filters):
        for k, v in filters.items():
            if isinstance(v, (list, tuple, set)):
                df = df[df[k].isin(v)]
            else:
                df = df[df[k] == v]
        return df.reset_index(drop=True)
    dm._apply_filter = apply_filter

    # Mock _datasets for column introspection
    entry_history = MagicMock()
    entry_history.columns = ["kiosk_id", "year", "revenue"]
    entry_history._computed_columns = []
    entry_locations = MagicMock()
    entry_locations.columns = ["kiosk_id", "city"]
    entry_locations._computed_columns = []
    dm._datasets = {
        "history": entry_history,
        "locations": entry_locations,
    }
    return dm


@pytest.fixture
def composite_source(mock_dm):
    joins = [JoinSpec(left="history", right="locations", on="kiosk_id", how="inner")]
    return CompositeDataSource(
        name="combined", joins=joins,
        dataset_manager=mock_dm, description="Test composite",
    )


class TestJoinSpec:
    def test_basic_creation(self):
        j = JoinSpec(left="a", right="b", on="id")
        assert j.how == "inner"
        assert j.suffixes == ("", "_right")

    def test_list_on(self):
        j = JoinSpec(left="a", right="b", on=["id1", "id2"])
        assert j.on == ["id1", "id2"]


class TestCompositeDataSource:
    def test_component_names(self, composite_source):
        assert composite_source.component_names == {"history", "locations"}

    def test_has_builtin_cache(self, composite_source):
        assert composite_source.has_builtin_cache is True

    def test_describe(self, composite_source):
        desc = composite_source.describe()
        assert "INNER JOIN" in desc
        assert "history" in desc
        assert "locations" in desc

    @pytest.mark.asyncio
    async def test_single_join(self, composite_source):
        result = await composite_source.fetch()
        assert "kiosk_id" in result.columns
        assert "revenue" in result.columns
        assert "city" in result.columns
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_filter_propagation(self, composite_source):
        result = await composite_source.fetch(filter={"year": 2025})
        # year filter applies to history only
        assert len(result) == 2
        assert all(result["year"] == 2025)

    @pytest.mark.asyncio
    async def test_filter_skipped_for_missing_column(self, composite_source):
        """Filter on column that only exists in one component."""
        result = await composite_source.fetch(filter={"city": "Miami"})
        # city filter applies to locations only, then joined
        assert len(result) == 1
        assert result["city"].iloc[0] == "Miami"

    @pytest.mark.asyncio
    async def test_missing_component_raises(self, mock_dm):
        joins = [JoinSpec(left="history", right="missing", on="id")]
        source = CompositeDataSource(
            name="bad", joins=joins, dataset_manager=mock_dm,
        )
        mock_dm._datasets["missing"] = None  # or just not present
        with pytest.raises(ValueError, match="not found"):
            await source.fetch()

    @pytest.mark.asyncio
    async def test_missing_join_column_raises(self, mock_dm):
        joins = [JoinSpec(left="history", right="locations", on="nonexistent")]
        source = CompositeDataSource(
            name="bad", joins=joins, dataset_manager=mock_dm,
        )
        with pytest.raises(ValueError, match="not found"):
            await source.fetch()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/composite-datasets.spec.md` for full context
2. **Check dependencies** — verify TASK-427 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-431-composite-datasource.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
