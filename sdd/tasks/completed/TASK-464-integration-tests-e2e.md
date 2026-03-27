# TASK-464: Integration Tests & End-to-End Validation

**Feature**: whatif-toolkit-decomposition
**Spec**: `sdd/specs/whatif-toolkit-decomposition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-458
**Assigned-to**: unassigned

---

## Context

> This task validates the complete feature end-to-end: WhatIfToolkit with DatasetManager
> integration, result persistence in PythonPandasTool, the full multi-step workflow, and
> the interaction between WhatIf and statistical tools. Also validates the Pokemon scenario
> described in the spec.
> Reference: Spec sections 6 (User Flows) and 7 (Testing Strategy — Integration Tests).

---

## Scope

- Create `tests/tools/test_whatif_integration.py` with integration tests:
  1. `test_toolkit_with_dataset_manager`: Scenario resolves datasets from DM, results registered back
  2. `test_result_accessible_in_pandas_tool`: After simulate, result DataFrame available via PythonPandasTool
  3. `test_full_workflow_end_to_end`: describe → add_actions → set_constraints → simulate → compare
  4. `test_legacy_whatif_delegates_to_toolkit`: Existing WhatIfTool API produces same results via delegation
  5. `test_pokemon_scenario_quick_impact`: "What if we remove Belkin?" via quick_impact
  6. `test_pokemon_scenario_full_workflow`: "Add 1000 kiosks + 4 warehouses, maintain EBITDA margin > 15%"
  7. `test_quick_impact_all_action_types`: Run quick_impact with each of the 5 action types

- These tests use real DataFrames (no mocks for DataFrame operations) but mock DatasetManager and PythonPandasTool

**NOT in scope**: Performance benchmarks, LLM integration testing

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/tools/test_whatif_integration.py` | CREATE | Integration test suite |

---

## Implementation Notes

### Test Data
Use the Pokemon-style dataset from existing tests:
```python
@pytest.fixture
def pokemon_df():
    return pd.DataFrame({
        'Project': ['IT Vision', 'Walmart', 'Symbits', 'Belkin', 'Flex',
                     'Pokemon', 'Rexon', 'Altria'],
        'Region': ['North', 'South', 'East', 'West', 'North',
                    'South', 'East', 'West'],
        'Revenue': [500000, 800000, 300000, 400000, 350000,
                    600000, 250000, 450000],
        'Expenses': [400000, 600000, 250000, 350000, 300000,
                     480000, 200000, 380000],
        'kiosks': [50, 80, 30, 40, 35, 60, 25, 45],
        'warehouses': [3, 5, 2, 3, 2, 4, 2, 3],
        'visits': [1000, 2000, 800, 1200, 900, 1500, 600, 1100]
    })
```

### Full Workflow Test Pattern
```python
@pytest.mark.asyncio
async def test_full_workflow_end_to_end(self, toolkit, pokemon_df):
    # Step 1: describe
    desc_result = await toolkit.describe_scenario(
        df_name="pokemon",
        scenario_description="add kiosks and warehouses",
        derived_metrics=[DerivedMetric(name="ebitda", formula="Revenue - Expenses")]
    )
    scenario_id = ...  # extract from desc_result

    # Step 2: add actions
    await toolkit.add_actions(scenario_id=scenario_id, actions=[...])

    # Step 3: set constraints
    await toolkit.set_constraints(scenario_id=scenario_id, objectives=[...], constraints=[...])

    # Step 4: simulate
    sim_result = await toolkit.simulate(scenario_id=scenario_id)
    assert "Revenue" in sim_result

    # Verify result registered in DatasetManager
    toolkit._dm.add_dataframe.assert_called_once()
```

### Key Constraints
- Integration tests should run without external services (no DB, no Redis)
- Mock DatasetManager for registration calls but use real DataFrames for computation
- Verify the exact same test data produces consistent results across quick_impact and full workflow

### References in Codebase
- `tests/tools/test_whatif.py` — existing test fixtures and patterns
- `packages/ai-parrot-tools/src/parrot_tools/whatif.py` — test data patterns

---

## Acceptance Criteria

- [ ] Full workflow (describe → add_actions → set_constraints → simulate → compare) completes without errors
- [ ] Results are registered in mock DatasetManager
- [ ] Legacy WhatIfTool produces equivalent results via delegation
- [ ] Pokemon scenario works for both quick_impact and full workflow
- [ ] All 5 quick_impact action types work in integration context
- [ ] Tests pass: `pytest tests/tools/test_whatif_integration.py -v`

---

## Test Specification

```python
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock
from parrot_tools.whatif_toolkit import WhatIfToolkit
from parrot_tools.whatif import WhatIfTool, DerivedMetric, WhatIfAction, WhatIfObjective, WhatIfConstraint


@pytest.fixture
def pokemon_df():
    return pd.DataFrame({
        'Project': ['IT Vision', 'Walmart', 'Symbits', 'Belkin', 'Flex'],
        'Revenue': [500000, 800000, 300000, 400000, 350000],
        'Expenses': [400000, 600000, 250000, 350000, 300000],
        'kiosks': [50, 80, 30, 40, 35],
        'warehouses': [3, 5, 2, 3, 2]
    })


@pytest.fixture
def toolkit(pokemon_df):
    dm = MagicMock()
    dm.get_dataframe = AsyncMock(return_value={'dataframe': pokemon_df})
    dm.add_dataframe = AsyncMock(return_value="registered")
    pandas_tool = MagicMock()
    pandas_tool.sync_from_manager = MagicMock()
    return WhatIfToolkit(dataset_manager=dm, pandas_tool=pandas_tool)


class TestFullWorkflow:
    @pytest.mark.asyncio
    async def test_describe_add_simulate_compare(self, toolkit):
        # describe
        desc = await toolkit.describe_scenario(
            df_name="pokemon", scenario_description="remove Belkin project"
        )
        # extract scenario_id (implement based on actual return format)

        # add actions
        # simulate
        # compare two scenarios
        pass  # Detailed implementation by agent

class TestPokemonScenario:
    @pytest.mark.asyncio
    async def test_quick_impact_remove_belkin(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="pokemon",
            action_description="remove Belkin",
            action_type="exclude_values",
            target="Project",
            parameters={"column": "Project", "values": ["Belkin"]}
        )
        assert "Revenue" in result

class TestLegacyCompat:
    @pytest.mark.asyncio
    async def test_legacy_tool_produces_result(self, pokemon_df):
        """Existing WhatIfTool pattern still works."""
        # Setup with parent agent
        pass  # Detailed implementation by agent
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/whatif-toolkit-decomposition.spec.md` sections 6 and 7
2. **Check dependencies** — verify TASK-458 is in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Run all related tests**: `pytest tests/tools/test_whatif*.py -v`
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-464-integration-tests-e2e.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
