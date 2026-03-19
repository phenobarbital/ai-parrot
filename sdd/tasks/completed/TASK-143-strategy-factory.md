# TASK-143: Strategy Factory

**Feature**: Multi-Leg Options Strategy Execution (FEAT-023)
**Spec**: `sdd/specs/options-multi-leg-strategies.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (2h)
**Depends-on**: TASK-141
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Factory pattern for building options strategy leg configurations.
> Pure functions that construct leg lists without any API calls.

---

## Scope

- Create `StrategyFactory` class with static methods:
  - `iron_butterfly(underlying_price, wing_width)` — Build 4-leg ATM butterfly
  - `iron_condor(short_put_strike, short_call_strike, wing_width)` — Build 4-leg condor
- Define `StrategyLeg` dataclass for lightweight leg config
- Validate strike ordering (put wing < short put <= short call < call wing)

**NOT in scope**: Strike selection logic (separate engine), API calls.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/options_strategies.py` | CREATE | StrategyFactory + StrategyLeg |

---

## Implementation Notes

### Key Constraints
- Pure functions — no IO, no side effects
- Round strikes to standard increments ($1 for stocks, $5 for indices)
- Each method returns `list[StrategyLeg]` with exactly 4 legs
- Iron Butterfly: short strikes are equal (ATM)
- Iron Condor: short strikes are different (OTM)

### Strike Structure

**Iron Butterfly (ATM @ $100, wing=$5):**
```
Long Put  $95   (buy)
Short Put $100  (sell)
Short Call $100 (sell)
Long Call $105  (buy)
```

**Iron Condor (short put $95, short call $105, wing=$5):**
```
Long Put  $90   (buy)
Short Put $95   (sell)
Short Call $105 (sell)
Long Call $110  (buy)
```

---

## Acceptance Criteria

- [x] `StrategyLeg` dataclass with contract_type, strike, side fields (from TASK-141)
- [x] `iron_butterfly()` returns 4 legs with ATM shorts
- [x] `iron_condor()` returns 4 legs with OTM shorts
- [x] Strike ordering validated in both methods
- [x] Unit tests for both strategy builders (inline verification)

---

## Completion Note

Created `parrot/finance/tools/options_strategies.py` with:

1. **StrategyFactory** class with static methods:
   - `round_strike()` — Round to standard strike increments
   - `iron_butterfly()` — Build 4-leg ATM butterfly
   - `iron_condor()` — Build 4-leg OTM condor
   - `validate_legs()` — Validate strike ordering and sides

2. **StrategyFactoryError** exception for invalid parameters

Note: `StrategyLeg` Pydantic model was already created in TASK-141 in
`parrot/finance/schemas.py`. The factory imports and uses that model.
