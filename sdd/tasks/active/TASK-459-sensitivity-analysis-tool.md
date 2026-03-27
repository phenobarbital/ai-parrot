# TASK-459: SensitivityAnalysisTool

**Feature**: whatif-toolkit-decomposition
**Spec**: `sdd/specs/whatif-toolkit-decomposition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> SensitivityAnalysisTool determines which input variables have the greatest impact on a target
> metric. It generates tornado-style analysis and elasticity coefficients — essential for answering
> "which variable should I focus on?" before running what-if simulations.
> Reference: Spec section 3.4 — SensitivityAnalysisTool.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/sensitivity_analysis.py` with:
  - `SensitivityAnalysisInput` Pydantic schema (df_name, target_metric, input_variables, variation_range, derived_metrics, method)
  - `SensitivityAnalysisTool(AbstractTool)` class
  - `_execute()` method implementing one-at-a-time sensitivity analysis:
    1. Resolve DataFrame (from parent agent's dataframes)
    2. Calculate base value of target metric
    3. For each input variable: vary by ±variation_range%, recalculate target metric
    4. Compute impact (absolute change) and elasticity (% change in output / % change in input)
    5. Rank variables by absolute impact (descending)
    6. Return: markdown table with ranked impacts + elasticity coefficients
  - Support derived metrics (via MetricsCalculator from whatif.py)
  - Support "all_at_once" method (spider plot data) as secondary option

- Write comprehensive unit tests

**NOT in scope**: Visualization/chart generation (return data only), integration with WhatIfToolkit

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/sensitivity_analysis.py` | CREATE | Tool implementation |
| `tests/tools/test_sensitivity_analysis.py` | CREATE | Unit tests |

---

## Implementation Notes

### One-at-a-Time Algorithm
```python
async def _execute(self, **kwargs) -> ToolResult:
    input_data = SensitivityAnalysisInput(**kwargs)
    df = self._get_dataframe(input_data.df_name)

    calculator = MetricsCalculator()
    for dm in input_data.derived_metrics:
        calculator.register_metric(dm.name, dm.formula)

    # Calculate base value
    base_value = calculator.get_base_value(df, input_data.target_metric)

    results = []
    variables = input_data.input_variables or [
        c for c in df.select_dtypes(include='number').columns
        if c != input_data.target_metric
    ]

    for var in variables:
        for direction, factor in [("low", 1 - input_data.variation_range/100),
                                   ("high", 1 + input_data.variation_range/100)]:
            df_modified = df.copy()
            df_modified[var] = df_modified[var] * factor
            new_value = calculator.get_base_value(df_modified, input_data.target_metric)
            # Store impact
        # Calculate elasticity = (delta_output / base_output) / (delta_input / base_input)
```

### Key Constraints
- Must handle derived metrics that reference the variable being varied (recalculate correctly)
- If target_metric is a column (not derived), and the variable is the same column, elasticity = 1.0
- Auto-exclude non-numeric columns from input_variables
- Use existing `MetricsCalculator` from `whatif.py` for derived metric evaluation

### Pattern to Follow
```python
# Follow existing tool patterns
from parrot_tools.abstract import AbstractTool, ToolResult
from parrot_tools.whatif import MetricsCalculator, DerivedMetric

class SensitivityAnalysisTool(AbstractTool):
    name = "sensitivity_analysis"
    description = "Analyze which variables have the greatest impact on a target metric"
    args_schema = SensitivityAnalysisInput
```

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/whatif.py` — MetricsCalculator to reuse
- `packages/ai-parrot-tools/src/parrot_tools/correlationanalysis.py` — similar tool pattern
- `packages/ai-parrot-tools/src/parrot_tools/abstract.py` — AbstractTool base

---

## Acceptance Criteria

- [ ] Tool correctly ranks variables by impact on target metric
- [ ] Elasticity coefficients are mathematically correct
- [ ] Derived metrics are properly recalculated when base columns vary
- [ ] Auto-detects numeric columns when input_variables not specified
- [ ] Returns formatted markdown table
- [ ] Handles edge cases: single variable, zero base value, constant columns
- [ ] Tests pass: `pytest tests/tools/test_sensitivity_analysis.py -v`

---

## Test Specification

```python
import pytest
import pandas as pd
from parrot_tools.sensitivity_analysis import SensitivityAnalysisTool, SensitivityAnalysisInput
from parrot_tools.whatif import DerivedMetric


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'revenue': [100000, 200000, 150000, 180000],
        'expenses': [80000, 150000, 120000, 140000],
        'kiosks': [50, 80, 60, 70],
        'warehouses': [3, 5, 4, 4]
    })


class TestSensitivityAnalysis:
    @pytest.mark.asyncio
    async def test_ranks_by_impact(self, sample_df):
        tool = SensitivityAnalysisTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': sample_df}})()
        result = await tool._execute(
            df_name="test",
            target_metric="revenue",
            variation_range=20.0
        )
        assert result.success
        assert "revenue" in result.result.lower() or "impact" in str(result.result).lower()

    @pytest.mark.asyncio
    async def test_with_derived_metric(self, sample_df):
        tool = SensitivityAnalysisTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': sample_df}})()
        result = await tool._execute(
            df_name="test",
            target_metric="ebitda",
            derived_metrics=[DerivedMetric(name="ebitda", formula="revenue - expenses")],
            variation_range=20.0
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_elasticity_is_one_for_self(self, sample_df):
        """When varying revenue and measuring revenue, elasticity should be ~1.0."""
        tool = SensitivityAnalysisTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': sample_df}})()
        result = await tool._execute(
            df_name="test",
            target_metric="revenue",
            input_variables=["revenue"],
            variation_range=20.0
        )
        assert result.success
        # Elasticity for self should be approximately 1.0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/whatif-toolkit-decomposition.spec.md` section 3.4
2. **Check dependencies** — this task has no dependencies (parallel)
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-459-sensitivity-analysis-tool.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
