# TASK-146: Place Iron Butterfly

**Feature**: Multi-Leg Options Strategy Execution (FEAT-023)
**Spec**: `sdd/specs/options-multi-leg-strategies.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (4h)
**Depends-on**: TASK-143, TASK-145
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Core execution method for Iron Butterfly strategy. Combines strike selection,
> risk validation, and multi-leg order placement.

---

## Scope

- Implement `place_iron_butterfly()` tool method in `AlpacaOptionsToolkit`
- Get underlying price
- Use StrikeSelectionEngine to find ATM + wing strikes
- Validate risk (max_loss <= max_risk_pct of buying power)
- Build 4-leg order using Alpaca's MLEG order class
- Submit order and return confirmation

**NOT in scope**: Position monitoring, P&L tracking.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/alpaca_options.py` | MODIFY | Add place_iron_butterfly method |

---

## Implementation Notes

### Key Constraints
- Use `OrderClass.MLEG` for atomic 4-leg execution
- All legs must be same expiration
- Calculate max_profit = net_credit received
- Calculate max_loss = wing_width - net_credit
- Calculate breakevens = [ATM - credit, ATM + credit]

### Order Structure
```python
from alpaca.trading.requests import OptionLegRequest, MarketOrderRequest
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce

legs = [
    OptionLegRequest(symbol=long_put_sym, side=OrderSide.BUY, ratio_qty=1),
    OptionLegRequest(symbol=short_put_sym, side=OrderSide.SELL, ratio_qty=1),
    OptionLegRequest(symbol=short_call_sym, side=OrderSide.SELL, ratio_qty=1),
    OptionLegRequest(symbol=long_call_sym, side=OrderSide.BUY, ratio_qty=1),
]

order = MarketOrderRequest(
    qty=quantity,
    order_class=OrderClass.MLEG,
    time_in_force=TimeInForce.DAY,
    legs=legs,
)
```

---

## Acceptance Criteria

- [x] Fetches underlying price before strike selection
- [x] Uses StrikeSelectionEngine for strike discovery
- [x] Validates max_loss <= buying_power * max_risk_pct
- [x] Places 4-leg MLEG order via Alpaca
- [x] Returns order_id, max_profit, max_loss, breakevens
- [x] Handles errors gracefully (no valid strikes, insufficient BP)
- [x] Works with paper trading account

---

## Completion Note

Implemented `place_iron_butterfly()` in `AlpacaOptionsToolkit`:

1. **PlaceIronButterflyInput** Pydantic schema with validation
2. **Risk validation**: Checks max_loss against buying_power * max_risk_pct
3. **P&L calculation**: net_credit, max_profit, max_loss, breakevens
4. **MLEG order**: 4-leg atomic order using Alpaca's OrderClass.MLEG
5. **Error handling**: StrikeSelectionError, APIError, risk limits

Added imports:
- `MarketOrderRequest`, `OptionLegRequest` from alpaca.trading.requests
- `OrderClass`, `OrderSide`, `TimeInForce` from alpaca.trading.enums
- `StrikeSelectionEngine` from strike_selection module

---
**Verification (2026-03-05)**:
- Verified implementation in `parrot/finance/tools/alpaca_options.py`.
- Verified risk validation and MLEG order structure.
- Added and ran `test_place_iron_butterfly_success` in `tests/test_alpaca_options_toolkit.py` (passed).
- Verified error handling with `test_place_iron_butterfly_no_options_found` (passed).

