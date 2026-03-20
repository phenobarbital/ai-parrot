# TASK-078: Black-Scholes Pricing Engine

**Feature**: Options Analytics Toolkit
**Spec**: `sdd/specs/options-analytics.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-077
**Assigned-to**: claude-opus-session

---

## Context

This is the core computation module for the Options Analytics Toolkit. It implements the Black-Scholes pricing model, Greeks calculations, and implied volatility solver. This module is used by all other modules in the toolkit.

The implementation should follow the reference from `trading_skills/src/trading_skills/black_scholes.py` but with modifications for AI-Parrot's pure computation approach (no IO, no yfinance).

Reference: Spec Section 2 "Data Models" and Section 3 "Module 2: Black-Scholes Engine"

---

## Scope

- Implement core BS pricing: `black_scholes_price(S, K, T, r, sigma, option_type)` → float
- Implement full Greeks: `black_scholes_greeks(S, K, T, r, sigma, option_type)` → GreeksResult
- Implement standalone Greeks: `black_scholes_delta()`, `black_scholes_vega()`
- Implement IV solver: `implied_volatility()` with Newton-Raphson + bisection fallback
- Implement IV estimation heuristic: `estimate_iv()` for when market IV unavailable
- Implement Put-Call Parity validation: `validate_put_call_parity()`
- Implement batch Greeks: `compute_chain_greeks()` vectorized with numpy
- Implement Probability of Profit: `probability_of_profit()`
- Handle edge cases: T=0, sigma=0, deep ITM/OTM, negative rates

**NOT in scope**:
- Spread analysis (TASK-079)
- PMCC scanning (TASK-080)
- Binomial tree pricing (Phase 2)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/options/black_scholes.py` | CREATE | All BS pricing and Greeks functions |
| `tests/test_black_scholes.py` | CREATE | Unit tests for BS engine |
| `parrot/tools/options/__init__.py` | MODIFY | Add black_scholes exports |

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/tools/options/black_scholes.py
from scipy.stats import norm
import math
import numpy as np
from typing import Optional
from .models import IVResult, GreeksResult

def black_scholes_price(
    S: float,       # Spot price
    K: float,       # Strike price
    T: float,       # Time to expiry in years
    r: float,       # Risk-free rate
    sigma: float,   # Volatility
    option_type: str  # "call" or "put"
) -> float:
    """Calculate Black-Scholes option price."""
    if T <= 0:
        # At expiry, intrinsic value only
        if option_type == "call":
            return max(S - K, 0)
        return max(K - S, 0)

    if sigma <= 0:
        raise ValueError("Volatility must be positive")

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if option_type == "call":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str,
    initial_guess: float = 0.3,
    max_iterations: int = 100,
    tolerance: float = 1e-6
) -> IVResult:
    """
    Solve for implied volatility using Newton-Raphson with bisection fallback.
    """
    # Newton-Raphson first
    sigma = initial_guess
    for i in range(max_iterations):
        price = black_scholes_price(S, K, T, r, sigma, option_type)
        vega = black_scholes_vega(S, K, T, r, sigma)

        if abs(vega) < 1e-10:
            break  # Vega too small, switch to bisection

        diff = price - market_price
        if abs(diff) < tolerance:
            return IVResult(iv=sigma, converged=True, iterations=i+1, method="newton_raphson")

        sigma = sigma - diff / vega
        if sigma <= 0:
            break  # Went negative, switch to bisection

    # Bisection fallback
    # ... implement bisection search between 0.01 and 5.0
```

### Key Constraints

- Pure computation only — no IO, no external API calls
- Use scipy.stats.norm for cumulative distribution
- Use numpy for vectorized batch operations
- Raise `ValueError` for invalid inputs (not error dicts)
- Return dataclasses from models.py for structured output
- Handle all edge cases gracefully

### References in Codebase

- `trading_skills/src/trading_skills/black_scholes.py` — reference implementation (204 lines)
- `parrot/tools/options/models.py` — IVResult, GreeksResult dataclasses

---

## Acceptance Criteria

- [ ] All pricing functions implemented and tested
- [ ] Greeks calculations match known reference values within 0.01% tolerance
- [ ] IV solver converges for 99%+ of realistic market prices
- [ ] Batch Greeks computation is ≥10x faster than individual calls (benchmark)
- [ ] Edge cases handled: T=0, sigma=0, deep ITM/OTM
- [ ] Tests pass: `pytest tests/test_black_scholes.py -v`
- [ ] No linting errors: `ruff check parrot/tools/options/black_scholes.py`

---

## Test Specification

```python
# tests/test_black_scholes.py
import pytest
import numpy as np
from parrot.tools.options.black_scholes import (
    black_scholes_price, black_scholes_greeks, black_scholes_delta,
    black_scholes_vega, implied_volatility, estimate_iv,
    validate_put_call_parity, compute_chain_greeks, probability_of_profit
)
from parrot.tools.options.models import IVResult, GreeksResult


