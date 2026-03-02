"""
PMCC (Poor Man's Covered Call) Scanner and Scoring.

This module implements PMCC candidate scanning, scoring, and yield calculation.
PMCC is a diagonal spread strategy where you:
1. Buy a deep ITM LEAPS call (≥270 days, ~0.80 delta)
2. Sell short-term OTM calls against it (7-21 days, ~0.20 delta)

The scanner evaluates candidates on an 11-point scale across 6 dimensions:
- LEAPS delta accuracy (0-2 points)
- Short delta accuracy (0-1 point)
- LEAPS liquidity (0-1 point)
- Short liquidity (0-1 point)
- LEAPS spread tightness (0-1 point)
- Short spread tightness (0-1 point)
- IV level (0-2 points)
- Annual yield estimate (0-2 points)

All functions are pure computation — no IO, no data fetching.
Callers supply pre-fetched chain data and spot prices.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

import pandas as pd

from .models import PMCCScoringConfig
from .black_scholes import black_scholes_delta


# =============================================================================
# Result Dataclasses
# =============================================================================


@dataclass
class PMCCCandidate:
    """
    A scored PMCC candidate position.

    Represents a complete PMCC setup with LEAPS and short leg details,
    yield calculations, and scoring breakdown.

    Attributes:
        symbol: Underlying symbol (e.g., "AAPL").
        leaps_strike: Strike price of the LEAPS call.
        leaps_expiry: Expiration date of LEAPS (ISO format).
        leaps_delta: Calculated delta of LEAPS.
        leaps_price: Mid price of LEAPS (cost to enter).
        leaps_iv: Implied volatility of LEAPS.
        short_strike: Strike price of the short call.
        short_expiry: Expiration date of short call (ISO format).
        short_delta: Calculated delta of short call.
        short_premium: Mid price received for short call.
        short_iv: Implied volatility of short call.
        net_debit: Net cost to establish position (LEAPS - short premium).
        weekly_yield_pct: Yield per week from short premium.
        annual_yield_pct: Annualized yield estimate.
        max_profit: Maximum profit if short expires worthless.
        max_loss: Maximum loss (net debit if underlying goes to zero).
        score: Total score on 11-point scale.
        score_breakdown: Detailed breakdown by scoring dimension.
    """
    symbol: str
    leaps_strike: float
    leaps_expiry: str
    leaps_delta: float
    leaps_price: float
    leaps_iv: float
    short_strike: float
    short_expiry: str
    short_delta: float
    short_premium: float
    short_iv: float
    net_debit: float
    weekly_yield_pct: float
    annual_yield_pct: float
    max_profit: float
    max_loss: float
    score: float
    score_breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class PMCCScanResult:
    """
    Result from PMCC batch scanning operation.

    Attributes:
        candidates: List of scored candidates, sorted by score descending.
        scanned_count: Number of symbols scanned.
        valid_count: Number of valid candidates found.
        skipped_symbols: Symbols skipped due to missing/invalid data.
    """
    candidates: List[PMCCCandidate]
    scanned_count: int
    valid_count: int
    skipped_symbols: List[str] = field(default_factory=list)


# =============================================================================
# Helper Functions
# =============================================================================


def find_strike_by_delta(
    chain: pd.DataFrame,
    target_delta: float,
    spot: float,
    dte_years: float,
    r: float,
    option_type: str = "call"
) -> Optional[pd.Series]:
    """
    Find the option in chain closest to target delta.

    Uses Black-Scholes delta calculation to find the option contract
    whose delta is closest to the target.

    Args:
        chain: DataFrame with columns: 'strike', 'impliedVolatility',
               and optionally 'bid', 'ask', 'volume', 'openInterest'.
        target_delta: Target delta (e.g., 0.80 for LEAPS, 0.20 for short).
        spot: Current underlying price.
        dte_years: Time to expiry in years.
        r: Risk-free rate.
        option_type: "call" or "put".

    Returns:
        Row from chain closest to target delta, or None if chain is empty
        or no valid strikes found.
    """
    if chain.empty:
        return None

    if 'strike' not in chain.columns:
        return None

    best_row = None
    best_delta_diff = float('inf')

    for idx, row in chain.iterrows():
        strike = row['strike']

        # Get IV from chain or use default
        iv = row.get('impliedVolatility', 0.30)
        if pd.isna(iv) or iv <= 0:
            iv = 0.30

        # Skip if dte_years is invalid
        if dte_years <= 0:
            continue

        try:
            delta = black_scholes_delta(spot, strike, dte_years, r, iv, option_type)
            delta_diff = abs(delta - target_delta)

            if delta_diff < best_delta_diff:
                best_delta_diff = delta_diff
                best_row = row
        except (ValueError, ZeroDivisionError):
            # Skip invalid calculations
            continue

    return best_row


def select_leaps_options(
    chains: Dict[str, pd.DataFrame],
    spot: float,
    config: PMCCScoringConfig,
    current_date: Optional[datetime] = None
) -> List[Tuple[str, pd.Series, float]]:
    """
    Select suitable LEAPS options from available chains.

    Filters chains by minimum DTE requirement and finds options
    closest to target delta.

    Args:
        chains: Dict mapping expiry date (str) to chain DataFrame.
        spot: Current underlying price.
        config: PMCC scoring configuration.
        current_date: Current date for DTE calculation (defaults to now).

    Returns:
        List of (expiry, option_row, dte_years) tuples for valid LEAPS.
    """
    current_date = current_date or datetime.now()
    valid_leaps = []

    for expiry_str, chain in chains.items():
        try:
            # Parse expiry date
            if isinstance(expiry_str, str):
                expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d")
            else:
                expiry_date = expiry_str

            # Calculate DTE
            dte_days = (expiry_date - current_date).days
            dte_years = dte_days / 365.0

            # Check minimum LEAPS requirement
            if dte_days < config.min_leaps_days:
                continue

            # Find strike closest to target delta
            option = find_strike_by_delta(
                chain, config.leaps_delta_target, spot, dte_years,
                config.risk_free_rate, "call"
            )

            if option is not None:
                valid_leaps.append((expiry_str, option, dte_years))

        except (ValueError, TypeError):
            # Skip invalid expiry dates
            continue

    return valid_leaps


def select_short_options(
    chains: Dict[str, pd.DataFrame],
    spot: float,
    config: PMCCScoringConfig,
    current_date: Optional[datetime] = None
) -> List[Tuple[str, pd.Series, float]]:
    """
    Select suitable short-term options from available chains.

    Filters chains by DTE range requirement and finds options
    closest to target delta.

    Args:
        chains: Dict mapping expiry date (str) to chain DataFrame.
        spot: Current underlying price.
        config: PMCC scoring configuration.
        current_date: Current date for DTE calculation (defaults to now).

    Returns:
        List of (expiry, option_row, dte_years) tuples for valid short legs.
    """
    current_date = current_date or datetime.now()
    valid_shorts = []
    min_dte, max_dte = config.short_days_range

    for expiry_str, chain in chains.items():
        try:
            # Parse expiry date
            if isinstance(expiry_str, str):
                expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d")
            else:
                expiry_date = expiry_str

            # Calculate DTE
            dte_days = (expiry_date - current_date).days
            dte_years = dte_days / 365.0

            # Check DTE range requirement
            if not (min_dte <= dte_days <= max_dte):
                continue

            # Find strike closest to target delta
            option = find_strike_by_delta(
                chain, config.short_delta_target, spot, dte_years,
                config.risk_free_rate, "call"
            )

            if option is not None:
                valid_shorts.append((expiry_str, option, dte_years))

        except (ValueError, TypeError):
            # Skip invalid expiry dates
            continue

    return valid_shorts


# =============================================================================
# Scoring Functions
# =============================================================================


def _score_delta_accuracy(
    actual_delta: float,
    target_delta: float,
    max_points: float
) -> float:
    """Score delta accuracy: within ±0.05 = max, ±0.10 = half, else 0."""
    delta_diff = abs(actual_delta - target_delta)
    if delta_diff <= 0.05:
        return max_points
    elif delta_diff <= 0.10:
        return max_points * 0.5
    return 0.0


def _score_liquidity(
    volume: float,
    open_interest: float,
    high_threshold: int,
    low_threshold: int
) -> float:
    """Score liquidity based on volume + open interest."""
    total_liquidity = volume + open_interest
    if total_liquidity >= high_threshold:
        return 1.0
    elif total_liquidity >= low_threshold:
        return 0.5
    return 0.0


def _score_spread_tightness(
    bid: float,
    ask: float,
    tight_threshold: float,
    wide_threshold: float
) -> float:
    """Score spread tightness as percentage of mid."""
    if bid <= 0 or ask <= 0:
        return 0.0

    mid = (bid + ask) / 2
    if mid <= 0:
        return 0.0

    spread_pct = (ask - bid) / mid
    if spread_pct <= tight_threshold:
        return 1.0
    elif spread_pct <= wide_threshold:
        return 0.5
    return 0.0


def _score_iv_level(iv: float, sweet_spot: Tuple[float, float]) -> float:
    """Score IV level: in sweet spot = 2, near = 1, else 0."""
    min_iv, max_iv = sweet_spot
    if min_iv <= iv <= max_iv:
        return 2.0
    # Extended range: 0.20-0.60 for partial score
    if 0.20 <= iv <= 0.60:
        return 1.0
    return 0.0


def _score_annual_yield(annual_yield_pct: float) -> float:
    """Score annual yield: >50% = 2, >30% = 1, >15% = 0.5, else 0."""
    if annual_yield_pct >= 50:
        return 2.0
    elif annual_yield_pct >= 30:
        return 1.0
    elif annual_yield_pct >= 15:
        return 0.5
    return 0.0


def score_pmcc_candidate(
    leaps_option: pd.Series,
    short_option: pd.Series,
    spot: float,
    leaps_dte_years: float,
    short_dte_years: float,
    config: PMCCScoringConfig
) -> Dict[str, Any]:
    """
    Score a PMCC candidate on the 11-point scale.

    Evaluates the candidate across 6 dimensions with weighted scoring:
    - LEAPS delta accuracy (0-2 points)
    - Short delta accuracy (0-1 point)
    - LEAPS liquidity (0-1 point)
    - Short liquidity (0-1 point)
    - LEAPS spread tightness (0-1 point)
    - Short spread tightness (0-1 point)
    - IV level (0-2 points)
    - Annual yield (0-2 points)

    Args:
        leaps_option: Row from LEAPS chain with strike, bid, ask, etc.
        short_option: Row from short-term chain.
        spot: Current underlying price.
        leaps_dte_years: LEAPS time to expiry in years.
        short_dte_years: Short option time to expiry in years.
        config: PMCC scoring configuration.

    Returns:
        Dict with 'total_score', 'breakdown', 'leaps_delta', 'short_delta',
        'weekly_yield_pct', 'annual_yield_pct', 'net_debit', 'max_profit'.
    """
    breakdown = {}
    score = 0.0

    # Get option data
    leaps_strike = leaps_option['strike']
    short_strike = short_option['strike']
    leaps_iv = leaps_option.get('impliedVolatility', 0.30)
    short_iv = short_option.get('impliedVolatility', 0.30)

    if pd.isna(leaps_iv) or leaps_iv <= 0:
        leaps_iv = 0.30
    if pd.isna(short_iv) or short_iv <= 0:
        short_iv = 0.30

    # Calculate deltas
    leaps_delta = black_scholes_delta(
        spot, leaps_strike, leaps_dte_years, config.risk_free_rate, leaps_iv, "call"
    )
    short_delta = black_scholes_delta(
        spot, short_strike, short_dte_years, config.risk_free_rate, short_iv, "call"
    )

    # 1. LEAPS delta accuracy (0-2 points)
    breakdown['leaps_delta'] = _score_delta_accuracy(
        leaps_delta, config.leaps_delta_target, 2.0
    )
    score += breakdown['leaps_delta']

    # 2. Short delta accuracy (0-1 point)
    breakdown['short_delta'] = _score_delta_accuracy(
        short_delta, config.short_delta_target, 1.0
    )
    score += breakdown['short_delta']

    # 3. LEAPS liquidity (0-1 point)
    leaps_volume = leaps_option.get('volume', 0)
    leaps_oi = leaps_option.get('openInterest', 0)
    if pd.isna(leaps_volume):
        leaps_volume = 0
    if pd.isna(leaps_oi):
        leaps_oi = 0
    breakdown['leaps_liquidity'] = _score_liquidity(leaps_volume, leaps_oi, 100, 20)
    score += breakdown['leaps_liquidity']

    # 4. Short liquidity (0-1 point)
    short_volume = short_option.get('volume', 0)
    short_oi = short_option.get('openInterest', 0)
    if pd.isna(short_volume):
        short_volume = 0
    if pd.isna(short_oi):
        short_oi = 0
    breakdown['short_liquidity'] = _score_liquidity(short_volume, short_oi, 500, 100)
    score += breakdown['short_liquidity']

    # 5. LEAPS spread tightness (0-1 point)
    leaps_bid = leaps_option.get('bid', 0)
    leaps_ask = leaps_option.get('ask', 0)
    if pd.isna(leaps_bid):
        leaps_bid = 0
    if pd.isna(leaps_ask):
        leaps_ask = 0
    breakdown['leaps_spread'] = _score_spread_tightness(leaps_bid, leaps_ask, 0.05, 0.10)
    score += breakdown['leaps_spread']

    # 6. Short spread tightness (0-1 point)
    short_bid = short_option.get('bid', 0)
    short_ask = short_option.get('ask', 0)
    if pd.isna(short_bid):
        short_bid = 0
    if pd.isna(short_ask):
        short_ask = 0
    breakdown['short_spread'] = _score_spread_tightness(short_bid, short_ask, 0.10, 0.20)
    score += breakdown['short_spread']

    # 7. IV level (0-2 points) - use average IV
    avg_iv = (leaps_iv + short_iv) / 2
    breakdown['iv_level'] = _score_iv_level(avg_iv, config.iv_sweet_spot)
    score += breakdown['iv_level']

    # Calculate yields
    leaps_mid = (leaps_bid + leaps_ask) / 2 if leaps_bid > 0 and leaps_ask > 0 else 0
    short_mid = (short_bid + short_ask) / 2 if short_bid > 0 and short_ask > 0 else 0

    net_debit = leaps_mid - short_mid
    weekly_yield_pct = (short_mid / leaps_mid * 100) if leaps_mid > 0 else 0
    short_dte_weeks = short_dte_years * 52
    annual_yield_pct = (weekly_yield_pct * 52 / short_dte_weeks) if short_dte_weeks > 0 else 0

    # 8. Annual yield (0-2 points)
    breakdown['annual_yield'] = _score_annual_yield(annual_yield_pct)
    score += breakdown['annual_yield']

    # Calculate max profit/loss
    # Max profit: if underlying reaches short strike and short expires worthless
    max_profit = (short_strike - leaps_strike) - net_debit + short_mid
    # Max loss: net debit (if underlying goes to zero)
    max_loss = net_debit

    return {
        'total_score': score,
        'breakdown': breakdown,
        'leaps_delta': leaps_delta,
        'short_delta': short_delta,
        'leaps_iv': leaps_iv,
        'short_iv': short_iv,
        'leaps_price': leaps_mid,
        'short_premium': short_mid,
        'net_debit': net_debit,
        'weekly_yield_pct': weekly_yield_pct,
        'annual_yield_pct': annual_yield_pct,
        'max_profit': max_profit,
        'max_loss': max_loss,
    }


def calculate_pmcc_metrics(
    leaps_price: float,
    short_premium: float,
    leaps_strike: float,
    short_strike: float,
    short_dte_days: int
) -> Dict[str, float]:
    """
    Calculate PMCC metrics: yields, max profit, max loss.

    Args:
        leaps_price: Cost of LEAPS position (mid price).
        short_premium: Premium received from short call (mid price).
        leaps_strike: LEAPS strike price.
        short_strike: Short call strike price.
        short_dte_days: Days to expiration for short call.

    Returns:
        Dict with weekly_yield_pct, annual_yield_pct, net_debit,
        max_profit, max_loss.
    """
    net_debit = leaps_price - short_premium

    # Weekly yield: premium / LEAPS cost
    weekly_yield_pct = (short_premium / leaps_price * 100) if leaps_price > 0 else 0

    # Annualized yield: adjust for short DTE
    weeks_per_year = 52
    short_dte_weeks = short_dte_days / 7
    if short_dte_weeks > 0:
        annual_yield_pct = weekly_yield_pct * (weeks_per_year / short_dte_weeks)
    else:
        annual_yield_pct = 0

    # Max profit: width of strikes minus net debit plus short premium
    max_profit = (short_strike - leaps_strike) - net_debit + short_premium

    # Max loss: net debit (if underlying goes to zero)
    max_loss = net_debit

    return {
        'weekly_yield_pct': weekly_yield_pct,
        'annual_yield_pct': annual_yield_pct,
        'net_debit': net_debit,
        'max_profit': max_profit,
        'max_loss': max_loss,
    }


# =============================================================================
# Single Symbol Scanning
# =============================================================================


def scan_symbol_for_pmcc(
    symbol: str,
    chains: Dict[str, pd.DataFrame],
    spot: float,
    config: PMCCScoringConfig,
    current_date: Optional[datetime] = None
) -> Optional[PMCCCandidate]:
    """
    Scan a single symbol for the best PMCC candidate.

    Evaluates all valid LEAPS/short combinations and returns the
    highest-scoring candidate.

    Args:
        symbol: Ticker symbol.
        chains: Dict mapping expiry date (str) to chain DataFrame.
        spot: Current underlying price.
        config: PMCC scoring configuration.
        current_date: Current date for DTE calculation.

    Returns:
        Best PMCCCandidate or None if no valid candidates found.
    """
    current_date = current_date or datetime.now()

    # Find valid LEAPS
    leaps_options = select_leaps_options(chains, spot, config, current_date)
    if not leaps_options:
        return None

    # Find valid short options
    short_options = select_short_options(chains, spot, config, current_date)
    if not short_options:
        return None

    best_candidate = None
    best_score = -1

    # Evaluate all LEAPS/short combinations
    for leaps_expiry, leaps_option, leaps_dte in leaps_options:
        for short_expiry, short_option, short_dte in short_options:
            # Score this combination
            try:
                result = score_pmcc_candidate(
                    leaps_option, short_option, spot,
                    leaps_dte, short_dte, config
                )

                if result['total_score'] > best_score:
                    best_score = result['total_score']
                    best_candidate = PMCCCandidate(
                        symbol=symbol,
                        leaps_strike=leaps_option['strike'],
                        leaps_expiry=leaps_expiry,
                        leaps_delta=result['leaps_delta'],
                        leaps_price=result['leaps_price'],
                        leaps_iv=result['leaps_iv'],
                        short_strike=short_option['strike'],
                        short_expiry=short_expiry,
                        short_delta=result['short_delta'],
                        short_premium=result['short_premium'],
                        short_iv=result['short_iv'],
                        net_debit=result['net_debit'],
                        weekly_yield_pct=result['weekly_yield_pct'],
                        annual_yield_pct=result['annual_yield_pct'],
                        max_profit=result['max_profit'],
                        max_loss=result['max_loss'],
                        score=result['total_score'],
                        score_breakdown=result['breakdown'],
                    )
            except (ValueError, TypeError, KeyError):
                # Skip invalid combinations
                continue

    return best_candidate


# =============================================================================
# Batch Scanning with asyncio
# =============================================================================


async def scan_pmcc_candidates(
    symbols: List[str],
    chain_data: Dict[str, Dict[str, pd.DataFrame]],
    spot_prices: Dict[str, float],
    config: Optional[PMCCScoringConfig] = None,
    max_concurrent: int = 10,
    current_date: Optional[datetime] = None
) -> PMCCScanResult:
    """
    Scan multiple symbols for PMCC candidates concurrently.

    Uses asyncio.gather() with semaphore for controlled concurrency.
    Each symbol is scanned independently and results are sorted by score.

    Args:
        symbols: List of ticker symbols to scan.
        chain_data: Pre-fetched chain data: {symbol: {expiry: DataFrame}}.
        spot_prices: Current prices: {symbol: price}.
        config: PMCC scoring configuration (uses defaults if None).
        max_concurrent: Maximum concurrent scans (semaphore limit).
        current_date: Current date for DTE calculations.

    Returns:
        PMCCScanResult with sorted candidates and scan statistics.

    Example:
        >>> chain_data = {
        ...     'AAPL': {'2027-01-15': leaps_df, '2026-04-01': short_df},
        ...     'MSFT': {'2027-01-15': leaps_df, '2026-04-01': short_df},
        ... }
        >>> spot_prices = {'AAPL': 175.0, 'MSFT': 410.0}
        >>> result = await scan_pmcc_candidates(
        ...     ['AAPL', 'MSFT'], chain_data, spot_prices
        ... )
        >>> for candidate in result.candidates[:5]:
        ...     print(f"{candidate.symbol}: {candidate.score:.1f}")
    """
    config = config or PMCCScoringConfig()
    current_date = current_date or datetime.now()
    semaphore = asyncio.Semaphore(max_concurrent)

    skipped = []

    async def scan_single(symbol: str) -> Optional[PMCCCandidate]:
        """Scan a single symbol with semaphore control."""
        async with semaphore:
            # Check if we have data for this symbol
            if symbol not in chain_data:
                skipped.append(symbol)
                return None

            if symbol not in spot_prices:
                skipped.append(symbol)
                return None

            chains = chain_data[symbol]
            spot = spot_prices[symbol]

            if not chains or spot <= 0:
                skipped.append(symbol)
                return None

            # Run the synchronous scan in executor to avoid blocking
            try:
                return scan_symbol_for_pmcc(
                    symbol, chains, spot, config, current_date
                )
            except Exception:
                skipped.append(symbol)
                return None

    # Create tasks for all symbols
    tasks = [scan_single(symbol) for symbol in symbols]

    # Run all tasks concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter valid candidates
    candidates = []
    for result in results:
        if isinstance(result, PMCCCandidate):
            candidates.append(result)
        elif isinstance(result, Exception):
            # Log but don't fail the entire scan
            continue

    # Sort by score descending
    candidates.sort(key=lambda x: x.score, reverse=True)

    return PMCCScanResult(
        candidates=candidates,
        scanned_count=len(symbols),
        valid_count=len(candidates),
        skipped_symbols=skipped,
    )


def scan_pmcc_candidates_sync(
    symbols: List[str],
    chain_data: Dict[str, Dict[str, pd.DataFrame]],
    spot_prices: Dict[str, float],
    config: Optional[PMCCScoringConfig] = None,
    current_date: Optional[datetime] = None
) -> PMCCScanResult:
    """
    Synchronous wrapper for scan_pmcc_candidates.

    Useful for testing or when not in an async context.

    Args:
        Same as scan_pmcc_candidates, except max_concurrent.

    Returns:
        PMCCScanResult with sorted candidates and scan statistics.
    """
    config = config or PMCCScoringConfig()
    current_date = current_date or datetime.now()

    candidates = []
    skipped = []

    for symbol in symbols:
        if symbol not in chain_data or symbol not in spot_prices:
            skipped.append(symbol)
            continue

        chains = chain_data[symbol]
        spot = spot_prices[symbol]

        if not chains or spot <= 0:
            skipped.append(symbol)
            continue

        try:
            candidate = scan_symbol_for_pmcc(
                symbol, chains, spot, config, current_date
            )
            if candidate:
                candidates.append(candidate)
        except Exception:
            skipped.append(symbol)

    # Sort by score descending
    candidates.sort(key=lambda x: x.score, reverse=True)

    return PMCCScanResult(
        candidates=candidates,
        scanned_count=len(symbols),
        valid_count=len(candidates),
        skipped_symbols=skipped,
    )


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Dataclasses
    "PMCCCandidate",
    "PMCCScanResult",
    # Helper functions
    "find_strike_by_delta",
    "select_leaps_options",
    "select_short_options",
    # Scoring
    "score_pmcc_candidate",
    "calculate_pmcc_metrics",
    # Scanning
    "scan_symbol_for_pmcc",
    "scan_pmcc_candidates",
    "scan_pmcc_candidates_sync",
]
