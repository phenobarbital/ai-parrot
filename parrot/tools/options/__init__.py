"""
Options Analytics Toolkit.

A pure computation layer for options pricing, Greeks calculation,
strategy analysis, and PMCC scanning. This toolkit does NOT fetch
market data — callers supply spot prices, chains, and volatility inputs.

Modules:
- models: Dataclasses and Pydantic input models
- black_scholes: Black-Scholes pricing engine
- spreads: Spread strategy analyzers (TASK-079)
- pmcc: PMCC scanner and scoring (TASK-080)
- toolkit: OptionsAnalyticsToolkit class (TASK-081)

Usage:
    from parrot.tools.options import (
        # Models
        IVResult, GreeksResult, OptionLeg, PMCCScoringConfig,
        ComputeGreeksInput, AnalyzeSpreadInput,
        # Black-Scholes
        black_scholes_price, black_scholes_greeks, implied_volatility,
        # Toolkit
        OptionsAnalyticsToolkit,
    )
"""
from .models import (
    # Dataclasses
    IVResult,
    GreeksResult,
    OptionLeg,
    PMCCScoringConfig,
    # Pydantic models
    ComputeGreeksInput,
    AnalyzeSpreadInput,
    AnalyzeStraddleInput,
    AnalyzeStrangleInput,
    AnalyzeIronCondorInput,
)

from .black_scholes import (
    # Core pricing
    black_scholes_price,
    # Individual Greeks
    black_scholes_delta,
    black_scholes_gamma,
    black_scholes_vega,
    black_scholes_theta,
    black_scholes_rho,
    # Full Greeks
    black_scholes_greeks,
    # IV solver
    implied_volatility,
    estimate_iv,
    # Parity
    validate_put_call_parity,
    # Batch operations
    compute_chain_greeks,
    # Probability
    probability_of_profit,
    probability_in_range,
)

from .spreads import (
    SpreadAnalysis,
    analyze_vertical,
    analyze_diagonal,
    analyze_straddle,
    analyze_strangle,
    analyze_iron_condor,
)

from .pmcc import (
    PMCCCandidate,
    PMCCScanResult,
    find_strike_by_delta,
    select_leaps_options,
    select_short_options,
    score_pmcc_candidate,
    calculate_pmcc_metrics,
    scan_symbol_for_pmcc,
    scan_pmcc_candidates,
    scan_pmcc_candidates_sync,
)

from .toolkit import OptionsAnalyticsToolkit

__all__ = [
    # Dataclasses
    "IVResult",
    "GreeksResult",
    "OptionLeg",
    "PMCCScoringConfig",
    # Pydantic models
    "ComputeGreeksInput",
    "AnalyzeSpreadInput",
    "AnalyzeStraddleInput",
    "AnalyzeStrangleInput",
    "AnalyzeIronCondorInput",
    # Black-Scholes pricing
    "black_scholes_price",
    "black_scholes_delta",
    "black_scholes_gamma",
    "black_scholes_vega",
    "black_scholes_theta",
    "black_scholes_rho",
    "black_scholes_greeks",
    "implied_volatility",
    "estimate_iv",
    "validate_put_call_parity",
    "compute_chain_greeks",
    "probability_of_profit",
    "probability_in_range",
    # Spread analyzers
    "SpreadAnalysis",
    "analyze_vertical",
    "analyze_diagonal",
    "analyze_straddle",
    "analyze_strangle",
    "analyze_iron_condor",
    # PMCC scanner
    "PMCCCandidate",
    "PMCCScanResult",
    "find_strike_by_delta",
    "select_leaps_options",
    "select_short_options",
    "score_pmcc_candidate",
    "calculate_pmcc_metrics",
    "scan_symbol_for_pmcc",
    "scan_pmcc_candidates",
    "scan_pmcc_candidates_sync",
    # Toolkit
    "OptionsAnalyticsToolkit",
]
