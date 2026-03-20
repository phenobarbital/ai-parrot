# TASK-092: MassiveToolkit Input Models

**Feature**: MassiveToolkit
**Spec**: `sdd/specs/massive-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-opus-session

---

## Context

This task implements the Pydantic input models for all 5 MassiveToolkit tools. These models define the schema for agent tool calls and are the foundation for the toolkit implementation.

Reference: Spec Section 2 "Data Models"

---

## Scope

- Implement `OptionsChainInput` model with expiration/strike/type filters
- Implement `ShortInterestInput` model with symbol, limit, order
- Implement `ShortVolumeInput` model with date range filters
- Implement `EarningsDataInput` model with symbol, date, importance filters
- Implement `AnalystRatingsInput` model with action filter and consensus flag
- Add output response models for derived metrics (trend, change_pct, etc.)

**NOT in scope**:
- SDK client implementation (TASK-093)
- Caching logic (TASK-094)
- Toolkit class implementation (TASK-095)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/massive/__init__.py` | CREATE | Package init (empty for now) |
| `parrot/tools/massive/models.py` | CREATE | All Pydantic input/output models |

---

## Implementation Notes

### Pattern to Follow

```python
# Reference: parrot/tools/finnhub.py
from pydantic import BaseModel, Field

class OptionsChainInput(BaseModel):
    underlying: str = Field(..., description="Underlying ticker symbol (e.g. 'AAPL')")
    expiration_date_gte: str | None = Field(None, description="Min expiration date YYYY-MM-DD")
    # ... rest of fields
```

### Key Constraints

- Use `str | None` syntax (Python 3.10+), not `Optional[str]`
- All fields must have `Field()` with description for LLM tool schemas
- Use sensible defaults from spec (limit=250 for options, limit=10 for short interest, etc.)
- Include type validation where appropriate (e.g., `contract_type` must be 'call', 'put', or None)

### References in Codebase

- `parrot/tools/finnhub.py` — Pydantic models for similar financial toolkit
- `parrot/tools/alpaca/models.py` — Another example of financial data models

---

## Acceptance Criteria

- [ ] All 5 input models implemented with full Field descriptions
- [ ] Output models for derived metrics (OptionsChainOutput, ShortInterestOutput, etc.)
- [ ] No linting errors: `ruff check parrot/tools/massive/`
- [ ] Models importable: `from parrot.tools.massive.models import OptionsChainInput`
- [ ] Validation works: invalid contract_type raises ValidationError

---

## Test Specification

```python
# tests/test_massive_models.py
import pytest
from pydantic import ValidationError
from parrot.tools.massive.models import (
    OptionsChainInput,
    ShortInterestInput,
    ShortVolumeInput,
    EarningsDataInput,
    AnalystRatingsInput,
)


class TestOptionsChainInput:
    def test_minimal_input(self):
        """Only underlying is required."""
        inp = OptionsChainInput(underlying="AAPL")
        assert inp.underlying == "AAPL"
        assert inp.limit == 250  # default

    def test_full_input(self):
        """All fields populated."""
        inp = OptionsChainInput(
            underlying="AAPL",
            expiration_date_gte="2026-03-01",
            expiration_date_lte="2026-04-30",
            strike_price_gte=180.0,
            strike_price_lte=200.0,
            contract_type="call",
            limit=100,
        )
        assert inp.contract_type == "call"


class TestShortInterestInput:
    def test_defaults(self):
        """Defaults applied correctly."""
        inp = ShortInterestInput(symbol="GME")
        assert inp.limit == 10
        assert inp.order == "desc"


class TestAnalystRatingsInput:
    def test_action_filter(self):
        """Action filter accepted."""
        inp = AnalystRatingsInput(symbol="AAPL", action="upgrade")
        assert inp.action == "upgrade"
        assert inp.include_consensus is True  # default
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/massive-toolkit.spec.md` for full model definitions
2. **Check dependencies** — none for this task
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** all models in `parrot/tools/massive/models.py`
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-092-massive-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:
- Implemented all 5 input models with full Field descriptions and validation
- Implemented 16 output models for structured responses with derived metrics
- Used Literal types for constrained string fields (contract_type, action, trend, etc.)
- Added validation constraints (min/max length, ge/le bounds)
- All 30 unit tests pass

**Deviations from spec**: Added NextEarnings model for next scheduled earnings (not in original spec but needed for EarningsOutput.next_earnings field)
