"""
Volatility Analytics for QuantToolkit.

Provides volatility analysis for sentiment and risk monitoring:
- Realized volatility estimators (close-to-close, Parkinson, Garman-Klass)
- Volatility cone analysis (percentile ranks across windows)
- IV vs RV spread analysis with regime classification

Volatility Estimator Comparison:
- Close-to-Close: Most common, uses return standard deviation
- Parkinson (1980): Uses high-low range, ~5x more efficient
- Garman-Klass (1980): Uses OHLC, most efficient estimator
"""

from typing import Literal

import numpy as np
import pandas as pd


# =============================================================================
# REALIZED VOLATILITY ESTIMATORS
# =============================================================================


def compute_realized_volatility(
    returns: list[float],
    window: int = 20,
    annualization: int = 252,
    method: Literal["close_to_close", "parkinson", "garman_klass"] = "close_to_close",
    ohlc_data: dict[str, list[float]] | None = None,
) -> list[float]:
    """Compute rolling realized volatility.

    Methods:
    - close_to_close: Standard deviation of returns (most common)
    - parkinson: Uses high-low range, ~5x more efficient than close-to-close
    - garman_klass: Uses OHLC, most efficient estimator

    Args:
        returns: Daily return series (for close_to_close method).
        window: Rolling window size.
        annualization: 252 for stocks, 365 for crypto.
        method: Volatility estimator method.
        ohlc_data: Required for parkinson/garman_klass.
            Format: {"high": [], "low": [], "open": [], "close": []}

    Returns:
        List of rolling annualized volatility values.

    Raises:
        ValueError: If method requires ohlc_data but not provided.
    """
    if method == "close_to_close":
        return _compute_close_to_close_vol(returns, window, annualization)
    elif method == "parkinson":
        return _compute_parkinson_vol(ohlc_data, window, annualization)
    elif method == "garman_klass":
        return _compute_garman_klass_vol(ohlc_data, window, annualization)
    else:
        raise ValueError(f"Unknown method: {method}")


def _compute_close_to_close_vol(
    returns: list[float],
    window: int,
    annualization: int,
) -> list[float]:
    """Close-to-close volatility using return standard deviation."""
    if len(returns) < window:
        return []
    returns_arr = np.array(returns)
    rolling_std = pd.Series(returns_arr).rolling(window).std()
    annualized = rolling_std.dropna() * np.sqrt(annualization)
    return [float(v) for v in annualized]


def _compute_parkinson_vol(
    ohlc_data: dict[str, list[float]] | None,
    window: int,
    annualization: int,
) -> list[float]:
    """Parkinson (1980) volatility estimator.

    Uses high-low range. More efficient than close-to-close.

    Formula: sigma^2 = (1 / (4 * ln(2))) * E[ln(H/L)^2]
    """
    if ohlc_data is None:
        raise ValueError("ohlc_data required for Parkinson estimator")

    high = np.array(ohlc_data["high"])
    low = np.array(ohlc_data["low"])

    if len(high) < window or len(low) < window:
        return []

    # Avoid division by zero
    low = np.where(low <= 0, np.nan, low)
    high = np.where(high <= 0, np.nan, high)

    log_hl_sq = np.log(high / low) ** 2
    factor = 1 / (4 * np.log(2))

    rolling_var = pd.Series(log_hl_sq).rolling(window).mean() * factor
    annualized = np.sqrt(rolling_var.dropna() * annualization)

    return [float(v) for v in annualized if not np.isnan(v)]


def _compute_garman_klass_vol(
    ohlc_data: dict[str, list[float]] | None,
    window: int,
    annualization: int,
) -> list[float]:
    """Garman-Klass (1980) volatility estimator.

    Uses full OHLC data. Most efficient estimator.

    Formula: sigma^2 = 0.5 * ln(H/L)^2 - (2*ln(2) - 1) * ln(C/O)^2
    """
    if ohlc_data is None:
        raise ValueError("ohlc_data required for Garman-Klass estimator")

    high = np.array(ohlc_data["high"])
    low = np.array(ohlc_data["low"])
    open_ = np.array(ohlc_data["open"])
    close = np.array(ohlc_data["close"])

    if len(high) < window:
        return []

    # Avoid division by zero
    low = np.where(low <= 0, np.nan, low)
    open_ = np.where(open_ <= 0, np.nan, open_)

    log_hl_sq = np.log(high / low) ** 2
    log_co_sq = np.log(close / open_) ** 2

    gk_var = 0.5 * log_hl_sq - (2 * np.log(2) - 1) * log_co_sq

    rolling_var = pd.Series(gk_var).rolling(window).mean()
    # Handle negative variance (can happen with certain data)
    rolling_var = rolling_var.clip(lower=0)
    annualized = np.sqrt(rolling_var.dropna() * annualization)

    return [float(v) for v in annualized if not np.isnan(v)]


