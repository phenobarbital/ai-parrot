# TASK-145: Strike Selection Engine

**Feature**: Multi-Leg Options Strategy Execution (FEAT-023)
**Spec**: `sdd/specs/options-multi-leg-strategies.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (3h)
**Depends-on**: TASK-144
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Engine for selecting optimal strikes based on criteria like delta targets,
> ATM proximity, and liquidity thresholds.

---

## Scope

- Create `StrikeSelectionEngine` class with methods:
  - `find_atm_strike(options, underlying_price)` — Find closest to ATM
  - `find_strike_by_delta(options, target_delta, contract_type)` — Find by delta
  - `validate_liquidity(option, min_oi, max_spread_pct)` — Check liquidity
  - `select_iron_butterfly_strikes(chain, underlying_price, wing_width)` — Full selection
  - `select_iron_condor_strikes(chain, underlying_price, short_delta, wing_width)` — Full selection

**NOT in scope**: Order execution, strategy factory (uses factory output).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/strike_selection.py` | CREATE | StrikeSelectionEngine class |

---

## Implementation Notes

### Key Constraints
- ATM selection: minimize `abs(strike - underlying_price)`
- Delta selection: minimize `abs(abs(delta) - target_delta)`
- Liquidity: OI >= threshold AND spread% <= threshold
- Return `None` if no suitable strike found

### Selection Logic

**Iron Butterfly:**
1. Find ATM strike for short put/call (same strike)
2. Find wing strikes at ATM ± wing_width
3. Validate all 4 strikes have liquidity

**Iron Condor:**
1. Find OTM put at target delta (e.g., -0.30)
2. Find OTM call at target delta (e.g., +0.30)
3. Find wings at short_strike ± wing_width
4. Validate all 4 strikes have liquidity

---

## Acceptance Criteria

- [x] `find_atm_strike()` returns strike closest to underlying
- [x] `find_strike_by_delta()` returns strike closest to target delta
- [x] `validate_liquidity()` checks spread thresholds (OI not in real-time data)
- [x] `select_iron_butterfly_strikes()` returns 4 validated strikes
- [x] `select_iron_condor_strikes()` returns 4 validated strikes
- [x] Returns None/raises if no valid strikes found

---

## Completion Note

Created `parrot/finance/tools/strike_selection.py` with:

1. **SelectedStrikes** dataclass for strike selection results
2. **StrikeSelectionError** exception class
3. **StrikeSelectionEngine** class with methods:
   - `find_atm_strike()` — Find closest to underlying price
   - `find_strike_by_delta()` — Find by delta target (handles put/call signs)
   - `find_strike_at_offset()` — Find at specific offset from base
   - `validate_liquidity()` — Check bid-ask spread thresholds
   - `select_iron_butterfly_strikes()` — Full 4-leg ATM selection
   - `select_iron_condor_strikes()` — Full 4-leg OTM delta selection

Note: Open Interest not available in real-time snapshot data;
using bid-ask spread percentage for liquidity validation.

---
**Verification (2026-03-05)**:
- Verified implementation in `parrot/finance/tools/strike_selection.py`.
- Verified `StrikeSelectionEngine` methods: `find_atm_strike`, `find_strike_by_delta`, `validate_liquidity`, etc.
- Ran unit tests in `tests/test_alpaca_options_toolkit.py` (TestStrikeSelectionEngine class) and confirmed all 11 tests pass.

