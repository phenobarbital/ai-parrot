"""
MonteCarloSimulationTool — Stochastic simulation with distributions.

Runs N simulations to provide probability distributions of outcomes
instead of single-point estimates.
"""
from typing import Dict, List, Optional, Type

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from .abstract import AbstractTool, ToolResult
from .whatif import DerivedMetric, MetricsCalculator


class VariableDistribution(BaseModel):
    """Distribution specification for a variable."""

    column: str = Field(description="Column name to vary")
    distribution: str = Field(
        default="normal",
        description="Distribution: 'normal', 'uniform', 'triangular', 'lognormal'",
    )
    params: Dict[str, float] = Field(
        description=(
            "Distribution params: normal={mean_pct, std_pct}, "
            "uniform={min_pct, max_pct}, "
            "triangular={min_pct, mode_pct, max_pct}, "
            "lognormal={mean_pct, std_pct}"
        )
    )


class MonteCarloInput(BaseModel):
    """Input schema for MonteCarloSimulationTool."""

    df_name: str = Field(description="Name or alias of the dataset")
    target_metrics: List[str] = Field(
        description="Metrics to measure (columns or derived)"
    )
    variables: List[VariableDistribution] = Field(
        description="Variables to randomize"
    )
    n_simulations: int = Field(
        default=10000, description="Number of simulations (1000-100000)"
    )
    derived_metrics: List[DerivedMetric] = Field(default_factory=list)
    confidence_levels: List[float] = Field(
        default=[0.05, 0.25, 0.50, 0.75, 0.95],
        description="Percentiles to report",
    )


MAX_SIMULATIONS = 100000
MIN_SIMULATIONS = 100


class MonteCarloSimulationTool(AbstractTool):
    """Run Monte Carlo simulations to provide probability distributions of outcomes.

    Answers questions like 'what is the range of possible EBITDA values if
    kiosks vary between 800-1200?' with confidence intervals.
    """

    args_schema: Type[BaseModel] = MonteCarloInput

    def __init__(self, **kwargs):
        super().__init__(
            name="montecarlo",
            description=(
                "Run Monte Carlo stochastic simulations to provide probability "
                "distributions and confidence intervals for target metrics."
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

    @staticmethod
    def _sample_multiplier(
        rng: np.random.Generator, var: VariableDistribution
    ) -> float:
        """Sample a single multiplier from the variable's distribution."""
        params = var.params
        dist = var.distribution.lower()

        if dist == "normal":
            mean_pct = params.get("mean_pct", 0)
            std_pct = params.get("std_pct", 10)
            return 1.0 + rng.normal(mean_pct, std_pct) / 100.0
        elif dist == "uniform":
            min_pct = params.get("min_pct", -20)
            max_pct = params.get("max_pct", 20)
            return 1.0 + rng.uniform(min_pct, max_pct) / 100.0
        elif dist == "triangular":
            min_pct = params.get("min_pct", -20)
            mode_pct = params.get("mode_pct", 0)
            max_pct = params.get("max_pct", 20)
            return 1.0 + rng.triangular(min_pct, mode_pct, max_pct) / 100.0
        elif dist == "lognormal":
            mean_pct = params.get("mean_pct", 0)
            std_pct = params.get("std_pct", 10)
            return np.exp(
                rng.normal(np.log(1.0 + mean_pct / 100.0), std_pct / 100.0)
            )
        else:
            raise ValueError(f"Unknown distribution: {var.distribution}")

    def _run_simulations(
        self,
        df: pd.DataFrame,
        variables: List[VariableDistribution],
        n_simulations: int,
        target_metrics: List[str],
        calculator: MetricsCalculator,
    ) -> Dict[str, np.ndarray]:
        """Run Monte Carlo simulation."""
        rng = np.random.default_rng()
        results = {metric: np.zeros(n_simulations) for metric in target_metrics}

        for i in range(n_simulations):
            df_sim = df.copy()
            for var in variables:
                if var.column in df_sim.columns:
                    multiplier = self._sample_multiplier(rng, var)
                    df_sim[var.column] = df_sim[var.column] * multiplier

            for metric in target_metrics:
                results[metric][i] = calculator.get_base_value(df_sim, metric)

        return results

    async def _execute(self, **kwargs) -> ToolResult:
        """Execute Monte Carlo simulation."""
        try:
            input_data = MonteCarloInput(**kwargs)
        except Exception as e:
            return ToolResult(success=False, result={}, error=f"Invalid input: {e}")

        # Validate n_simulations
        if input_data.n_simulations > MAX_SIMULATIONS:
            return ToolResult(
                success=False, result={},
                error=f"n_simulations ({input_data.n_simulations}) exceeds maximum ({MAX_SIMULATIONS})",
            )
        if input_data.n_simulations < MIN_SIMULATIONS:
            return ToolResult(
                success=False, result={},
                error=f"n_simulations ({input_data.n_simulations}) below minimum ({MIN_SIMULATIONS})",
            )

        try:
            df = self._get_dataframe(input_data.df_name)
        except ValueError as e:
            return ToolResult(success=False, result={}, error=str(e))

        # Setup calculator
        calculator = MetricsCalculator()
        for dm in input_data.derived_metrics:
            calculator.register_metric(dm.name, dm.formula, dm.description or "")

        # Validate target metrics
        for metric in input_data.target_metrics:
            try:
                calculator.get_base_value(df, metric)
            except Exception as e:
                return ToolResult(
                    success=False, result={},
                    error=f"Cannot calculate metric '{metric}': {e}",
                )

        # Validate variables
        for var in input_data.variables:
            if var.column not in df.columns:
                return ToolResult(
                    success=False, result={},
                    error=f"Variable column '{var.column}' not found in dataset",
                )

        # Run simulations
        try:
            sim_results = self._run_simulations(
                df,
                input_data.variables,
                input_data.n_simulations,
                input_data.target_metrics,
                calculator,
            )
        except Exception as e:
            return ToolResult(
                success=False, result={},
                error=f"Simulation error: {e}",
            )

        # Calculate percentiles
        percentile_data = {}
        for metric, values in sim_results.items():
            pcts = np.percentile(values, [l * 100 for l in input_data.confidence_levels])
            percentile_data[metric] = {
                f"P{int(cl * 100)}": pct
                for cl, pct in zip(input_data.confidence_levels, pcts)
            }
            percentile_data[metric]["mean"] = float(np.mean(values))
            percentile_data[metric]["std"] = float(np.std(values))

        # Format output
        var_desc = ", ".join(
            f"{v.column} ({v.distribution})" for v in input_data.variables
        )
        lines = [
            f"Monte Carlo Simulation ({input_data.n_simulations:,} runs):",
            f"Variables: {var_desc}",
            "",
        ]

        # Percentile table
        pct_labels = [f"P{int(cl * 100)}" for cl in input_data.confidence_levels]
        header = "| Metric | " + " | ".join(pct_labels) + " |"
        sep = "|--------|" + "|".join(["--------"] * len(pct_labels)) + "|"
        lines.append(header)
        lines.append(sep)

        for metric, pdata in percentile_data.items():
            vals = [f"${pdata[lbl]:,.0f}" for lbl in pct_labels]
            lines.append(f"| {metric} | " + " | ".join(vals) + " |")

        lines.append("")
        for metric, pdata in percentile_data.items():
            lines.append(
                f"{metric}: mean=${pdata['mean']:,.0f}, std=${pdata['std']:,.0f}"
            )

        return ToolResult(
            success=True,
            result="\n".join(lines),
            metadata={"percentiles": percentile_data, "n_simulations": input_data.n_simulations},
        )
