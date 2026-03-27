# TASK-461: StatisticalTestsTool

**Feature**: whatif-toolkit-decomposition
**Spec**: `sdd/specs/whatif-toolkit-decomposition.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> StatisticalTestsTool validates whether differences between groups or scenarios are
> statistically significant. Answers "is the revenue difference between North and South
> real or just noise?" using t-tests, ANOVA, chi-square, and non-parametric alternatives.
> Reference: Spec section 3.6 — StatisticalTestsTool.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/statistical_tests.py` with:
  - `StatisticalTestInput` Pydantic schema (df_name, test_type, target_column, group_column, groups, alpha, alternative)
  - `StatisticalTestsTool(AbstractTool)` class
  - `_execute()` supporting 6 test types:
    - `ttest`: Independent two-sample t-test (`scipy.stats.ttest_ind`)
    - `anova`: One-way ANOVA (`scipy.stats.f_oneway`)
    - `chi_square`: Chi-squared test of independence (`scipy.stats.chi2_contingency`)
    - `mann_whitney`: Non-parametric two-sample (`scipy.stats.mannwhitneyu`)
    - `kruskal_wallis`: Non-parametric multi-sample (`scipy.stats.kruskal`)
    - `normality`: Shapiro-Wilk test (`scipy.stats.shapiro`)
  - Calculate effect size (Cohen's d for t-test, eta-squared for ANOVA)
  - Generate plain-language interpretation of results
  - Return: test statistic, p-value, effect size, confidence interval (where applicable), interpretation

- Write unit tests with known statistical distributions

**NOT in scope**: Bayesian tests, multiple comparison corrections (Bonferroni), paired tests

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/statistical_tests.py` | CREATE | Tool implementation |
| `tests/tools/test_statistical_tests.py` | CREATE | Unit tests |

---

## Implementation Notes

### Test Dispatch Pattern
```python
from scipy import stats as scipy_stats

TEST_DISPATCH = {
    "ttest": "_run_ttest",
    "anova": "_run_anova",
    "chi_square": "_run_chi_square",
    "mann_whitney": "_run_mann_whitney",
    "kruskal_wallis": "_run_kruskal_wallis",
    "normality": "_run_normality"
}

async def _execute(self, **kwargs) -> ToolResult:
    input_data = StatisticalTestInput(**kwargs)
    df = self._get_dataframe(input_data.df_name)

    method_name = TEST_DISPATCH.get(input_data.test_type)
    if not method_name:
        return ToolResult(success=False, error=f"Unknown test: {input_data.test_type}")

    method = getattr(self, method_name)
    return method(df, input_data)
```

### Effect Size Calculations
```python
def _cohens_d(self, group1, group2):
    """Cohen's d for two independent groups."""
    n1, n2 = len(group1), len(group2)
    var1, var2 = group1.var(), group2.var()
    pooled_std = np.sqrt(((n1-1)*var1 + (n2-1)*var2) / (n1+n2-2))
    return (group1.mean() - group2.mean()) / pooled_std if pooled_std > 0 else 0

def _eta_squared(self, f_stat, df_between, df_within):
    """Eta-squared for ANOVA."""
    return (f_stat * df_between) / (f_stat * df_between + df_within)
```

### Interpretation Template
```python
def _interpret_pvalue(self, p_value, alpha, test_name, metric, groups):
    if p_value < alpha:
        return (f"The difference in {metric} between {' and '.join(groups)} "
                f"is statistically significant (p={p_value:.4f} < {alpha})")
    else:
        return (f"No statistically significant difference in {metric} "
                f"between {' and '.join(groups)} (p={p_value:.4f} >= {alpha})")
```

### Key Constraints
- `scipy.stats` is already available (via statsmodels dependency)
- For chi_square: target_column must be categorical or discretized
- For ttest/mann_whitney: exactly 2 groups required
- For anova/kruskal: 2+ groups required
- Handle groups with too few observations gracefully

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/seasonaldetection.py` — uses scipy.stats (ADF, KPSS)
- `packages/ai-parrot-tools/src/parrot_tools/correlationanalysis.py` — similar analysis pattern

---

## Acceptance Criteria

- [ ] All 6 test types produce correct results (verified against known values)
- [ ] Effect sizes calculated correctly (Cohen's d, eta-squared)
- [ ] Plain-language interpretation is clear and accurate
- [ ] Handles edge cases: groups with 1 observation, identical distributions, non-numeric columns
- [ ] Validates required parameters per test type (e.g., group_column for ttest)
- [ ] Tests pass: `pytest tests/tools/test_statistical_tests.py -v`

---

## Test Specification

```python
import pytest
import pandas as pd
import numpy as np
from parrot_tools.statistical_tests import StatisticalTestsTool


@pytest.fixture
def df_with_groups():
    """DataFrame with known significant difference between groups."""
    np.random.seed(42)
    return pd.DataFrame({
        'Region': ['North']*50 + ['South']*50,
        'Revenue': list(np.random.normal(1000, 100, 50)) + list(np.random.normal(800, 100, 50)),
        'Category': ['A']*30 + ['B']*20 + ['A']*20 + ['B']*30
    })


class TestStatisticalTests:
    @pytest.mark.asyncio
    async def test_ttest_detects_significant_difference(self, df_with_groups):
        tool = StatisticalTestsTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': df_with_groups}})()
        result = await tool._execute(
            df_name="test", test_type="ttest",
            target_column="Revenue", group_column="Region"
        )
        assert result.success
        assert "significant" in str(result.result).lower()

    @pytest.mark.asyncio
    async def test_anova_with_multiple_groups(self, df_with_groups):
        tool = StatisticalTestsTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': df_with_groups}})()
        result = await tool._execute(
            df_name="test", test_type="anova",
            target_column="Revenue", group_column="Region"
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_normality_check(self, df_with_groups):
        tool = StatisticalTestsTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': df_with_groups}})()
        result = await tool._execute(
            df_name="test", test_type="normality",
            target_column="Revenue"
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_chi_square(self, df_with_groups):
        tool = StatisticalTestsTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': df_with_groups}})()
        result = await tool._execute(
            df_name="test", test_type="chi_square",
            target_column="Category", group_column="Region"
        )
        assert result.success
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/whatif-toolkit-decomposition.spec.md` section 3.6
2. **Check dependencies** — this task has no dependencies (parallel)
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-461-statistical-tests-tool.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
