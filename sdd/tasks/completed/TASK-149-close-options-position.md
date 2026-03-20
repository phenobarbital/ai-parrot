# TASK-149: Close Options Position

**Feature**: Multi-Leg Options Strategy Execution (FEAT-023)
**Spec**: `sdd/specs/options-multi-leg-strategies.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (2h)
**Depends-on**: TASK-148
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Close an existing multi-leg options position atomically.
> All 4 legs must be closed in a single MLEG order.

---

## Scope

- Implement `close_options_position()` tool method in `AlpacaOptionsToolkit`
- Accept position_id to identify position
- Build reverse MLEG order (buy what was sold, sell what was bought)
- Support market or limit close
- Return realized P&L

**NOT in scope**: Partial closes, rolling to new expiration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/alpaca_options.py` | MODIFY | Add close_options_position method |

---

## Implementation Notes

### Key Constraints
- Reverse the side of each leg:
  - Original BUY → SELL
  - Original SELL → BUY
- Use same OrderClass.MLEG for atomic close
- For limit orders, specify target credit to receive
- Calculate realized P&L = close_credit - open_debit (for credit spreads)

### Close Logic
```python
# Reverse legs for closing
close_legs = []
for leg in position.legs:
    close_side = OrderSide.SELL if leg.side == "long" else OrderSide.BUY
    close_legs.append(OptionLegRequest(
        symbol=leg.symbol,
        side=close_side,
        ratio_qty=1,
    ))
```

---

## Acceptance Criteria

- [x] Accepts position_id and retrieves position
- [x] Builds reverse MLEG order with correct sides
- [x] Supports market close (immediate)
- [x] Supports limit close with target credit
- [x] Returns estimated P&L (realized on fill)
- [x] Handles position not found gracefully

---

## Completion Note

Implemented `close_options_position()` in `AlpacaOptionsToolkit`:

1. **CloseOptionsPositionInput** Pydantic schema with:
   - position_id (required): Format 'UNDERLYING_EXPIRATION'
   - order_type: 'market' or 'limit'
   - limit_credit: Required for limit orders

2. **Position lookup**: Uses get_options_positions() to find target
3. **Reverse order logic**: Flips sides (long→SELL, short→BUY)
4. **P&L calculation**: Estimates P&L from entry vs current prices
5. **Order types**: MarketOrderRequest or LimitOrderRequest with MLEG
6. **Error handling**: Position not found, missing limit_credit

Returns: order_id, status, position_id, estimated_pnl, legs_closed,
entry_value, close_value, strategy_type, paper mode flag.

---
**Verification (2026-03-05)**:
- Verified implementation in `parrot/finance/tools/alpaca_options.py`.
- Verified reverse order logic (flipping sides) for multi-leg positions.
- Added and ran `test_close_options_position_success` in `tests/test_alpaca_options_toolkit.py` (passed).
- Verified error handling for invalid positions (passed).

