"""
Correlation Engine for QuantToolkit.

Provides correlation analysis for portfolio risk monitoring:
- Correlation matrix computation (Pearson, Spearman, Kendall)
- Correlation regime detection (short vs long-term shifts)
- Cross-asset correlation with calendar alignment

CRITICAL: Always correlate on returns, NOT prices.
Correlating prices gives spurious correlations due to random walk behavior.
"""

from typing import Literal

import numpy as np
import pandas as pd

from .models import CorrelationInput


# =============================================================================
# PRICE TO RETURNS CONVERSION
# =============================================================================


def prices_to_returns(prices: np.ndarray) -> np.ndarray:
    """Convert price series to returns.

    Args:
        prices: Array of closing prices.

    Returns:
        Array of daily returns (pct_change).
    """
    if len(prices) < 2:
        return np.array([])
    return np.diff(prices) / prices[:-1]


# =============================================================================
# CORRELATION MATRIX
# =============================================================================


def compute_correlation_matrix(
    price_data: dict[str, list[float]],
    method: Literal["pearson", "spearman", "kendall"] = "pearson",
    returns_based: bool = True,
) -> dict:
    """Compute correlation matrix for multiple assets.

    IMPORTANT: Always correlate returns, not prices.
    Correlating prices gives spurious correlations due to random walk behavior.

    Args:
        price_data: Dictionary of {symbol: [prices]}.
        method: Correlation method ('pearson', 'spearman', 'kendall').
        returns_based: If True, convert prices to returns first (recommended).

    Returns:
        Dictionary with:
        - matrix: Nested dict {symbol: {symbol: correlation}}
        - method: The method used
        - returns_based: Whether returns were used
    """
    if not price_data:
        return {
            "matrix": {},
            "method": method,
            "returns_based": returns_based,
        }

    df = pd.DataFrame(price_data)

    if returns_based:
        df = df.pct_change().dropna()

    if df.empty or len(df) < 2:
        # Not enough data for correlation
        symbols = list(price_data.keys())
        empty_matrix = {s: {s2: np.nan for s2 in symbols} for s in symbols}
        return {
            "matrix": empty_matrix,
            "method": method,
            "returns_based": returns_based,
        }

    corr_matrix = df.corr(method=method)

    return {
        "matrix": corr_matrix.to_dict(),
        "method": method,
        "returns_based": returns_based,
    }


def compute_correlation_from_input(inp: CorrelationInput) -> dict:
    """Compute correlation matrix from CorrelationInput model.

    Args:
        inp: CorrelationInput with price_data, method, and returns_based flag.

    Returns:
        Dictionary with correlation matrix and metadata.
    """
    return compute_correlation_matrix(
        price_data=inp.price_data,
        method=inp.method,
        returns_based=inp.returns_based,
    )


# =============================================================================
# CORRELATION REGIME DETECTION
# =============================================================================


def detect_correlation_regimes(
    price_data: dict[str, list[float]],
    short_window: int = 20,
    long_window: int = 120,
    z_threshold: float = 2.0,
) -> dict:
    """Compare short-term vs long-term correlations to detect regime changes.

    This directly serves the risk crew instruction:
    "Flag when correlations deviate >2 std from historical norm"

    Args:
        price_data: Dictionary of {symbol: [prices]}.
        short_window: Recent window for short-term correlation.
        long_window: Historical window for long-term baseline.
        z_threshold: Standard deviation threshold for alerts.

    Returns:
        Dictionary with:
        - regime_alerts: List of {pair, short_corr, long_corr, z_score, alert}
        - correlation_matrix_short: Short-term correlation matrix
        - correlation_matrix_long: Long-term correlation matrix

    Raises:
        ValueError: If insufficient data points.
    """
    if not price_data:
        return {
            "regime_alerts": [],
            "correlation_matrix_short": {},
            "correlation_matrix_long": {},
        }

    df = pd.DataFrame(price_data).pct_change().dropna()

    if len(df) < long_window:
        raise ValueError(
            f"Need at least {long_window} data points, got {len(df)}"
        )

    # Short-term correlation (recent)
    short_df = df.tail(short_window)
    short_corr = short_df.corr()

    # Long-term correlation (historical)
    long_corr = df.corr()

    # Compute alerts for each pair
    alerts = []
    symbols = list(price_data.keys())

    for i, sym1 in enumerate(symbols):
        for sym2 in symbols[i + 1 :]:
            short_c = short_corr.loc[sym1, sym2]
            long_c = long_corr.loc[sym1, sym2]

            # Compute rolling correlation to get std
            rolling_corr = df[sym1].rolling(short_window).corr(df[sym2])
            corr_std = rolling_corr.std()

            if corr_std > 0 and not np.isnan(corr_std):
                z_score = (short_c - long_c) / corr_std

                if abs(z_score) > z_threshold:
                    alert_type = (
                        "correlation_spike" if z_score > 0 else "correlation_drop"
                    )
                    alerts.append({
                        "pair": f"{sym1}-{sym2}",
                        "short_corr": round(float(short_c), 4),
                        "long_corr": round(float(long_c), 4),
                        "z_score": round(float(z_score), 2),
                        "alert": alert_type,
                    })

    return {
        "regime_alerts": alerts,
        "correlation_matrix_short": short_corr.to_dict(),
        "correlation_matrix_long": long_corr.to_dict(),
    }


