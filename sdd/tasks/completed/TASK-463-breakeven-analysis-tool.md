# TASK-463: BreakEvenAnalysisTool

**Feature**: whatif-toolkit-decomposition
**Spec**: `sdd/specs/whatif-toolkit-decomposition.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> BreakEvenAnalysisTool finds threshold values — "how many kiosks do we need to cover the cost
> of 4 new warehouses?" or "at what revenue level does the project break even?"
> Uses root-finding algorithms to solve for the variable value where target_metric = target_value.
> Reference: Spec section 3.8 — BreakEvenAnalysisTool.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/breakeven.py` with:
  - `BreakEvenInput` Pydantic schema (df_name, target_metric, target_value, variable, variable_range, fixed_changes, derived_metrics)
  - `BreakEvenAnalysisTool(AbstractTool)` class
  - `_execute()` implementing:
    1. Resolve DataFrame
    2. Apply fixed_changes (e.g., add 4 warehouses to all rows, or add new rows)
    3. Define objective function: f(x) = calculate_target_metric_at(variable=x) - target_value
    4. Use `scipy.optimize.brentq` for root finding within variable_range
    5. Generate sensitivity curve: calculate target_metric at several points around break-even
    6. Calculate margin of safety from current position
    7. Return: break-even value, current value, margin of safety, sensitivity table

- Support derived metrics via MetricsCalculator
- Handle both "additive" changes (add N units) and "multiplicative" changes (scale by X%)
- Write comprehensive unit tests

**NOT in scope**: Multi-variable break-even (solve for one variable at a time), visualization

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/breakeven.py` | CREATE | Tool implementation |
| `tests/tools/test_breakeven.py` | CREATE | Unit tests |

---

## Implementation Notes

### Root Finding
```python
from scipy.optimize import brentq

def _find_breakeven(self, df, variable, target_metric, target_value,
                     fixed_changes, calculator, variable_range):
    """Find variable value where target_metric equals target_value."""
    current_value = df[variable].sum()

    def objective(x_total):
        """Objective function: target_metric at x_total - target_value."""
        # Scale the variable column so its sum equals x_total
        scale_factor = x_total / current_value if current_value > 0 else 1.0
        df_modified = df.copy()

        # Apply fixed changes first
        for col, change in fixed_changes.items():
            if col in df_modified.columns:
                df_modified[col] = df_modified[col] + change

        # Scale the variable
        df_modified[variable] = df_modified[variable] * scale_factor

        # Calculate target metric
        metric_value = calculator.get_base_value(df_modified, target_metric)
        return metric_value - target_value

    # Determine search range
    if variable_range:
        lo, hi = variable_range
    else:
        lo = 0
        hi = current_value * 10

    # Check that root exists (function changes sign)
    f_lo, f_hi = objective(lo), objective(hi)
    if f_lo * f_hi > 0:
        # No root in range — return closest bound
        return None, "No break-even point found in the specified range"

    breakeven = brentq(objective, lo, hi, xtol=0.01)
    return breakeven, None
```

### Sensitivity Curve
Generate 7-10 points around break-even to show how the metric changes:
```python
def _generate_sensitivity_curve(self, df, variable, target_metric, breakeven_value,
                                  fixed_changes, calculator, n_points=9):
    """Generate sensitivity curve around break-even."""
    current = df[variable].sum()
    points = np.linspace(current * 0.5, breakeven_value * 1.5, n_points)
    # ... calculate target_metric at each point
```

### Key Constraints
- `scipy.optimize.brentq` requires the function to change sign in the interval — handle gracefully when no root exists
- Fixed changes are additive by default (add N to every row's value for that column)
- Variable range defaults to [0, 10x current value] if not specified
- Must handle derived metrics (ebitda = revenue - expenses) correctly

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/whatif.py` — MetricsCalculator for derived metrics
- `packages/ai-parrot-tools/src/parrot_tools/abstract.py` — AbstractTool base

---

## Acceptance Criteria

- [ ] Correctly finds break-even point for simple linear cases
- [ ] Fixed changes are applied before solving
- [ ] Derived metrics work correctly in the objective function
- [ ] Sensitivity curve shows metric values at multiple points
- [ ] Margin of safety calculated correctly
- [ ] Handles "no root found" gracefully with clear message
- [ ] Handles edge cases: zero current value, negative ranges
- [ ] Tests pass: `pytest tests/tools/test_breakeven.py -v`

---

## Test Specification

```python
import pytest
import pandas as pd
import numpy as np
from parrot_tools.breakeven import BreakEvenAnalysisTool
from parrot_tools.whatif import DerivedMetric


@pytest.fixture
def pokemon_df():
    """Simplified Pokemon dataset."""
    return pd.DataFrame({
        'Project': ['A', 'B', 'C', 'D', 'E'],
        'revenue': [500000, 800000, 300000, 400000, 350000],
        'expenses': [400000, 600000, 250000, 350000, 300000],
        'kiosks': [50, 80, 30, 40, 35],
        'warehouses': [3, 5, 2, 3, 2]
    })


class TestBreakEven:
    @pytest.mark.asyncio
    async def test_simple_breakeven(self, pokemon_df):
        """Find break-even kiosks for ebitda = 0."""
        tool = BreakEvenAnalysisTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': pokemon_df}})()
        result = await tool._execute(
            df_name="test",
            target_metric="ebitda",
            target_value=0,
            variable="kiosks",
            derived_metrics=[DerivedMetric(name="ebitda", formula="revenue - expenses")]
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_breakeven_with_fixed_changes(self, pokemon_df):
        """Break-even kiosks after adding 4 warehouses (increases expenses)."""
        tool = BreakEvenAnalysisTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': pokemon_df}})()
        result = await tool._execute(
            df_name="test",
            target_metric="ebitda",
            target_value=0,
            variable="kiosks",
            fixed_changes={"expenses": 45000},  # each warehouse costs 45k
            derived_metrics=[DerivedMetric(name="ebitda", formula="revenue - expenses")]
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_sensitivity_curve_included(self, pokemon_df):
        tool = BreakEvenAnalysisTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': pokemon_df}})()
        result = await tool._execute(
            df_name="test",
            target_metric="revenue",
            target_value=3000000,
            variable="kiosks"
        )
        assert result.success
        assert "sensitivity" in str(result.result).lower() or "curve" in str(result.result).lower()

    @pytest.mark.asyncio
    async def test_no_root_found(self, pokemon_df):
        """Target value impossible to reach."""
        tool = BreakEvenAnalysisTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': pokemon_df}})()
        result = await tool._execute(
            df_name="test",
            target_metric="revenue",
            target_value=-1000000,  # impossible negative target
            variable="kiosks",
            variable_range=[0, 500]
        )
        assert result.success  # should succeed but report "no root found"
        assert "not found" in str(result.result).lower() or "no break-even" in str(result.result).lower()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/whatif-toolkit-decomposition.spec.md` section 3.8
2. **Check dependencies** — this task has no dependencies (parallel)
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-463-breakeven-analysis-tool.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
