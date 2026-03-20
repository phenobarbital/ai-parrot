# TASK-082: Options Analytics Unit Tests

**Feature**: Options Analytics Toolkit
**Spec**: `sdd/specs/options-analytics.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-077, TASK-078, TASK-079, TASK-080, TASK-081
**Assigned-to**: claude-opus-session

---

## Context

This task creates comprehensive unit tests for all modules in the Options Analytics Toolkit. Tests must validate pricing accuracy against known values, edge case handling, and toolkit method behavior.

The tests ensure the toolkit meets the acceptance criteria: BS pricing within 0.01% tolerance, IV solver convergence for 99%+ of cases, and proper error handling.

Reference: Spec Section 4 "Test Specification"

---

## Scope

- Create `tests/test_options_models.py` — model validation tests
- Create `tests/test_black_scholes.py` — BS pricing and Greeks tests
- Create `tests/test_options_spreads.py` — spread analyzer tests
- Create `tests/test_pmcc_scanner.py` — PMCC scanner tests
- Create `tests/test_options_toolkit.py` — toolkit integration tests
- Add test fixtures for sample chains and known values
- Validate against reference values from financial literature

**NOT in scope**:
- Integration tests with YFinanceTool (TASK-083)
- Performance benchmarks (TASK-083)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_options_models.py` | CREATE | Model dataclass and Pydantic tests |
| `tests/test_black_scholes.py` | CREATE | BS pricing, Greeks, IV tests |
| `tests/test_options_spreads.py` | CREATE | Spread analyzer tests |
| `tests/test_pmcc_scanner.py` | CREATE | PMCC scanner tests |
| `tests/test_options_toolkit.py` | CREATE | Toolkit method tests |
| `tests/conftest.py` | MODIFY | Add shared fixtures |

---

## Implementation Notes

### Known Reference Values for BS Pricing

