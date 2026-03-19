# TASK-084: QuantToolkit Data Models

**Feature**: FEAT-017 QuantToolkit
**Spec**: `sdd/specs/quant-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-opus-session

---

## Context

This task creates the foundational Pydantic models for all QuantToolkit operations. These models define the input/output contracts for risk metrics, correlation analysis, stress testing, Piotroski scoring, and volatility calculations.

This is the first task in the FEAT-015 implementation — all other modules depend on these models.

Reference: Spec Section 2 (Data Models) and Section 3 (Module 1).

---

## Scope

- Create the `parrot/tools/quant/` package directory
- Implement all Pydantic input models:
  - `PortfolioRiskInput` — for portfolio-level risk computation
  - `AssetRiskInput` — for single-asset risk metrics
  - `CorrelationInput` — for correlation analysis
  - `StressScenario` — for stress test scenarios
  - `PiotroskiInput` — for F-Score calculation
- Implement all Pydantic output models:
  - `RiskMetricsOutput` — single-asset risk results
  - `PortfolioRiskOutput` — portfolio risk results
- Add validation constraints (weights sum to 1.0, confidence in valid range, etc.)
- Write unit tests for model validation

**NOT in scope**:
- Computation logic (that's in subsequent tasks)
- The main QuantToolkit class (TASK-079)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/quant/__init__.py` | CREATE | Package init (empty for now) |
| `parrot/tools/quant/models.py` | CREATE | All Pydantic input/output models |
| `tests/tools/test_quant/__init__.py` | CREATE | Test package init |
| `tests/tools/test_quant/test_models.py` | CREATE | Unit tests for models |

---

## Implementation Notes

### Pattern to Follow

```python
from pydantic import BaseModel, Field, model_validator
from typing import Literal

class PortfolioRiskInput(BaseModel):
    """Input for portfolio-level risk computation."""
    returns_data: dict[str, list[float]] = Field(
        ..., description="Dict of {symbol: [daily_returns]} for each position"
    )
    weights: list[float] = Field(
        ..., description="Position weights (must sum to 1.0)"
    )
    symbols: list[str] = Field(
        ..., description="Symbol names matching returns_data keys"
    )
    confidence: float = Field(0.95, ge=0.01, le=0.99, description="VaR confidence level")
    risk_free_rate: float = Field(0.04, description="Annualized risk-free rate")
    annualization_factor: int = Field(252, description="252 for stocks, 365 for crypto")

    @model_validator(mode='after')
    def validate_weights(self) -> 'PortfolioRiskInput':
        if abs(sum(self.weights) - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {sum(self.weights)}")
        if len(self.weights) != len(self.symbols):
            raise ValueError("weights and symbols must have same length")
        return self
```

### Key Constraints
- Use Pydantic v2 syntax (`model_validator` not `validator`)
- Add `Field` descriptions for all parameters (used by LLM tools)
- Validate that weights sum to 1.0 within tolerance (0.01)
- Validate that symbols match returns_data keys
- Confidence must be between 0.01 and 0.99

### References in Codebase
- `parrot/tools/ibkr/models.py` — similar toolkit models pattern
- `parrot/finance/schemas.py` — `PortfolioSnapshot`, `Position` dataclasses

---

## Acceptance Criteria

- [x] Package `parrot/tools/quant/` exists with `__init__.py`
- [x] All 7 Pydantic models defined per spec
- [x] Validation constraints enforced (weights sum, confidence range)
- [x] All tests pass: `pytest tests/tools/test_quant/test_models.py -v`
- [x] Imports work: `from parrot.tools.quant.models import PortfolioRiskInput`

---

## Test Specification

```python
# tests/tools/test_quant/test_models.py
import pytest
from parrot.tools.quant.models import (
    PortfolioRiskInput, AssetRiskInput, CorrelationInput,
    StressScenario, PiotroskiInput, RiskMetricsOutput, PortfolioRiskOutput
)


class TestPortfolioRiskInput:
    def test_valid_input(self):
        """Valid input with weights summing to 1.0."""
        inp = PortfolioRiskInput(
            returns_data={"AAPL": [0.01, 0.02], "SPY": [0.005, 0.01]},
            weights=[0.6, 0.4],
            symbols=["AAPL", "SPY"],
        )
        assert inp.confidence == 0.95  # default

    def test_weights_must_sum_to_one(self):
        """Weights not summing to 1.0 raises error."""
        with pytest.raises(ValueError, match="sum to 1.0"):
            PortfolioRiskInput(
                returns_data={"AAPL": [0.01], "SPY": [0.01]},
                weights=[0.5, 0.3],  # sums to 0.8
                symbols=["AAPL", "SPY"],
            )

    def test_symbols_weights_length_mismatch(self):
        """Mismatched symbols and weights raises error."""
        with pytest.raises(ValueError, match="same length"):
            PortfolioRiskInput(
                returns_data={"AAPL": [0.01], "SPY": [0.01]},
                weights=[0.6, 0.3, 0.1],
                symbols=["AAPL", "SPY"],
            )

    def test_confidence_bounds(self):
        """Confidence must be between 0.01 and 0.99."""
        with pytest.raises(ValueError):
            PortfolioRiskInput(
                returns_data={"AAPL": [0.01]},
                weights=[1.0],
                symbols=["AAPL"],
                confidence=1.5,
            )


class TestAssetRiskInput:
    def test_defaults(self):
        """Default values are set correctly."""
        inp = AssetRiskInput(returns=[0.01, 0.02, -0.01])
        assert inp.risk_free_rate == 0.04
        assert inp.annualization_factor == 252
        assert inp.benchmark_returns is None


class TestStressScenario:
    def test_scenario_creation(self):
        """Stress scenario with shocks."""
        scenario = StressScenario(
            name="covid_crash",
            asset_shocks={"SPY": -0.34, "BTC": -0.50},
        )
        assert scenario.name == "covid_crash"
        assert scenario.asset_shocks["SPY"] == -0.34


class TestRiskMetricsOutput:
    def test_output_fields(self):
        """Output model has all required fields."""
        out = RiskMetricsOutput(
            volatility_annual=0.25,
            beta=1.2,
            sharpe_ratio=1.5,
            max_drawdown=-0.15,
            var_95=-0.02,
            var_99=-0.03,
            cvar_95=-0.025,
        )
        assert out.volatility_annual == 0.25
        assert out.beta == 1.2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/quant-toolkit.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-077-quant-data-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:
- Created `parrot/tools/quant/` package with `__init__.py` and `models.py`
- Implemented 5 input models: `PortfolioRiskInput`, `AssetRiskInput`, `CorrelationInput`, `StressScenario`, `PiotroskiInput`
- Implemented 2 output models: `RiskMetricsOutput`, `PortfolioRiskOutput`
- All models use Pydantic v2 with `Field` descriptions for LLM tool compatibility
- `PortfolioRiskInput` includes `model_validator` for weights sum (1.0 ± 0.01) and symbols/weights length match
- Comprehensive test suite: 31 tests covering validation, defaults, edge cases, and imports
- Linting and tests pass

**Deviations from spec**: None. Implementation follows spec exactly.
