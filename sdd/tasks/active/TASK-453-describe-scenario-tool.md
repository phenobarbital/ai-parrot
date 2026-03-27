# TASK-453: Implement describe_scenario Tool Method

**Feature**: whatif-toolkit-decomposition
**Spec**: `sdd/specs/whatif-toolkit-decomposition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-452
**Assigned-to**: unassigned

---

## Context

> `describe_scenario` is the entry point for the multi-step WhatIf workflow. It creates a validated
> scenario, resolves the dataset from DatasetManager, auto-detects column types, validates derived
> metric formulas, and returns rich metadata so the LLM can plan its next tool calls.
> Reference: Spec section 3.1 — Tool 1: describe_scenario.

---

## Scope

- Implement `async def describe_scenario(self, df_name: str, scenario_description: str, derived_metrics: List[DerivedMetric] = None) -> str` in `WhatIfToolkit`
- Resolve dataset from DatasetManager: try `dm.get_dataframe(df_name)`, handle aliases
- If DatasetManager not available, fall back to looking up `_parent_agent.dataframes` (graceful degradation)
- Materialize lazy datasets if needed
- Auto-detect column types: numeric columns (with sum stats), categorical columns (with unique counts)
- Validate derived metric formulas against actual column names (catch bad column references early)
- Create `ScenarioState` and store in `self._scenarios`
- Generate suggested actions based on data shape (categorical columns → exclude_values/close_region, numeric → adjust_metric/scale_proportional)
- Return formatted string with: scenario_id, column inventory, derived metrics status, suggested actions
- Write unit tests with mock DatasetManager and real DataFrames

**NOT in scope**: add_actions, set_constraints, simulate logic

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/whatif_toolkit.py` | MODIFY | Implement describe_scenario method |
| `tests/tools/test_whatif_describe_scenario.py` | CREATE | Unit tests |

---

## Implementation Notes

### Dataset Resolution Logic
```python
async def _resolve_dataframe(self, df_name: str) -> Tuple[str, pd.DataFrame]:
    """Resolve DataFrame by name or alias from DatasetManager or parent agent."""
    if self._dm:
        result = await self._dm.get_dataframe(df_name)
        if result and 'dataframe' in result:
            return df_name, result['dataframe']
    # Fallback to parent agent
    if self._parent_agent and hasattr(self._parent_agent, 'dataframes'):
        df = self._parent_agent.dataframes.get(df_name)
        if df is not None:
            return df_name, df
    raise ValueError(f"Dataset '{df_name}' not found")
```

### Key Constraints
- Must validate ALL derived metric formulas before creating the scenario (fail fast)
- Use `MetricsCalculator` from existing `whatif.py` to validate formulas
- Auto-suggest actions but don't auto-add them — LLM decides via add_actions

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — DatasetManager API
- `packages/ai-parrot-tools/src/parrot_tools/whatif.py` — MetricsCalculator for formula validation

---

## Acceptance Criteria

- [ ] `describe_scenario` creates a scenario and returns a valid scenario_id
- [ ] Column types are correctly detected (numeric vs categorical)
- [ ] Derived metric formulas are validated against DataFrame columns
- [ ] Invalid formulas raise clear error messages before scenario creation
- [ ] Works with DatasetManager (primary path)
- [ ] Works without DatasetManager via parent agent fallback
- [ ] Tests pass: `pytest tests/tools/test_whatif_describe_scenario.py -v`

---

## Test Specification

```python
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock
from parrot_tools.whatif_toolkit import WhatIfToolkit
from parrot_tools.whatif import DerivedMetric


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'Project': ['A', 'B', 'C', 'D'],
        'Region': ['North', 'South', 'North', 'South'],
        'Revenue': [100000, 200000, 150000, 180000],
        'Expenses': [80000, 150000, 120000, 140000],
        'kiosks': [50, 80, 60, 70]
    })


@pytest.fixture
def toolkit_with_dm(sample_df):
    dm = MagicMock()
    dm.get_dataframe = AsyncMock(return_value={'dataframe': sample_df})
    return WhatIfToolkit(dataset_manager=dm)


class TestDescribeScenario:
    @pytest.mark.asyncio
    async def test_creates_scenario(self, toolkit_with_dm):
        result = await toolkit_with_dm.describe_scenario(
            df_name="test", scenario_description="test scenario"
        )
        assert "sc_" in result
        assert len(toolkit_with_dm._scenarios) == 1

    @pytest.mark.asyncio
    async def test_detects_column_types(self, toolkit_with_dm):
        result = await toolkit_with_dm.describe_scenario(
            df_name="test", scenario_description="test"
        )
        assert "Revenue" in result
        assert "numeric" in result.lower() or "categorical" in result.lower()

    @pytest.mark.asyncio
    async def test_validates_derived_metrics(self, toolkit_with_dm):
        result = await toolkit_with_dm.describe_scenario(
            df_name="test", scenario_description="test",
            derived_metrics=[DerivedMetric(name="ebitda", formula="Revenue - Expenses")]
        )
        assert "ebitda" in result
        assert "validated" in result.lower() or "OK" in result

    @pytest.mark.asyncio
    async def test_invalid_formula_fails(self, toolkit_with_dm):
        with pytest.raises(ValueError, match="nonexistent"):
            await toolkit_with_dm.describe_scenario(
                df_name="test", scenario_description="test",
                derived_metrics=[DerivedMetric(name="bad", formula="nonexistent_col * 2")]
            )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/whatif-toolkit-decomposition.spec.md` section 3.1
2. **Check dependencies** — verify TASK-452 is in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-453-describe-scenario-tool.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
