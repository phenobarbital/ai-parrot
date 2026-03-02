"""
Option Spread Strategy Analyzers.

This module implements analysis functions for multi-leg option strategies:
- Vertical spreads (bull/bear call/put)
- Diagonal spreads (PMCC, calendar-like)
- Straddles (long/short)
- Strangles (long/short)
- Iron Condors

Each analyzer computes:
- Max profit / max loss
- Breakeven point(s)
- Probability of profit (POP)
- Expected value (EV)
- Net Greeks for the position

All functions are pure computation — no IO, no data fetching.
Callers supply pre-fetched option data.
"""
import math
from dataclasses import dataclass
from typing import Optional, Literal

from .models import OptionLeg
from .black_scholes import (
    black_scholes_greeks,
    probability_of_profit as bs_pop,
    probability_in_range,
)


# =============================================================================
# Result Dataclasses
# =============================================================================


@dataclass
class SpreadAnalysis:
    """
    Result from spread strategy analysis.

    Attributes:
        strategy_type: Type of spread ("vertical", "diagonal", "straddle", etc.)
        direction: "debit" (pay to enter) or "credit" (receive to enter)
        net_debit: Net amount paid (for debit spreads)
        net_credit: Net amount received (for credit spreads)
        max_profit: Maximum profit potential
        max_loss: Maximum loss potential
        breakeven: Single breakeven point (for verticals)
        breakeven_up: Upper breakeven (for straddles/strangles/IC)
        breakeven_down: Lower breakeven (for straddles/strangles/IC)
        risk_reward_ratio: max_profit / max_loss
        pop: Probability of profit (0-1)
        expected_value: POP * max_profit - (1-POP) * max_loss
        net_delta: Net position delta
        net_gamma: Net position gamma
        net_theta: Net position theta (per day)
        net_vega: Net position vega (per 1% vol)
    """
    strategy_type: str
    direction: Literal["debit", "credit"]
    net_debit: Optional[float]
    net_credit: Optional[float]
    max_profit: float
    max_loss: float
    breakeven: Optional[float]
    breakeven_up: Optional[float]
    breakeven_down: Optional[float]
    risk_reward_ratio: float
    pop: float
    expected_value: float
    net_delta: float
    net_gamma: float
    net_theta: float
    net_vega: float


# =============================================================================
# Vertical Spread Analyzer
# =============================================================================


