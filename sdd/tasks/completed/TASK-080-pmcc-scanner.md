# TASK-080: PMCC Scanner

**Feature**: Options Analytics Toolkit
**Spec**: `sdd/specs/options-analytics.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-077, TASK-078
**Assigned-to**: claude-opus-session

---

## Context

This module implements the Poor Man's Covered Call (PMCC) scanner and scoring system. PMCC is a diagonal spread strategy where you buy a deep ITM LEAPS call and sell short-term OTM calls against it.

The scanner evaluates candidates on an 11-point scale across 6 dimensions: delta accuracy, liquidity, spread tightness, IV level, and annual yield estimate.

Reference: Spec Section 3 "Module 4: PMCC Scanner" and `trading_skills/src/trading_skills/scanner_pmcc.py`

---

## Scope

- Implement PMCC scoring algorithm (11-point scale, 6 dimensions)
- Implement LEAPS selection logic (≥270 days, target delta 0.80)
- Implement short leg selection (7-21 day range, target delta 0.20)
- Implement yield calculation (weekly yield, annualized estimate)
- Implement `find_strike_by_delta()` helper using Black-Scholes
- Implement batch scanning with `asyncio.gather()` + semaphore
- Make scoring weights configurable via `PMCCScoringConfig`
- Add risk-adjusted scoring (optional beta/correlation factor)

**NOT in scope**:
- Data fetching (callers supply chain data)
- Earnings calendar integration (Open Question in spec)
- Toolkit wrapper class (TASK-081)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/options/pmcc.py` | CREATE | PMCC scoring and scanning logic |
| `tests/test_pmcc_scanner.py` | CREATE | Unit tests for PMCC scanner |
| `parrot/tools/options/__init__.py` | MODIFY | Add pmcc exports |

---

## Implementation Notes

### Scoring Algorithm (11-point scale)

| Criterion | Points | Condition |
|-----------|--------|-----------|
| LEAPS delta accuracy | 0-2 | Within ±0.05 of target → 2, ±0.10 → 1 |
| Short delta accuracy | 0-1 | Within ±0.05 → 1, ±0.10 → 0.5 |
| LEAPS liquidity | 0-1 | volume+OI > 100 → 1, > 20 → 0.5 |
| Short liquidity | 0-1 | volume+OI > 500 → 1, > 100 → 0.5 |
| LEAPS spread tightness | 0-1 | spread% < 5% → 1, < 10% → 0.5 |
| Short spread tightness | 0-1 | spread% < 10% → 1, < 20% → 0.5 |
| IV level (sweet spot) | 0-2 | 25-50% → 2, 20-60% → 1 |
| Annual yield estimate | 0-2 | > 50% → 2, > 30% → 1, > 15% → 0.5 |

### Pattern to Follow

