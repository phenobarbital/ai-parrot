"""
QuantToolkit - Quantitative Risk Analysis Toolkit.

Provides agent-accessible tools for portfolio risk management,
correlation analysis, fundamental scoring, volatility analytics,
and stress testing.

Designed for allocation to:
- risk_analyst: VaR, beta, drawdown, Sharpe, correlation, stress testing
- risk_research_crew: rolling metrics, regime detection
- equity_analyst: Piotroski F-Score, comparative risk metrics
- sentiment_analyst: volatility cone, IV/RV spread

Usage:
    toolkit = QuantToolkit()
    tools = await toolkit.get_tools()
    # Agent can now use: compute_risk_metrics, compute_portfolio_risk, etc.
"""

from typing import Literal

import numpy as np
from ..toolkit import AbstractToolkit
from . import risk_metrics
from . import correlation
from . import piotroski
from . import volatility
from . import stress_testing
from .models import (
    PiotroskiInput,
    StressScenario,
    AssetRiskInput,
    PortfolioRiskInput,
)


class QuantToolkit(AbstractToolkit):
    """
    Quantitative risk analysis, portfolio metrics, and fundamental scoring toolkit.

    Provides computational tools for:
    - Risk metrics (VaR, CVaR, beta, Sharpe, drawdown)
    - Correlation analysis and regime detection
    - Piotroski F-Score fundamental scoring
    - Volatility analytics (realized vol, cone, IV/RV spread)
    - Stress testing with predefined scenarios

    Example:
        >>> toolkit = QuantToolkit()
        >>> tools = await toolkit.get_tools()
        >>> # Returns 12 tools for agent use
    """

    name = "quant_toolkit"

    # =========================================================================
    # RISK METRICS
    # =========================================================================

    async def compute_risk_metrics(
        self,
        returns: list[float],
        benchmark_returns: list[float] | None = None,
        risk_free_rate: float = 0.04,
        annualization_factor: int = 252,
    ) -> dict:
        """
        Compute risk metrics for a single asset.

        Calculates VaR, CVaR, beta, Sharpe ratio, and maximum drawdown
        for a given return series.

        Args:
            returns: Daily return series (e.g., [0.01, -0.02, 0.005, ...])
            benchmark_returns: Benchmark returns for beta calculation (optional)
            risk_free_rate: Annualized risk-free rate (default 4%)
            annualization_factor: Trading days per year (252 stocks, 365 crypto)

        Returns:
            Dictionary containing:
            - volatility_annual: Annualized volatility
            - beta: Beta relative to benchmark (None if no benchmark)
            - sharpe_ratio: Annualized Sharpe ratio
            - max_drawdown: Maximum drawdown as decimal (e.g., -0.25 = -25%)
            - var_95: 1-day VaR at 95% confidence
            - var_99: 1-day VaR at 99% confidence
            - cvar_95: Expected shortfall at 95% confidence
        """
        inp = AssetRiskInput(
            returns=returns,
            benchmark_returns=benchmark_returns,
            risk_free_rate=risk_free_rate,
            annualization_factor=annualization_factor,
        )
        result = risk_metrics.compute_single_asset_risk(inp)
        return result.model_dump()

    async def compute_portfolio_risk(
        self,
        returns_data: dict[str, list[float]],
        weights: list[float],
        symbols: list[str],
        confidence: float = 0.95,
        risk_free_rate: float = 0.04,
        annualization_factor: int = 252,
        method: Literal["parametric", "historical"] = "parametric",
    ) -> dict:
        """
        Compute portfolio-level risk metrics.

        Calculates portfolio VaR, CVaR, volatility, beta, Sharpe ratio,
        and exposure metrics for a multi-asset portfolio.

        Args:
            returns_data: Dict of {symbol: [daily_returns]} for each position
            weights: Position weights (must sum to 1.0)
            symbols: Symbol names matching returns_data keys
            confidence: VaR confidence level (default 0.95 for 95%)
            risk_free_rate: Annualized risk-free rate
            annualization_factor: Trading days per year
            method: VaR method - "parametric" or "historical"

        Returns:
            Dictionary containing:
            - var_1d_95_pct: 1-day portfolio VaR at 95% confidence
            - var_1d_99_pct: 1-day portfolio VaR at 99% confidence
            - cvar_1d_95_pct: 1-day portfolio CVaR at 95%
            - portfolio_volatility: Annualized portfolio volatility
            - portfolio_beta: Portfolio beta (None if no benchmark)
            - portfolio_sharpe: Annualized portfolio Sharpe ratio
            - max_drawdown: Maximum portfolio drawdown
            - net_exposure: Long - short exposure
            - gross_exposure: |Long| + |short| exposure
        """
        inp = PortfolioRiskInput(
            returns_data=returns_data,
            weights=weights,
            symbols=symbols,
            confidence=confidence,
            risk_free_rate=risk_free_rate,
            annualization_factor=annualization_factor,
        )
        result = risk_metrics.compute_portfolio_risk(inp)
        return result.model_dump()

    async def compute_rolling_metrics(
        self,
        returns: list[float],
        window: int = 60,
        benchmark_returns: list[float] | None = None,
        risk_free_rate: float = 0.04,
        annualization_factor: int = 252,
    ) -> dict:
        """
        Compute rolling risk metrics for regime detection.

        Useful for identifying when volatility, risk, or correlation
        is changing over time.

        Args:
            returns: Daily return series
            window: Rolling window size in trading days (default 60)
            benchmark_returns: Benchmark for beta calculation (optional)
            risk_free_rate: Annualized risk-free rate
            annualization_factor: Trading days per year

        Returns:
            Dictionary containing:
            - rolling_vol: List of rolling annualized volatilities
            - rolling_sharpe: List of rolling Sharpe ratios
            - rolling_var95: List of rolling VaR at 95%
            - rolling_beta: List of rolling betas (None if no benchmark)
        """
        returns_arr = np.array(returns)
        benchmark_arr = np.array(benchmark_returns) if benchmark_returns else None
        result = risk_metrics.compute_rolling_metrics(
            returns=returns_arr,
            window=window,
            benchmark_returns=benchmark_arr,
            risk_free_rate=risk_free_rate,
            annualization_factor=annualization_factor,
        )
        # Convert numpy arrays to lists for JSON serialization
        return {
            k: v.tolist() if isinstance(v, np.ndarray) else v
            for k, v in result.items()
        }

    # =========================================================================
    # CORRELATION ANALYSIS
    # =========================================================================

    async def compute_correlation_matrix(
        self,
        price_data: dict[str, list[float]],
        method: Literal["pearson", "spearman", "kendall"] = "pearson",
        returns_based: bool = True,
    ) -> dict:
        """
        Compute correlation matrix for multiple assets.

        IMPORTANT: Correlates returns by default (not prices) to avoid
        spurious correlation from random walk behavior in price series.

        Args:
            price_data: Dict of {symbol: [close_prices]} for each asset
            method: Correlation method - "pearson", "spearman", or "kendall"
            returns_based: If True, convert prices to returns first (recommended)

        Returns:
            Dictionary containing:
            - matrix: {symbol: {symbol: correlation}} nested dict
            - method: Correlation method used
            - returns_based: Whether returns were used
        """
        return correlation.compute_correlation_matrix(
            price_data=price_data,
            method=method,
            returns_based=returns_based,
        )

    async def detect_correlation_regimes(
        self,
        price_data: dict[str, list[float]],
        short_window: int = 20,
        long_window: int = 120,
        z_threshold: float = 2.0,
    ) -> dict:
        """
        Detect correlation regime changes between asset pairs.

        Compares short-term vs long-term correlations and flags pairs
        where the deviation exceeds the z-threshold. Useful for detecting
        market regime changes and contagion.

        Args:
            price_data: Dict of {symbol: [close_prices]} for each asset
            short_window: Recent window for comparison (default 20 days)
            long_window: Historical window for baseline (default 120 days)
            z_threshold: Standard deviations for alert trigger (default 2.0)

        Returns:
            Dictionary containing:
            - regime_alerts: List of {pair, short_corr, long_corr, z_score, alert}
            - correlation_matrix_short: Short-term correlation matrix
            - correlation_matrix_long: Long-term correlation matrix
        """
        return correlation.detect_correlation_regimes(
            price_data=price_data,
            short_window=short_window,
            long_window=long_window,
            z_threshold=z_threshold,
        )

    async def compute_cross_asset_correlation(
        self,
        equity_prices: dict[str, list[float]],
        crypto_prices: dict[str, list[float]],
        timestamps_equity: list[str],
        timestamps_crypto: list[str],
    ) -> dict:
        """
        Compute correlation between equities and crypto with calendar alignment.

        Handles different trading calendars (equity: 252 trading days/year,
        crypto: 365 days/year) by aligning on common dates.

        Args:
            equity_prices: {symbol: [prices]} for equities (SPY, QQQ, etc.)
            crypto_prices: {symbol: [prices]} for crypto (BTC, ETH, etc.)
            timestamps_equity: Date strings for equity prices (YYYY-MM-DD)
            timestamps_crypto: Date strings for crypto prices (YYYY-MM-DD)

        Returns:
            Dictionary containing:
            - cross_asset_correlations: {pair: correlation} for cross-asset pairs
            - full_matrix: Full correlation matrix across all assets
            - common_dates_count: Number of dates used for correlation
        """
        return correlation.compute_cross_asset_correlation(
            equity_prices=equity_prices,
            crypto_prices=crypto_prices,
            timestamps_equity=timestamps_equity,
            timestamps_crypto=timestamps_crypto,
        )

    # =========================================================================
    # PIOTROSKI F-SCORE
    # =========================================================================

    async def calculate_piotroski_score(
        self,
        quarterly_financials: dict[str, float],
        prior_year_financials: dict[str, float] | None = None,
    ) -> dict:
        """
        Calculate Piotroski F-Score (0-9) for fundamental quality assessment.

        Evaluates company financial health using 9 accounting criteria:
        - Profitability (4 pts): positive NI, positive ROA, positive OCF, OCF > NI
        - Leverage (3 pts): lower debt ratio, higher current ratio, no dilution
        - Efficiency (2 pts): higher gross margin YoY, higher asset turnover YoY

        Args:
            quarterly_financials: Current quarter data including:
                - net_income: Net income
                - total_assets: Total assets
                - operating_cash_flow: Operating cash flow
                - total_debt: Total debt (optional)
                - current_assets: Current assets (optional)
                - current_liabilities: Current liabilities (optional)
                - shares_outstanding: Shares outstanding (optional)
                - revenue: Revenue (optional)
                - cost_of_revenue: Cost of revenue (optional)
            prior_year_financials: Prior year data for YoY comparison (optional)

        Returns:
            Dictionary containing:
            - total_score: F-Score (0-9)
            - criteria: {criterion: {score, value, threshold}}
            - data_completeness_pct: % of criteria that could be evaluated
            - interpretation: "Excellent" | "Good" | "Fair" | "Poor"
            - category_scores: {profitability, leverage, efficiency}
        """
        input_data = PiotroskiInput(
            quarterly_financials=quarterly_financials,
            prior_year_financials=prior_year_financials or {},
        )
        return piotroski.calculate_piotroski_score(input_data)

    async def batch_piotroski_scores(
        self,
        symbols_data: dict[str, dict],
    ) -> dict[str, dict]:
        """
        Calculate F-Scores for multiple stocks in batch.

        Efficient for comparing fundamental quality across a universe of stocks.

        Args:
            symbols_data: Dict mapping symbol to financial data:
                {symbol: {
                    "quarterly_financials": {...},
                    "prior_year_financials": {...}
                }}

        Returns:
            Dict mapping symbol to score result:
            {symbol: {total_score, criteria, interpretation, ...}}
        """
        inputs = {
            symbol: PiotroskiInput(**data)
            for symbol, data in symbols_data.items()
        }
        return piotroski.batch_piotroski_scores(inputs)

    # =========================================================================
    # VOLATILITY ANALYTICS
    # =========================================================================

    async def compute_realized_volatility(
        self,
        returns: list[float],
        window: int = 20,
        annualization: int = 252,
        method: Literal["close_to_close", "parkinson", "garman_klass"] = "close_to_close",
        ohlc_data: dict[str, list[float]] | None = None,
    ) -> list[float]:
        """
        Compute rolling realized volatility using various estimators.

        Methods compared:
        - close_to_close: Standard deviation of returns (most common)
        - parkinson: Uses high-low range (~5x more efficient than close-to-close)
        - garman_klass: Uses full OHLC data (most efficient estimator)

        Args:
            returns: Daily return series (for close_to_close method)
            window: Rolling window size in days (default 20)
            annualization: Trading days per year (252 stocks, 365 crypto)
            method: Volatility estimator to use
            ohlc_data: Required for parkinson/garman_klass methods:
                {"high": [], "low": [], "open": [], "close": []}

        Returns:
            List of rolling annualized volatility values
        """
        return volatility.compute_realized_volatility(
            returns=returns,
            window=window,
            annualization=annualization,
            method=method,
            ohlc_data=ohlc_data,
        )

    async def compute_volatility_cone(
        self,
        returns: list[float],
        windows: list[int] | None = None,
        annualization: int = 252,
    ) -> dict:
        """
        Compute percentile ranks of current volatility across multiple windows.

        Answers: "Is current 20-day vol high or low relative to history?"
        Useful for identifying elevated or suppressed volatility regimes.

        Args:
            returns: Daily return series
            windows: List of lookback windows (default [10, 20, 30, 60, 90, 120])
            annualization: Trading days per year

        Returns:
            Dict with structure {window: {current, percentile, min, max, median}}:
            - current: Current window volatility
            - percentile: Percentile rank (0-100) vs history
            - min: Historical minimum volatility
            - max: Historical maximum volatility
            - median: Historical median volatility
        """
        return volatility.compute_volatility_cone(
            returns=returns,
            windows=windows,
            annualization=annualization,
        )

    async def compute_iv_rv_spread(
        self,
        implied_vol: float,
        realized_vol_series: list[float],
        window: int = 20,
    ) -> dict:
        """
        Compute IV vs RV spread for options sentiment analysis.

        Compares implied volatility (from options prices) to realized volatility
        to identify fear/complacency regimes:
        - IV >> RV: Fear premium elevated (contrarian buy signal, sell premium)
        - IV << RV: Complacency (buy protection, vol likely to spike)
        - IV ≈ RV: Normal regime

        Args:
            implied_vol: Current implied volatility (annualized, from options)
            realized_vol_series: Historical realized volatility series
            window: Window for current RV calculation (default 20)

        Returns:
            Dictionary containing:
            - implied_vol: Input IV
            - realized_vol: Current RV (windowed average)
            - spread: IV - RV
            - spread_pct: (IV - RV) / RV * 100
            - percentile: Historical percentile of current spread
            - regime: "fear_premium" | "complacent" | "normal"
        """
        return volatility.compute_iv_rv_spread(
            implied_vol=implied_vol,
            realized_vol_series=realized_vol_series,
            window=window,
        )

    # =========================================================================
    # STRESS TESTING
    # =========================================================================

    async def stress_test_portfolio(
        self,
        portfolio_values: dict[str, float],
        scenario_names: list[str] | None = None,
        custom_scenarios: list[dict] | None = None,
    ) -> dict:
        """
        Apply stress scenarios to a portfolio and estimate potential losses.

        Predefined scenarios available:
        - covid_crash_2020: March 2020 COVID market crash
        - rate_hike_shock: Aggressive interest rate increase
        - crypto_winter: Severe crypto bear market (2022-style)
        - black_swan: Generic severe market stress event
        - stagflation: High inflation + low growth scenario

        Args:
            portfolio_values: {symbol: current_market_value} for each position
            scenario_names: List of predefined scenario names to apply
            custom_scenarios: Custom scenarios as list of:
                [{"name": str, "asset_shocks": {symbol: shock_pct}, "description": str}]
                where shock_pct is decimal (e.g., -0.34 = -34%)

        Returns:
            Dictionary containing:
            - scenario_results: {scenario_name: {
                portfolio_loss_pct, portfolio_loss_usd,
                position_impacts, worst_position, best_position
              }}
            - worst_scenario: Name of scenario with largest loss
            - max_loss_pct: Maximum portfolio loss across all scenarios
        """
        scenarios = []

        # Add predefined scenarios
        if scenario_names:
            for name in scenario_names:
                scenarios.append(stress_testing.get_predefined_scenario(name))

        # Add custom scenarios
        if custom_scenarios:
            for s in custom_scenarios:
                scenarios.append(StressScenario(**s))

        if not scenarios:
            # Default to all predefined scenarios
            scenario_names_list = stress_testing.list_predefined_scenarios()
            scenarios = [
                stress_testing.get_predefined_scenario(n)
                for n in scenario_names_list
            ]

        symbols = list(portfolio_values.keys())
        total_value = sum(portfolio_values.values())
        weights = [v / total_value for v in portfolio_values.values()] if total_value > 0 else []

        return stress_testing.stress_test_portfolio(
            portfolio_values=portfolio_values,
            weights=weights,
            symbols=symbols,
            scenarios=scenarios,
        )
