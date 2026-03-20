# TASK-077: Options Analytics Data Models

**Feature**: Options Analytics Toolkit
**Spec**: `sdd/specs/options-analytics.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-opus-session

---

## Context

This is the foundational task for the Options Analytics Toolkit (FEAT-015). It defines all shared dataclasses and Pydantic input models used by the Black-Scholes engine, spread analyzers, and PMCC scanner.

These models must be created first as they are imported by all other modules in the toolkit.

Reference: Spec Section 2 "Data Models" and Section 3 "Module 1: Data Models"

---

## Scope

- Create `parrot/tools/options/` directory structure
- Implement all dataclasses: `IVResult`, `GreeksResult`, `OptionLeg`, `PMCCScoringConfig`
- Implement all Pydantic input models: `ComputeGreeksInput`, `AnalyzeSpreadInput`
- Add comprehensive docstrings for all models
- Export all models from `__init__.py`

**NOT in scope**:
- Black-Scholes calculations (TASK-078)
- Spread analysis logic (TASK-079)
- Toolkit class (TASK-081)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/options/__init__.py` | CREATE | Package init with model exports |
| `parrot/tools/options/models.py` | CREATE | All dataclasses and Pydantic models |
| `tests/test_options_models.py` | CREATE | Basic model validation tests |

---

## Implementation Notes

### Pattern to Follow

```python
# Use dataclasses for return types (internal computation)
from dataclasses import dataclass
from typing import Optional

@dataclass
class IVResult:
    """Result from implied volatility calculation."""
    iv: float
    converged: bool
    iterations: int
    method: str  # "newton_raphson" | "bisection"

# Use Pydantic for tool inputs (external interface)
from pydantic import BaseModel, Field

class ComputeGreeksInput(BaseModel):
    """Input model for computing option Greeks."""
    spot: float = Field(..., description="Current underlying price")
    strike: float = Field(..., description="Option strike price")
    # ...
```

### Key Constraints

- All dataclasses must be immutable-friendly (no mutable default args)
- Pydantic models must have complete Field descriptions (used as LLM tool descriptions)
- Follow existing naming conventions in `parrot/tools/`
- Type hints required on all fields

### References in Codebase

- `parrot/tools/toolkit.py` — AbstractToolkit pattern for reference
- `parrot/integrations/ibkr/models.py` — Pydantic model patterns for finance

---

## Acceptance Criteria

- [ ] Directory `parrot/tools/options/` exists with proper structure
- [ ] All 4 dataclasses implemented: `IVResult`, `GreeksResult`, `OptionLeg`, `PMCCScoringConfig`
- [ ] All 2+ Pydantic models implemented: `ComputeGreeksInput`, `AnalyzeSpreadInput`
- [ ] All models importable: `from parrot.tools.options import IVResult, GreeksResult, ...`
- [ ] Tests pass: `pytest tests/test_options_models.py -v`
- [ ] No linting errors: `ruff check parrot/tools/options/`

---

## Test Specification

```python
# tests/test_options_models.py
import pytest
from parrot.tools.options.models import (
    IVResult, GreeksResult, OptionLeg, PMCCScoringConfig,
    ComputeGreeksInput, AnalyzeSpreadInput
)


class TestDataclasses:
    def test_iv_result_creation(self):
        """IVResult dataclass creates correctly."""
        result = IVResult(iv=0.25, converged=True, iterations=5, method="newton_raphson")
        assert result.iv == 0.25
        assert result.converged is True
        assert result.method == "newton_raphson"

    def test_greeks_result_creation(self):
        """GreeksResult dataclass creates correctly."""
        result = GreeksResult(
            price=5.50, delta=0.55, gamma=0.02,
            theta=-0.05, vega=0.15, rho=0.03
        )
        assert result.delta == 0.55
        assert result.theta == -0.05

    def test_option_leg_creation(self):
        """OptionLeg dataclass creates correctly."""
        leg = OptionLeg(
            strike=100.0, option_type="call",
            bid=5.20, ask=5.40, mid=5.30, iv=0.25
        )
        assert leg.strike == 100.0
        assert leg.mid == 5.30

    def test_pmcc_config_defaults(self):
        """PMCCScoringConfig has correct defaults."""
        config = PMCCScoringConfig()
        assert config.leaps_delta_target == 0.80
        assert config.short_delta_target == 0.20
        assert config.min_leaps_days == 270


class TestPydanticModels:
    def test_compute_greeks_input_validation(self):
        """ComputeGreeksInput validates required fields."""
        input_model = ComputeGreeksInput(
            spot=100.0, strike=105.0, dte_days=30,
            volatility=0.25, option_type="call"
        )
        assert input_model.spot == 100.0
        assert input_model.risk_free_rate == 0.05  # default

    def test_compute_greeks_input_invalid(self):
        """ComputeGreeksInput rejects invalid input."""
        with pytest.raises(Exception):
            ComputeGreeksInput(
                spot="invalid", strike=105.0, dte_days=30,
                volatility=0.25, option_type="call"
            )

    def test_analyze_spread_input(self):
        """AnalyzeSpreadInput validates correctly."""
        input_model = AnalyzeSpreadInput(
            underlying_price=100.0,
            long_strike=95.0, long_bid=6.50, long_ask=6.80,
            short_strike=105.0, short_bid=1.40, short_ask=1.60,
            option_type="call", expiry_days=30, volatility=0.25
        )
        assert input_model.underlying_price == 100.0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/options-analytics.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Create directory** `parrot/tools/options/`
5. **Implement** models.py following the scope above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-077-options-data-models.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:
- Created `parrot/tools/options/` directory with `__init__.py` and `models.py`
- Implemented 4 dataclasses: `IVResult` (frozen), `GreeksResult` (frozen), `OptionLeg`, `PMCCScoringConfig`
- Implemented 5 Pydantic models: `ComputeGreeksInput`, `AnalyzeSpreadInput`, `AnalyzeStraddleInput`, `AnalyzeStrangleInput`, `AnalyzeIronCondorInput`
- Added comprehensive docstrings and Field descriptions for LLM context
- All 27 tests pass
- No linting errors

**Deviations from spec**: Added 3 extra Pydantic models (`AnalyzeStraddleInput`, `AnalyzeStrangleInput`, `AnalyzeIronCondorInput`) for the spread analyzer module - these were implied by the spec but not explicitly listed in the task.
