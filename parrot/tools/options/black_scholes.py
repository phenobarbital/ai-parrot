"""
Black-Scholes Option Pricing Engine.

This module implements the Black-Scholes-Merton option pricing model,
Greeks calculations, implied volatility solver, and related utilities.

All functions are pure computation — no IO, no external API calls.
They accept numerical inputs and return structured results.

Key Functions:
- black_scholes_price: Calculate theoretical option price
- black_scholes_greeks: Calculate all Greeks for an option
- implied_volatility: Solve for IV from market price
- compute_chain_greeks: Vectorized batch Greeks computation
- probability_of_profit: Calculate POP for a position

References:
- Black, F., & Scholes, M. (1973). The Pricing of Options and Corporate Liabilities.
- Hull, J. (2018). Options, Futures, and Other Derivatives.
"""
import math
from typing import Optional, Dict, Any, Literal

import numpy as np
import pandas as pd
from scipy.stats import norm

from .models import IVResult, GreeksResult


# =============================================================================
# Core Black-Scholes Pricing
# =============================================================================


def black_scholes_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: Literal["call", "put"]
) -> float:
    """
    Calculate the Black-Scholes theoretical option price.

    Args:
        S: Current spot price of the underlying asset.
        K: Strike price of the option.
        T: Time to expiration in years (e.g., 30 days = 30/365).
        r: Risk-free interest rate (annualized, e.g., 0.05 for 5%).
        sigma: Volatility (annualized, e.g., 0.25 for 25%).
        option_type: "call" or "put".

    Returns:
        Theoretical option price.

    Raises:
        ValueError: If sigma <= 0 (when T > 0) or invalid option_type.

    Examples:
        >>> black_scholes_price(100, 100, 1.0, 0.05, 0.20, "call")
        10.450583572185565
    """
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got '{option_type}'")

    # At expiration, return intrinsic value
    if T <= 0:
        if option_type == "call":
            return max(S - K, 0.0)
        return max(K - S, 0.0)

    # Validate volatility
    if sigma <= 0:
        raise ValueError("Volatility (sigma) must be positive when T > 0")

    # Calculate d1 and d2
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    # Calculate price based on option type
    if option_type == "call":
        price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

    return price


# =============================================================================
# Individual Greeks
# =============================================================================


def black_scholes_delta(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: Literal["call", "put"]
) -> float:
    """
    Calculate option delta (dPrice/dSpot).

    Delta measures the rate of change of option price with respect to
    changes in the underlying asset's price.

    Args:
        S: Spot price.
        K: Strike price.
        T: Time to expiration in years.
        r: Risk-free rate.
        sigma: Volatility.
        option_type: "call" or "put".

    Returns:
        Delta value. Range: [0, 1] for calls, [-1, 0] for puts.
    """
    if T <= 0:
        # At expiry: delta is 1 for ITM, 0 for OTM
        if option_type == "call":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0

    if sigma <= 0:
        raise ValueError("Volatility must be positive")

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))

    if option_type == "call":
        return norm.cdf(d1)
    return norm.cdf(d1) - 1.0


def black_scholes_gamma(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float
) -> float:
    """
    Calculate option gamma (d²Price/dSpot²).

    Gamma measures the rate of change of delta with respect to
    changes in the underlying price. Same for calls and puts.

    Args:
        S: Spot price.
        K: Strike price.
        T: Time to expiration in years.
        r: Risk-free rate.
        sigma: Volatility.

    Returns:
        Gamma value (always positive).
    """
    if T <= 0 or sigma <= 0:
        return 0.0

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)

    return norm.pdf(d1) / (S * sigma * sqrt_T)


def black_scholes_vega(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float
) -> float:
    """
    Calculate option vega (dPrice/dSigma).

    Vega measures sensitivity to changes in implied volatility.
    Same for calls and puts. Returned per 1% (0.01) change in vol.

    Args:
        S: Spot price.
        K: Strike price.
        T: Time to expiration in years.
        r: Risk-free rate.
        sigma: Volatility.

    Returns:
        Vega value per 1% vol change (price change for 0.01 sigma change).
    """
    if T <= 0 or sigma <= 0:
        return 0.0

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)

    # Raw vega (per 1 unit change in sigma)
    raw_vega = S * sqrt_T * norm.pdf(d1)

    # Return per 1% (0.01) change
    return raw_vega * 0.01


