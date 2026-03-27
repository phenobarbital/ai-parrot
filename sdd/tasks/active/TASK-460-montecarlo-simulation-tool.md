# TASK-460: MonteCarloSimulationTool

**Feature**: whatif-toolkit-decomposition
**Spec**: `sdd/specs/whatif-toolkit-decomposition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> MonteCarloSimulationTool runs stochastic simulations to provide probability distributions of
> outcomes instead of single-point estimates. This answers questions like "what's the range of
> possible EBITDA values if kiosks vary between 800-1200?" with confidence intervals.
> Reference: Spec section 3.5 — MonteCarloSimulationTool.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/montecarlo.py` with:
  - `VariableDistribution` Pydantic schema (column, distribution, params)
  - `MonteCarloInput` Pydantic schema (df_name, target_metrics, variables, n_simulations, derived_metrics, confidence_levels)
  - `MonteCarloSimulationTool(AbstractTool)` class
  - `_execute()` method implementing:
    1. Resolve DataFrame
    2. Set up distribution samplers using `scipy.stats` or `numpy.random`
    3. For each simulation (n_simulations):
       a. Sample random multiplier for each variable from its distribution
       b. Apply multipliers to DataFrame columns
       c. Calculate target metrics (including derived via MetricsCalculator)
       d. Store metric values
    4. Calculate percentiles at specified confidence_levels
    5. Calculate probability of exceeding/falling below user-defined thresholds
    6. Return: percentile table, probability statements, summary statistics

  - Support 4 distributions: normal, uniform, triangular, lognormal
  - Operate on **aggregated metrics** (column sums) not row-level — this keeps it fast

- Write comprehensive unit tests including convergence checks

**NOT in scope**: Row-level simulation, GPU acceleration, visualization generation

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/montecarlo.py` | CREATE | Tool implementation |
| `tests/tools/test_montecarlo.py` | CREATE | Unit tests |

---

## Implementation Notes

### Simulation Loop (Vectorized)
```python
import numpy as np
from scipy import stats as scipy_stats

def _run_simulations(self, df, variables, n_simulations, target_metrics, calculator):
    """Run Monte Carlo simulation — vectorized for performance."""
    rng = np.random.default_rng()

    # Pre-calculate base column sums for scaling
    results = {metric: np.zeros(n_simulations) for metric in target_metrics}

    for i in range(n_simulations):
        df_sim = df.copy()
        for var in variables:
            multiplier = self._sample_multiplier(rng, var)
            df_sim[var.column] = df_sim[var.column] * multiplier

        for metric in target_metrics:
            results[metric][i] = calculator.get_base_value(df_sim, metric)

    return results

def _sample_multiplier(self, rng, var: VariableDistribution) -> float:
    """Sample a single multiplier from the variable's distribution."""
    params = var.params
    if var.distribution == "normal":
        mean_pct = params.get("mean_pct", 0)
        std_pct = params.get("std_pct", 10)
        return 1.0 + rng.normal(mean_pct, std_pct) / 100.0
    elif var.distribution == "uniform":
        min_pct = params.get("min_pct", -20)
        max_pct = params.get("max_pct", 20)
        return 1.0 + rng.uniform(min_pct, max_pct) / 100.0
    elif var.distribution == "triangular":
        min_pct = params.get("min_pct", -20)
        mode_pct = params.get("mode_pct", 0)
        max_pct = params.get("max_pct", 20)
        return 1.0 + rng.triangular(min_pct, mode_pct, max_pct) / 100.0
    elif var.distribution == "lognormal":
        mean_pct = params.get("mean_pct", 0)
        std_pct = params.get("std_pct", 10)
        return np.exp(rng.normal(np.log(1.0 + mean_pct/100.0), std_pct/100.0))
```

### Performance Considerations
- For 10K simulations on a 1000-row DataFrame, this should complete in <5 seconds
- Operate on column sums (aggregated), not per-row — `calculator.get_base_value()` sums the column
- Cap n_simulations at 100,000 to prevent resource exhaustion
- Use `numpy.random.default_rng()` for reproducible, fast random generation

### Key Constraints
- Validate n_simulations range: 1000 to 100000
- Validate distribution names and required params
- If derived metrics reference a varied column, the recalculation must happen per-simulation
- Return percentiles matching the requested confidence_levels

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/whatif.py` — MetricsCalculator for derived metrics
- `packages/ai-parrot-tools/src/parrot_tools/prophetforecast.py` — similar tool pattern with stats

---

## Acceptance Criteria

- [ ] Runs 10K simulations in <5 seconds for a 1000-row DataFrame
- [ ] All 4 distributions produce correct shapes (verified against scipy)
- [ ] Percentiles are accurate (within statistical tolerance)
- [ ] Derived metrics are correctly recalculated per simulation
- [ ] Returns formatted percentile table and probability statements
- [ ] Validates input ranges and distribution parameters
- [ ] Tests pass: `pytest tests/tools/test_montecarlo.py -v`

---

## Test Specification

```python
import pytest
import pandas as pd
import numpy as np
from parrot_tools.montecarlo import MonteCarloSimulationTool, MonteCarloInput, VariableDistribution
from parrot_tools.whatif import DerivedMetric


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'revenue': [100000, 200000, 150000, 180000],
        'expenses': [80000, 150000, 120000, 140000],
        'kiosks': [50, 80, 60, 70]
    })


class TestMonteCarlo:
    @pytest.mark.asyncio
    async def test_uniform_distribution(self, sample_df):
        tool = MonteCarloSimulationTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': sample_df}})()
        result = await tool._execute(
            df_name="test",
            target_metrics=["revenue"],
            variables=[VariableDistribution(
                column="kiosks",
                distribution="uniform",
                params={"min_pct": -20, "max_pct": 20}
            )],
            n_simulations=5000
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_normal_distribution_convergence(self, sample_df):
        """Mean of results should converge to base value for zero-mean normal."""
        tool = MonteCarloSimulationTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': sample_df}})()
        result = await tool._execute(
            df_name="test",
            target_metrics=["revenue"],
            variables=[VariableDistribution(
                column="kiosks",
                distribution="normal",
                params={"mean_pct": 0, "std_pct": 10}
            )],
            n_simulations=10000
        )
        assert result.success
        # P50 should be close to base value

    @pytest.mark.asyncio
    async def test_with_derived_metrics(self, sample_df):
        tool = MonteCarloSimulationTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': sample_df}})()
        result = await tool._execute(
            df_name="test",
            target_metrics=["ebitda"],
            variables=[VariableDistribution(
                column="revenue",
                distribution="normal",
                params={"mean_pct": 10, "std_pct": 5}
            )],
            derived_metrics=[DerivedMetric(name="ebitda", formula="revenue - expenses")],
            n_simulations=5000
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_rejects_too_many_simulations(self, sample_df):
        tool = MonteCarloSimulationTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': sample_df}})()
        result = await tool._execute(
            df_name="test",
            target_metrics=["revenue"],
            variables=[VariableDistribution(
                column="kiosks", distribution="uniform",
                params={"min_pct": -10, "max_pct": 10}
            )],
            n_simulations=200000  # exceeds max
        )
        assert not result.success
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/whatif-toolkit-decomposition.spec.md` section 3.5
2. **Check dependencies** — this task has no dependencies (parallel)
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-460-montecarlo-simulation-tool.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