```python
# parrot/tools/options/pmcc.py
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import asyncio
import pandas as pd
from .models import PMCCScoringConfig, OptionLeg
from .black_scholes import black_scholes_delta, black_scholes_price

@dataclass
class PMCCCandidate:
    """A scored PMCC candidate."""
    symbol: str
    leaps_strike: float
    leaps_expiry: str
    leaps_delta: float
    leaps_price: float
    short_strike: float
    short_expiry: str
    short_delta: float
    short_premium: float
    net_debit: float
    weekly_yield_pct: float
    annual_yield_pct: float
    max_profit: float
    score: float
    score_breakdown: Dict[str, float]


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

    Args:
        chain: DataFrame with 'strike', 'impliedVolatility' columns
        target_delta: Target delta (e.g., 0.80 for LEAPS, 0.20 for short)
        spot: Current underlying price
        dte_years: Time to expiry in years
        r: Risk-free rate
        option_type: "call" or "put"

    Returns:
        Row from chain closest to target delta, or None if not found
    """
    best_row = None
    best_delta_diff = float('inf')

    for _, row in chain.iterrows():
        iv = row.get('impliedVolatility', 0.30)
        delta = black_scholes_delta(spot, row['strike'], dte_years, r, iv, option_type)
        delta_diff = abs(delta - target_delta)

        if delta_diff < best_delta_diff:
            best_delta_diff = delta_diff
            best_row = row

    return best_row


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

    Returns dict with total_score and breakdown.
    """
    score = 0.0
    breakdown = {}

    # 1. LEAPS delta accuracy (0-2 points)
    leaps_delta = black_scholes_delta(
        spot, leaps_option['strike'], leaps_dte_years,
        config.risk_free_rate, leaps_option.get('impliedVolatility', 0.30), "call"
    )
    delta_diff = abs(leaps_delta - config.leaps_delta_target)
    if delta_diff <= 0.05:
        breakdown['leaps_delta'] = 2.0
    elif delta_diff <= 0.10:
        breakdown['leaps_delta'] = 1.0
    else:
        breakdown['leaps_delta'] = 0.0
    score += breakdown['leaps_delta']

    # 2. Short delta accuracy (0-1 point)
    short_delta = black_scholes_delta(
        spot, short_option['strike'], short_dte_years,
        config.risk_free_rate, short_option.get('impliedVolatility', 0.30), "call"
    )
    delta_diff = abs(short_delta - config.short_delta_target)
    if delta_diff <= 0.05:
        breakdown['short_delta'] = 1.0
    elif delta_diff <= 0.10:
        breakdown['short_delta'] = 0.5
    else:
        breakdown['short_delta'] = 0.0
    score += breakdown['short_delta']

    # ... continue for all 6 dimensions

    return {
        'total_score': score,
        'breakdown': breakdown,
        'leaps_delta': leaps_delta,
        'short_delta': short_delta,
    }


async def scan_pmcc_candidates(
    symbols: List[str],
    chain_data: Dict[str, Dict],  # {symbol: {expiry: DataFrame}}
    spot_prices: Dict[str, float],
    config: Optional[PMCCScoringConfig] = None,
    max_concurrent: int = 10
) -> List[PMCCCandidate]:
    """
    Scan multiple symbols for PMCC candidates.

    Args:
        symbols: List of symbols to scan
        chain_data: Pre-fetched chain data {symbol: {expiry: DataFrame}}
        spot_prices: {symbol: current_price}
        config: Scoring configuration (uses defaults if None)
        max_concurrent: Max concurrent scans (semaphore limit)

    Returns:
        List of PMCCCandidate sorted by score descending
    """
    config = config or PMCCScoringConfig()
    semaphore = asyncio.Semaphore(max_concurrent)

    async def scan_single(symbol: str) -> Optional[PMCCCandidate]:
        async with semaphore:
            # Implementation here
            ...

    tasks = [scan_single(symbol) for symbol in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    candidates = [r for r in results if isinstance(r, PMCCCandidate)]
    return sorted(candidates, key=lambda x: x.score, reverse=True)
```

### Key Constraints

- Accept pre-fetched chain DataFrames (no yfinance calls)
- Scoring weights must be configurable via PMCCScoringConfig
- Use asyncio.gather() with semaphore for batch scanning
- Return sorted list of PMCCCandidate dataclasses
- Handle missing data gracefully (skip symbols with incomplete chains)

### References in Codebase

- `trading_skills/src/trading_skills/scanner_pmcc.py` — reference implementation (302 lines)
- `parrot/tools/options/black_scholes.py` — black_scholes_delta()
- `parrot/tools/options/models.py` — PMCCScoringConfig

---

## Acceptance Criteria

- [ ] Scoring algorithm matches trading_skills reference
- [ ] LEAPS selection finds options ≥270 days with target delta
- [ ] Short leg selection finds options in 7-21 day range
- [ ] Yield calculations are accurate (weekly and annualized)
- [ ] Batch scanning uses asyncio.gather() with semaphore
- [ ] Tests pass: `pytest tests/test_pmcc_scanner.py -v`
- [ ] No linting errors: `ruff check parrot/tools/options/pmcc.py`

---

## Test Specification

