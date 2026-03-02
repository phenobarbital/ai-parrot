"""
Pydantic models for QuantToolkit input/output contracts.

These models define the data structures used across all quantitative
analysis functions: risk metrics, correlation, Piotroski F-Score,
volatility analytics, and stress testing.
"""

from typing import Literal
from pydantic import BaseModel, Field, model_validator


# =============================================================================
# INPUT MODELS
# =============================================================================


class PortfolioRiskInput(BaseModel):
    """Input for portfolio-level risk computation.

    Used by compute_portfolio_risk() to calculate VaR, CVaR, beta,
    Sharpe ratio, and other portfolio-level metrics.
    """

    returns_data: dict[str, list[float]] = Field(
        ...,
        description="Dict of {symbol: [daily_returns]} for each position",
    )
    weights: list[float] = Field(
        ...,
        description="Position weights (must sum to 1.0)",
    )
    symbols: list[str] = Field(
        ...,
        description="Symbol names matching returns_data keys",
    )
    confidence: float = Field(
        0.95,
        ge=0.01,
        le=0.99,
        description="VaR confidence level (e.g., 0.95 for 95%)",
    )
    risk_free_rate: float = Field(
        0.04,
        description="Annualized risk-free rate (e.g., 0.04 for 4%)",
    )
    annualization_factor: int = Field(
        252,
        description="Trading days per year (252 for stocks, 365 for crypto)",
    )

    @model_validator(mode="after")
    def validate_weights(self) -> "PortfolioRiskInput":
        """Validate that weights sum to 1.0 and match symbols length."""
        weight_sum = sum(self.weights)
        if abs(weight_sum - 1.0) > 0.01:
            raise ValueError(
                f"Weights must sum to 1.0, got {weight_sum:.4f}"
            )
        if len(self.weights) != len(self.symbols):
            raise ValueError(
                f"weights and symbols must have same length "
                f"(weights={len(self.weights)}, symbols={len(self.symbols)})"
            )
        return self


class AssetRiskInput(BaseModel):
    """Input for single-asset risk metrics.

    Used by compute_risk_metrics() to calculate VaR, CVaR, beta,
    Sharpe ratio, and maximum drawdown for a single asset.
    """

    returns: list[float] = Field(
        ...,
        description="Daily return series for the asset",
    )
    benchmark_returns: list[float] | None = Field(
        None,
        description="Benchmark returns for beta calculation (e.g., SPY)",
    )
    risk_free_rate: float = Field(
        0.04,
        description="Annualized risk-free rate",
    )
    annualization_factor: int = Field(
        252,
        description="Trading days per year (252 for stocks, 365 for crypto)",
    )


class CorrelationInput(BaseModel):
    """Input for correlation analysis.

    Used by compute_correlation_matrix() to calculate pairwise
    correlations between multiple assets.
    """

    price_data: dict[str, list[float]] = Field(
        ...,
        description="Dict of {symbol: [close_prices]} for each asset",
    )
    method: Literal["pearson", "spearman", "kendall"] = Field(
        "pearson",
        description="Correlation method to use",
    )
    returns_based: bool = Field(
        True,
        description="If True, convert prices to returns before correlating (recommended)",
    )


class StressScenario(BaseModel):
    """A single stress test scenario definition.

    Used by stress_test_portfolio() to define hypothetical or historical
    shock scenarios with percentage changes per asset.
    """

    name: str = Field(
        ...,
        description="Scenario name (e.g., 'covid_crash_2020', 'rate_hike_shock')",
    )
    description: str | None = Field(
        None,
        description="Human-readable description of the scenario",
    )
    asset_shocks: dict[str, float] = Field(
        ...,
        description="Dict of {symbol: shock_pct} where shock_pct is decimal (e.g., -0.34 for -34%)",
    )


class PiotroskiInput(BaseModel):
    """Input for Piotroski F-Score calculation.

    Used by calculate_piotroski_score() to evaluate company financial
    health using 9 accounting criteria.
    """

    quarterly_financials: dict[str, float] = Field(
        ...,
        description="Current quarter financial data (net_income, total_assets, etc.)",
    )
    prior_year_financials: dict[str, float] = Field(
        default_factory=dict,
        description="Prior year data for YoY comparison (current_ratio, gross_margin, etc.)",
    )


# =============================================================================
# OUTPUT MODELS
# =============================================================================


class RiskMetricsOutput(BaseModel):
    """Output from single-asset risk calculation.

    Contains all computed risk metrics for a single asset.
    """

    volatility_annual: float = Field(
        ...,
        description="Annualized volatility (standard deviation of returns)",
    )
    beta: float | None = Field(
        None,
        description="Beta relative to benchmark (None if no benchmark provided)",
    )
    sharpe_ratio: float = Field(
        ...,
        description="Annualized Sharpe ratio (excess return / volatility)",
    )
    max_drawdown: float = Field(
        ...,
        description="Maximum drawdown as decimal (e.g., -0.25 for -25%)",
    )
    var_95: float = Field(
        ...,
        description="1-day Value at Risk at 95% confidence (decimal)",
    )
    var_99: float = Field(
        ...,
        description="1-day Value at Risk at 99% confidence (decimal)",
    )
    cvar_95: float = Field(
        ...,
        description="Conditional VaR (Expected Shortfall) at 95% confidence",
    )


class PortfolioRiskOutput(BaseModel):
    """Output from portfolio risk calculation.

    Contains portfolio-level risk metrics for use in AnalystReport
    and ExecutorConstraints validation.
    """

    var_1d_95_pct: float = Field(
        ...,
        description="1-day portfolio VaR at 95% confidence as percentage",
    )
    var_1d_99_pct: float = Field(
        ...,
        description="1-day portfolio VaR at 99% confidence as percentage",
    )
    cvar_1d_95_pct: float = Field(
        ...,
        description="1-day portfolio CVaR at 95% confidence as percentage",
    )
    portfolio_volatility: float = Field(
        ...,
        description="Annualized portfolio volatility",
    )
    portfolio_beta: float | None = Field(
        None,
        description="Portfolio beta relative to benchmark",
    )
    portfolio_sharpe: float = Field(
        ...,
        description="Annualized portfolio Sharpe ratio",
    )
    max_drawdown: float = Field(
        ...,
        description="Maximum portfolio drawdown as decimal",
    )
    net_exposure: float = Field(
        ...,
        description="Net exposure (long - short) as decimal",
    )
    gross_exposure: float = Field(
        ...,
        description="Gross exposure (|long| + |short|) as decimal",
    )
