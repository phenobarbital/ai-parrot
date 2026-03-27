# TASK-454: Implement add_actions and set_constraints Tool Methods

**Feature**: whatif-toolkit-decomposition
**Spec**: `sdd/specs/whatif-toolkit-decomposition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-452, TASK-453
**Assigned-to**: unassigned

---

## Context

> `add_actions` and `set_constraints` are the configuration tools in the multi-step workflow.
> They validate user-specified actions and constraints against the scenario's DataFrame schema
> and store them in the ScenarioState for later execution by `simulate`.
> Reference: Spec section 3.1 — Tool 2 (add_actions) and Tool 3 (set_constraints).

---

## Scope

- Implement `async def add_actions(self, scenario_id: str, actions: List[WhatIfAction]) -> str` in `WhatIfToolkit`
  - Look up scenario by ID (raise clear error if not found)
  - For each action: validate column/target exists in DataFrame, validate entity values exist (for scale_entity), validate parameters are reasonable
  - Append valid actions to `ScenarioState.actions`
  - Report invalid actions with specific error messages (don't fail the whole call)
  - Return: summary of added actions with validation status per action

- Implement `async def set_constraints(self, scenario_id: str, objectives: List[WhatIfObjective] = None, constraints: List[WhatIfConstraint] = None) -> str` in `WhatIfToolkit`
  - Look up scenario by ID
  - Validate metric names exist as columns or registered derived metrics
  - Validate constraint values (e.g., max_change > 0, min_value < max_value of metric)
  - Store in ScenarioState
  - Return: summary of configured optimization

- Write unit tests for both methods

**NOT in scope**: simulate execution, quick_impact, compare_scenarios

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/whatif_toolkit.py` | MODIFY | Implement add_actions, set_constraints |
| `tests/tools/test_whatif_actions_constraints.py` | CREATE | Unit tests |

---

## Implementation Notes

### Action Validation Logic
```python
async def _validate_action(self, action: WhatIfAction, df: pd.DataFrame) -> Tuple[bool, str]:
    """Validate a single action against the DataFrame schema."""
    if action.type == "exclude_values":
        col = action.parameters.get("column", action.target)
        if col not in df.columns:
            return False, f"Column '{col}' not found. Available: {list(df.columns)}"
        values = action.parameters.get("values", [])
        if values:
            actual = set(df[col].unique())
            missing = set(values) - actual
            if missing:
                return False, f"Values {missing} not found in '{col}'"
    # ... similar for other types
    return True, "OK"
```

### Key Constraints
- Partial success: if 3 of 5 actions are valid, add the 3 valid ones and report the 2 failures
- For `set_constraints`: objectives and constraints are both optional (user may only set one)
- Metric names in constraints must be either DataFrame columns OR registered derived metrics from describe_scenario

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/whatif.py` lines 1074-1113 — action configuration logic to mirror

---

## Acceptance Criteria

- [ ] `add_actions` adds valid actions and reports invalid ones
- [ ] Column/entity validation catches typos with helpful error messages
- [ ] `set_constraints` validates metric names against columns + derived metrics
- [ ] Invalid scenario_id raises clear error
- [ ] Partial success works (valid actions added, invalid reported)
- [ ] Tests pass: `pytest tests/tools/test_whatif_actions_constraints.py -v`

---

## Test Specification

```python
import pytest
import pandas as pd
from parrot_tools.whatif_toolkit import WhatIfToolkit
from parrot_tools.whatif import WhatIfAction, WhatIfObjective, WhatIfConstraint, DerivedMetric


@pytest.fixture
def toolkit_with_scenario(sample_df):
    """Toolkit with one scenario already created."""
    toolkit = WhatIfToolkit()
    # Pre-populate a scenario
    from parrot_tools.whatif_toolkit import ScenarioState
    toolkit._scenarios["sc_1"] = ScenarioState(
        id="sc_1", description="test", df_name="test",
        df=sample_df, derived_metrics=[], actions=[],
        objectives=[], constraints=[]
    )
    return toolkit


class TestAddActions:
    @pytest.mark.asyncio
    async def test_add_valid_action(self, toolkit_with_scenario):
        result = await toolkit_with_scenario.add_actions(
            scenario_id="sc_1",
            actions=[WhatIfAction(type="exclude_values", target="Project",
                                   parameters={"column": "Project", "values": ["A"]})]
        )
        assert len(toolkit_with_scenario._scenarios["sc_1"].actions) == 1

    @pytest.mark.asyncio
    async def test_invalid_column_reported(self, toolkit_with_scenario):
        result = await toolkit_with_scenario.add_actions(
            scenario_id="sc_1",
            actions=[WhatIfAction(type="exclude_values", target="BadColumn",
                                   parameters={"column": "BadColumn", "values": ["X"]})]
        )
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_invalid_scenario_id(self, toolkit_with_scenario):
        with pytest.raises(ValueError):
            await toolkit_with_scenario.add_actions(scenario_id="bad_id", actions=[])


class TestSetConstraints:
    @pytest.mark.asyncio
    async def test_set_valid_objective(self, toolkit_with_scenario):
        result = await toolkit_with_scenario.set_constraints(
            scenario_id="sc_1",
            objectives=[WhatIfObjective(type="maximize", metric="Revenue")]
        )
        assert len(toolkit_with_scenario._scenarios["sc_1"].objectives) == 1

    @pytest.mark.asyncio
    async def test_invalid_metric_name(self, toolkit_with_scenario):
        result = await toolkit_with_scenario.set_constraints(
            scenario_id="sc_1",
            constraints=[WhatIfConstraint(type="max_change", metric="nonexistent", value=5.0)]
        )
        assert "not found" in result.lower() or "invalid" in result.lower()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/whatif-toolkit-decomposition.spec.md` sections 3.1 Tool 2-3
2. **Check dependencies** — verify TASK-452, TASK-453 are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-454-add-actions-set-constraints.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