# =============================================================================
# CROSS-ASSET CORRELATION
# =============================================================================


def compute_cross_asset_correlation(
    equity_prices: dict[str, list[float]],
    crypto_prices: dict[str, list[float]],
    timestamps_equity: list[str],
    timestamps_crypto: list[str],
    alignment: str = "daily_close",
) -> dict:
    """Compute correlation between equities (252 trading days) and crypto (365 days).

    Aligns on common dates before computing correlation.

    Args:
        equity_prices: Dictionary of {symbol: [prices]} for equities.
        crypto_prices: Dictionary of {symbol: [prices]} for crypto.
        timestamps_equity: List of date strings for equity prices.
        timestamps_crypto: List of date strings for crypto prices.
        alignment: Alignment method (currently only 'daily_close' supported).

    Returns:
        Dictionary with:
        - cross_asset_correlations: {pair: correlation}
        - full_matrix: Complete correlation matrix
        - common_dates_count: Number of overlapping dates
        - alignment: Alignment method used

    Raises:
        ValueError: If insufficient overlapping dates.
    """
    if not equity_prices or not crypto_prices:
        return {
            "cross_asset_correlations": {},
            "full_matrix": {},
            "common_dates_count": 0,
            "alignment": alignment,
        }

    # Create DataFrames with timestamps
    eq_df = pd.DataFrame(
        equity_prices, index=pd.to_datetime(timestamps_equity)
    )
    cr_df = pd.DataFrame(
        crypto_prices, index=pd.to_datetime(timestamps_crypto)
    )

    # Find common dates
    common_dates = eq_df.index.intersection(cr_df.index)

    if len(common_dates) < 20:
        raise ValueError(
            f"Insufficient overlapping dates for correlation: "
            f"got {len(common_dates)}, need at least 20"
        )

    # Align to common dates
    eq_aligned = eq_df.loc[common_dates]
    cr_aligned = cr_df.loc[common_dates]

    # Combine and compute returns
    combined = pd.concat([eq_aligned, cr_aligned], axis=1)
    returns = combined.pct_change().dropna()

    if len(returns) < 2:
        raise ValueError("Insufficient data after computing returns")

    corr_matrix = returns.corr()

    # Extract cross-asset pairs
    eq_symbols = list(equity_prices.keys())
    cr_symbols = list(crypto_prices.keys())

    cross_pairs = {}
    for eq in eq_symbols:
        for cr in cr_symbols:
            corr_value = corr_matrix.loc[eq, cr]
            cross_pairs[f"{eq}-{cr}"] = round(float(corr_value), 4)

    return {
        "cross_asset_correlations": cross_pairs,
        "full_matrix": corr_matrix.to_dict(),
        "common_dates_count": len(common_dates),
        "alignment": alignment,
    }


# =============================================================================
# PAIRWISE CORRELATION
# =============================================================================


def compute_pairwise_correlation(
    returns_a: list[float],
    returns_b: list[float],
    method: Literal["pearson", "spearman", "kendall"] = "pearson",
) -> float:
    """Compute correlation between two return series.

    Args:
        returns_a: First return series.
        returns_b: Second return series.
        method: Correlation method.

    Returns:
        Correlation coefficient.

    Raises:
        ValueError: If series have different lengths.
    """
    if len(returns_a) != len(returns_b):
        raise ValueError("Return series must have same length")

    if len(returns_a) < 2:
        return 0.0

    series_a = pd.Series(returns_a)
    series_b = pd.Series(returns_b)

    return float(series_a.corr(series_b, method=method))


# =============================================================================
# ROLLING CORRELATION
# =============================================================================


def compute_rolling_correlation(
    returns_a: list[float],
    returns_b: list[float],
    window: int = 20,
) -> np.ndarray:
    """Compute rolling correlation between two return series.

    Args:
        returns_a: First return series.
        returns_b: Second return series.
        window: Rolling window size.

    Returns:
        Array of rolling correlations.

    Raises:
        ValueError: If series have different lengths.
    """
    if len(returns_a) != len(returns_b):
        raise ValueError("Return series must have same length")

    if len(returns_a) < window:
        return np.array([])

    series_a = pd.Series(returns_a)
    series_b = pd.Series(returns_b)

    rolling_corr = series_a.rolling(window).corr(series_b)

    return rolling_corr.dropna().values


# =============================================================================
# CORRELATION HEATMAP DATA
# =============================================================================


def get_correlation_heatmap_data(
    price_data: dict[str, list[float]],
    method: Literal["pearson", "spearman", "kendall"] = "pearson",
) -> dict:
    """Get correlation data formatted for heatmap visualization.

    Args:
        price_data: Dictionary of {symbol: [prices]}.
        method: Correlation method.

    Returns:
        Dictionary with:
        - symbols: List of symbols
        - correlations: 2D list for heatmap
        - method: Method used
    """
    result = compute_correlation_matrix(price_data, method=method)
    symbols = list(price_data.keys())

    # Convert to 2D array for heatmap
    correlations = []
    for sym1 in symbols:
        row = []
        for sym2 in symbols:
            val = result["matrix"].get(sym1, {}).get(sym2, np.nan)
            row.append(round(float(val), 4) if not np.isnan(val) else None)
        correlations.append(row)

    return {
        "symbols": symbols,
        "correlations": correlations,
        "method": method,
    }
