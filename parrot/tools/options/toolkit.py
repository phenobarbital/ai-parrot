"""
Options Analytics Toolkit.

A unified toolkit providing options pricing, Greeks, strategy analysis,
and PMCC scanning capabilities. Designed for use by AI agents.

This toolkit wraps pure computation functions from the options analytics
modules (black_scholes, spreads, pmcc) as async tool methods. It does NOT
fetch market data — callers supply spot prices, chains, and volatility inputs.

Designed to be allocated to:
- equity_analyst: spread analysis, PMCC scanning, yield calculations
- risk_analyst: Greeks exposure, stress testing, portfolio Greeks
- sentiment_analyst: IV skew analysis, put/call ratio analysis

Example:
    toolkit = OptionsAnalyticsToolkit()
    result = await toolkit.compute_greeks(
        spot=100.0, strike=105.0, dte_days=30,
        volatility=0.25, option_type="call"
    )
"""
from typing import Dict, List, Any, Optional, Literal
from navconfig.logging import logging

from ..toolkit import AbstractToolkit
from ..decorators import tool_schema
from .models import (
    ComputeGreeksInput,
    AnalyzeSpreadInput,
    AnalyzeStraddleInput,
    AnalyzeStrangleInput,
    AnalyzeIronCondorInput,
    OptionLeg,
    PMCCScoringConfig,
)
from .black_scholes import (
    black_scholes_greeks,
    black_scholes_price,
    implied_volatility,
    compute_chain_greeks as _compute_chain_greeks,
    probability_of_profit,
    validate_put_call_parity,
)
from .spreads import (
    analyze_vertical,
    analyze_diagonal,
    analyze_straddle,
    analyze_strangle,
    analyze_iron_condor,
)
from .pmcc import scan_pmcc_candidates as _scan_pmcc


