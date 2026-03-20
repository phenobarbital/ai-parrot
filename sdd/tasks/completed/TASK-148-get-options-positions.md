# TASK-148: Get Options Positions

**Feature**: Multi-Leg Options Strategy Execution (FEAT-023)
**Spec**: `sdd/specs/options-multi-leg-strategies.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (2h)
**Depends-on**: TASK-142
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Retrieve current options positions from Alpaca with Greeks and P&L.
> Required for position monitoring and risk analysis.

---

## Scope

- Implement `get_options_positions()` tool method in `AlpacaOptionsToolkit`
- Fetch all open options positions from Alpaca
- Group multi-leg positions by strategy (identify butterflies/condors)
- Calculate current P&L for each position
- Fetch current Greeks for each leg
- Return list of `OptionsPosition` dicts

**NOT in scope**: Close logic, historical positions.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/alpaca_options.py` | MODIFY | Add get_options_positions method |

---

## Implementation Notes

### Key Constraints
- Use `client.get_all_positions()` and filter for options
- Group legs by underlying + expiration to identify strategies
- Detect strategy type from leg structure:
  - 4 legs, 2 shorts ATM = iron_butterfly
  - 4 legs, 2 shorts OTM = iron_condor
  - 2 legs = vertical spread
- Current P&L = (current_value - entry_value) * multiplier

### Position Identification
```python
# Options positions have symbols like: AAPL240315C00150000
# Parse: underlying, expiration, type (C/P), strike
def parse_occ_symbol(symbol: str) -> dict:
    # Returns {underlying, expiration, type, strike}
    ...
```

---

## Acceptance Criteria

- [x] Returns list of OptionsPosition dicts
- [x] Each position includes all legs with current prices
- [x] Strategy type correctly identified
- [x] Current P&L calculated for each position
- [x] Greeks included for each leg (fetched from snapshots)
- [x] Optional filter by underlying symbol

---

## Completion Note

Implemented `get_options_positions()` in `AlpacaOptionsToolkit`:

1. **GetOptionsPositionsInput** Pydantic schema with optional underlying filter
2. **Position retrieval**: Fetches all positions, filters to options by OCC format
3. **Snapshot integration**: Fetches real-time Greeks via OptionSnapshotRequest
4. **Position grouping**: Groups legs by underlying + expiration
5. **Strategy detection**: `_detect_strategy_type()` identifies:
   - single, vertical, straddle, strangle
   - iron_butterfly (shorts at same strike)
   - iron_condor (shorts at different strikes)
   - custom (anything else)
6. **P&L calculation**: Aggregates unrealized P&L across legs
7. **Position Greeks**: Sums delta/gamma/theta/vega across legs

Returns: positions list, total_positions count, total_pnl aggregate.

---
**Verification (2026-03-05)**:
- Verified implementation in `parrot/finance/tools/alpaca_options.py`.
- Verified position grouping and strategy detection logic.
- Ran unit tests in `tests/test_alpaca_options_toolkit.py` (TestGetOptionsPositions class) and confirmed all 3 tests pass.

