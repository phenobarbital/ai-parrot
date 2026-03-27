# TASK-455: Implement simulate Tool Method with DatasetManager Integration

**Feature**: whatif-toolkit-decomposition
**Spec**: `sdd/specs/whatif-toolkit-decomposition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-452, TASK-453, TASK-454
**Assigned-to**: unassigned

---

## Context

> `simulate` is the execution engine of the multi-step workflow. It takes a fully configured
> ScenarioState, builds a WhatIfDSL instance, runs the solver, and critically registers the
> result DataFrame back into DatasetManager so the LLM can analyze results with PythonPandasTool.
> Reference: Spec section 3.1 — Tool 4: simulate.

---

## Scope

- Implement `async def simulate(self, scenario_id: str, algorithm: str = "greedy", max_actions: int = 5) -> str` in `WhatIfToolkit`
  - Look up scenario by ID, verify `is_ready` (has actions)
  - Build `WhatIfDSL` from ScenarioState:
    - Register derived metrics via `dsl.register_derived_metric()`
    - Initialize optimizer
    - Configure objectives (minimize/maximize/target)
    - Configure constraints (max_change/min_value/max_value/ratio)
    - Configure actions (map WhatIfAction types to DSL methods)
  - Run `dsl.solve(max_actions=max_actions, algorithm=algorithm)`
  - Store `ScenarioResult` in `ScenarioState.result`
  - **Register result DataFrame in DatasetManager** as `whatif_{scenario_id}_result`
  - **Sync PythonPandasTool** if available
  - Generate comparison table (markdown), actions applied, verdict
  - Return formatted result string

- Write unit tests with real DataFrame and mock DatasetManager

**NOT in scope**: quick_impact (TASK-456), compare_scenarios (TASK-457)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/whatif_toolkit.py` | MODIFY | Implement simulate method |
| `tests/tools/test_whatif_simulate.py` | CREATE | Unit tests |

---

## Implementation Notes

### Action Mapping (WhatIfAction → DSL calls)
The mapping from WhatIfAction types to DSL methods already exists in `whatif.py` lines 1074-1113.
Reuse the same logic but extract it into a helper:

```python
def _configure_dsl_actions(self, dsl: WhatIfDSL, actions: List[WhatIfAction]) -> None:
    """Map WhatIfAction list to DSL method calls."""
    for action in actions:
        action_type = action.type.lower()
        if action_type == "close_region":
            dsl.can_close_regions(action.parameters.get("regions"))
        elif action_type == "exclude_values":
            dsl.can_exclude_values(
                action.parameters.get("column", action.target),
                action.parameters.get("values")
            )
        # ... same pattern as existing WhatIfTool._execute
```

### DatasetManager Result Registration
```python
# After solving:
if self._dm:
    await self._dm.add_dataframe(
        name=f"whatif_{scenario.id}_result",
        df=result.result_df,
        description=f"WhatIf simulation result: {scenario.description}"
    )
    if self._pandas:
        self._pandas.sync_from_manager()
```

### Reuse Existing Formatting
- Reuse `_create_comparison_table()`, `_describe_action()`, `_generate_veredict()`, `_summarize_df()` from existing `WhatIfTool` — either import them or move to a shared utils module.

### Key Constraints
- Must handle the case where DatasetManager is None (skip result registration)
- Must handle the case where PythonPandasTool is None (skip sync)
- Raise clear error if scenario has no actions (`is_ready == False`)
- Re-running simulate on an already-solved scenario should re-solve (overwrite previous result)

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/whatif.py` lines 963-1169 — existing `_execute()` logic to adapt

---

## Acceptance Criteria

- [ ] `simulate` runs solver and returns comparison table
- [ ] Result DataFrame is registered in DatasetManager as `whatif_{id}_result`
- [ ] PythonPandasTool is synced after registration
- [ ] Works without DatasetManager (skips registration gracefully)
- [ ] Raises error for unsolved scenario (no actions)
- [ ] Both greedy and genetic algorithms work
- [ ] Tests pass: `pytest tests/tools/test_whatif_simulate.py -v`

---

## Test Specification

```python
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock
from parrot_tools.whatif_toolkit import WhatIfToolkit, ScenarioState
from parrot_tools.whatif import WhatIfAction, WhatIfObjective, DerivedMetric


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'Project': ['IT Vision', 'Walmart', 'Symbits', 'Belkin', 'Flex'],
        'Revenue': [500000, 800000, 300000, 400000, 350000],
        'Expenses': [400000, 600000, 250000, 350000, 300000],
        'kiosks': [50, 80, 30, 40, 35]
    })


@pytest.fixture
def toolkit_with_ready_scenario(sample_df):
    dm = MagicMock()
    dm.add_dataframe = AsyncMock(return_value="registered")
    toolkit = WhatIfToolkit(dataset_manager=dm)
    toolkit._scenarios["sc_1"] = ScenarioState(
        id="sc_1", description="test scenario", df_name="test",
        df=sample_df, derived_metrics=[],
        actions=[WhatIfAction(type="exclude_values", target="Project",
                               parameters={"column": "Project", "values": ["Belkin"]})],
        objectives=[], constraints=[]
    )
    return toolkit


class TestSimulate:
    @pytest.mark.asyncio
    async def test_simulate_returns_comparison(self, toolkit_with_ready_scenario):
        result = await toolkit_with_ready_scenario.simulate(scenario_id="sc_1")
        assert "Metric" in result or "Revenue" in result

    @pytest.mark.asyncio
    async def test_registers_result_in_dm(self, toolkit_with_ready_scenario):
        await toolkit_with_ready_scenario.simulate(scenario_id="sc_1")
        toolkit_with_ready_scenario._dm.add_dataframe.assert_called_once()

    @pytest.mark.asyncio
    async def test_scenario_is_solved_after_simulate(self, toolkit_with_ready_scenario):
        await toolkit_with_ready_scenario.simulate(scenario_id="sc_1")
        assert toolkit_with_ready_scenario._scenarios["sc_1"].is_solved

    @pytest.mark.asyncio
    async def test_error_when_no_actions(self, sample_df):
        toolkit = WhatIfToolkit()
        toolkit._scenarios["sc_empty"] = ScenarioState(
            id="sc_empty", description="empty", df_name="test",
            df=sample_df, derived_metrics=[], actions=[],
            objectives=[], constraints=[]
        )
        with pytest.raises(ValueError, match="no actions"):
            await toolkit.simulate(scenario_id="sc_empty")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/whatif-toolkit-decomposition.spec.md` section 3.1 Tool 4
2. **Check dependencies** — verify TASK-452, TASK-453, TASK-454 are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-455-simulate-tool.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