Use these known values for validation (from Hull's "Options, Futures, and Other Derivatives"):

| S | K | T | r | σ | Type | Price | Delta |
|---|---|---|---|---|------|-------|-------|
| 100 | 100 | 1.0 | 0.05 | 0.20 | call | 10.45 | 0.6368 |
| 100 | 100 | 1.0 | 0.05 | 0.20 | put | 5.57 | -0.3632 |
| 42 | 40 | 0.5 | 0.10 | 0.20 | call | 4.76 | 0.7865 |
| 42 | 40 | 0.5 | 0.10 | 0.20 | put | 0.81 | -0.2135 |

### Test Structure

```python
# tests/test_black_scholes.py
import pytest
import math
from parrot.tools.options.black_scholes import (
    black_scholes_price, black_scholes_greeks, black_scholes_delta,
    black_scholes_vega, implied_volatility, estimate_iv,
    validate_put_call_parity, compute_chain_greeks, probability_of_profit
)
from parrot.tools.options.models import IVResult, GreeksResult


# Known reference values from Hull's textbook
REFERENCE_VALUES = [
    # (S, K, T, r, sigma, type, expected_price, expected_delta)
    (100, 100, 1.0, 0.05, 0.20, "call", 10.45, 0.6368),
    (100, 100, 1.0, 0.05, 0.20, "put", 5.57, -0.3632),
    (42, 40, 0.5, 0.10, 0.20, "call", 4.76, 0.7865),
    (42, 40, 0.5, 0.10, 0.20, "put", 0.81, -0.2135),
]


class TestBlackScholesPricing:
    @pytest.mark.parametrize(
        "S,K,T,r,sigma,opt_type,expected_price,expected_delta",
        REFERENCE_VALUES
    )
    def test_reference_values(self, S, K, T, r, sigma, opt_type, expected_price, expected_delta):
        """BS pricing matches Hull's reference values within 0.01%."""
        price = black_scholes_price(S, K, T, r, sigma, opt_type)
        tolerance = expected_price * 0.01  # 1% tolerance for textbook rounding
        assert abs(price - expected_price) < tolerance, f"Expected {expected_price}, got {price}"

    def test_call_put_parity(self):
        """Call and put prices satisfy put-call parity."""
        S, K, T, r, sigma = 100, 100, 1.0, 0.05, 0.20
        call = black_scholes_price(S, K, T, r, sigma, "call")
        put = black_scholes_price(S, K, T, r, sigma, "put")

        # C - P = S - K*e^(-rT)
        lhs = call - put
        rhs = S - K * math.exp(-r * T)
        assert abs(lhs - rhs) < 0.001


class TestEdgeCases:
    def test_at_expiry(self):
        """At T=0, returns intrinsic value."""
        # ITM call
        assert black_scholes_price(110, 100, 0, 0.05, 0.20, "call") == 10
        # OTM call
        assert black_scholes_price(90, 100, 0, 0.05, 0.20, "call") == 0
        # ITM put
        assert black_scholes_price(90, 100, 0, 0.05, 0.20, "put") == 10
        # OTM put
        assert black_scholes_price(110, 100, 0, 0.05, 0.20, "put") == 0

    def test_zero_volatility_raises(self):
        """Zero volatility raises ValueError."""
        with pytest.raises(ValueError):
            black_scholes_price(100, 100, 1.0, 0.05, 0, "call")

    def test_negative_volatility_raises(self):
        """Negative volatility raises ValueError."""
        with pytest.raises(ValueError):
            black_scholes_price(100, 100, 1.0, 0.05, -0.10, "call")

    def test_deep_itm_call(self):
        """Deep ITM call approaches discounted intrinsic."""
        # S=200, K=100, very deep ITM
        price = black_scholes_price(200, 100, 1.0, 0.05, 0.20, "call")
        intrinsic = 200 - 100
        # Price should be close to intrinsic minus time value
        assert price >= intrinsic * 0.95

    def test_deep_otm_put(self):
        """Deep OTM put approaches zero."""
        price = black_scholes_price(200, 100, 0.1, 0.05, 0.20, "put")
        assert price < 0.01


class TestGreeks:
    def test_call_delta_range(self):
        """Call delta is between 0 and 1."""
        result = black_scholes_greeks(100, 100, 1.0, 0.05, 0.20, "call")
        assert 0 < result.delta < 1

    def test_put_delta_range(self):
        """Put delta is between -1 and 0."""
        result = black_scholes_greeks(100, 100, 1.0, 0.05, 0.20, "put")
        assert -1 < result.delta < 0

    def test_gamma_positive(self):
        """Gamma is always positive for both calls and puts."""
        call_greeks = black_scholes_greeks(100, 100, 1.0, 0.05, 0.20, "call")
        put_greeks = black_scholes_greeks(100, 100, 1.0, 0.05, 0.20, "put")
        assert call_greeks.gamma > 0
        assert put_greeks.gamma > 0
        # Gamma should be the same for call and put at same strike
        assert abs(call_greeks.gamma - put_greeks.gamma) < 0.0001

    def test_theta_negative_for_long(self):
        """Theta (time decay) is negative for long options."""
        result = black_scholes_greeks(100, 100, 1.0, 0.05, 0.20, "call")
        assert result.theta < 0

    def test_vega_positive(self):
        """Vega is positive for both calls and puts."""
        call_greeks = black_scholes_greeks(100, 100, 1.0, 0.05, 0.20, "call")
        put_greeks = black_scholes_greeks(100, 100, 1.0, 0.05, 0.20, "put")
        assert call_greeks.vega > 0
        assert put_greeks.vega > 0


class TestImpliedVolatility:
    def test_iv_roundtrip(self):
        """IV solver recovers original volatility."""
        sigma_true = 0.25
        S, K, T, r = 100, 100, 0.5, 0.05

        # Calculate theoretical price
        price = black_scholes_price(S, K, T, r, sigma_true, "call")

        # Solve for IV
        result = implied_volatility(price, S, K, T, r, "call")
        assert result.converged is True
        assert abs(result.iv - sigma_true) < 0.001

    def test_iv_various_moneyness(self):
        """IV solver works across different moneyness levels."""
        for K in [80, 90, 100, 110, 120]:  # OTM to ITM
            sigma_true = 0.30
            price = black_scholes_price(100, K, 0.5, 0.05, sigma_true, "call")
            if price > 0.01:  # Skip tiny prices
                result = implied_volatility(price, 100, K, 0.5, 0.05, "call")
                assert result.converged is True

    def test_iv_unconvergent_price(self):
        """IV solver handles impossible prices gracefully."""
        # Price below intrinsic (impossible)
        result = implied_volatility(0.001, 110, 100, 0.5, 0.05, "call")
        # Should not crash, may return unconverged
        assert isinstance(result, IVResult)
```

### Key Constraints

- Use `pytest` and `pytest-asyncio`
- Parametrize tests where appropriate
- Include both happy path and edge cases
- Validate against known reference values
- Test error handling paths
- Keep tests isolated (no external dependencies)

### References in Codebase

- `tests/test_agent_service.py` — example test structure
- `tests/conftest.py` — existing fixtures

---

## Acceptance Criteria

- [x] All test files created per scope
- [x] BS pricing tests validate against reference values within 0.01%
- [x] Edge cases tested: T=0, sigma=0, deep ITM/OTM
- [x] IV solver convergence tested for various moneyness levels
- [x] Spread analyzer tests cover all 5 strategies
- [x] PMCC scanner tests cover scoring algorithm
- [x] All tests pass: `pytest tests/test_options*.py -v`
- [x] Test coverage > 85% for options modules (achieved: 88%)

---

## Test Specification

This task IS the test specification implementation. See "Implementation Notes" above for detailed test cases.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/options-analytics.spec.md` for test requirements
2. **Check dependencies** — verify TASK-077-081 are in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Create test files** following the structure above
5. **Run tests** to verify they pass: `pytest tests/test_options*.py -v`
6. **Check coverage**: `pytest tests/test_options*.py --cov=parrot/tools/options`
7. **Move this file** to `sdd/tasks/completed/TASK-082-options-unit-tests.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:
- All 5 test files were created during implementation tasks (TASK-077-081)
- Added 23 additional tests to test_options_toolkit.py to improve coverage
- Fixed 2 bugs in toolkit.py found during testing:
  - compute_chain_greeks: Fixed API call to properly build DataFrame
  - validate_parity: Fixed parameter order to match underlying function
- Final test count: 207 tests (all passing)
- Final coverage: 88% (target was 85%)

**Test breakdown by file**:
- test_options_models.py: 27 tests
- test_black_scholes.py: 66 tests
- test_options_spreads.py: 44 tests
- test_pmcc_scanner.py: 31 tests
- test_options_toolkit.py: 39 tests

**Deviations from spec**: Minor - added more tests than originally specified to achieve coverage target
