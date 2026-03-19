# TASK-079: Spread Strategy Analyzer

**Feature**: Options Analytics Toolkit
**Spec**: `sdd/specs/options-analytics.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-077, TASK-078
**Assigned-to**: claude-opus-session

---

## Context

This module implements analysis functions for 5 multi-leg option strategies: verticals, diagonals (PMCC), straddles, strangles, and iron condors. Each analyzer computes max profit, max loss, breakevens, probability of profit (POP), and expected value.

The implementation should follow the reference from `trading_skills/src/trading_skills/spreads.py` but with key enhancements: POP calculation, expected value, and net Greeks aggregation.

Reference: Spec Section 3 "Module 3: Spread Strategy Analyzer"

---

## Scope

- Implement `analyze_vertical()` — bull/bear call/put spreads
- Implement `analyze_diagonal()` — PMCC and calendar-like strategies
- Implement `analyze_straddle()` — long/short straddles
- Implement `analyze_strangle()` — long/short strangles
- Implement `analyze_iron_condor()` — iron condor credit spread
- Add POP calculation for all strategies (using lognormal distribution)
- Add expected value calculation: `EV = POP * max_profit - (1-POP) * max_loss`
- Add net Greeks aggregation for multi-leg positions
- Return structured dicts compatible with MemoRecommendation schema

**NOT in scope**:
- Data fetching (callers supply option leg data)
- PMCC scanning (TASK-080)
- Toolkit wrapper class (TASK-081)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/options/spreads.py` | CREATE | All spread analysis functions |
| `tests/test_options_spreads.py` | CREATE | Unit tests for spread analyzers |
| `parrot/tools/options/__init__.py` | MODIFY | Add spreads exports |

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/tools/options/spreads.py
from typing import Optional
from dataclasses import dataclass
from scipy.stats import norm
import math
from .models import OptionLeg, GreeksResult
from .black_scholes import black_scholes_greeks, black_scholes_price

@dataclass
class SpreadAnalysis:
    """Result from spread strategy analysis."""
    strategy_type: str
    direction: str  # "debit" or "credit"
    net_debit: Optional[float]  # For debit spreads
    net_credit: Optional[float]  # For credit spreads
    max_profit: float
    max_loss: float
    breakeven: float  # Single breakeven for verticals
    breakeven_up: Optional[float]  # Upper breakeven for straddles/strangles
    breakeven_down: Optional[float]  # Lower breakeven for straddles/strangles
    risk_reward_ratio: float
    pop: float  # Probability of profit
    expected_value: float
    net_delta: float
    net_gamma: float
    net_theta: float
    net_vega: float


def analyze_vertical(
    underlying_price: float,
    long_leg: OptionLeg,
    short_leg: OptionLeg,
    option_type: str,  # "call" or "put"
    expiry_days: int,
    volatility: float,
    risk_free_rate: float = 0.05
) -> SpreadAnalysis:
    """
    Analyze a vertical spread (bull call, bear call, bull put, bear put).

    For bull call spread:
        - Buy lower strike call, sell higher strike call
        - Max profit = width - net_debit
        - Max loss = net_debit
        - Breakeven = long_strike + net_debit
    """
    # Calculate net debit/credit
    long_mid = (long_leg.bid + long_leg.ask) / 2
    short_mid = (short_leg.bid + short_leg.ask) / 2
    net_debit = long_mid - short_mid

    width = abs(short_leg.strike - long_leg.strike)

    if net_debit > 0:
        # Debit spread
        max_profit = width - net_debit
        max_loss = net_debit
        direction = "debit"
    else:
        # Credit spread
        net_credit = -net_debit
        max_profit = net_credit
        max_loss = width - net_credit
        direction = "credit"

    # Breakeven calculation
    if option_type == "call":
        breakeven = long_leg.strike + net_debit
    else:
        breakeven = long_leg.strike - net_debit

    # POP calculation (simplified for vertical)
    T = expiry_days / 365
    # For debit call spread: POP = P(price > breakeven)
    d = (math.log(underlying_price / breakeven) + (risk_free_rate - 0.5 * volatility**2) * T) / (volatility * math.sqrt(T))
    if option_type == "call" and net_debit > 0:
        pop = norm.cdf(d)
    else:
        pop = 1 - norm.cdf(d)

    expected_value = pop * max_profit - (1 - pop) * max_loss

    # Net Greeks
    long_greeks = black_scholes_greeks(underlying_price, long_leg.strike, T, risk_free_rate, volatility, option_type)
    short_greeks = black_scholes_greeks(underlying_price, short_leg.strike, T, risk_free_rate, volatility, option_type)

    return SpreadAnalysis(
        strategy_type="vertical",
        direction=direction,
        net_debit=net_debit if net_debit > 0 else None,
        net_credit=-net_debit if net_debit < 0 else None,
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven=breakeven,
        breakeven_up=None,
        breakeven_down=None,
        risk_reward_ratio=max_profit / max_loss if max_loss > 0 else float('inf'),
        pop=pop,
        expected_value=expected_value,
        net_delta=long_greeks.delta - short_greeks.delta,
        net_gamma=long_greeks.gamma - short_greeks.gamma,
        net_theta=long_greeks.theta - short_greeks.theta,
        net_vega=long_greeks.vega - short_greeks.vega,
    )
