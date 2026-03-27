# TASK-452: WhatIfToolkit Scaffold & ScenarioState Model

**Feature**: whatif-toolkit-decomposition
**Spec**: `sdd/specs/whatif-toolkit-decomposition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This is the foundation task for FEAT-065. It creates the `WhatIfToolkit` class skeleton
> extending `AbstractToolkit`, the `ScenarioState` dataclass for managing incremental scenario
> building, and the Pydantic input schemas for all 6 tools. No tool logic is implemented here —
> only the structure that subsequent tasks will fill in.
> Reference: Spec sections 2 (Architectural Design) and 3.1 (WhatIfToolkit constructor).

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/whatif_toolkit.py` with:
  - `ScenarioState` dataclass with `id`, `description`, `df_name`, `df`, `derived_metrics`, `actions`, `objectives`, `constraints`, `result`, `created_at`, `is_ready`, `is_solved`
  - All 6 Pydantic input schemas: `DescribeScenarioInput`, `AddActionsInput`, `SetConstraintsInput`, `SimulateInput`, `QuickImpactInput`, `CompareScenariosInput`
  - `WhatIfToolkit(AbstractToolkit)` class with constructor accepting `dataset_manager` and `pandas_tool`
  - `_scenarios: Dict[str, ScenarioState]` internal state
  - `_counter: int` for generating scenario IDs
  - `_generate_id()` helper method
  - Stub async methods for all 6 tools (raising `NotImplementedError`) so the toolkit is structurally complete
- Import existing models from `whatif.py`: `DerivedMetric`, `WhatIfObjective`, `WhatIfConstraint`, `WhatIfAction` (reuse, don't duplicate)
- Write basic unit tests validating: schema construction, toolkit instantiation, scenario state properties

**NOT in scope**: Actual tool logic (TASK-453 through TASK-457), backward compat wrapper (TASK-458), registry updates (TASK-458)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/whatif_toolkit.py` | CREATE | Toolkit class, ScenarioState, input schemas |
| `tests/tools/test_whatif_toolkit_scaffold.py` | CREATE | Unit tests for models and instantiation |

---

## Implementation Notes

### Pattern to Follow
```python
# Follow AbstractToolkit pattern from parrot/tools/toolkit.py
from parrot_tools.toolkit import AbstractToolkit
from parrot_tools.whatif import (
    DerivedMetric, WhatIfObjective, WhatIfConstraint, WhatIfAction,
    WhatIfDSL, MetricsCalculator, ScenarioOptimizer, ScenarioResult
)

class WhatIfToolkit(AbstractToolkit):
    name = "whatif"
    description = "What-If scenario analysis toolkit"
    exclude_tools = ("start", "stop", "cleanup")

    def __init__(self, dataset_manager=None, pandas_tool=None, **kwargs):
        super().__init__(**kwargs)
        self._dm = dataset_manager
        self._pandas = pandas_tool
        self._scenarios: Dict[str, ScenarioState] = {}
        self._counter = 0
```

### Key Constraints
- Reuse existing Pydantic models from `whatif.py` — do NOT duplicate `DerivedMetric`, `WhatIfAction`, etc.
- `ScenarioState` uses `dataclass` (not Pydantic) since it holds `pd.DataFrame` and internal state
- All 6 methods must be `async def` so AbstractToolkit auto-generates tools from them
- Each method must have a clear docstring — this becomes the tool description for the LLM

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/whatif.py` — existing models to import
- `packages/ai-parrot/src/parrot/tools/toolkit.py` — AbstractToolkit base class
- `packages/ai-parrot-tools/src/parrot_tools/composite_score.py` — example toolkit

---

## Acceptance Criteria

- [ ] `WhatIfToolkit` instantiates without errors
- [ ] `ScenarioState` dataclass works with `is_ready` and `is_solved` properties
- [ ] All 6 input schemas validate correct input and reject invalid input
- [ ] `toolkit.get_tools()` returns 6 tools (one per async method)
- [ ] `toolkit.list_tool_names()` returns the 6 expected names
- [ ] Tests pass: `pytest tests/tools/test_whatif_toolkit_scaffold.py -v`

---

## Test Specification

```python
# tests/tools/test_whatif_toolkit_scaffold.py
import pytest
import pandas as pd
from parrot_tools.whatif_toolkit import (
    WhatIfToolkit, ScenarioState,
    DescribeScenarioInput, QuickImpactInput
)


class TestScenarioState:
    def test_is_ready_false_when_no_actions(self):
        state = ScenarioState(
            id="sc_1", description="test", df_name="test",
            df=pd.DataFrame(), derived_metrics=[], actions=[],
            objectives=[], constraints=[]
        )
        assert state.is_ready is False

    def test_is_ready_true_with_actions(self):
        state = ScenarioState(
            id="sc_1", description="test", df_name="test",
            df=pd.DataFrame(), derived_metrics=[],
            actions=[{"type": "adjust_metric", "target": "x", "parameters": {}}],
            objectives=[], constraints=[]
        )
        assert state.is_ready is True

    def test_is_solved_false_initially(self):
        state = ScenarioState(
            id="sc_1", description="test", df_name="test",
            df=pd.DataFrame(), derived_metrics=[], actions=[],
            objectives=[], constraints=[]
        )
        assert state.is_solved is False


class TestWhatIfToolkit:
    def test_instantiation(self):
        toolkit = WhatIfToolkit()
        assert toolkit is not None

    def test_get_tools_returns_six(self):
        toolkit = WhatIfToolkit()
        tools = toolkit.get_tools()
        assert len(tools) == 6

    def test_tool_names(self):
        toolkit = WhatIfToolkit()
        names = toolkit.list_tool_names()
        expected = {"describe_scenario", "add_actions", "set_constraints",
                    "simulate", "quick_impact", "compare_scenarios"}
        assert set(names) == expected


class TestInputSchemas:
    def test_describe_scenario_input_valid(self):
        inp = DescribeScenarioInput(
            df_name="test_df",
            scenario_description="test scenario"
        )
        assert inp.df_name == "test_df"

    def test_quick_impact_input_valid(self):
        inp = QuickImpactInput(
            df_name="test_df",
            action_description="remove Belkin",
            action_type="exclude_values",
            target="Project"
        )
        assert inp.action_type == "exclude_values"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/whatif-toolkit-decomposition.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-452-whatif-toolkit-scaffold.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
