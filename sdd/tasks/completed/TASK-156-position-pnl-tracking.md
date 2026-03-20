# TASK-156: Position P&L Tracking

**Feature**: Multi-Leg Options Strategy Execution (FEAT-023)
**Spec**: `sdd/specs/options-multi-leg-strategies.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (2h)
**Depends-on**: TASK-148
**Assigned-to**: claude-session

---

## Context

> Track P&L for options positions including unrealized and realized.
> Essential for position monitoring and risk management.

---

## Scope

- Calculate unrealized P&L for open positions
- Calculate realized P&L on position close
- Track P&L as percentage of max risk
- Add P&L fields to position response

**NOT in scope**: Historical P&L tracking, database persistence.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/alpaca_options.py` | MODIFY | Add P&L calculations |
| `tests/test_alpaca_options_toolkit.py` | MODIFY | Add P&L tracking tests |

---

## Implementation Notes

### P&L Calculation

**For Credit Spreads (Iron Butterfly/Condor):**
```python
# Entry credit = sum of sold legs - sum of bought legs
entry_credit = sum(leg.entry_price for leg in short_legs) - \
               sum(leg.entry_price for leg in long_legs)

# Current value = same calculation with current prices
current_value = sum(leg.current_price for leg in short_legs) - \
                sum(leg.current_price for leg in long_legs)

# Unrealized P&L (for credit spreads, lower value = profit)
unrealized_pnl = (entry_credit - current_value) * 100  # Per contract

# P&L as % of max risk
pnl_pct = unrealized_pnl / max_loss * 100
```

### Response Fields
```python
{
    "current_pnl": 150.00,  # USD
    "current_pnl_pct": 42.5,  # % of max profit
    "pnl_vs_risk": 30.0,  # % of max loss
    "time_value_remaining_pct": 85.0,  # % of entry credit
}
```

---

## Acceptance Criteria

- [x] Unrealized P&L calculated for open positions
- [x] P&L percentage vs max profit calculated
- [x] P&L percentage vs max risk calculated
- [x] Realized P&L returned on close
- [x] All P&L values in OptionsPosition response

---

## Completion Note

**Completed**: 2026-03-04

### Implementation Summary

1. **Added `_calculate_pnl_metrics()` helper method** to `AlpacaOptionsToolkit`:
   - Calculates entry_credit, current_value, unrealized_pnl
   - Computes max_profit and max_loss based on strategy type
   - Returns current_pnl_pct (% of max profit), pnl_vs_risk (% of max loss)
   - Calculates time_value_remaining_pct (position decay tracking)

2. **Updated `get_options_positions()`** to include P&L metrics:
   - All positions now include: entry_credit, current_value, current_pnl
   - Added: max_profit, max_loss, current_pnl_pct, pnl_vs_risk, time_value_remaining_pct

3. **Updated `close_options_position()`** to include realized P&L metrics:
   - Returns: entry_credit, close_value, realized_pnl
   - Added: realized_pnl_pct, realized_vs_risk

4. **Added 6 P&L tracking tests**:
   - test_calculate_pnl_iron_butterfly_at_entry
   - test_calculate_pnl_iron_butterfly_profit
   - test_calculate_pnl_iron_butterfly_loss
   - test_calculate_pnl_vertical_credit_spread
   - test_calculate_pnl_single_long_call
   - test_positions_include_pnl_fields

### Test Results
- 49 tests passing (43 original + 6 new P&L tests)
- All linting checks pass