```

### Key Constraints

- All functions accept OptionLeg dataclasses or raw numerical inputs
- Return SpreadAnalysis dataclass for consistent structure
- POP must use lognormal distribution (standard for options)
- Net Greeks must account for long (+) and short (-) positions
- Handle both debit and credit variants for each strategy
- No data fetching — pure computation only

### Strategy Formulas

**Vertical Spread:**
- Bull call: Buy lower K call, sell higher K call (debit)
- Bear call: Sell lower K call, buy higher K call (credit)
- Bull put: Sell higher K put, buy lower K put (credit)
- Bear put: Buy higher K put, sell lower K put (debit)

**Straddle:**
- Buy call + put at same strike
- Breakeven_up = strike + total_cost
- Breakeven_down = strike - total_cost
- POP = P(|move| > total_cost / strike)

**Strangle:**
- Buy OTM call + OTM put
- Breakeven_up = call_strike + total_cost
- Breakeven_down = put_strike - total_cost

**Iron Condor:**
- Bull put spread + bear call spread
- Net credit = put_credit + call_credit
- Max loss = width - net_credit (whichever wing is hit)
- POP = P(price stays between short strikes)

### References in Codebase

- `trading_skills/src/trading_skills/spreads.py` — reference implementation (270 lines)
- `parrot/tools/options/black_scholes.py` — Greeks calculations
- `parrot/tools/options/models.py` — OptionLeg dataclass

---

## Acceptance Criteria

- [ ] All 5 spread analyzers implemented: vertical, diagonal, straddle, strangle, iron_condor
- [ ] Each analyzer returns max_profit, max_loss, breakeven(s), POP, EV, net Greeks
- [ ] POP calculations use proper lognormal distribution
- [ ] Net Greeks correctly aggregate long/short positions
- [ ] Tests pass: `pytest tests/test_options_spreads.py -v`
- [ ] No linting errors: `ruff check parrot/tools/options/spreads.py`

---

## Test Specification

```python
# tests/test_options_spreads.py
import pytest
from parrot.tools.options.spreads import (
    analyze_vertical, analyze_diagonal, analyze_straddle,
    analyze_strangle, analyze_iron_condor, SpreadAnalysis
)
from parrot.tools.options.models import OptionLeg


@pytest.fixture
def bull_call_legs():
    """Bull call spread: buy 100 call, sell 105 call."""
    return {
        "long": OptionLeg(strike=100, option_type="call", bid=5.20, ask=5.40, mid=5.30, iv=0.25),
        "short": OptionLeg(strike=105, option_type="call", bid=2.80, ask=3.00, mid=2.90, iv=0.26),
    }


class TestVerticalSpread:
    def test_bull_call_spread(self, bull_call_legs):
        """Bull call spread analysis is correct."""
        result = analyze_vertical(
            underlying_price=100.0,
            long_leg=bull_call_legs["long"],
            short_leg=bull_call_legs["short"],
            option_type="call",
            expiry_days=30,
            volatility=0.25
        )
        assert isinstance(result, SpreadAnalysis)
        assert result.strategy_type == "vertical"
        assert result.direction == "debit"
        assert result.net_debit > 0
        assert result.max_profit == 5.0 - result.net_debit  # Width - debit
        assert result.max_loss == result.net_debit
        assert 0 < result.pop < 1
        assert result.net_delta > 0  # Bull spread has positive delta

    def test_bear_put_spread(self):
        """Bear put spread analysis is correct."""
        long_leg = OptionLeg(strike=105, option_type="put", bid=6.00, ask=6.20, mid=6.10, iv=0.25)
        short_leg = OptionLeg(strike=100, option_type="put", bid=3.00, ask=3.20, mid=3.10, iv=0.25)

        result = analyze_vertical(
            underlying_price=100.0,
            long_leg=long_leg,
            short_leg=short_leg,
            option_type="put",
            expiry_days=30,
            volatility=0.25
        )
        assert result.direction == "debit"
        assert result.net_delta < 0  # Bear spread has negative delta


