"""
SensitivityAnalysisTool — One-at-a-time sensitivity analysis.

Determines which input variables have the greatest impact on a target metric.
Generates tornado-style rankings and elasticity coefficients.
"""
from typing import Dict, List, Optional, Type

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from .abstract import AbstractTool, ToolResult
from .whatif import DerivedMetric, MetricsCalculator


class SensitivityAnalysisInput(BaseModel):
    """Input schema for SensitivityAnalysisTool."""

    df_name: str = Field(description="Name or alias of the dataset")
    target_metric: str = Field(
        description="Target column or derived metric to analyze"
    )
    input_variables: Optional[List[str]] = Field(
        default=None,
        description="Columns to vary. If None, uses all numeric columns except target",
    )
    variation_range: float = Field(
        default=20.0,
        description="Percentage variation to test (e.g., 20 means +/-20%)",
    )
    derived_metrics: List[DerivedMetric] = Field(
        default_factory=list,
        description="Formulas for computed metrics",
    )
    method: str = Field(
        default="one_at_a_time",
        description="Method: 'one_at_a_time' (tornado) or 'all_at_once' (spider)",
    )


class SensitivityAnalysisTool(AbstractTool):
    """Analyze which variables have the greatest impact on a target metric.

    Performs one-at-a-time sensitivity analysis: varies each input variable
    by +/-N% while holding others constant, measures impact on the target
    metric, and ranks variables by absolute impact.
    """

    args_schema: Type[BaseModel] = SensitivityAnalysisInput

    def __init__(self, **kwargs):
        super().__init__(
            name="sensitivity_analysis",
            description=(
                "Analyze which variables have the greatest impact on a target metric. "
                "Varies each input by +/-N% and ranks by impact and elasticity."
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

    async def _execute(self, **kwargs) -> ToolResult:
        """Execute sensitivity analysis."""
        try:
            input_data = SensitivityAnalysisInput(**kwargs)
        except Exception as e:
            return ToolResult(success=False, result={}, error=f"Invalid input: {e}")

        try:
            df = self._get_dataframe(input_data.df_name)
        except ValueError as e:
            return ToolResult(success=False, result={}, error=str(e))

        # Setup calculator
        calculator = MetricsCalculator()
        for dm in input_data.derived_metrics:
            calculator.register_metric(dm.name, dm.formula, dm.description or "")

        # Calculate base value
        try:
            base_value = calculator.get_base_value(df, input_data.target_metric)
        except Exception as e:
            return ToolResult(
                success=False, result={},
                error=f"Cannot calculate target metric '{input_data.target_metric}': {e}",
            )

        # Determine variables to analyze
        variables = input_data.input_variables
        if variables is None:
            variables = [
                c
                for c in df.select_dtypes(include="number").columns
                if c != input_data.target_metric
            ]

        if not variables:
            return ToolResult(
                success=False, result={},
                error="No numeric input variables found to analyze",
            )

        variation = input_data.variation_range / 100.0
        results = []

        for var in variables:
            if var not in df.columns:
                continue
            if not pd.api.types.is_numeric_dtype(df[var]):
                continue

            base_var_sum = df[var].sum()

            impacts = {}
            for direction, factor in [("low", 1 - variation), ("high", 1 + variation)]:
                df_mod = df.copy()
                df_mod[var] = df_mod[var] * factor
                new_value = calculator.get_base_value(df_mod, input_data.target_metric)
                impacts[direction] = new_value - base_value

            abs_range = abs(impacts["high"] - impacts["low"])

            # Elasticity = (% change in output) / (% change in input)
            if base_value != 0 and base_var_sum != 0:
                pct_output = (impacts["high"] - impacts["low"]) / abs(base_value)
                pct_input = 2 * variation  # from -var to +var
                elasticity = pct_output / pct_input if pct_input != 0 else 0.0
            else:
                elasticity = 0.0

            results.append({
                "variable": var,
                "low_impact": impacts["low"],
                "high_impact": impacts["high"],
                "range": abs_range,
                "elasticity": elasticity,
            })

        # Sort by absolute range (descending)
        results.sort(key=lambda r: r["range"], reverse=True)

        # Format output
        lines = [
            f"Sensitivity Analysis for '{input_data.target_metric}' "
            f"(+/-{input_data.variation_range}% variation):",
            f"Base value: {base_value:,.2f}",
            "",
            "| Variable | -{0}% Impact | +{0}% Impact | Range | Elasticity |".format(
                int(input_data.variation_range)
            ),
            "|----------|-------------|-------------|-------|------------|",
        ]

        for r in results:
            lines.append(
                f"| {r['variable']} | {r['low_impact']:+,.0f} | "
                f"{r['high_impact']:+,.0f} | {r['range']:,.0f} | "
                f"{r['elasticity']:.2f} |"
            )

        if results:
            lines.append("")
            lines.append(
                f"Top driver: '{results[0]['variable']}' has the highest "
                f"impact on {input_data.target_metric}."
            )

        return ToolResult(
            success=True,
            result="\n".join(lines),
            metadata={"results": results, "base_value": base_value},
        )
