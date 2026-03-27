"""
BreakEvenAnalysisTool — threshold and root-finding analysis.

Finds the variable value where a target metric reaches a specified threshold.
Uses scipy.optimize.brentq for root finding.
"""
from typing import Dict, List, Optional, Type

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scipy.optimize import brentq

from .abstract import AbstractTool, ToolResult
from .whatif import DerivedMetric, MetricsCalculator


class BreakEvenInput(BaseModel):
    """Input schema for BreakEvenAnalysisTool."""

    df_name: str = Field(description="Name or alias of the dataset")
    target_metric: str = Field(
        description="Metric that must reach the threshold (e.g., 'ebitda')"
    )
    target_value: float = Field(
        default=0.0,
        description="Target value for break-even (default: 0 for true break-even)",
    )
    variable: str = Field(
        description="Variable to solve for (e.g., 'kiosks')"
    )
    variable_range: Optional[List[float]] = Field(
        default=None,
        description="Search range [min, max]. If None, uses 0 to 10x current value",
    )
    fixed_changes: Dict[str, float] = Field(
        default_factory=dict,
        description="Fixed changes to apply before solving (e.g., {'warehouses': 4})",
    )
    derived_metrics: List[DerivedMetric] = Field(default_factory=list)


class BreakEvenAnalysisTool(AbstractTool):
    """Find threshold values for target metrics.

    Answers 'how many kiosks do we need to cover the cost of 4 new warehouses?'
    using root-finding algorithms.
    """

    args_schema: Type[BaseModel] = BreakEvenInput

    def __init__(self, **kwargs):
        super().__init__(
            name="breakeven",
            description=(
                "Find the break-even point: the variable value where a target "
                "metric reaches a specified threshold."
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

    def _build_objective(
        self,
        df: pd.DataFrame,
        variable: str,
        target_metric: str,
        target_value: float,
        fixed_changes: Dict[str, float],
        calculator: MetricsCalculator,
        current_var_sum: float,
    ):
        """Build the objective function f(x) = metric_at(x) - target."""

        def objective(x_total: float) -> float:
            scale_factor = x_total / current_var_sum if current_var_sum > 0 else 1.0
            df_mod = df.copy()

            # Apply fixed changes
            for col, change in fixed_changes.items():
                if col in df_mod.columns:
                    df_mod[col] = df_mod[col].astype(float) + change

            # Scale the variable
            df_mod[variable] = df_mod[variable].astype(float) * scale_factor

            metric_value = calculator.get_base_value(df_mod, target_metric)
            return metric_value - target_value

        return objective

    def _generate_sensitivity_curve(
        self,
        df: pd.DataFrame,
        variable: str,
        target_metric: str,
        fixed_changes: Dict[str, float],
        calculator: MetricsCalculator,
        current_var_sum: float,
        breakeven_value: Optional[float],
        n_points: int = 9,
    ) -> List[Dict]:
        """Generate sensitivity curve around break-even."""
        if breakeven_value is not None:
            lo = current_var_sum * 0.5
            hi = max(breakeven_value * 1.5, current_var_sum * 1.5)
        else:
            lo = current_var_sum * 0.1
            hi = current_var_sum * 3.0

        points = np.linspace(lo, hi, n_points)
        curve = []
        for x_val in points:
            scale = x_val / current_var_sum if current_var_sum > 0 else 1.0
            df_mod = df.copy()
            for col, change in fixed_changes.items():
                if col in df_mod.columns:
                    df_mod[col] = df_mod[col].astype(float) + change
            df_mod[variable] = df_mod[variable].astype(float) * scale
            metric_val = calculator.get_base_value(df_mod, target_metric)
            curve.append({"variable_total": float(x_val), "metric_value": float(metric_val)})
        return curve

    async def _execute(self, **kwargs) -> ToolResult:
        """Execute break-even analysis."""
        try:
            input_data = BreakEvenInput(**kwargs)
        except Exception as e:
            return ToolResult(success=False, result={}, error=f"Invalid input: {e}")

        try:
            df = self._get_dataframe(input_data.df_name)
        except ValueError as e:
            return ToolResult(success=False, result={}, error=str(e))

        if input_data.variable not in df.columns:
            return ToolResult(
                success=False, result={},
                error=f"Variable column '{input_data.variable}' not found",
            )

        # Setup calculator
        calculator = MetricsCalculator()
        for dm in input_data.derived_metrics:
            calculator.register_metric(dm.name, dm.formula, dm.description or "")

        # Verify target metric
        try:
            calculator.get_base_value(df, input_data.target_metric)
        except Exception as e:
            return ToolResult(
                success=False, result={},
                error=f"Cannot calculate target metric '{input_data.target_metric}': {e}",
            )

        current_var_sum = float(df[input_data.variable].sum())
        if current_var_sum == 0:
            return ToolResult(
                success=False, result={},
                error=f"Variable '{input_data.variable}' has sum of 0, cannot scale",
            )

        # Current metric value (with fixed changes applied)
        df_current = df.copy()
        for col, change in input_data.fixed_changes.items():
            if col in df_current.columns:
                df_current[col] = df_current[col].astype(float) + change
        current_metric = calculator.get_base_value(df_current, input_data.target_metric)

        # Build objective function
        objective = self._build_objective(
            df, input_data.variable, input_data.target_metric,
            input_data.target_value, input_data.fixed_changes,
            calculator, current_var_sum,
        )

        # Determine search range
        if input_data.variable_range:
            lo, hi = input_data.variable_range
        else:
            lo = max(current_var_sum * 0.01, 0.01)
            hi = current_var_sum * 10

        # Try root finding
        breakeven_value = None
        error_msg = None
        try:
            f_lo = objective(lo)
            f_hi = objective(hi)
            if f_lo * f_hi > 0:
                error_msg = "No break-even point found in the specified range"
            else:
                breakeven_value = brentq(objective, lo, hi, xtol=0.01)
        except Exception as e:
            error_msg = f"Root finding error: {e}"

        # Sensitivity curve
        curve = self._generate_sensitivity_curve(
            df, input_data.variable, input_data.target_metric,
            input_data.fixed_changes, calculator,
            current_var_sum, breakeven_value,
        )

        # Format output
        lines = ["Break-Even Analysis:", ""]

        if input_data.fixed_changes:
            changes_desc = ", ".join(
                f"{k}: +{v}" for k, v in input_data.fixed_changes.items()
            )
            lines.append(f"Fixed changes applied: {changes_desc}")

        lines.append(
            f"Current {input_data.variable}: {current_var_sum:,.0f}"
        )
        lines.append(
            f"Current {input_data.target_metric} (after fixed changes): "
            f"{current_metric:,.2f}"
        )
        lines.append(
            f"Target {input_data.target_metric}: {input_data.target_value:,.2f}"
        )
        lines.append("")

        if breakeven_value is not None:
            delta = breakeven_value - current_var_sum
            lines.append(
                f"Break-even point: {breakeven_value:,.0f} {input_data.variable} "
                f"(need {delta:+,.0f})"
            )
            margin = current_var_sum - breakeven_value
            lines.append(f"Margin of safety: {margin:+,.0f} {input_data.variable}")
        else:
            lines.append(f"No break-even found: {error_msg}")

        lines.append("")
        lines.append("Sensitivity curve:")
        lines.append(f"| {input_data.variable} | {input_data.target_metric} |")
        lines.append("|----------|-----------|")
        for point in curve:
            marker = ""
            if breakeven_value and abs(point["variable_total"] - breakeven_value) < (hi - lo) / 20:
                marker = " <-- break-even"
            lines.append(
                f"| {point['variable_total']:,.0f} | "
                f"{point['metric_value']:,.2f}{marker} |"
            )

        return ToolResult(
            success=True,
            result="\n".join(lines),
            metadata={
                "breakeven_value": breakeven_value,
                "current_value": current_var_sum,
                "current_metric": current_metric,
                "sensitivity_curve": curve,
            },
        )