class TestStraddle:
    def test_long_straddle(self):
        """Long straddle analysis is correct."""
        result = analyze_straddle(
            underlying_price=100.0,
            strike=100.0,
            call_bid=5.20, call_ask=5.40,
            put_bid=4.80, put_ask=5.00,
            expiry_days=30,
            volatility=0.25
        )
        total_cost = 5.30 + 4.90  # Mid prices
        assert result.breakeven_up == 100.0 + total_cost
        assert result.breakeven_down == 100.0 - total_cost
        assert result.max_loss == total_cost
        assert result.max_profit == float('inf') or result.max_profit > 1000  # Unlimited


class TestStrangle:
    def test_long_strangle(self):
        """Long strangle analysis is correct."""
        result = analyze_strangle(
            underlying_price=100.0,
            put_strike=95.0, call_strike=105.0,
            put_bid=2.00, put_ask=2.20,
            call_bid=2.00, call_ask=2.20,
            expiry_days=30,
            volatility=0.25
        )
        assert result.breakeven_up > 105.0
        assert result.breakeven_down < 95.0
        assert 0 < result.pop < 1


class TestIronCondor:
    def test_iron_condor(self):
        """Iron condor analysis is correct."""
        result = analyze_iron_condor(
            underlying_price=100.0,
            put_buy_strike=90.0, put_sell_strike=95.0,
            call_sell_strike=105.0, call_buy_strike=110.0,
            put_buy_price=0.50, put_sell_price=1.50,
            call_sell_price=1.50, call_buy_price=0.50,
            expiry_days=30,
            volatility=0.20
        )
        assert result.net_credit > 0
        assert result.max_loss == 5.0 - result.net_credit  # Width - credit
        assert 95.0 < result.breakeven_down < 105.0 < result.breakeven_up
        assert result.pop > 0.5  # IC typically has high POP


class TestNetGreeks:
    def test_vertical_net_greeks(self, bull_call_legs):
        """Net Greeks are correctly calculated for vertical."""
        result = analyze_vertical(
            underlying_price=100.0,
            long_leg=bull_call_legs["long"],
            short_leg=bull_call_legs["short"],
            option_type="call",
            expiry_days=30,
            volatility=0.25
        )
        # Net delta for bull call spread should be positive but < 1
        assert 0 < result.net_delta < 1
        # Net gamma should be small (gamma is highest at ATM strikes)
        assert abs(result.net_gamma) < 0.1
        # Net vega should be small for tight verticals
        assert abs(result.net_vega) < 5
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/options-analytics.spec.md` for full context
2. **Check dependencies** — verify TASK-077, TASK-078 are in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Reference** `trading_skills/src/trading_skills/spreads.py` for implementation
5. **Implement** all 5 spread analyzers per scope
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-079-spread-analyzer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:
- Implemented all 5 spread analyzers in `parrot/tools/options/spreads.py` (~710 lines)
- `analyze_vertical()`: Bull/bear call/put spreads with proper debit/credit detection
- `analyze_diagonal()`: PMCC/calendar-like strategies with multi-DTE support
- `analyze_straddle()`: Long straddles with unlimited profit handling
- `analyze_strangle()`: Long strangles with OTM strikes
- `analyze_iron_condor()`: Credit spread with 4-leg Greeks aggregation
- All analyzers compute: max_profit, max_loss, breakeven(s), POP, EV, net Greeks
- POP uses lognormal distribution via `probability_of_profit` and `probability_in_range`
- Created 44 unit tests in `tests/test_options_spreads.py` — all passing
- Updated `parrot/tools/options/__init__.py` with spread exports
- Linting clean: `ruff check` passes

**Deviations from spec**: none