class TestBlackScholesPrice:
    def test_atm_call(self):
        """ATM call pricing matches known value."""
        # S=100, K=100, T=1, r=0.05, sigma=0.20
        price = black_scholes_price(100, 100, 1.0, 0.05, 0.20, "call")
        assert abs(price - 10.45) < 0.1  # Approximate known value

    def test_atm_put(self):
        """ATM put pricing matches known value."""
        price = black_scholes_price(100, 100, 1.0, 0.05, 0.20, "put")
        assert abs(price - 5.57) < 0.1  # Approximate known value

    def test_deep_itm_call(self):
        """Deep ITM call approaches intrinsic value."""
        price = black_scholes_price(150, 100, 0.1, 0.05, 0.20, "call")
        intrinsic = 50
        assert price >= intrinsic

    def test_deep_otm_put(self):
        """Deep OTM put approaches zero."""
        price = black_scholes_price(150, 100, 0.1, 0.05, 0.20, "put")
        assert price < 0.01

    def test_t_zero(self):
        """At expiry, returns intrinsic value."""
        call_price = black_scholes_price(105, 100, 0, 0.05, 0.20, "call")
        assert call_price == 5.0
        put_price = black_scholes_price(95, 100, 0, 0.05, 0.20, "put")
        assert put_price == 5.0

    def test_invalid_sigma(self):
        """Zero or negative volatility raises ValueError."""
        with pytest.raises(ValueError):
            black_scholes_price(100, 100, 1.0, 0.05, 0, "call")


class TestBlackScholesGreeks:
    def test_call_greeks(self):
        """Greeks for call option have correct signs."""
        result = black_scholes_greeks(100, 100, 1.0, 0.05, 0.20, "call")
        assert isinstance(result, GreeksResult)
        assert 0 < result.delta < 1  # Call delta is positive
        assert result.gamma > 0  # Gamma always positive
        assert result.theta < 0  # Theta is time decay
        assert result.vega > 0  # Vega always positive

    def test_put_greeks(self):
        """Greeks for put option have correct signs."""
        result = black_scholes_greeks(100, 100, 1.0, 0.05, 0.20, "put")
        assert -1 < result.delta < 0  # Put delta is negative
        assert result.gamma > 0  # Gamma always positive
        assert result.vega > 0  # Vega always positive


class TestImpliedVolatility:
    def test_iv_convergence(self):
        """IV solver converges on known market price."""
        # First calculate a theoretical price
        sigma_true = 0.25
        price = black_scholes_price(100, 100, 0.5, 0.05, sigma_true, "call")

        # Then solve for IV
        result = implied_volatility(price, 100, 100, 0.5, 0.05, "call")
        assert result.converged is True
        assert abs(result.iv - sigma_true) < 0.001

    def test_iv_bisection_fallback(self):
        """IV solver falls back to bisection when Newton-Raphson fails."""
        # Edge case that might challenge Newton-Raphson
        result = implied_volatility(0.01, 100, 150, 0.1, 0.05, "call")
        assert result.method in ["newton_raphson", "bisection"]

    def test_iv_impossible_price(self):
        """IV solver handles impossible prices gracefully."""
        # Price below intrinsic value
        result = implied_volatility(0.0, 110, 100, 0.5, 0.05, "call")
        assert result.converged is False or result.iv is None


class TestBatchGreeks:
    def test_chain_greeks_vectorized(self):
        """Batch computation matches individual calls."""
        import pandas as pd
        chain = pd.DataFrame({
            'strike': [95.0, 100.0, 105.0],
            'impliedVolatility': [0.25, 0.25, 0.25]
        })
        result = compute_chain_greeks(chain, spot=100.0, r=0.05, dte_years=30/365)

        assert 'delta' in result.columns
        assert 'gamma' in result.columns
        assert len(result) == 3


class TestPutCallParity:
    def test_parity_holds(self):
        """Put-call parity validation passes for theoretical prices."""
        S, K, T, r, sigma = 100, 100, 1.0, 0.05, 0.20
        call_price = black_scholes_price(S, K, T, r, sigma, "call")
        put_price = black_scholes_price(S, K, T, r, sigma, "put")

        result = validate_put_call_parity(call_price, put_price, S, K, T, r)
        assert result["arbitrage_flag"] is False
        assert abs(result["spread"]) < 0.01
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/options-analytics.spec.md` for full context
2. **Check dependencies** — verify TASK-077 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Reference** `trading_skills/src/trading_skills/black_scholes.py` for implementation
5. **Implement** all functions per scope
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-078-black-scholes-engine.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:
- Implemented full Black-Scholes pricing engine in `parrot/tools/options/black_scholes.py`
- Core functions: `black_scholes_price`, `black_scholes_greeks`
- Individual Greeks: `black_scholes_delta`, `black_scholes_gamma`, `black_scholes_vega`, `black_scholes_theta`, `black_scholes_rho`
- IV solver: `implied_volatility` with Newton-Raphson + bisection fallback
- Utilities: `estimate_iv`, `validate_put_call_parity`
- Batch operations: `compute_chain_greeks` (vectorized with numpy)
- Probability: `probability_of_profit`, `probability_in_range`
- All 66 tests pass, validates against Hull's reference values
- No linting errors

**Deviations from spec**: Added `probability_in_range()` for iron condor analysis (useful addition)
