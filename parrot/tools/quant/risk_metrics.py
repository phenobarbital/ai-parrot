"""
Risk Metrics Engine for QuantToolkit.

Provides comprehensive risk calculations for single assets and portfolios:
- VaR (Value at Risk) - parametric and historical methods
- CVaR (Conditional VaR / Expected Shortfall)
- Beta vs benchmark
- Sharpe ratio
- Maximum drawdown
- Rolling metrics
"""

import numpy as np
import pandas as pd
from scipy import stats

from .models import (
    AssetRiskInput,
    PortfolioRiskInput,
    RiskMetricsOutput,
    PortfolioRiskOutput,
)


# =============================================================================
# RETURNS COMPUTATION
# =============================================================================


def compute_returns(prices: list[float]) -> np.ndarray:
    """Convert price series to daily returns.

    Args:
        prices: List of closing prices.

    Returns:
        Array of daily returns (pct_change).
    """
    prices_arr = np.array(prices)
    if len(prices_arr) < 2:
        return np.array([])
    return np.diff(prices_arr) / prices_arr[:-1]


# =============================================================================
# VALUE AT RISK (VaR)
# =============================================================================


def compute_var_parametric(
    returns: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Parametric VaR assuming normal distribution.

    VaR_alpha = mu + z_alpha * sigma

    Where z_alpha is the z-score for the (1-confidence) quantile.

    Args:
        returns: Array of daily returns.
        confidence: Confidence level (e.g., 0.95 for 95%).

    Returns:
        VaR as a decimal (negative value indicates loss).
    """
    if len(returns) == 0:
        return 0.0
    mean = np.mean(returns)
    std = np.std(returns, ddof=1)
    if std == 0:
        return 0.0
    z_score = stats.norm.ppf(1 - confidence)
    return float(mean + z_score * std)


def compute_var_historical(
    returns: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Historical VaR using empirical percentile.

    Args:
        returns: Array of daily returns.
        confidence: Confidence level (e.g., 0.95 for 95%).

    Returns:
        VaR as a decimal (negative value indicates loss).
    """
    if len(returns) == 0:
        return 0.0
    percentile = (1 - confidence) * 100
    return float(np.percentile(returns, percentile))


# =============================================================================
# CONDITIONAL VaR (CVaR / Expected Shortfall)
# =============================================================================


def compute_cvar(
    returns: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Conditional VaR (Expected Shortfall).

    Average of returns beyond the VaR threshold.
    CVaR is always more conservative (more negative) than VaR.

    Args:
        returns: Array of daily returns.
        confidence: Confidence level.

    Returns:
        CVaR as a decimal (negative value indicates loss).
    """
    if len(returns) == 0:
        return 0.0
    var = compute_var_parametric(returns, confidence)
    tail_losses = returns[returns <= var]
    if len(tail_losses) == 0:
        return var
    return float(np.mean(tail_losses))


# =============================================================================
# MAXIMUM DRAWDOWN
# =============================================================================


def compute_max_drawdown(returns: np.ndarray) -> float:
    """Maximum drawdown from cumulative returns.

    Args:
        returns: Array of daily returns.

    Returns:
        Maximum drawdown as a decimal (negative value).
    """
    if len(returns) == 0:
        return 0.0
    cumulative = (1 + returns).cumprod()
    running_max = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - running_max) / running_max
    return float(np.min(drawdown))


# =============================================================================
# BETA
# =============================================================================


def compute_beta(
    asset_returns: np.ndarray,
    benchmark_returns: np.ndarray,
) -> float:
    """Beta = Cov(asset, benchmark) / Var(benchmark).

    Args:
        asset_returns: Asset daily returns.
        benchmark_returns: Benchmark daily returns.

    Returns:
        Beta coefficient.

    Raises:
        ValueError: If arrays have different lengths.
    """
    if len(asset_returns) != len(benchmark_returns):
        raise ValueError("Returns arrays must have same length")
    if len(asset_returns) == 0:
        return 0.0
    benchmark_var = np.var(benchmark_returns, ddof=1)
    if benchmark_var == 0:
        return 0.0
    covariance = np.cov(asset_returns, benchmark_returns)[0, 1]
    return float(covariance / benchmark_var)


# =============================================================================
# SHARPE RATIO
# =============================================================================


def compute_sharpe_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.04,
    annualization_factor: int = 252,
) -> float:
    """Annualized Sharpe ratio.

    Sharpe = (annualized_return - risk_free_rate) / annualized_volatility

    Args:
        returns: Array of daily returns.
        risk_free_rate: Annualized risk-free rate (e.g., 0.04 for 4%).
        annualization_factor: Trading days per year (252 for stocks, 365 for crypto).

    Returns:
        Annualized Sharpe ratio.
    """
    if len(returns) == 0:
        return 0.0
    annual_return = np.mean(returns) * annualization_factor
    annual_vol = np.std(returns, ddof=1) * np.sqrt(annualization_factor)
    if annual_vol == 0:
        return 0.0
    excess_return = annual_return - risk_free_rate
    return float(excess_return / annual_vol)


# =============================================================================
# VOLATILITY
# =============================================================================


def compute_volatility_annual(
    returns: np.ndarray,
    annualization_factor: int = 252,
) -> float:
    """Annualized volatility.

    Args:
        returns: Array of daily returns.
        annualization_factor: Trading days per year.

    Returns:
        Annualized volatility.
    """
    if len(returns) == 0:
        return 0.0
    daily_std = np.std(returns, ddof=1)
    return float(daily_std * np.sqrt(annualization_factor))


# =============================================================================
# PORTFOLIO VAR
# =============================================================================


def compute_portfolio_var_parametric(
    returns_df: pd.DataFrame,
    weights: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Portfolio VaR using variance-covariance method.

    portfolio_var = z * sqrt(w' * Cov * w)

    Args:
        returns_df: DataFrame with asset returns (columns are assets).
        weights: Portfolio weights.
        confidence: Confidence level.

    Returns:
        Portfolio VaR as a decimal.
    """
    if returns_df.empty or len(weights) == 0:
        return 0.0
    cov_matrix = returns_df.cov().values
    portfolio_variance = np.dot(weights, np.dot(cov_matrix, weights))
    portfolio_std = np.sqrt(portfolio_variance)
    z_score = stats.norm.ppf(1 - confidence)
    return float(z_score * portfolio_std)


def compute_portfolio_var_historical(
    returns_df: pd.DataFrame,
    weights: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Portfolio VaR using historical simulation.

    Computes portfolio returns for each day and takes the empirical percentile.

    Args:
        returns_df: DataFrame with asset returns.
        weights: Portfolio weights.
        confidence: Confidence level.

    Returns:
        Portfolio VaR as a decimal.
    """
    if returns_df.empty or len(weights) == 0:
        return 0.0
    portfolio_returns = returns_df.values @ weights
    percentile = (1 - confidence) * 100
    return float(np.percentile(portfolio_returns, percentile))


def compute_portfolio_cvar(
    returns_df: pd.DataFrame,
    weights: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Portfolio CVaR (Expected Shortfall).

    Args:
        returns_df: DataFrame with asset returns.
        weights: Portfolio weights.
        confidence: Confidence level.

    Returns:
        Portfolio CVaR as a decimal.
    """
    if returns_df.empty or len(weights) == 0:
        return 0.0
    portfolio_returns = returns_df.values @ weights
    return compute_cvar(portfolio_returns, confidence)


# =============================================================================
# ROLLING METRICS
# =============================================================================


def compute_rolling_metrics(
    returns: np.ndarray,
    window: int = 20,
    risk_free_rate: float = 0.04,
    annualization_factor: int = 252,
    benchmark_returns: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Compute rolling risk metrics.

    Args:
        returns: Array of daily returns.
        window: Rolling window size.
        risk_free_rate: Annualized risk-free rate.
        annualization_factor: Trading days per year.
        benchmark_returns: Optional benchmark for beta calculation.

    Returns:
        Dictionary with rolling metrics arrays:
        - rolling_vol: Rolling annualized volatility
        - rolling_sharpe: Rolling Sharpe ratio
        - rolling_var_95: Rolling 95% VaR
        - rolling_beta: Rolling beta (if benchmark provided)
    """
    if len(returns) < window:
        return {
            "rolling_vol": np.array([]),
            "rolling_sharpe": np.array([]),
            "rolling_var_95": np.array([]),
            "rolling_beta": np.array([]),
        }

    n_points = len(returns) - window + 1
    rolling_vol = np.zeros(n_points)
    rolling_sharpe = np.zeros(n_points)
    rolling_var_95 = np.zeros(n_points)
    rolling_beta = np.zeros(n_points)

    for i in range(n_points):
        window_returns = returns[i : i + window]
        rolling_vol[i] = compute_volatility_annual(
            window_returns, annualization_factor
        )
        rolling_sharpe[i] = compute_sharpe_ratio(
            window_returns, risk_free_rate, annualization_factor
        )
        rolling_var_95[i] = compute_var_parametric(window_returns, 0.95)

        if benchmark_returns is not None and len(benchmark_returns) == len(returns):
            benchmark_window = benchmark_returns[i : i + window]
            rolling_beta[i] = compute_beta(window_returns, benchmark_window)

    return {
        "rolling_vol": rolling_vol,
        "rolling_sharpe": rolling_sharpe,
        "rolling_var_95": rolling_var_95,
        "rolling_beta": rolling_beta,
    }


# =============================================================================
# HIGH-LEVEL WRAPPERS (using Pydantic models)
# =============================================================================


def compute_single_asset_risk(inp: AssetRiskInput) -> RiskMetricsOutput:
    """Compute all risk metrics for a single asset.

    Args:
        inp: AssetRiskInput with returns and optional benchmark.

    Returns:
        RiskMetricsOutput with all computed metrics.
    """
    returns = np.array(inp.returns)

    volatility_annual = compute_volatility_annual(
        returns, inp.annualization_factor
    )
    sharpe_ratio = compute_sharpe_ratio(
        returns, inp.risk_free_rate, inp.annualization_factor
    )
    max_drawdown = compute_max_drawdown(returns)
    var_95 = compute_var_parametric(returns, 0.95)
    var_99 = compute_var_parametric(returns, 0.99)
    cvar_95 = compute_cvar(returns, 0.95)

    beta = None
    if inp.benchmark_returns is not None:
        benchmark = np.array(inp.benchmark_returns)
        beta = compute_beta(returns, benchmark)

    return RiskMetricsOutput(
        volatility_annual=volatility_annual,
        beta=beta,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
        var_95=var_95,
        var_99=var_99,
        cvar_95=cvar_95,
    )


def compute_portfolio_risk(inp: PortfolioRiskInput) -> PortfolioRiskOutput:
    """Compute all risk metrics for a portfolio.

    Args:
        inp: PortfolioRiskInput with returns data, weights, and symbols.

    Returns:
        PortfolioRiskOutput with all computed metrics.
    """
    # Build returns DataFrame from input
    returns_df = pd.DataFrame(inp.returns_data)
    weights = np.array(inp.weights)

    # Align columns with symbols order
    returns_df = returns_df[inp.symbols]

    # Compute portfolio returns for aggregate metrics
    portfolio_returns = returns_df.values @ weights

    # VaR calculations
    var_95_parametric = compute_portfolio_var_parametric(
        returns_df, weights, 0.95
    )
    var_99_parametric = compute_portfolio_var_parametric(
        returns_df, weights, 0.99
    )
    cvar_95 = compute_portfolio_cvar(returns_df, weights, 0.95)

    # Portfolio-level metrics
    portfolio_volatility = compute_volatility_annual(
        portfolio_returns, inp.annualization_factor
    )
    portfolio_sharpe = compute_sharpe_ratio(
        portfolio_returns, inp.risk_free_rate, inp.annualization_factor
    )
    max_drawdown = compute_max_drawdown(portfolio_returns)

    # Exposure calculations
    net_exposure = float(np.sum(weights))
    gross_exposure = float(np.sum(np.abs(weights)))

    # Portfolio beta (requires benchmark - use SPY if available in returns)
    portfolio_beta = None

    return PortfolioRiskOutput(
        var_1d_95_pct=var_95_parametric,
        var_1d_99_pct=var_99_parametric,
        cvar_1d_95_pct=cvar_95,
        portfolio_volatility=portfolio_volatility,
        portfolio_beta=portfolio_beta,
        portfolio_sharpe=portfolio_sharpe,
        max_drawdown=max_drawdown,
        net_exposure=net_exposure,
        gross_exposure=gross_exposure,
    )


def compute_exposure(weights: list[float]) -> dict[str, float]:
    """Compute net and gross exposure from weights.

    Args:
        weights: List of position weights (negative for short).

    Returns:
        Dictionary with net_exposure and gross_exposure.
    """
    weights_arr = np.array(weights)
    return {
        "net_exposure": float(np.sum(weights_arr)),
        "gross_exposure": float(np.sum(np.abs(weights_arr))),
    }