def analyze_vertical(
    underlying_price: float,
    long_leg: OptionLeg,
    short_leg: OptionLeg,
    option_type: Literal["call", "put"],
    expiry_days: int,
    volatility: float,
    risk_free_rate: float = 0.05
) -> SpreadAnalysis:
    """
    Analyze a vertical spread (bull call, bear call, bull put, bear put).

    Vertical spreads involve buying and selling options of the same type
    with different strikes but same expiration.

    Strategy types:
    - Bull call spread: Buy lower strike call, sell higher strike call (debit)
    - Bear call spread: Sell lower strike call, buy higher strike call (credit)
    - Bull put spread: Sell higher strike put, buy lower strike put (credit)
    - Bear put spread: Buy higher strike put, sell lower strike put (debit)

    Args:
        underlying_price: Current price of underlying asset.
        long_leg: The option being bought.
        short_leg: The option being sold.
        option_type: "call" or "put".
        expiry_days: Days until expiration.
        volatility: Implied volatility for calculations.
        risk_free_rate: Risk-free rate.

    Returns:
        SpreadAnalysis with full metrics.
    """
    # Calculate mid prices
    long_mid = long_leg.mid if long_leg.mid else (long_leg.bid + long_leg.ask) / 2
    short_mid = short_leg.mid if short_leg.mid else (short_leg.bid + short_leg.ask) / 2

    # Net cost (positive = debit, negative = credit)
    net_cost = long_mid - short_mid
    width = abs(short_leg.strike - long_leg.strike)

    # Determine direction and calculate P/L
    if net_cost > 0:
        direction = "debit"
        net_debit = net_cost
        net_credit = None
        max_loss = net_debit
        max_profit = width - net_debit
    else:
        direction = "credit"
        net_credit = -net_cost
        net_debit = None
        max_profit = net_credit
        max_loss = width - net_credit

    # Breakeven calculation
    if option_type == "call":
        # For call spreads, breakeven is at lower strike + net cost
        if long_leg.strike < short_leg.strike:
            # Bull call spread
            breakeven = long_leg.strike + net_cost
        else:
            # Bear call spread
            breakeven = short_leg.strike + abs(net_cost)
    else:
        # For put spreads
        if long_leg.strike > short_leg.strike:
            # Bear put spread
            breakeven = long_leg.strike - net_cost
        else:
            # Bull put spread
            breakeven = short_leg.strike - abs(net_cost)

    # POP calculation
    T = expiry_days / 365.0
    if T > 0 and volatility > 0:
        # For debit spreads: profit when price moves favorably
        if option_type == "call":
            if direction == "debit":
                # Bull call: profit when price > breakeven
                pop = bs_pop(underlying_price, breakeven, T, volatility, risk_free_rate, "above")
            else:
                # Bear call: profit when price < breakeven
                pop = bs_pop(underlying_price, breakeven, T, volatility, risk_free_rate, "below")
        else:
            if direction == "debit":
                # Bear put: profit when price < breakeven
                pop = bs_pop(underlying_price, breakeven, T, volatility, risk_free_rate, "below")
            else:
                # Bull put: profit when price > breakeven
                pop = bs_pop(underlying_price, breakeven, T, volatility, risk_free_rate, "above")
    else:
        # At expiry
        if option_type == "call":
            pop = 1.0 if underlying_price > breakeven else 0.0
        else:
            pop = 1.0 if underlying_price < breakeven else 0.0

    # Expected value
    expected_value = pop * max_profit - (1 - pop) * max_loss

    # Risk/reward ratio
    risk_reward = max_profit / max_loss if max_loss > 0 else float('inf')

    # Net Greeks calculation
    if T > 0 and volatility > 0:
        long_greeks = black_scholes_greeks(
            underlying_price, long_leg.strike, T, risk_free_rate, volatility, option_type
        )
        short_greeks = black_scholes_greeks(
            underlying_price, short_leg.strike, T, risk_free_rate, volatility, option_type
        )

        net_delta = long_greeks.delta - short_greeks.delta
        net_gamma = long_greeks.gamma - short_greeks.gamma
        net_theta = long_greeks.theta - short_greeks.theta
        net_vega = long_greeks.vega - short_greeks.vega
    else:
        net_delta = net_gamma = net_theta = net_vega = 0.0

    return SpreadAnalysis(
        strategy_type="vertical",
        direction=direction,
        net_debit=net_debit,
        net_credit=net_credit,
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven=breakeven,
        breakeven_up=None,
        breakeven_down=None,
        risk_reward_ratio=risk_reward,
        pop=pop,
        expected_value=expected_value,
        net_delta=net_delta,
        net_gamma=net_gamma,
        net_theta=net_theta,
        net_vega=net_vega,
    )


# =============================================================================
# Diagonal Spread Analyzer (PMCC / Calendar-like)
# =============================================================================