def black_scholes_theta(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: Literal["call", "put"]
) -> float:
    """
    Calculate option theta (dPrice/dTime).

    Theta measures the rate of time decay per calendar day.
    Returns negative value for long options (time decay is a cost).

    Args:
        S: Spot price.
        K: Strike price.
        T: Time to expiration in years.
        r: Risk-free rate.
        sigma: Volatility.
        option_type: "call" or "put".

    Returns:
        Theta per calendar day (negative for long options).
    """
    if T <= 0 or sigma <= 0:
        return 0.0

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    # Common term
    term1 = -(S * norm.pdf(d1) * sigma) / (2 * sqrt_T)

    if option_type == "call":
        term2 = -r * K * math.exp(-r * T) * norm.cdf(d2)
        theta_annual = term1 + term2
    else:
        term2 = r * K * math.exp(-r * T) * norm.cdf(-d2)
        theta_annual = term1 + term2

    # Convert to per-day
    return theta_annual / 365.0


def black_scholes_rho(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: Literal["call", "put"]
) -> float:
    """
    Calculate option rho (dPrice/dRate).

    Rho measures sensitivity to changes in the risk-free rate.
    Returned per 1% (0.01) change in rate.

    Args:
        S: Spot price.
        K: Strike price.
        T: Time to expiration in years.
        r: Risk-free rate.
        sigma: Volatility.
        option_type: "call" or "put".

    Returns:
        Rho per 1% rate change.
    """
    if T <= 0 or sigma <= 0:
        return 0.0

    sqrt_T = math.sqrt(T)
    d2 = (math.log(S / K) + (r - 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)

    if option_type == "call":
        raw_rho = K * T * math.exp(-r * T) * norm.cdf(d2)
    else:
        raw_rho = -K * T * math.exp(-r * T) * norm.cdf(-d2)

    # Return per 1% (0.01) rate change
    return raw_rho * 0.01


# =============================================================================
# Full Greeks Calculation
# =============================================================================


def black_scholes_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: Literal["call", "put"]
) -> GreeksResult:
    """
    Calculate all Black-Scholes Greeks for an option.

    Args:
        S: Spot price.
        K: Strike price.
        T: Time to expiration in years.
        r: Risk-free rate.
        sigma: Volatility.
        option_type: "call" or "put".

    Returns:
        GreeksResult dataclass with price, delta, gamma, theta, vega, rho.

    Raises:
        ValueError: If sigma <= 0 when T > 0.
    """
    price = black_scholes_price(S, K, T, r, sigma, option_type)
    delta = black_scholes_delta(S, K, T, r, sigma, option_type)
    gamma = black_scholes_gamma(S, K, T, r, sigma)
    theta = black_scholes_theta(S, K, T, r, sigma, option_type)
    vega = black_scholes_vega(S, K, T, r, sigma)
    rho = black_scholes_rho(S, K, T, r, sigma, option_type)

    return GreeksResult(
        price=price,
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
        rho=rho
    )


# =============================================================================
# Implied Volatility Solver
# =============================================================================