# =============================================================================
# SINGLE-POINT VOLATILITY
# =============================================================================


def compute_volatility_single(
    returns: list[float],
    annualization: int = 252,
) -> float:
    """Compute single volatility value from returns.

    Args:
        returns: Return series.
        annualization: Annualization factor.

    Returns:
        Annualized volatility.
    """
    if len(returns) < 2:
        return 0.0
    std = np.std(returns, ddof=1)
    return float(std * np.sqrt(annualization))


# =============================================================================
# VOLATILITY CONE
# =============================================================================


def compute_volatility_cone(
    returns: list[float],
    windows: list[int] | None = None,
    annualization: int = 252,
) -> dict:
    """Compute percentile ranks of current volatility across multiple windows.

    Answers: "Is current 20-day vol high or low relative to history?"

    Args:
        returns: Daily return series.
        windows: List of window sizes to analyze. Default: [10, 20, 30, 60, 90, 120].
        annualization: Annualization factor.

    Returns:
        Dictionary with structure:
        {
            window: {
                "current": float,
                "percentile": float (0-100),
                "min": float,
                "max": float,
                "median": float,
            }
        }
    """
    if windows is None:
        windows = [10, 20, 30, 60, 90, 120]

    returns_arr = np.array(returns)
    result = {}

    for window in windows:
        if len(returns_arr) < window + 1:
            continue

        # Compute rolling volatility history
        rolling_vol = (
            pd.Series(returns_arr).rolling(window).std() * np.sqrt(annualization)
        )
        rolling_vol = rolling_vol.dropna()

        if len(rolling_vol) == 0:
            continue

        current_vol = float(rolling_vol.iloc[-1])
        percentile = float((rolling_vol < current_vol).mean() * 100)

        result[window] = {
            "current": round(current_vol, 4),
            "percentile": round(percentile, 1),
            "min": round(float(rolling_vol.min()), 4),
            "max": round(float(rolling_vol.max()), 4),
            "median": round(float(rolling_vol.median()), 4),
        }

    return result


def interpret_volatility_cone(cone_result: dict) -> str:
    """Interpret volatility cone results.

    Args:
        cone_result: Result from compute_volatility_cone.

    Returns:
        Interpretation string.
    """
    if not cone_result:
        return "Insufficient data for volatility cone analysis."

    # Use 20-day window if available, otherwise first available
    key_window = 20 if 20 in cone_result else list(cone_result.keys())[0]
    data = cone_result[key_window]

    percentile = data["percentile"]

    if percentile >= 80:
        return f"Volatility is ELEVATED ({percentile:.0f}th percentile). Current {key_window}-day vol is near historical highs."
    elif percentile <= 20:
        return f"Volatility is LOW ({percentile:.0f}th percentile). Current {key_window}-day vol is near historical lows."
    else:
        return f"Volatility is NORMAL ({percentile:.0f}th percentile). Current {key_window}-day vol is within typical range."


# =============================================================================
# IV vs RV SPREAD ANALYSIS
# =============================================================================