```python
# tests/test_pmcc_scanner.py
import pytest
import pandas as pd
from parrot.tools.options.pmcc import (
    find_strike_by_delta, score_pmcc_candidate, scan_pmcc_candidates,
    PMCCCandidate
)
from parrot.tools.options.models import PMCCScoringConfig


@pytest.fixture
def sample_leaps_chain():
    """Sample LEAPS chain DataFrame."""
    return pd.DataFrame({
        'strike': [80.0, 85.0, 90.0, 95.0, 100.0],
        'bid': [22.0, 17.5, 13.5, 10.0, 7.0],
        'ask': [22.5, 18.0, 14.0, 10.5, 7.5],
        'impliedVolatility': [0.28, 0.27, 0.26, 0.25, 0.24],
        'volume': [50, 120, 200, 150, 80],
        'openInterest': [500, 800, 1200, 900, 400],
    })


@pytest.fixture
def sample_short_chain():
    """Sample short-term chain DataFrame."""
    return pd.DataFrame({
        'strike': [100.0, 105.0, 110.0, 115.0, 120.0],
        'bid': [4.50, 2.20, 0.90, 0.30, 0.10],
        'ask': [4.70, 2.40, 1.10, 0.40, 0.15],
        'impliedVolatility': [0.25, 0.26, 0.27, 0.28, 0.30],
        'volume': [200, 500, 400, 150, 50],
        'openInterest': [1500, 2500, 2000, 800, 300],
    })


class TestFindStrikeByDelta:
    def test_find_leaps_delta(self, sample_leaps_chain):
        """Finds strike closest to 0.80 delta for LEAPS."""
        result = find_strike_by_delta(
            sample_leaps_chain, target_delta=0.80,
            spot=100.0, dte_years=1.0, r=0.05
        )
        assert result is not None
        # Deep ITM strike should be selected
        assert result['strike'] < 100.0

    def test_find_short_delta(self, sample_short_chain):
        """Finds strike closest to 0.20 delta for short leg."""
        result = find_strike_by_delta(
            sample_short_chain, target_delta=0.20,
            spot=100.0, dte_years=21/365, r=0.05
        )
        assert result is not None
        # OTM strike should be selected
        assert result['strike'] > 100.0


class TestScorePMCC:
    def test_perfect_score(self, sample_leaps_chain, sample_short_chain):
        """Perfect candidate gets high score."""
        leaps = sample_leaps_chain.iloc[1]  # 85 strike (deep ITM)
        short = sample_short_chain.iloc[1]  # 105 strike (OTM)

        result = score_pmcc_candidate(
            leaps, short, spot=100.0,
            leaps_dte_years=1.0, short_dte_years=21/365,
            config=PMCCScoringConfig()
        )
        assert 'total_score' in result
        assert 'breakdown' in result
        assert result['total_score'] >= 0

    def test_score_breakdown(self, sample_leaps_chain, sample_short_chain):
        """Score breakdown includes all dimensions."""
        leaps = sample_leaps_chain.iloc[2]
        short = sample_short_chain.iloc[2]

        result = score_pmcc_candidate(
            leaps, short, spot=100.0,
            leaps_dte_years=1.0, short_dte_years=21/365,
            config=PMCCScoringConfig()
        )
        breakdown = result['breakdown']
        assert 'leaps_delta' in breakdown
        assert 'short_delta' in breakdown


class TestYieldCalculation:
    def test_weekly_yield(self, sample_leaps_chain, sample_short_chain):
        """Weekly yield is calculated correctly."""
        leaps_mid = 17.75  # (17.5 + 18.0) / 2
        short_mid = 2.30   # (2.20 + 2.40) / 2
        expected_weekly_yield = (short_mid / leaps_mid) * 100

        # This would be part of the full candidate scoring
        assert expected_weekly_yield > 10  # Reasonable yield


class TestBatchScanning:
    @pytest.mark.asyncio
    async def test_scan_multiple_symbols(self):
        """Batch scan returns sorted candidates."""
        # Mock chain data for 2 symbols
        chain_data = {
            'AAPL': {'2027-01-15': pd.DataFrame({'strike': [150, 160], 'bid': [10, 5], 'ask': [11, 6], 'impliedVolatility': [0.3, 0.3], 'volume': [100, 100], 'openInterest': [500, 500]})},
            'MSFT': {'2027-01-15': pd.DataFrame({'strike': [300, 320], 'bid': [20, 10], 'ask': [22, 12], 'impliedVolatility': [0.25, 0.25], 'volume': [100, 100], 'openInterest': [500, 500]})},
        }
        spot_prices = {'AAPL': 155.0, 'MSFT': 310.0}

        results = await scan_pmcc_candidates(
            ['AAPL', 'MSFT'], chain_data, spot_prices
        )
        # Results should be sorted by score
        if len(results) >= 2:
            assert results[0].score >= results[1].score
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/options-analytics.spec.md` for full context
2. **Check dependencies** — verify TASK-077, TASK-078 are in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Reference** `trading_skills/src/trading_skills/scanner_pmcc.py` for implementation
5. **Implement** all functions per scope
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-080-pmcc-scanner.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:
- Implemented PMCC scanner in `parrot/tools/options/pmcc.py` (~590 lines)
- `PMCCCandidate` dataclass with all fields: symbol, LEAPS/short details, yields, score breakdown
- `PMCCScanResult` dataclass for batch scan results
- `find_strike_by_delta()` - finds option closest to target delta using Black-Scholes
- `select_leaps_options()` - filters chains by min DTE (270 days)
- `select_short_options()` - filters chains by DTE range (7-21 days)
- `score_pmcc_candidate()` - 11-point scoring across 8 dimensions
- `calculate_pmcc_metrics()` - yield and P/L calculations
- `scan_symbol_for_pmcc()` - single symbol scanning
- `scan_pmcc_candidates()` - async batch scanning with semaphore
- `scan_pmcc_candidates_sync()` - synchronous wrapper for testing
- Created 31 unit tests in `tests/test_pmcc_scanner.py` — all passing
- Updated `parrot/tools/options/__init__.py` with PMCC exports
- Linting clean: `ruff check` passes

**Deviations from spec**: none