def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: Literal["call", "put"],
    initial_guess: float = 0.3,
    max_iterations: int = 100,
    tolerance: float = 1e-6
) -> IVResult:
    """
    Solve for implied volatility using Newton-Raphson with bisection fallback.

    Args:
        market_price: Observed market price of the option.
        S: Spot price.
        K: Strike price.
        T: Time to expiration in years.
        r: Risk-free rate.
        option_type: "call" or "put".
        initial_guess: Starting volatility estimate (default 0.3 = 30%).
        max_iterations: Maximum solver iterations.
        tolerance: Convergence tolerance.

    Returns:
        IVResult with iv, converged flag, iterations, and method used.
    """
    # Edge case: at expiry
    if T <= 0:
        return IVResult(iv=0.0, converged=False, iterations=0, method="newton_raphson")

    # Edge case: price is below intrinsic value (impossible)
    if option_type == "call":
        intrinsic = max(S - K * math.exp(-r * T), 0.0)
    else:
        intrinsic = max(K * math.exp(-r * T) - S, 0.0)

    if market_price < intrinsic - tolerance:
        return IVResult(iv=0.0, converged=False, iterations=0, method="newton_raphson")

    # Edge case: price is essentially at intrinsic (very low IV)
    if market_price <= intrinsic + tolerance:
        return IVResult(iv=0.001, converged=True, iterations=1, method="newton_raphson")

    # Try Newton-Raphson first
    sigma = initial_guess
    for i in range(max_iterations):
        try:
            price = black_scholes_price(S, K, T, r, sigma, option_type)
            vega_raw = black_scholes_vega(S, K, T, r, sigma) / 0.01  # Convert back to raw

            if abs(vega_raw) < 1e-10:
                break  # Vega too small, switch to bisection

            diff = price - market_price
            if abs(diff) < tolerance:
                return IVResult(
                    iv=sigma,
                    converged=True,
                    iterations=i + 1,
                    method="newton_raphson"
                )

            # Newton-Raphson update
            sigma_new = sigma - diff / vega_raw

            # Check for invalid update
            if sigma_new <= 0 or sigma_new > 10:
                break

            sigma = sigma_new

        except (ValueError, ZeroDivisionError):
            break

    # Bisection fallback
    return _bisection_iv(market_price, S, K, T, r, option_type, max_iterations, tolerance)


def _bisection_iv(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str,
    max_iterations: int,
    tolerance: float
) -> IVResult:
    """
    Bisection method for IV solving (fallback).

    Searches between sigma_low=0.001 and sigma_high=5.0.
    """
    sigma_low = 0.001
    sigma_high = 5.0

    for i in range(max_iterations):
        sigma_mid = (sigma_low + sigma_high) / 2.0

        try:
            price_mid = black_scholes_price(S, K, T, r, sigma_mid, option_type)
        except ValueError:
            return IVResult(iv=0.0, converged=False, iterations=i + 1, method="bisection")

        diff = price_mid - market_price

        if abs(diff) < tolerance:
            return IVResult(
                iv=sigma_mid,
                converged=True,
                iterations=i + 1,
                method="bisection"
            )

        if diff > 0:
            sigma_high = sigma_mid
        else:
            sigma_low = sigma_mid

        # Check if bounds are too close
        if sigma_high - sigma_low < tolerance:
            return IVResult(
                iv=sigma_mid,
                converged=True,
                iterations=i + 1,
                method="bisection"
            )

    return IVResult(
        iv=(sigma_low + sigma_high) / 2.0,
        converged=False,
        iterations=max_iterations,
        method="bisection"
    )


def estimate_iv(
    S: float,
    K: float,
    T: float,
    option_type: Literal["call", "put"],
    historical_vol: Optional[float] = None
) -> float:
    """
    Estimate implied volatility when market IV is unavailable.

    Uses a heuristic based on moneyness and time to expiry.
    This is a rough approximation for initialization purposes.

    Args:
        S: Spot price.
        K: Strike price.
        T: Time to expiration in years.
        option_type: "call" or "put".
        historical_vol: Historical volatility if available (better base).

    Returns:
        Estimated IV as a float.
    """
    # Base volatility
    base_vol = historical_vol if historical_vol else 0.30

    # Moneyness adjustment
    moneyness = S / K
    if option_type == "call":
        # OTM calls tend to have higher IV (volatility smile)
        if moneyness < 0.95:  # ITM call
            moneyness_adj = 0.95
        elif moneyness > 1.05:  # OTM call
            moneyness_adj = 1.0 + (moneyness - 1.0) * 0.5
        else:
            moneyness_adj = 1.0
    else:
        # OTM puts tend to have higher IV (volatility skew)
        if moneyness > 1.05:  # ITM put
            moneyness_adj = 0.95
        elif moneyness < 0.95:  # OTM put
            moneyness_adj = 1.0 + (1.0 - moneyness) * 0.5
        else:
            moneyness_adj = 1.0

    # Time adjustment (shorter expiry often has higher IV)
    if T < 0.05:  # Less than ~18 days
        time_adj = 1.2
    elif T < 0.25:  # Less than 3 months
        time_adj = 1.1
    else:
        time_adj = 1.0

    return base_vol * moneyness_adj * time_adj