def analyze_diagonal(
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
) -> SpreadAnalysis:
    """
    Analyze a diagonal spread (PMCC or calendar-like strategy).

    A diagonal spread involves buying a longer-dated option and selling
    a shorter-dated option at a different strike. PMCC (Poor Man's Covered Call)
    is a common diagonal strategy.

    Args:
        underlying_price: Current price of underlying.
        long_strike: Strike of the LEAPS (long-dated option).
        long_price: Price paid for the LEAPS.
        long_dte_days: Days to expiration for LEAPS.
        short_strike: Strike of the short-term option sold.
        short_price: Premium received for short option.
        short_dte_days: Days to expiration for short option.
        option_type: "call" or "put".
        volatility: Implied volatility.
        risk_free_rate: Risk-free rate.

    Returns:
        SpreadAnalysis with diagonal-specific metrics.
    """
    # Net debit (LEAPS cost - short premium)
    net_debit = long_price - short_price

    # For PMCC: max loss is the net debit if underlying goes to zero
    # Max profit is theoretically limited by short strike assignment
    if option_type == "call":
        # Max profit when underlying at short strike at short expiry
        max_profit_at_short_expiry = short_strike - long_strike + short_price
        if max_profit_at_short_expiry < 0:
            max_profit_at_short_expiry = short_price  # Just the premium if inverted
        max_loss = net_debit
    else:
        # For put diagonal
        max_profit_at_short_expiry = long_strike - short_strike + short_price
        if max_profit_at_short_expiry < 0:
            max_profit_at_short_expiry = short_price
        max_loss = net_debit

    # Breakeven approximation (depends on LEAPS value at short expiry)
    # Simplified: breakeven when LEAPS value = net_debit
    if option_type == "call":
        breakeven = long_strike + net_debit
    else:
        breakeven = long_strike - net_debit

    # POP for diagonal is complex; approximate using short expiry
    T_short = short_dte_days / 365.0
    if T_short > 0 and volatility > 0:
        if option_type == "call":
            # Profit if price stays below short strike (keep premium)
            # or above breakeven (LEAPS gains offset)
            pop = bs_pop(underlying_price, short_strike, T_short, volatility, risk_free_rate, "below")
        else:
            pop = bs_pop(underlying_price, short_strike, T_short, volatility, risk_free_rate, "above")
    else:
        pop = 0.5  # Uncertain at edge cases

    expected_value = pop * max_profit_at_short_expiry - (1 - pop) * max_loss

    # Greeks at current time using short DTE for responsiveness
    T_long = long_dte_days / 365.0
    T_short = short_dte_days / 365.0

    if T_short > 0 and T_long > 0 and volatility > 0:
        long_greeks = black_scholes_greeks(
            underlying_price, long_strike, T_long, risk_free_rate, volatility, option_type
        )
        short_greeks = black_scholes_greeks(
            underlying_price, short_strike, T_short, risk_free_rate, volatility, option_type
        )

        net_delta = long_greeks.delta - short_greeks.delta
        net_gamma = long_greeks.gamma - short_greeks.gamma
        net_theta = long_greeks.theta - short_greeks.theta  # Short theta helps
        net_vega = long_greeks.vega - short_greeks.vega
    else:
        net_delta = net_gamma = net_theta = net_vega = 0.0

    return SpreadAnalysis(
        strategy_type="diagonal",
        direction="debit",
        net_debit=net_debit,
        net_credit=None,
        max_profit=max_profit_at_short_expiry,
        max_loss=max_loss,
        breakeven=breakeven,
        breakeven_up=None,
        breakeven_down=None,
        risk_reward_ratio=max_profit_at_short_expiry / max_loss if max_loss > 0 else float('inf'),
        pop=pop,
        expected_value=expected_value,
        net_delta=net_delta,
        net_gamma=net_gamma,
        net_theta=net_theta,
        net_vega=net_vega,
    )


# =============================================================================
# Straddle Analyzer
# =============================================================================


