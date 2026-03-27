"""
RegressionAnalysisTool — linear/polynomial/log regression.

Models quantitative relationships between variables using pure numpy + scipy.
"""
from typing import Dict, List, Optional, Type

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scipy import stats as scipy_stats

from .abstract import AbstractTool, ToolResult


class RegressionInput(BaseModel):
    """Input schema for RegressionAnalysisTool."""

    df_name: str = Field(description="Name or alias of the dataset")
    target: str = Field(description="Dependent variable (Y) to predict")
    predictors: List[str] = Field(
        description="Independent variables (X1, X2, ...)"
    )
    model_type: str = Field(
        default="linear",
        description="Model: 'linear', 'polynomial' (degree 2), 'log'",
    )
    predict_at: Optional[Dict[str, float]] = Field(
        default=None,
        description="Predict Y for given X values (e.g., {'kiosks': 1450})",
    )
    include_diagnostics: bool = Field(
        default=True,
        description="Include R-squared, residual analysis, significance tests",
    )


class RegressionAnalysisTool(AbstractTool):
    """Model quantitative relationships between variables.

    Fits linear, polynomial, or log regression using numpy/scipy.
    Returns model equation, coefficients, fit diagnostics, and predictions.
    """

    args_schema: Type[BaseModel] = RegressionInput

    def __init__(self, **kwargs):
        super().__init__(
            name="regression_analysis",
            description=(
                "Model relationships between variables using linear, polynomial, "
                "or log regression. Returns equation, R-squared, and predictions."
            ),
            **kwargs,
        )
        self._parent_agent = None

    def _get_dataframe(self, df_name: str) -> pd.DataFrame:
        """Resolve DataFrame from parent agent."""
        if self._parent_agent and hasattr(self._parent_agent, "dataframes"):
            df = self._parent_agent.dataframes.get(df_name)
            if df is not None:
                return df
        raise ValueError(f"Dataset '{df_name}' not found")

    def _fit_linear(
        self, X: np.ndarray, y: np.ndarray, predictor_names: List[str]
    ) -> Dict:
        """OLS regression using numpy only."""
        n = len(y)
        X_design = np.column_stack([np.ones(n), X])
        k = X_design.shape[1]

        coeffs, residuals, rank, sv = np.linalg.lstsq(X_design, y, rcond=None)

        y_pred = X_design @ coeffs
        resid = y - y_pred

        ss_res = np.sum(resid ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        adj_r_squared = (
            1 - (1 - r_squared) * (n - 1) / (n - k)
            if n > k
            else 0.0
        )

        # Standard errors and t-statistics
        mse = ss_res / (n - k) if n > k else 0.0
        try:
            var_coeff = mse * np.linalg.inv(X_design.T @ X_design).diagonal()
            se = np.sqrt(np.abs(var_coeff))
            t_stats = coeffs / np.where(se > 0, se, 1.0)
            p_values = [
                float(2 * (1 - scipy_stats.t.cdf(abs(t), df=max(n - k, 1))))
                for t in t_stats
            ]
        except np.linalg.LinAlgError:
            se = np.zeros(k)
            t_stats = np.zeros(k)
            p_values = [1.0] * k

        names = ["intercept"] + predictor_names

        return {
            "coefficients": coeffs,
            "names": names,
            "std_errors": se,
            "t_statistics": t_stats,
            "p_values": p_values,
            "r_squared": r_squared,
            "adj_r_squared": adj_r_squared,
            "residuals": resid,
            "mse": mse,
            "X_design": X_design,
            "n": n,
            "k": k,
        }

    def _predict_with_ci(
        self, X_new: np.ndarray, fit_result: Dict, alpha: float = 0.05
    ) -> tuple:
        """Predict with prediction interval."""
        X_new_design = np.concatenate([[1], X_new])
        y_pred = X_new_design @ fit_result["coefficients"]

        try:
            XtX_inv = np.linalg.inv(
                fit_result["X_design"].T @ fit_result["X_design"]
            )
            pred_var = fit_result["mse"] * (1 + X_new_design @ XtX_inv @ X_new_design)
            t_crit = scipy_stats.t.ppf(
                1 - alpha / 2, df=max(fit_result["n"] - fit_result["k"], 1)
            )
            margin = t_crit * np.sqrt(max(pred_var, 0))
        except Exception:
            margin = 0.0

        return float(y_pred), float(y_pred - margin), float(y_pred + margin)

    async def _execute(self, **kwargs) -> ToolResult:
        """Execute regression analysis."""
        try:
            input_data = RegressionInput(**kwargs)
        except Exception as e:
            return ToolResult(success=False, result={}, error=f"Invalid input: {e}")

        try:
            df = self._get_dataframe(input_data.df_name)
        except ValueError as e:
            return ToolResult(success=False, result={}, error=str(e))

        # Validate columns
        if input_data.target not in df.columns:
            return ToolResult(
                success=False, result={},
                error=f"Target column '{input_data.target}' not found",
            )
        for p in input_data.predictors:
            if p not in df.columns:
                return ToolResult(
                    success=False, result={},
                    error=f"Predictor column '{p}' not found",
                )

        # Drop NaN rows
        cols = [input_data.target] + input_data.predictors
        df_clean = df[cols].dropna()
        if len(df_clean) < 3:
            return ToolResult(
                success=False, result={},
                error="Not enough data points (need at least 3)",
            )

        y = df_clean[input_data.target].values.astype(float)
        X_raw = df_clean[input_data.predictors].values.astype(float)

        model_type = input_data.model_type.lower()
        predictor_names = list(input_data.predictors)

        # Transform features based on model type
        if model_type == "polynomial":
            # Degree 2 polynomial for each predictor
            X_poly_parts = [X_raw]
            poly_names = list(predictor_names)
            for i, name in enumerate(input_data.predictors):
                X_poly_parts.append(X_raw[:, i : i + 1] ** 2)
                poly_names.append(f"{name}^2")
            X = np.hstack(X_poly_parts)
            predictor_names = poly_names
        elif model_type == "log":
            # Log-transform predictors (handle zeros)
            X = np.log(np.maximum(X_raw, 1e-10))
            predictor_names = [f"log({n})" for n in predictor_names]
        else:
            X = X_raw

        # Fit model
        try:
            fit = self._fit_linear(X, y, predictor_names)
        except Exception as e:
            return ToolResult(
                success=False, result={},
                error=f"Regression fitting error: {e}",
            )

        # Format output
        lines = [
            f"{model_type.capitalize()} Regression: {input_data.target} ~ "
            f"{' + '.join(input_data.predictors)}",
            "",
        ]

        # Model equation
        eq_parts = [f"{fit['coefficients'][0]:,.2f}"]
        for i, name in enumerate(predictor_names):
            coeff = fit["coefficients"][i + 1]
            eq_parts.append(f"{coeff:+,.2f} * {name}")
        lines.append(f"Model: {input_data.target} = {' '.join(eq_parts)}")
        lines.append(f"R-squared: {fit['r_squared']:.4f}")
        lines.append(f"Adjusted R-squared: {fit['adj_r_squared']:.4f}")
        lines.append("")

        # Coefficients table
        if input_data.include_diagnostics:
            lines.append(
                "| Predictor | Coefficient | Std Error | t-stat | p-value | Significant |"
            )
            lines.append(
                "|-----------|-------------|-----------|--------|---------|-------------|"
            )
            for i, name in enumerate(fit["names"]):
                coeff = fit["coefficients"][i]
                se = fit["std_errors"][i]
                t = fit["t_statistics"][i]
                p = fit["p_values"][i]
                sig = "Yes" if p < 0.05 else "No"
                lines.append(
                    f"| {name} | {coeff:,.4f} | {se:,.4f} | "
                    f"{t:.2f} | {p:.4f} | {sig} |"
                )

        # Prediction
        if input_data.predict_at:
            lines.append("")
            x_vals = []
            for p in input_data.predictors:
                x_vals.append(input_data.predict_at.get(p, 0.0))

            x_arr = np.array(x_vals)
            if model_type == "polynomial":
                x_arr = np.concatenate([x_arr, x_arr ** 2])
            elif model_type == "log":
                x_arr = np.log(np.maximum(x_arr, 1e-10))

            y_pred, ci_lo, ci_hi = self._predict_with_ci(x_arr, fit)
            pred_desc = ", ".join(
                f"{k}={v}" for k, v in input_data.predict_at.items()
            )
            lines.append(f"Prediction at {pred_desc}:")
            lines.append(
                f"  Expected {input_data.target}: {y_pred:,.2f} "
                f"(95% CI: [{ci_lo:,.2f}, {ci_hi:,.2f}])"
            )

        return ToolResult(
            success=True,
            result="\n".join(lines),
            metadata={
                "r_squared": fit["r_squared"],
                "adj_r_squared": fit["adj_r_squared"],
                "coefficients": {
                    name: float(fit["coefficients"][i])
                    for i, name in enumerate(fit["names"])
                },
            },
        )
