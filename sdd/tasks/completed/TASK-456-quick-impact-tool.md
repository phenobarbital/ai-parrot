# TASK-456: Implement quick_impact Tool Method

**Feature**: whatif-toolkit-decomposition
**Spec**: `sdd/specs/whatif-toolkit-decomposition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-452
**Assigned-to**: unassigned

---

## Context

> `quick_impact` is the fast-path tool designed to handle ~70% of simple what-if queries in a
> single tool call. Unlike the multi-step workflow (describe → add_actions → simulate), this
> tool resolves dataset, applies a single action, and returns the comparison — all at once.
> This is critical for LLM usability: Gemini and other models reliably call a single focused tool.
> Reference: Spec section 3.1 — Tool 5: quick_impact.

---

## Scope

- Implement `async def quick_impact(self, df_name: str, action_description: str, action_type: str, target: str, parameters: Dict[str, Any] = None) -> str` in `WhatIfToolkit`
  - Resolve dataset from DatasetManager (reuse `_resolve_dataframe` from TASK-453)
  - Create a temporary `WhatIfDSL` instance
  - Map `action_type` to a single DSL action:
    - `exclude_values` → `can_exclude_values()` + solve with max_actions=1
    - `scale_entity` → `can_scale_entity()` + solve with max_actions=1
    - `adjust_metric` → `can_adjust_metric()` + solve with max_actions=1
    - `scale_proportional` → `can_scale_proportional()` + solve with max_actions=1
    - `close_region` → `can_close_regions()` + solve with max_actions=1
  - Apply action directly (no optimization objectives/constraints — just apply and show impact)
  - Generate before/after comparison table
  - Optionally register result DataFrame in DatasetManager
  - Return: comparison table + verdict

- Write comprehensive unit tests covering all 5 action types

**NOT in scope**: Multi-step workflow tools, optimization, constraints

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/whatif_toolkit.py` | MODIFY | Implement quick_impact method |
| `tests/tools/test_whatif_quick_impact.py` | CREATE | Unit tests for all action types |

---

## Implementation Notes

### Direct Application (No Optimization)
For quick_impact, we bypass the solver for most action types. Instead of defining possible actions
and running greedy/genetic optimization, apply the action directly:

```python
async def quick_impact(self, df_name, action_description, action_type, target, parameters=None):
    parameters = parameters or {}
    _, df = await self._resolve_dataframe(df_name)

    dsl = WhatIfDSL(df, name=action_description)

    # Register any derived metrics from parameters
    for dm in parameters.get("derived_metrics", []):
        dsl.register_derived_metric(dm["name"], dm["formula"])
    dsl.initialize_optimizer()

    # Configure and solve with single action
    action_type_lower = action_type.lower()
    if action_type_lower == "exclude_values":
        column = parameters.get("column", target)
        values = parameters.get("values", [target])
        dsl.can_exclude_values(column, values)
    elif action_type_lower == "scale_entity":
        dsl.can_scale_entity(
            entity_column=parameters.get("entity_column", target),
            target_columns=parameters.get("target_columns", []),
            entities=parameters.get("entities", []),
            min_pct=parameters.get("min_pct", -50),
            max_pct=parameters.get("max_pct", -50)
        )
    # ... similar for other types

    result = dsl.solve(max_actions=1, algorithm="greedy")
    # Format and return comparison
```

### Key Constraints
- Must work independently of describe_scenario (no scenario_id required)
- Must handle derived_metrics in parameters for proportional scaling
- Error messages should be user-friendly (suggest correct column names on typo)
- Performance: should complete in <1 second for DataFrames up to 100K rows

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/whatif.py` — WhatIfDSL action methods
- `tests/tools/test_whatif.py` — existing test patterns for action types

---

## Acceptance Criteria

- [ ] `quick_impact` works for all 5 action types (exclude_values, scale_entity, adjust_metric, scale_proportional, close_region)
- [ ] Returns markdown comparison table
- [ ] Works with DatasetManager for dataset resolution
- [ ] Works with parent agent fallback
- [ ] Handles missing column names gracefully
- [ ] Handles empty DataFrame gracefully
- [ ] Registers result in DatasetManager when available
- [ ] Tests pass: `pytest tests/tools/test_whatif_quick_impact.py -v`

---

## Test Specification

```python
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock
from parrot_tools.whatif_toolkit import WhatIfToolkit


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'Project': ['IT Vision', 'Walmart', 'Symbits', 'Belkin', 'Flex'],
        'Region': ['North', 'South', 'East', 'West', 'North'],
        'Revenue': [500000, 800000, 300000, 400000, 350000],
        'Expenses': [400000, 600000, 250000, 350000, 300000],
        'kiosks': [50, 80, 30, 40, 35],
        'visits': [1000, 2000, 800, 1200, 900]
    })


@pytest.fixture
def toolkit(sample_df):
    dm = MagicMock()
    dm.get_dataframe = AsyncMock(return_value={'dataframe': sample_df})
    dm.add_dataframe = AsyncMock(return_value="ok")
    return WhatIfToolkit(dataset_manager=dm)


class TestQuickImpact:
    @pytest.mark.asyncio
    async def test_exclude_values(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="test",
            action_description="remove Belkin",
            action_type="exclude_values",
            target="Project",
            parameters={"column": "Project", "values": ["Belkin"]}
        )
        assert "Revenue" in result
        assert "Belkin" in result or "exclude" in result.lower()

    @pytest.mark.asyncio
    async def test_scale_entity(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="test",
            action_description="reduce Belkin by 50%",
            action_type="scale_entity",
            target="Project",
            parameters={
                "entity_column": "Project",
                "entities": ["Belkin"],
                "target_columns": ["Revenue", "Expenses"],
                "min_pct": -50, "max_pct": -50
            }
        )
        assert "Revenue" in result

    @pytest.mark.asyncio
    async def test_close_region(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="test",
            action_description="close North region",
            action_type="close_region",
            target="Region",
            parameters={"regions": ["North"]}
        )
        assert "Revenue" in result

    @pytest.mark.asyncio
    async def test_adjust_metric(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="test",
            action_description="increase visits by 30%",
            action_type="adjust_metric",
            target="visits",
            parameters={"min_pct": 30, "max_pct": 30}
        )
        assert "visits" in result.lower() or "Visits" in result

    @pytest.mark.asyncio
    async def test_invalid_column(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="test",
            action_description="remove X",
            action_type="exclude_values",
            target="NonExistent",
            parameters={"column": "NonExistent", "values": ["X"]}
        )
        assert "not found" in result.lower() or "error" in result.lower()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/whatif-toolkit-decomposition.spec.md` section 3.1 Tool 5
2. **Check dependencies** — verify TASK-452 is in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-456-quick-impact-tool.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