def analyze_straddle(
    underlying_price: float,
    strike: float,
    call_bid: float,
    call_ask: float,
    put_bid: float,
    put_ask: float,
    expiry_days: int,
    volatility: float,
    risk_free_rate: float = 0.05
) -> SpreadAnalysis:
    """
    Analyze a long straddle (buy call + put at same strike).

    A straddle profits from large moves in either direction.
    Max loss is the total premium paid. Max profit is theoretically unlimited.

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
        SpreadAnalysis with straddle metrics.
    """
    # Calculate costs
    call_mid = (call_bid + call_ask) / 2
    put_mid = (put_bid + put_ask) / 2
    total_cost = call_mid + put_mid

    # Straddle is always a debit strategy
    net_debit = total_cost
    max_loss = total_cost

    # Max profit is theoretically unlimited (on upside)
    # We use a large number for practical purposes
    max_profit = float('inf')

    # Breakevens
    breakeven_up = strike + total_cost
    breakeven_down = strike - total_cost

    # POP: probability of price moving beyond either breakeven
    T = expiry_days / 365.0
    if T > 0 and volatility > 0:
        # POP = P(price < breakeven_down OR price > breakeven_up)
        # = P(price < breakeven_down) + P(price > breakeven_up)
        prob_below = bs_pop(underlying_price, breakeven_down, T, volatility, risk_free_rate, "below")
        prob_above = bs_pop(underlying_price, breakeven_up, T, volatility, risk_free_rate, "above")
        pop = prob_below + prob_above
    else:
        # At expiry
        if underlying_price < breakeven_down or underlying_price > breakeven_up:
            pop = 1.0
        else:
            pop = 0.0

    # For EV with unlimited profit, use expected move
    # Approximate expected profit using expected move
    expected_move_pct = volatility * math.sqrt(T) if T > 0 else 0
    expected_move = underlying_price * expected_move_pct
    avg_profit_if_profitable = max(expected_move - total_cost, 0)
    expected_value = pop * avg_profit_if_profitable - (1 - pop) * max_loss

    # Net Greeks (long call + long put)
    if T > 0 and volatility > 0:
        call_greeks = black_scholes_greeks(
            underlying_price, strike, T, risk_free_rate, volatility, "call"
        )
        put_greeks = black_scholes_greeks(
            underlying_price, strike, T, risk_free_rate, volatility, "put"
        )

        # Long both
        net_delta = call_greeks.delta + put_greeks.delta  # Near zero for ATM
        net_gamma = call_greeks.gamma + put_greeks.gamma  # Positive (long gamma)
        net_theta = call_greeks.theta + put_greeks.theta  # Negative (time decay)
        net_vega = call_greeks.vega + put_greeks.vega  # Positive (long vol)
    else:
        net_delta = net_gamma = net_theta = net_vega = 0.0

    return SpreadAnalysis(
        strategy_type="straddle",
        direction="debit",
        net_debit=net_debit,
        net_credit=None,
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven=None,
        breakeven_up=breakeven_up,
        breakeven_down=breakeven_down,
        risk_reward_ratio=float('inf'),  # Unlimited profit potential
        pop=pop,
        expected_value=expected_value,
        net_delta=net_delta,
        net_gamma=net_gamma,
        net_theta=net_theta,
        net_vega=net_vega,
    )


# =============================================================================
# Strangle Analyzer
# =============================================================================


def analyze_strangle(
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
) -> SpreadAnalysis:
    """
    Analyze a long strangle (buy OTM call + OTM put).

    A strangle is similar to a straddle but uses different strikes,
    typically OTM options making it cheaper but requiring larger moves.

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
        SpreadAnalysis with strangle metrics.
    """
    # Calculate costs
    call_mid = (call_bid + call_ask) / 2
    put_mid = (put_bid + put_ask) / 2
    total_cost = call_mid + put_mid

    # Strangle is a debit strategy
    net_debit = total_cost
    max_loss = total_cost
    max_profit = float('inf')  # Unlimited on upside

    # Breakevens
    breakeven_up = call_strike + total_cost
    breakeven_down = put_strike - total_cost

    # POP
    T = expiry_days / 365.0
    if T > 0 and volatility > 0:
        prob_below = bs_pop(underlying_price, breakeven_down, T, volatility, risk_free_rate, "below")
        prob_above = bs_pop(underlying_price, breakeven_up, T, volatility, risk_free_rate, "above")
        pop = prob_below + prob_above
    else:
        if underlying_price < breakeven_down or underlying_price > breakeven_up:
            pop = 1.0
        else:
            pop = 0.0

    # Expected value approximation
    expected_move_pct = volatility * math.sqrt(T) if T > 0 else 0
    expected_move = underlying_price * expected_move_pct
    avg_profit_if_profitable = max(expected_move - total_cost, 0)
    expected_value = pop * avg_profit_if_profitable - (1 - pop) * max_loss

    # Net Greeks
    if T > 0 and volatility > 0:
        call_greeks = black_scholes_greeks(
            underlying_price, call_strike, T, risk_free_rate, volatility, "call"
        )
        put_greeks = black_scholes_greeks(
            underlying_price, put_strike, T, risk_free_rate, volatility, "put"
        )

        net_delta = call_greeks.delta + put_greeks.delta
        net_gamma = call_greeks.gamma + put_greeks.gamma
        net_theta = call_greeks.theta + put_greeks.theta
        net_vega = call_greeks.vega + put_greeks.vega
    else:
        net_delta = net_gamma = net_theta = net_vega = 0.0

    return SpreadAnalysis(
        strategy_type="strangle",
        direction="debit",
        net_debit=net_debit,
        net_credit=None,
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven=None,
        breakeven_up=breakeven_up,
        breakeven_down=breakeven_down,
        risk_reward_ratio=float('inf'),
        pop=pop,
        expected_value=expected_value,
        net_delta=net_delta,
        net_gamma=net_gamma,
        net_theta=net_theta,
        net_vega=net_vega,
    )


