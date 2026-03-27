# TASK-462: RegressionAnalysisTool

**Feature**: whatif-toolkit-decomposition
**Spec**: `sdd/specs/whatif-toolkit-decomposition.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> RegressionAnalysisTool models quantitative relationships between variables. It answers
> "how does X affect Y?" and "if we add 1000 kiosks, what's the expected revenue increase?"
> using linear, polynomial, and log regression — all implemented with numpy/scipy only.
> Reference: Spec section 3.7 — RegressionAnalysisTool.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/regression_analysis.py` with:
  - `RegressionInput` Pydantic schema (df_name, target, predictors, model_type, predict_at, include_diagnostics)
  - `RegressionAnalysisTool(AbstractTool)` class
  - `_execute()` implementing:
    1. Resolve DataFrame
    2. Extract target (Y) and predictor (X) columns
    3. Fit model based on model_type:
       - `linear`: `numpy.linalg.lstsq` or `scipy.stats.linregress` (single predictor), or OLS via design matrix (multiple)
       - `polynomial`: degree 2-3 via `numpy.polyfit` (single predictor) or feature expansion
       - `log`: log-transform predictors, then linear fit
    4. Calculate R-squared, adjusted R-squared
    5. Calculate coefficient p-values via t-statistics
    6. If `predict_at` provided: predict Y with confidence interval
    7. Return: model equation, coefficients table, fit diagnostics, prediction

- No sklearn dependency — use numpy and scipy only
- Write unit tests with known linear relationships

**NOT in scope**: Regularization (Lasso/Ridge), logistic regression, feature engineering

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/regression_analysis.py` | CREATE | Tool implementation |
| `tests/tools/test_regression_analysis.py` | CREATE | Unit tests |

---

## Implementation Notes

### OLS via Design Matrix (numpy-only)
```python
import numpy as np
from scipy import stats as scipy_stats

def _fit_linear(self, X: np.ndarray, y: np.ndarray):
    """OLS regression using numpy only."""
    # Add intercept column
    n = len(y)
    X_design = np.column_stack([np.ones(n), X])
    k = X_design.shape[1]  # number of parameters

    # Solve normal equation: (X'X)^-1 X'y
    coeffs, residuals, rank, sv = np.linalg.lstsq(X_design, y, rcond=None)

    # Predictions and residuals
    y_pred = X_design @ coeffs
    resid = y - y_pred

    # R-squared
    ss_res = np.sum(resid**2)
    ss_tot = np.sum((y - y.mean())**2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    adj_r_squared = 1 - (1 - r_squared) * (n - 1) / (n - k) if n > k else 0

    # Standard errors and t-statistics
    mse = ss_res / (n - k) if n > k else 0
    var_coeff = mse * np.linalg.inv(X_design.T @ X_design).diagonal()
    se = np.sqrt(np.abs(var_coeff))
    t_stats = coeffs / se
    p_values = [2 * (1 - scipy_stats.t.cdf(abs(t), df=n-k)) for t in t_stats]

    return {
        'coefficients': coeffs,
        'std_errors': se,
        't_statistics': t_stats,
        'p_values': p_values,
        'r_squared': r_squared,
        'adj_r_squared': adj_r_squared,
        'residuals': resid
    }
```

### Prediction with Confidence Interval
```python
def _predict_with_ci(self, X_new, coeffs, X_design, mse, n, k, alpha=0.05):
    """Predict with confidence interval."""
    X_new_design = np.concatenate([[1], X_new])
    y_pred = X_new_design @ coeffs

    # Prediction interval
    XtX_inv = np.linalg.inv(X_design.T @ X_design)
    pred_var = mse * (1 + X_new_design @ XtX_inv @ X_new_design)
    t_crit = scipy_stats.t.ppf(1 - alpha/2, df=n-k)
    margin = t_crit * np.sqrt(pred_var)

    return y_pred, y_pred - margin, y_pred + margin
```

### Key Constraints
- No sklearn dependency — pure numpy + scipy
- Handle multicollinearity gracefully (warn if predictors are highly correlated)
- Handle single predictor (use simpler `linregress`) vs multiple predictors (use design matrix)
- `predict_at` dict keys must match predictor column names

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/correlationanalysis.py` — similar numerical analysis
- `packages/ai-parrot-tools/src/parrot_tools/seasonaldetection.py` — scipy.stats usage

---

## Acceptance Criteria

- [ ] Linear regression produces correct coefficients (verified against known data)
- [ ] R-squared calculation is correct
- [ ] Coefficient p-values are correct (verified against scipy.stats.linregress for single predictor)
- [ ] Prediction with confidence interval is mathematically correct
- [ ] Polynomial (degree 2) regression works
- [ ] Log regression works (log-transforms predictors)
- [ ] Multiple predictors work via design matrix
- [ ] Returns formatted output: model equation, coefficients table, diagnostics
- [ ] Tests pass: `pytest tests/tools/test_regression_analysis.py -v`

---

## Test Specification

```python
import pytest
import pandas as pd
import numpy as np
from parrot_tools.regression_analysis import RegressionAnalysisTool


@pytest.fixture
def linear_df():
    """DataFrame with known linear relationship: y = 2x + 10 + noise."""
    np.random.seed(42)
    x = np.linspace(10, 100, 50)
    y = 2 * x + 10 + np.random.normal(0, 5, 50)
    return pd.DataFrame({'kiosks': x, 'revenue': y})


@pytest.fixture
def multi_predictor_df():
    np.random.seed(42)
    n = 100
    kiosks = np.random.uniform(20, 100, n)
    warehouses = np.random.uniform(2, 10, n)
    revenue = 1250 * kiosks - 45000 * warehouses + 125000 + np.random.normal(0, 10000, n)
    return pd.DataFrame({'kiosks': kiosks, 'warehouses': warehouses, 'revenue': revenue})


class TestRegressionAnalysis:
    @pytest.mark.asyncio
    async def test_linear_coefficient_accuracy(self, linear_df):
        tool = RegressionAnalysisTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': linear_df}})()
        result = await tool._execute(
            df_name="test", target="revenue", predictors=["kiosks"],
            model_type="linear"
        )
        assert result.success
        # Coefficient should be close to 2.0
        assert "kiosks" in str(result.result)

    @pytest.mark.asyncio
    async def test_r_squared_high_for_linear(self, linear_df):
        tool = RegressionAnalysisTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': linear_df}})()
        result = await tool._execute(
            df_name="test", target="revenue", predictors=["kiosks"]
        )
        assert result.success
        # R-squared should be high (>0.9) for near-perfect linear data

    @pytest.mark.asyncio
    async def test_prediction_at_value(self, linear_df):
        tool = RegressionAnalysisTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': linear_df}})()
        result = await tool._execute(
            df_name="test", target="revenue", predictors=["kiosks"],
            predict_at={"kiosks": 50.0}
        )
        assert result.success
        # Prediction should be close to 2*50 + 10 = 110

    @pytest.mark.asyncio
    async def test_multiple_predictors(self, multi_predictor_df):
        tool = RegressionAnalysisTool()
        tool._parent_agent = type('Agent', (), {'dataframes': {'test': multi_predictor_df}})()
        result = await tool._execute(
            df_name="test", target="revenue",
            predictors=["kiosks", "warehouses"]
        )
        assert result.success
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/whatif-toolkit-decomposition.spec.md` section 3.7
2. **Check dependencies** — this task has no dependencies (parallel)
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-462-regression-analysis-tool.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
