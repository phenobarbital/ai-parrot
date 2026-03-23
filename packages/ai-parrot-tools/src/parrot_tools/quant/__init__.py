"""
QuantToolkit - Quantitative risk analysis and portfolio metrics.

Provides computational tools for:
- Risk metrics (VaR, CVaR, beta, Sharpe, drawdown)
- Correlation analysis and regime detection
- Piotroski F-Score fundamental scoring
- Volatility analytics
- Stress testing
"""

from .models import (
    PortfolioRiskInput,
    AssetRiskInput,
    CorrelationInput,
    StressScenario,
    PiotroskiInput,
    RiskMetricsOutput,
    PortfolioRiskOutput,
)
from .risk_metrics import (
    compute_returns,
    compute_var_parametric,
    compute_var_historical,
    compute_cvar,
    compute_max_drawdown,
    compute_beta,
    compute_sharpe_ratio,
    compute_volatility_annual,
    compute_portfolio_var_parametric,
    compute_portfolio_var_historical,
    compute_portfolio_cvar,
    compute_rolling_metrics,
    compute_single_asset_risk,
    compute_portfolio_risk,
    compute_exposure,
)
from .correlation import (
    prices_to_returns,
    compute_correlation_matrix,
    compute_correlation_from_input,
    detect_correlation_regimes,
    compute_cross_asset_correlation,
    compute_pairwise_correlation,
    compute_rolling_correlation,
    get_correlation_heatmap_data,
)
from .piotroski import (
    calculate_piotroski_score,
    batch_piotroski_scores,
    get_fscore_summary,
    rank_by_fscore,
)
from .volatility import (
    compute_realized_volatility,
    compute_volatility_single,
    compute_volatility_cone,
    interpret_volatility_cone,
    compute_iv_rv_spread,
    interpret_iv_rv_spread,
    compute_volatility_term_structure,
    classify_term_structure,
)
from .stress_testing import (
    stress_test_portfolio,
    get_predefined_scenario,
    list_predefined_scenarios,
    get_scenario_descriptions,
    create_volatility_shock_scenario,
    create_custom_scenario,
    create_sector_rotation_scenario,
    summarize_stress_results,
    get_concentrated_risk_positions,
    PREDEFINED_SCENARIOS,
)
from .toolkit import QuantToolkit

__all__ = [
    # Main Toolkit
    "QuantToolkit",
    # Models
    "PortfolioRiskInput",
    "AssetRiskInput",
    "CorrelationInput",
    "StressScenario",
    "PiotroskiInput",
    "RiskMetricsOutput",
    "PortfolioRiskOutput",
    # Risk Metrics
    "compute_returns",
    "compute_var_parametric",
    "compute_var_historical",
    "compute_cvar",
    "compute_max_drawdown",
    "compute_beta",
    "compute_sharpe_ratio",
    "compute_volatility_annual",
    "compute_portfolio_var_parametric",
    "compute_portfolio_var_historical",
    "compute_portfolio_cvar",
    "compute_rolling_metrics",
    "compute_single_asset_risk",
    "compute_portfolio_risk",
    "compute_exposure",
    # Correlation
    "prices_to_returns",
    "compute_correlation_matrix",
    "compute_correlation_from_input",
    "detect_correlation_regimes",
    "compute_cross_asset_correlation",
    "compute_pairwise_correlation",
    "compute_rolling_correlation",
    "get_correlation_heatmap_data",
    # Piotroski F-Score
    "calculate_piotroski_score",
    "batch_piotroski_scores",
    "get_fscore_summary",
    "rank_by_fscore",
    # Volatility Analytics
    "compute_realized_volatility",
    "compute_volatility_single",
    "compute_volatility_cone",
    "interpret_volatility_cone",
    "compute_iv_rv_spread",
    "interpret_iv_rv_spread",
    "compute_volatility_term_structure",
    "classify_term_structure",
    # Stress Testing
    "stress_test_portfolio",
    "get_predefined_scenario",
    "list_predefined_scenarios",
    "get_scenario_descriptions",
    "create_volatility_shock_scenario",
    "create_custom_scenario",
    "create_sector_rotation_scenario",
    "summarize_stress_results",
    "get_concentrated_risk_positions",
    "PREDEFINED_SCENARIOS",
]