# =============================================================================
# Iron Condor Analyzer
# =============================================================================


def analyze_iron_condor(
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
) -> SpreadAnalysis:
    """
    Analyze an iron condor (bull put spread + bear call spread).

    An iron condor profits when the underlying stays within a range.
    It combines:
    - Bull put spread: Sell higher strike put, buy lower strike put
    - Bear call spread: Sell lower strike call, buy higher strike call

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
        SpreadAnalysis with iron condor metrics.
    """
    # Net credit received
    put_credit = put_sell_price - put_buy_price
    call_credit = call_sell_price - call_buy_price
    net_credit = put_credit + call_credit

    # Wing widths
    put_width = put_sell_strike - put_buy_strike
    call_width = call_buy_strike - call_sell_strike

    # Max loss is the wider wing minus credit
    max_wing_width = max(put_width, call_width)
    max_loss = max_wing_width - net_credit
    max_profit = net_credit

    # Breakevens
    breakeven_down = put_sell_strike - net_credit
    breakeven_up = call_sell_strike + net_credit

    # POP: probability of staying between short strikes
    T = expiry_days / 365.0
    if T > 0 and volatility > 0:
        pop = probability_in_range(
            underlying_price, put_sell_strike, call_sell_strike,
            T, volatility, risk_free_rate
        )
    else:
        # At expiry
        if put_sell_strike <= underlying_price <= call_sell_strike:
            pop = 1.0
        else:
            pop = 0.0

    expected_value = pop * max_profit - (1 - pop) * max_loss

    # Net Greeks (4 legs)
    if T > 0 and volatility > 0:
        put_buy_greeks = black_scholes_greeks(
            underlying_price, put_buy_strike, T, risk_free_rate, volatility, "put"
        )
        put_sell_greeks = black_scholes_greeks(
            underlying_price, put_sell_strike, T, risk_free_rate, volatility, "put"
        )
        call_sell_greeks = black_scholes_greeks(
            underlying_price, call_sell_strike, T, risk_free_rate, volatility, "call"
        )
        call_buy_greeks = black_scholes_greeks(
            underlying_price, call_buy_strike, T, risk_free_rate, volatility, "call"
        )

        # Long put_buy, short put_sell, short call_sell, long call_buy
        net_delta = (
            put_buy_greeks.delta
            - put_sell_greeks.delta
            - call_sell_greeks.delta
            + call_buy_greeks.delta
        )
        net_gamma = (
            put_buy_greeks.gamma
            - put_sell_greeks.gamma
            - call_sell_greeks.gamma
            + call_buy_greeks.gamma
        )
        net_theta = (
            put_buy_greeks.theta
            - put_sell_greeks.theta
            - call_sell_greeks.theta
            + call_buy_greeks.theta
        )
        net_vega = (
            put_buy_greeks.vega
            - put_sell_greeks.vega
            - call_sell_greeks.vega
            + call_buy_greeks.vega
        )
    else:
        net_delta = net_gamma = net_theta = net_vega = 0.0

    return SpreadAnalysis(
        strategy_type="iron_condor",
        direction="credit",
        net_debit=None,
        net_credit=net_credit,
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven=None,
        breakeven_up=breakeven_up,
        breakeven_down=breakeven_down,
        risk_reward_ratio=max_profit / max_loss if max_loss > 0 else float('inf'),
        pop=pop,
        expected_value=expected_value,
        net_delta=net_delta,
        net_gamma=net_gamma,
        net_theta=net_theta,
        net_vega=net_vega,
    )


# =============================================================================
# Module exports
# =============================================================================

__all__ = [
    "SpreadAnalysis",
    "analyze_vertical",
    "analyze_diagonal",
    "analyze_straddle",
    "analyze_strangle",
    "analyze_iron_condor",
]