# =============================================================================
# Put-Call Parity
# =============================================================================


def validate_put_call_parity(
    call_price: float,
    put_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    tolerance: float = 0.05
) -> Dict[str, Any]:
    """
    Validate put-call parity relationship.

    Put-call parity states: C - P = S - K*e^(-rT)

    Args:
        call_price: Market call price.
        put_price: Market put price.
        S: Spot price.
        K: Strike price.
        T: Time to expiration.
        r: Risk-free rate.
        tolerance: Acceptable deviation as percentage of spot.

    Returns:
        Dict with:
        - theoretical_spread: Expected C - P from parity
        - market_spread: Actual C - P
        - spread: Deviation from parity
        - arbitrage_flag: True if deviation exceeds tolerance
    """
    theoretical_spread = S - K * math.exp(-r * T)
    market_spread = call_price - put_price
    deviation = market_spread - theoretical_spread

    # Check if arbitrage opportunity exists
    tolerance_value = S * tolerance
    arbitrage_flag = abs(deviation) > tolerance_value

    return {
        "theoretical_spread": theoretical_spread,
        "market_spread": market_spread,
        "spread": deviation,
        "arbitrage_flag": arbitrage_flag,
        "tolerance_used": tolerance_value
    }


# =============================================================================
# Batch / Vectorized Operations
# =============================================================================


def compute_chain_greeks(
    chain: pd.DataFrame,
    spot: float,
    r: float,
    dte_years: float,
    option_type: Literal["call", "put"] = "call",
    iv_column: str = "impliedVolatility"
) -> pd.DataFrame:
    """
    Compute Greeks for an entire option chain (vectorized).

    This is significantly faster than computing Greeks row-by-row
    for large chains, using numpy vectorization.

    Args:
        chain: DataFrame with 'strike' column and IV column.
        spot: Current spot price.
        r: Risk-free rate.
        dte_years: Days to expiration in years.
        option_type: "call" or "put".
        iv_column: Name of IV column in DataFrame.

    Returns:
        DataFrame with added columns: price, delta, gamma, theta, vega, rho.
    """
    result = chain.copy()

    # Extract arrays
    strikes = chain["strike"].values
    ivs = chain[iv_column].values if iv_column in chain.columns else np.full(len(chain), 0.25)

    # Handle edge case: at expiry
    if dte_years <= 0:
        if option_type == "call":
            result["price"] = np.maximum(spot - strikes, 0)
            result["delta"] = np.where(spot > strikes, 1.0, 0.0)
        else:
            result["price"] = np.maximum(strikes - spot, 0)
            result["delta"] = np.where(spot < strikes, -1.0, 0.0)
        result["gamma"] = 0.0
        result["theta"] = 0.0
        result["vega"] = 0.0
        result["rho"] = 0.0
        return result

    # Vectorized calculation
    sqrt_T = np.sqrt(dte_years)

    # Handle zero/negative IV
    valid_iv = ivs > 0
    safe_ivs = np.where(valid_iv, ivs, 0.25)  # Use 0.25 as fallback

    d1 = (np.log(spot / strikes) + (r + 0.5 * safe_ivs ** 2) * dte_years) / (safe_ivs * sqrt_T)
    d2 = d1 - safe_ivs * sqrt_T

    # Price
    if option_type == "call":
        prices = spot * norm.cdf(d1) - strikes * np.exp(-r * dte_years) * norm.cdf(d2)
        deltas = norm.cdf(d1)
        rhos = strikes * dte_years * np.exp(-r * dte_years) * norm.cdf(d2) * 0.01
    else:
        prices = strikes * np.exp(-r * dte_years) * norm.cdf(-d2) - spot * norm.cdf(-d1)
        deltas = norm.cdf(d1) - 1.0
        rhos = -strikes * dte_years * np.exp(-r * dte_years) * norm.cdf(-d2) * 0.01

    # Gamma (same for call and put)
    gammas = norm.pdf(d1) / (spot * safe_ivs * sqrt_T)

    # Vega (same for call and put, per 1% change)
    vegas = spot * sqrt_T * norm.pdf(d1) * 0.01

    # Theta
    term1 = -(spot * norm.pdf(d1) * safe_ivs) / (2 * sqrt_T)
    if option_type == "call":
        term2 = -r * strikes * np.exp(-r * dte_years) * norm.cdf(d2)
    else:
        term2 = r * strikes * np.exp(-r * dte_years) * norm.cdf(-d2)
    thetas = (term1 + term2) / 365.0

    # Assign to DataFrame
    result["price"] = prices
    result["delta"] = deltas
    result["gamma"] = gammas
    result["theta"] = thetas
    result["vega"] = vegas
    result["rho"] = rhos

    # Handle invalid IV rows
    result.loc[~valid_iv, ["gamma", "theta", "vega", "rho"]] = 0.0

    return result


