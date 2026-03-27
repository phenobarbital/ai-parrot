# TASK-457: Implement compare_scenarios Tool + System Prompt

**Feature**: whatif-toolkit-decomposition
**Spec**: `sdd/specs/whatif-toolkit-decomposition.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-452, TASK-455
**Assigned-to**: unassigned

---

## Context

> `compare_scenarios` enables side-by-side comparison of previously simulated scenarios.
> This task also adds the `WHATIF_TOOLKIT_SYSTEM_PROMPT` that guides LLMs on which tool to
> use for different query types (quick vs full workflow).
> Reference: Spec section 3.1 — Tool 6 and section 3.2 — System Prompt Update.

---

## Scope

- Implement `async def compare_scenarios(self, scenario_ids: List[str]) -> str` in `WhatIfToolkit`
  - Look up all scenario IDs, verify all are solved (`is_solved`)
  - Build comparison matrix: rows = metrics, columns = scenarios
  - For each metric, highlight which scenario performs best/worst
  - Include baseline column for reference
  - Return: markdown comparison table + recommendation summary

- Add `WHATIF_TOOLKIT_SYSTEM_PROMPT` constant in `whatif_toolkit.py`
  - Decision guide: quick_impact vs full workflow
  - Examples for each tool
  - Trigger patterns

- Add `integrate_whatif_toolkit()` helper function
  - Auto-detect DatasetManager and PythonPandasTool from agent
  - Register all tools
  - Inject system prompt

- Write unit tests

**NOT in scope**: The statistical tools, backward compat wrapper (TASK-458)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/whatif_toolkit.py` | MODIFY | Implement compare_scenarios, add system prompt, add integrate helper |
| `tests/tools/test_whatif_compare.py` | CREATE | Unit tests |

---

## Implementation Notes

### Comparison Matrix
```python
async def compare_scenarios(self, scenario_ids: List[str]) -> str:
    # Validate all scenarios exist and are solved
    scenarios = []
    for sid in scenario_ids:
        if sid not in self._scenarios:
            raise ValueError(f"Scenario '{sid}' not found")
        if not self._scenarios[sid].is_solved:
            raise ValueError(f"Scenario '{sid}' has not been simulated yet")
        scenarios.append(self._scenarios[sid])

    # Build comparison using ScenarioResult.compare() from each
    # One row per metric, one column per scenario
    # Highlight best/worst with ↑/↓ markers
```

### System Prompt
Use the `WHATIF_TOOLKIT_SYSTEM_PROMPT` from spec section 3.2. The key decision guide:
- "What if we remove X?" → quick_impact
- "What if we increase X by Y%?" → quick_impact
- "Optimize X without hurting Y" → describe_scenario → add_actions → set_constraints → simulate
- "Compare scenario A vs B" → compare_scenarios

### Key Constraints
- At least 2 scenario IDs required (validated by Pydantic schema `min_length=2`)
- All scenarios must share the same base dataset (or at least the same metric names)
- System prompt must be concise — LLMs have limited system prompt attention

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/whatif.py` lines 1263-1386 — existing system prompt to evolve
- `packages/ai-parrot-tools/src/parrot_tools/whatif.py` lines 1390-1410 — existing integrate_whatif_tool pattern

---

## Acceptance Criteria

- [ ] `compare_scenarios` generates a readable side-by-side comparison table
- [ ] Best/worst metrics are highlighted per scenario
- [ ] Raises clear error for non-existent or unsolved scenarios
- [ ] `WHATIF_TOOLKIT_SYSTEM_PROMPT` contains decision guide, trigger patterns, examples
- [ ] `integrate_whatif_toolkit()` registers all 6 tools and injects system prompt
- [ ] Tests pass: `pytest tests/tools/test_whatif_compare.py -v`

---

## Test Specification

```python
import pytest
import pandas as pd
from parrot_tools.whatif_toolkit import WhatIfToolkit, ScenarioState
from parrot_tools.whatif import ScenarioResult


@pytest.fixture
def toolkit_with_two_solved_scenarios():
    toolkit = WhatIfToolkit()
    df = pd.DataFrame({
        'Project': ['A', 'B', 'C'],
        'Revenue': [100, 200, 150],
        'Expenses': [80, 150, 120]
    })
    # Create two solved scenarios with mock results
    for i, name in enumerate(["sc_1", "sc_2"]):
        state = ScenarioState(
            id=name, description=f"scenario {i+1}", df_name="test",
            df=df, derived_metrics=[], actions=[{"dummy": True}],
            objectives=[], constraints=[]
        )
        # Mock the result
        state.result = True  # Simplified; real test uses ScenarioResult
        toolkit._scenarios[name] = state
    return toolkit


class TestCompareScenarios:
    @pytest.mark.asyncio
    async def test_compare_two_scenarios(self, toolkit_with_two_solved_scenarios):
        result = await toolkit_with_two_solved_scenarios.compare_scenarios(
            scenario_ids=["sc_1", "sc_2"]
        )
        assert "sc_1" in result or "scenario 1" in result

    @pytest.mark.asyncio
    async def test_error_unsolved_scenario(self):
        toolkit = WhatIfToolkit()
        toolkit._scenarios["sc_1"] = ScenarioState(
            id="sc_1", description="test", df_name="test",
            df=pd.DataFrame(), derived_metrics=[], actions=[],
            objectives=[], constraints=[]
        )
        with pytest.raises(ValueError, match="not been simulated"):
            await toolkit.compare_scenarios(scenario_ids=["sc_1", "sc_2"])


class TestSystemPrompt:
    def test_system_prompt_exists(self):
        from parrot_tools.whatif_toolkit import WHATIF_TOOLKIT_SYSTEM_PROMPT
        assert "quick_impact" in WHATIF_TOOLKIT_SYSTEM_PROMPT
        assert "describe_scenario" in WHATIF_TOOLKIT_SYSTEM_PROMPT

    def test_integrate_function_exists(self):
        from parrot_tools.whatif_toolkit import integrate_whatif_toolkit
        assert callable(integrate_whatif_toolkit)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/whatif-toolkit-decomposition.spec.md` sections 3.1 Tool 6, 3.2, 5
2. **Check dependencies** — verify TASK-452 and TASK-455 are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-457-compare-scenarios-sysprompt.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