class OptionsAnalyticsToolkit(AbstractToolkit):
    """
    Options pricing, Greeks, strategy analysis, and scanning toolkit.

    This toolkit provides pure analytical capabilities over pre-fetched
    option chain data. It does NOT fetch market data — callers supply
    spot prices, chains, and volatility inputs.

    All methods return dicts with a `success` key for consistent error handling.
    On success: `{"success": True, ...data...}`
    On failure: `{"success": False, "error": "...message..."}`

    Tools provided:
    - compute_greeks: Single option Greeks (delta, gamma, theta, vega, rho)
    - compute_chain_greeks: Batch Greeks for an entire chain
    - compute_implied_volatility: IV from market price
    - compute_option_price: Theoretical option price
    - analyze_iv_skew: Put vs call IV skew analysis
    - analyze_vertical_spread: Vertical spread analysis
    - analyze_diagonal_spread: Diagonal/PMCC spread analysis
    - analyze_straddle: Straddle analysis
    - analyze_strangle: Strangle analysis
    - analyze_iron_condor: Iron condor analysis
    - scan_pmcc_candidates: Batch PMCC scanning with scoring
    - stress_test_greeks: Greeks under multiple scenarios
    - portfolio_greeks_exposure: Aggregate net Greeks
    """

    name = "options_analytics_toolkit"

    def __init__(self, **kwargs):
        """Initialize the options analytics toolkit."""
        super().__init__(**kwargs)
        self.logger = logging.getLogger(__name__)

    # =========================================================================
    # Greeks Computation Tools
    # =========================================================================

    @tool_schema(ComputeGreeksInput, description="Compute option Greeks (delta, gamma, theta, vega, rho) for a single option")
    async def compute_greeks(
        self,
        spot: float,
        strike: float,
        dte_days: int,
        volatility: float,
        option_type: Literal["call", "put"],
        risk_free_rate: float = 0.05
    ) -> Dict[str, Any]:
        """
        Compute Black-Scholes Greeks for a single option.

        Args:
            spot: Current underlying price.
            strike: Option strike price.
            dte_days: Days to expiration.
            volatility: Annualized implied volatility (e.g., 0.30 for 30%).
            option_type: 'call' or 'put'.
            risk_free_rate: Risk-free rate (default 0.05).

        Returns:
            Dict with price, delta, gamma, theta, vega, rho.
        """
        try:
            T = dte_days / 365.0
            result = black_scholes_greeks(
                spot, strike, T, risk_free_rate, volatility, option_type
            )
            return {
                "success": True,
                "price": result.price,
                "delta": result.delta,
                "gamma": result.gamma,
                "theta": result.theta,
                "vega": result.vega,
                "rho": result.rho,
                "option_type": option_type,
                "spot": spot,
                "strike": strike,
                "dte_days": dte_days,
            }
        except ValueError as e:
            self.logger.warning(f"Greeks computation failed: {e}")
            return {"success": False, "error": str(e)}

    async def compute_chain_greeks(
        self,
        spot: float,
        strikes: List[float],
        dte_days: int,
        volatility: float,
        option_type: Literal["call", "put"],
        risk_free_rate: float = 0.05
    ) -> Dict[str, Any]:
        """
        Compute Greeks for multiple strikes (batch operation).

        Uses numpy vectorization for efficient computation across an entire chain.

        Args:
            spot: Current underlying price.
            strikes: List of strike prices.
            dte_days: Days to expiration.
            volatility: Annualized implied volatility.
            option_type: 'call' or 'put'.
            risk_free_rate: Risk-free rate.

        Returns:
            Dict with 'results' list containing Greeks for each strike.
        """
        try:
            import pandas as pd
            T = dte_days / 365.0
            # Build DataFrame expected by compute_chain_greeks
            chain_df = pd.DataFrame({
                "strike": strikes,
                "impliedVolatility": [volatility] * len(strikes)
            })
            df = _compute_chain_greeks(
                chain_df, spot, risk_free_rate, T, option_type
            )
            return {
                "success": True,
                "results": df.to_dict(orient='records'),
                "count": len(strikes),
            }
        except Exception as e:
            self.logger.warning(f"Chain Greeks computation failed: {e}")
            return {"success": False, "error": str(e)}

    async def compute_implied_volatility(
        self,
        market_price: float,
        spot: float,
        strike: float,
        dte_days: int,
        option_type: Literal["call", "put"],
        risk_free_rate: float = 0.05
    ) -> Dict[str, Any]:
        """
        Solve for implied volatility given market price.

        Uses Newton-Raphson with bisection fallback for robust convergence.

        Args:
            market_price: Observed market price of the option.
            spot: Current underlying price.
            strike: Option strike price.
            dte_days: Days to expiration.
            option_type: 'call' or 'put'.
            risk_free_rate: Risk-free rate.

        Returns:
            Dict with implied_volatility, converged flag, iterations, and method used.
        """
        try:
            T = dte_days / 365.0
            result = implied_volatility(
                market_price, spot, strike, T, risk_free_rate, option_type
            )
            return {
                "success": True,
                "implied_volatility": result.iv,
                "implied_volatility_pct": result.iv * 100,
                "converged": result.converged,
                "iterations": result.iterations,
                "method": result.method,
            }
        except Exception as e:
            self.logger.warning(f"IV computation failed: {e}")
            return {"success": False, "error": str(e)}

    async def compute_option_price(
        self,
        spot: float,
        strike: float,
        dte_days: int,
        volatility: float,
        option_type: Literal["call", "put"],
        risk_free_rate: float = 0.05
    ) -> Dict[str, Any]:
        """
        Compute theoretical Black-Scholes option price.

        Args:
            spot: Current underlying price.
            strike: Option strike price.
            dte_days: Days to expiration.
            volatility: Annualized implied volatility.
            option_type: 'call' or 'put'.
            risk_free_rate: Risk-free rate.

        Returns:
            Dict with theoretical price and intrinsic/extrinsic components.
        """
        try:
            T = dte_days / 365.0
            price = black_scholes_price(spot, strike, T, risk_free_rate, volatility, option_type)

            # Calculate intrinsic value
            if option_type == "call":
                intrinsic = max(spot - strike, 0)
            else:
                intrinsic = max(strike - spot, 0)

            extrinsic = price - intrinsic

            return {
                "success": True,
                "price": price,
                "intrinsic_value": intrinsic,
                "extrinsic_value": extrinsic,
                "option_type": option_type,
            }
        except Exception as e:
            self.logger.warning(f"Price computation failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # IV Analysis Tools
    # =========================================================================

    async def analyze_iv_skew(
        self,
        spot: float,
        put_strike: float,
        put_iv: float,
        call_strike: float,
        call_iv: float,
        dte_days: int
    ) -> Dict[str, Any]:
        """
        Analyze put vs call implied volatility skew.

        IV skew indicates market sentiment and expected move direction.
        Higher put IV suggests bearish sentiment (downside fear).
        Higher call IV suggests bullish sentiment (upside speculation).

        Args:
            spot: Current underlying price.
            put_strike: Strike of the put option.
            put_iv: Implied volatility of the put.
            call_strike: Strike of the call option.
            call_iv: Implied volatility of the call.
            dte_days: Days to expiration.

        Returns:
            Dict with skew metrics and interpretation.
        """
        try:
            # Calculate skew
            iv_diff = put_iv - call_iv
            iv_ratio = put_iv / call_iv if call_iv > 0 else float('inf')

            # Interpret skew
            if iv_diff > 0.02:
                sentiment = "bearish"
                interpretation = "Put IV > Call IV indicates downside protection demand"
            elif iv_diff < -0.02:
                sentiment = "bullish"
                interpretation = "Call IV > Put IV indicates upside speculation"
            else:
                sentiment = "neutral"
                interpretation = "Balanced IV suggests no strong directional bias"

            # Calculate moneyness
            put_moneyness = (spot - put_strike) / spot * 100
            call_moneyness = (call_strike - spot) / spot * 100

            return {
                "success": True,
                "put_iv": put_iv,
                "call_iv": call_iv,
                "iv_skew": iv_diff,
                "iv_ratio": iv_ratio,
                "sentiment": sentiment,
                "interpretation": interpretation,
                "put_moneyness_pct": put_moneyness,
                "call_moneyness_pct": call_moneyness,
                "dte_days": dte_days,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def validate_parity(
        self,
        spot: float,
        strike: float,
        call_price: float,
        put_price: float,
        dte_days: int,
        risk_free_rate: float = 0.05,
        tolerance: float = 0.05
    ) -> Dict[str, Any]:
        """
        Validate put-call parity for arbitrage detection.

        Put-call parity: C - P = S - K*exp(-rT)
        Violations may indicate arbitrage opportunities or data errors.

        Args:
            spot: Current underlying price.
            strike: Strike price (same for both).
            call_price: Market price of call.
            put_price: Market price of put.
            dte_days: Days to expiration.
            risk_free_rate: Risk-free rate.
            tolerance: Tolerance for parity deviation.

        Returns:
            Dict with parity validation results and any arbitrage signals.
        """
        try:
            T = dte_days / 365.0
            result = validate_put_call_parity(
                call_price, put_price, spot, strike, T, risk_free_rate, tolerance
            )
            return {
                "success": True,
                "parity_difference": result["spread"],
                "parity_valid": not result["arbitrage_flag"],
                "arbitrage_flag": bool(result["arbitrage_flag"]),
                "theoretical_difference": result["theoretical_spread"],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Spread Analysis Tools
    # =========================================================================

    @tool_schema(AnalyzeSpreadInput, description="Analyze a vertical spread (bull/bear call/put)")
    async def analyze_vertical_spread(
        self,
        underlying_price: float,
        long_strike: float,
        long_bid: float,
        long_ask: float,
        short_strike: float,
        short_bid: float,
        short_ask: float,
        option_type: Literal["call", "put"],
        expiry_days: int,
        volatility: float,
        risk_free_rate: float = 0.05
    ) -> Dict[str, Any]:
        """
        Analyze a vertical spread strategy.

        Supports bull call, bear call, bull put, and bear put spreads.
        Returns max profit, max loss, breakeven, POP, EV, and net Greeks.

        Args:
            underlying_price: Current price of underlying.
            long_strike: Strike price of the long (bought) option.
            long_bid: Bid price of long option.
            long_ask: Ask price of long option.
            short_strike: Strike price of the short (sold) option.
            short_bid: Bid price of short option.
            short_ask: Ask price of short option.
            option_type: 'call' or 'put'.
            expiry_days: Days to expiration.
            volatility: Implied volatility.
            risk_free_rate: Risk-free rate.

        Returns:
            Dict with spread analysis including P/L, breakeven, POP, and Greeks.
        """
        try:
            long_leg = OptionLeg(
                strike=long_strike,
                option_type=option_type,
                bid=long_bid,
                ask=long_ask,
                mid=(long_bid + long_ask) / 2
            )
            short_leg = OptionLeg(
                strike=short_strike,
                option_type=option_type,
                bid=short_bid,
                ask=short_ask,
                mid=(short_bid + short_ask) / 2
            )

            result = analyze_vertical(
                underlying_price, long_leg, short_leg,
                option_type, expiry_days, volatility, risk_free_rate
            )

            return {
                "success": True,
                "strategy_type": result.strategy_type,
                "direction": result.direction,
                "net_debit": result.net_debit,
                "net_credit": result.net_credit,
                "max_profit": result.max_profit,
                "max_loss": result.max_loss,
                "breakeven": result.breakeven,
                "risk_reward_ratio": result.risk_reward_ratio,
                "probability_of_profit": result.pop,
                "expected_value": result.expected_value,
                "net_greeks": {
                    "delta": result.net_delta,
                    "gamma": result.net_gamma,
                    "theta": result.net_theta,
                    "vega": result.net_vega,
                }
            }
        except Exception as e:
            self.logger.warning(f"Vertical spread analysis failed: {e}")
            return {"success": False, "error": str(e)}

    async def analyze_diagonal_spread(
        self,
        underlying_price: float,
        long_strike: float,
        long_price: float,
        long_dte_days: int,
        short_strike: float,
        short_price: float,
        short_dte_days: int,
        option_type: Literal["call", "put"],
        volatility: float,
        risk_free_rate: float = 0.05
    ) -> Dict[str, Any]:
        """
        Analyze a diagonal spread (PMCC or calendar-like strategy).

        A diagonal spread involves buying a longer-dated option and selling
        a shorter-dated option at a different strike.

        Args:
            underlying_price: Current price of underlying.
            long_strike: Strike of the LEAPS (long-dated option).
            long_price: Price paid for the LEAPS.
            long_dte_days: Days to expiration for LEAPS.
            short_strike: Strike of the short-term option.
            short_price: Premium received for short option.
            short_dte_days: Days to expiration for short option.
            option_type: 'call' or 'put'.
            volatility: Implied volatility.
            risk_free_rate: Risk-free rate.

        Returns:
            Dict with diagonal spread analysis.
        """
        try:
            result = analyze_diagonal(
                underlying_price,
                long_strike, long_price, long_dte_days,
                short_strike, short_price, short_dte_days,
                option_type, volatility, risk_free_rate
            )

            return {
                "success": True,
                "strategy_type": result.strategy_type,
                "direction": result.direction,
                "net_debit": result.net_debit,
                "max_profit": result.max_profit,
                "max_loss": result.max_loss,
                "breakeven": result.breakeven,
                "risk_reward_ratio": result.risk_reward_ratio,
                "probability_of_profit": result.pop,
                "expected_value": result.expected_value,
                "net_greeks": {
                    "delta": result.net_delta,
                    "gamma": result.net_gamma,
                    "theta": result.net_theta,
                    "vega": result.net_vega,
                }
            }
        except Exception as e:
            self.logger.warning(f"Diagonal spread analysis failed: {e}")
            return {"success": False, "error": str(e)}

    @tool_schema(AnalyzeStraddleInput, description="Analyze a straddle strategy (buy/sell call and put at same strike)")
    async def analyze_straddle_strategy(
        self,
        underlying_price: float,
        strike: float,
        call_bid: float,
        call_ask: float,
        put_bid: float,
        put_ask: float,
        expiry_days: int,
        volatility: float,
        risk_free_rate: float = 0.05
    ) -> Dict[str, Any]:
        """
        Analyze a straddle strategy (buy call + put at same strike).

        A straddle profits from large moves in either direction.
        Max loss is the total premium paid.

        Args:
            underlying_price: Current price of underlying.
            strike: Strike price (same for call and put).
            call_bid: Call option bid price.
            call_ask: Call option ask price.
            put_bid: Put option bid price.
            put_ask: Put option ask price.
            expiry_days: Days to expiration.
            volatility: Implied volatility.
            risk_free_rate: Risk-free rate.

        Returns:
            Dict with straddle analysis including breakevens and Greeks.
        """
        try:
            result = analyze_straddle(
                underlying_price, strike,
                call_bid, call_ask, put_bid, put_ask,
                expiry_days, volatility, risk_free_rate
            )

            return {
                "success": True,
                "strategy_type": result.strategy_type,
                "direction": result.direction,
                "net_debit": result.net_debit,
                "max_profit": "unlimited" if result.max_profit == float('inf') else result.max_profit,
                "max_loss": result.max_loss,
                "breakeven_up": result.breakeven_up,
                "breakeven_down": result.breakeven_down,
                "probability_of_profit": result.pop,
                "expected_value": result.expected_value,
                "net_greeks": {
                    "delta": result.net_delta,
                    "gamma": result.net_gamma,
                    "theta": result.net_theta,
                    "vega": result.net_vega,
                }
            }
        except Exception as e:
            self.logger.warning(f"Straddle analysis failed: {e}")
            return {"success": False, "error": str(e)}

    @tool_schema(AnalyzeStrangleInput, description="Analyze a strangle strategy (buy OTM call and put)")
    async def analyze_strangle_strategy(
        self,
        underlying_price: float,
        put_strike: float,
        call_strike: float,
        put_bid: float,
        put_ask: float,
        call_bid: float,
        call_ask: float,
        expiry_days: int,
        volatility: float,
        risk_free_rate: float = 0.05
    ) -> Dict[str, Any]:
        """
        Analyze a strangle strategy (buy OTM call + OTM put).

        A strangle is similar to a straddle but uses OTM options,
        making it cheaper but requiring larger moves to profit.

        Args:
            underlying_price: Current price of underlying.
            put_strike: Strike for put (typically below current price).
            call_strike: Strike for call (typically above current price).
            put_bid: Put option bid.
            put_ask: Put option ask.
            call_bid: Call option bid.
            call_ask: Call option ask.
            expiry_days: Days to expiration.
            volatility: Implied volatility.
            risk_free_rate: Risk-free rate.

        Returns:
            Dict with strangle analysis.
        """
        try:
            result = analyze_strangle(
                underlying_price, put_strike, call_strike,
                put_bid, put_ask, call_bid, call_ask,
                expiry_days, volatility, risk_free_rate
            )

            return {
                "success": True,
                "strategy_type": result.strategy_type,
                "direction": result.direction,
                "net_debit": result.net_debit,
                "max_profit": "unlimited" if result.max_profit == float('inf') else result.max_profit,
                "max_loss": result.max_loss,
                "breakeven_up": result.breakeven_up,
                "breakeven_down": result.breakeven_down,
                "probability_of_profit": result.pop,
                "expected_value": result.expected_value,
                "net_greeks": {
                    "delta": result.net_delta,
                    "gamma": result.net_gamma,
                    "theta": result.net_theta,
                    "vega": result.net_vega,
                }
            }
        except Exception as e:
            self.logger.warning(f"Strangle analysis failed: {e}")
            return {"success": False, "error": str(e)}

    @tool_schema(AnalyzeIronCondorInput, description="Analyze an iron condor strategy")
    async def analyze_iron_condor_strategy(
        self,
        underlying_price: float,
        put_buy_strike: float,
        put_sell_strike: float,
        call_sell_strike: float,
        call_buy_strike: float,
        put_buy_price: float,
        put_sell_price: float,
        call_sell_price: float,
        call_buy_price: float,
        expiry_days: int,
        volatility: float,
        risk_free_rate: float = 0.05
    ) -> Dict[str, Any]:
        """
        Analyze an iron condor strategy.

        An iron condor combines a bull put spread and a bear call spread,
        profiting when the underlying stays within a range.

        Args:
            underlying_price: Current price of underlying.
            put_buy_strike: Long put strike (lowest).
            put_sell_strike: Short put strike.
            call_sell_strike: Short call strike.
            call_buy_strike: Long call strike (highest).
            put_buy_price: Price paid for long put.
            put_sell_price: Price received for short put.
            call_sell_price: Price received for short call.
            call_buy_price: Price paid for long call.
            expiry_days: Days to expiration.
            volatility: Implied volatility.
            risk_free_rate: Risk-free rate.

        Returns:
            Dict with iron condor analysis.
        """
        try:
            result = analyze_iron_condor(
                underlying_price,
                put_buy_strike, put_sell_strike,
                call_sell_strike, call_buy_strike,
                put_buy_price, put_sell_price,
                call_sell_price, call_buy_price,
                expiry_days, volatility, risk_free_rate
            )

            return {
                "success": True,
                "strategy_type": result.strategy_type,
                "direction": result.direction,
                "net_credit": result.net_credit,
                "max_profit": result.max_profit,
                "max_loss": result.max_loss,
                "breakeven_up": result.breakeven_up,
                "breakeven_down": result.breakeven_down,
                "risk_reward_ratio": result.risk_reward_ratio,
                "probability_of_profit": result.pop,
                "expected_value": result.expected_value,
                "net_greeks": {
                    "delta": result.net_delta,
                    "gamma": result.net_gamma,
                    "theta": result.net_theta,
                    "vega": result.net_vega,
                }
            }
        except Exception as e:
            self.logger.warning(f"Iron condor analysis failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # PMCC Scanning Tools
    # =========================================================================

    async def scan_pmcc_candidates(
        self,
        symbols: List[str],
        chain_data: Dict[str, Dict],
        spot_prices: Dict[str, float],
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Batch scan symbols for PMCC (Poor Man's Covered Call) candidates.

        Evaluates each symbol's options for PMCC suitability using an
        11-point scoring system across delta accuracy, liquidity, spread
        tightness, IV level, and annual yield.

        Args:
            symbols: List of ticker symbols to scan.
            chain_data: Pre-fetched chain data: {symbol: {expiry: DataFrame}}.
            spot_prices: Current prices: {symbol: price}.
            config: Optional scoring configuration dict with keys:
                - leaps_delta_target (default 0.80)
                - short_delta_target (default 0.20)
                - min_leaps_days (default 270)
                - short_days_range (default [7, 21])
                - iv_sweet_spot (default [0.25, 0.50])
                - min_annual_yield (default 15.0)

        Returns:
            Dict with sorted candidates list, each containing score breakdown.
        """
        try:
            # Build scoring config from dict
            if config:
                scoring_config = PMCCScoringConfig(
                    leaps_delta_target=config.get('leaps_delta_target', 0.80),
                    short_delta_target=config.get('short_delta_target', 0.20),
                    min_leaps_days=config.get('min_leaps_days', 270),
                    short_days_range=tuple(config.get('short_days_range', [7, 21])),
                    iv_sweet_spot=tuple(config.get('iv_sweet_spot', [0.25, 0.50])),
                    min_annual_yield=config.get('min_annual_yield', 15.0),
                    risk_free_rate=config.get('risk_free_rate', 0.05),
                )
            else:
                scoring_config = PMCCScoringConfig()

            result = await _scan_pmcc(
                symbols, chain_data, spot_prices, scoring_config
            )

            return {
                "success": True,
                "candidates": [
                    {
                        "symbol": c.symbol,
                        "score": c.score,
                        "score_breakdown": c.score_breakdown,
                        "leaps_strike": c.leaps_strike,
                        "leaps_expiry": c.leaps_expiry,
                        "leaps_delta": c.leaps_delta,
                        "short_strike": c.short_strike,
                        "short_expiry": c.short_expiry,
                        "short_delta": c.short_delta,
                        "annual_yield_pct": c.annual_yield_pct,
                        "weekly_yield_pct": c.weekly_yield_pct,
                        "net_debit": c.net_debit,
                        "max_profit": c.max_profit,
                    }
                    for c in result.candidates
                ],
                "scanned_count": result.scanned_count,
                "valid_count": result.valid_count,
                "skipped_symbols": result.skipped_symbols,
            }
        except Exception as e:
            self.logger.warning(f"PMCC scan failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Risk Analysis Tools
    # =========================================================================

    async def stress_test_greeks(
        self,
        spot: float,
        strike: float,
        dte_days: int,
        volatility: float,
        option_type: Literal["call", "put"],
        scenarios: Dict[str, Dict[str, float]],
        risk_free_rate: float = 0.05
    ) -> Dict[str, Any]:
        """
        Compute Greeks under multiple 'what-if' scenarios.

        Useful for stress testing options positions against market moves.

        Args:
            spot: Current underlying price.
            strike: Option strike price.
            dte_days: Days to expiration.
            volatility: Base implied volatility.
            option_type: 'call' or 'put'.
            scenarios: Dict mapping scenario name to parameter changes:
                e.g., {"vol_up_5": {"volatility": 0.05}, "spot_down_10": {"spot": -10}}
                Changes are additive to base values.
            risk_free_rate: Risk-free rate.

        Returns:
            Dict with Greeks for each scenario, plus base case.
        """
        try:
            results = {}
            T = dte_days / 365.0

            # Base case
            base_greeks = black_scholes_greeks(
                spot, strike, T, risk_free_rate, volatility, option_type
            )
            results["base"] = {
                "price": base_greeks.price,
                "delta": base_greeks.delta,
                "gamma": base_greeks.gamma,
                "theta": base_greeks.theta,
                "vega": base_greeks.vega,
            }

            # Apply each scenario
            for name, changes in scenarios.items():
                s_spot = spot + changes.get('spot', 0)
                s_vol = volatility + changes.get('volatility', 0)
                s_dte = dte_days + int(changes.get('dte_days', 0))
                s_T = max(s_dte / 365.0, 0.001)  # Ensure positive T

                if s_vol <= 0:
                    results[name] = {"error": "Invalid volatility in scenario"}
                    continue

                try:
                    greeks = black_scholes_greeks(
                        s_spot, strike, s_T, risk_free_rate, s_vol, option_type
                    )
                    results[name] = {
                        "price": greeks.price,
                        "delta": greeks.delta,
                        "gamma": greeks.gamma,
                        "theta": greeks.theta,
                        "vega": greeks.vega,
                        "price_change": greeks.price - base_greeks.price,
                    }
                except Exception as e:
                    results[name] = {"error": str(e)}

            return {"success": True, "scenarios": results}
        except Exception as e:
            self.logger.warning(f"Stress test failed: {e}")
            return {"success": False, "error": str(e)}

    async def portfolio_greeks_exposure(
        self,
        positions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Compute net Greeks across a portfolio of option positions.

        Aggregates Greeks for multiple positions to show total exposure.

        Args:
            positions: List of position dicts, each with:
                - spot: Underlying price
                - strike: Option strike
                - dte_days: Days to expiration
                - volatility: Implied volatility
                - option_type: 'call' or 'put'
                - quantity: Position size (positive=long, negative=short)
                - risk_free_rate: (optional, default 0.05)

        Returns:
            Dict with aggregate net delta, gamma, theta, vega, rho.
        """
        try:
            net_delta = 0.0
            net_gamma = 0.0
            net_theta = 0.0
            net_vega = 0.0
            net_rho = 0.0
            position_details = []

            for pos in positions:
                T = pos['dte_days'] / 365.0
                r = pos.get('risk_free_rate', 0.05)
                qty = pos['quantity']

                greeks = black_scholes_greeks(
                    pos['spot'], pos['strike'], T, r,
                    pos['volatility'], pos['option_type']
                )

                # Aggregate with quantity
                pos_delta = greeks.delta * qty
                pos_gamma = greeks.gamma * qty
                pos_theta = greeks.theta * qty
                pos_vega = greeks.vega * qty
                pos_rho = greeks.rho * qty

                net_delta += pos_delta
                net_gamma += pos_gamma
                net_theta += pos_theta
                net_vega += pos_vega
                net_rho += pos_rho

                position_details.append({
                    "strike": pos['strike'],
                    "option_type": pos['option_type'],
                    "quantity": qty,
                    "delta_contribution": pos_delta,
                    "gamma_contribution": pos_gamma,
                    "theta_contribution": pos_theta,
                    "vega_contribution": pos_vega,
                })

            return {
                "success": True,
                "net_delta": net_delta,
                "net_gamma": net_gamma,
                "net_theta": net_theta,
                "net_vega": net_vega,
                "net_rho": net_rho,
                "position_count": len(positions),
                "position_details": position_details,
            }
        except Exception as e:
            self.logger.warning(f"Portfolio Greeks calculation failed: {e}")
            return {"success": False, "error": str(e)}

    async def calculate_probability_of_profit(
        self,
        spot: float,
        target_price: float,
        dte_days: int,
        volatility: float,
        direction: Literal["above", "below"],
        risk_free_rate: float = 0.05
    ) -> Dict[str, Any]:
        """
        Calculate probability of price being above or below a target.

        Uses lognormal distribution based on Black-Scholes assumptions.

        Args:
            spot: Current underlying price.
            target_price: Target price level.
            dte_days: Days to evaluation.
            volatility: Annualized implied volatility.
            direction: 'above' or 'below' target.
            risk_free_rate: Risk-free rate.

        Returns:
            Dict with probability and expected move.
        """
        try:
            T = dte_days / 365.0
            pop = probability_of_profit(
                spot, target_price, T, volatility, risk_free_rate, direction
            )

            # Expected move (1 standard deviation)
            import math
            expected_move_pct = volatility * math.sqrt(T)
            expected_move = spot * expected_move_pct

            return {
                "success": True,
                "probability": pop,
                "probability_pct": pop * 100,
                "direction": direction,
                "target_price": target_price,
                "expected_move_1sd": expected_move,
                "expected_move_1sd_pct": expected_move_pct * 100,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


# =============================================================================
# Module Exports
# =============================================================================

__all__ = ["OptionsAnalyticsToolkit"]