def compute_iv_rv_spread(
    implied_vol: float,
    realized_vol_series: list[float],
    window: int = 20,
) -> dict:
    """Compute IV vs RV spread and classify the regime.

    - IV >> RV: Fear premium is elevated (contrarian buy signal)
    - IV << RV: Complacency (contrarian sell signal)
    - IV ≈ RV: Normal regime

    Args:
        implied_vol: Current implied volatility (annualized, from options).
        realized_vol_series: Historical realized vol series.
        window: Window for current RV calculation.

    Returns:
        Dictionary with:
        - implied_vol: float
        - realized_vol: float
        - spread: float (IV - RV)
        - spread_pct: float ((IV - RV) / RV * 100)
        - percentile: float (where current spread falls historically)
        - regime: "fear_premium" | "complacent" | "normal"
    """
    if len(realized_vol_series) == 0:
        return {
            "implied_vol": round(implied_vol, 4),
            "realized_vol": 0.0,
            "spread": 0.0,
            "spread_pct": 0.0,
            "percentile": 50.0,
            "regime": "normal",
        }

    rv_arr = np.array(realized_vol_series)

    # Current realized vol
    current_rv = (
        float(np.mean(rv_arr[-window:])) if len(rv_arr) >= window else float(np.mean(rv_arr))
    )

    spread = implied_vol - current_rv
    spread_pct = (spread / current_rv * 100) if current_rv > 0 else 0.0

    # Compute historical spread percentile
    if len(rv_arr) > window:
        rolling_mean = pd.Series(rv_arr).rolling(window).mean().dropna().values
        if len(rolling_mean) > 0:
            # Align the arrays properly
            n_points = min(len(rv_arr) - window, len(rolling_mean))
            if n_points > 0:
                historical_spreads = rv_arr[window:window + n_points] - rolling_mean[:n_points]
                percentile = float((historical_spreads < spread).mean() * 100)
            else:
                percentile = 50.0
        else:
            percentile = 50.0
    else:
        percentile = 50.0

    # Classify regime
    regime = _classify_iv_rv_regime(spread_pct)

    return {
        "implied_vol": round(implied_vol, 4),
        "realized_vol": round(current_rv, 4),
        "spread": round(spread, 4),
        "spread_pct": round(spread_pct, 1),
        "percentile": round(percentile, 1),
        "regime": regime,
    }


def _classify_iv_rv_regime(spread_pct: float) -> str:
    """Classify IV/RV spread regime.

    Args:
        spread_pct: (IV - RV) / RV * 100

    Returns:
        Regime string: "fear_premium", "complacent", or "normal"
    """
    if spread_pct > 20:
        return "fear_premium"
    elif spread_pct < -20:
        return "complacent"
    else:
        return "normal"


def interpret_iv_rv_spread(spread_result: dict) -> str:
    """Interpret IV/RV spread results.

    Args:
        spread_result: Result from compute_iv_rv_spread.

    Returns:
        Interpretation string with trading implications.
    """
    regime = spread_result["regime"]
    spread_pct = spread_result["spread_pct"]
    iv = spread_result["implied_vol"]
    rv = spread_result["realized_vol"]

    if regime == "fear_premium":
        return (
            f"FEAR PREMIUM: IV ({iv:.1%}) is {spread_pct:.0f}% above RV ({rv:.1%}). "
            f"Options are expensive. Contrarian buy signal - consider selling premium."
        )
    elif regime == "complacent":
        return (
            f"COMPLACENCY: IV ({iv:.1%}) is {abs(spread_pct):.0f}% below RV ({rv:.1%}). "
            f"Options are cheap. Risk of volatility spike - consider buying protection."
        )
    else:
        return (
            f"NORMAL: IV ({iv:.1%}) is within 20% of RV ({rv:.1%}). "
            f"Volatility markets are fairly priced."
        )


# =============================================================================
# VOLATILITY TERM STRUCTURE
# =============================================================================


def compute_volatility_term_structure(
    returns: list[float],
    windows: list[int] | None = None,
    annualization: int = 252,
) -> dict:
    """Compute volatility across different time horizons.

    Args:
        returns: Daily return series.
        windows: List of window sizes. Default: [5, 10, 20, 60, 120].
        annualization: Annualization factor.

    Returns:
        Dictionary with {window: volatility}.
    """
    if windows is None:
        windows = [5, 10, 20, 60, 120]

    returns_arr = np.array(returns)
    result = {}

    for window in windows:
        if len(returns_arr) >= window:
            recent = returns_arr[-window:]
            vol = float(np.std(recent, ddof=1) * np.sqrt(annualization))
            result[window] = round(vol, 4)

    return result


def classify_term_structure(term_structure: dict) -> str:
    """Classify volatility term structure shape.

    Args:
        term_structure: Result from compute_volatility_term_structure.

    Returns:
        "contango" (normal), "backwardation" (inverted), or "flat".
    """
    if len(term_structure) < 2:
        return "insufficient_data"

    windows = sorted(term_structure.keys())
    short_term_vol = term_structure[windows[0]]
    long_term_vol = term_structure[windows[-1]]

    diff_pct = (long_term_vol - short_term_vol) / short_term_vol * 100 if short_term_vol > 0 else 0

    if diff_pct > 10:
        return "contango"  # Normal: long-term vol > short-term
    elif diff_pct < -10:
        return "backwardation"  # Inverted: short-term vol > long-term (stress)
    else:
        return "flat"