# =============================================================================
# Probability of Profit
# =============================================================================


def probability_of_profit(
    spot: float,
    breakeven: float,
    T: float,
    sigma: float,
    r: float = 0.05,
    direction: Literal["above", "below"] = "above"
) -> float:
    """
    Calculate probability of profit for a position.

    Uses lognormal distribution assumption (GBM).

    Args:
        spot: Current spot price.
        breakeven: Breakeven price for the position.
        T: Time to expiration in years.
        sigma: Implied volatility.
        r: Risk-free rate (used for drift).
        direction: "above" if profit when price > breakeven,
                  "below" if profit when price < breakeven.

    Returns:
        Probability between 0 and 1.
    """
    if T <= 0:
        # At expiry, binary outcome
        if direction == "above":
            return 1.0 if spot > breakeven else 0.0
        return 1.0 if spot < breakeven else 0.0

    if sigma <= 0:
        raise ValueError("Volatility must be positive")

    # Using risk-neutral drift (or can use r - 0.5*sigma^2 for physical)
    drift = r - 0.5 * sigma ** 2
    sqrt_T = math.sqrt(T)

    # d = (ln(breakeven/spot) - drift*T) / (sigma*sqrt(T))
    d = (math.log(breakeven / spot) - drift * T) / (sigma * sqrt_T)

    if direction == "above":
        # P(S_T > breakeven) = 1 - N(d)
        return 1.0 - norm.cdf(d)
    else:
        # P(S_T < breakeven) = N(d)
        return norm.cdf(d)


def probability_in_range(
    spot: float,
    lower_bound: float,
    upper_bound: float,
    T: float,
    sigma: float,
    r: float = 0.05
) -> float:
    """
    Calculate probability of price staying within a range.

    Useful for iron condors and other range-bound strategies.

    Args:
        spot: Current spot price.
        lower_bound: Lower price boundary.
        upper_bound: Upper price boundary.
        T: Time to expiration in years.
        sigma: Implied volatility.
        r: Risk-free rate.

    Returns:
        Probability of price ending between bounds.
    """
    prob_below_upper = probability_of_profit(spot, upper_bound, T, sigma, r, "below")
    prob_below_lower = probability_of_profit(spot, lower_bound, T, sigma, r, "below")

    return prob_below_upper - prob_below_lower


# =============================================================================
# Module exports
# =============================================================================

__all__ = [
    # Core pricing
    "black_scholes_price",
    # Individual Greeks
    "black_scholes_delta",
    "black_scholes_gamma",
    "black_scholes_vega",
    "black_scholes_theta",
    "black_scholes_rho",
    # Full Greeks
    "black_scholes_greeks",
    # IV solver
    "implied_volatility",
    "estimate_iv",
    # Parity
    "validate_put_call_parity",
    # Batch operations
    "compute_chain_greeks",
    # Probability
    "probability_of_profit",
    "probability_in_range",
]
