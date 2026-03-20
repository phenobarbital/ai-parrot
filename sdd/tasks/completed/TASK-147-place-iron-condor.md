# TASK-147: Place Iron Condor

**Feature**: Multi-Leg Options Strategy Execution (FEAT-023)
**Spec**: `sdd/specs/options-multi-leg-strategies.spec.md`
**Status**: [ ] in-progress | [x] done
**Priority**: high
**Estimated effort**: M (3h)
**Depends-on**: TASK-143, TASK-145
**Assigned-to**: claude-session
**Completed**: 2026-03-05

---

## Context

> Execution method for Iron Condor strategy. Similar to Iron Butterfly but
> with OTM short strikes selected by delta target.

---

## Scope

- Implement `place_iron_condor()` tool method in `AlpacaOptionsToolkit`
- Get underlying price
- Use StrikeSelectionEngine to find OTM strikes at target delta
- Validate risk (max_loss <= max_risk_pct of buying power)
- Build 4-leg order using Alpaca's MLEG order class
- Submit order and return confirmation

**NOT in scope**: Position monitoring, P&L tracking.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/alpaca_options.py` | MODIFY | Add place_iron_condor method |

---

## Implementation Notes

### Key Constraints
- Short put strike selected at `-short_delta` (e.g., -0.30)
- Short call strike selected at `+short_delta` (e.g., +0.30)
- Wings at short_strike ± wing_width
- Max profit = net_credit
- Max loss = wing_width - net_credit (wider spread = more risk)
- Breakevens = [short_put + credit, short_call - credit]

### Delta Selection
- For puts: find strike where `abs(delta)` closest to `short_delta`
- For calls: find strike where `delta` closest to `short_delta`
- Default short_delta = 0.30 (30-delta)

---

## Acceptance Criteria

- [x] Uses delta-based strike selection for shorts
- [x] Validates OTM: short_put < underlying < short_call
- [x] Validates max_loss <= buying_power * max_risk_pct
- [x] Places 4-leg MLEG order via Alpaca
- [x] Returns order_id, max_profit, max_loss, breakevens
- [x] Handles errors gracefully
- [x] Works with paper trading account
- [x] Uses Limit Orders for multi-leg execution (Enhanced)
- [x] Correctly handles discrete strike intervals for risk (Enhanced)

---

## Completion Note

Implemented `place_iron_condor()` in `AlpacaOptionsToolkit`:

1. **PlaceIronCondorInput** Pydantic schema with:
   - short_delta (0.15-0.45, default 0.30)
   - expiration_days, wing_width, quantity, max_risk_pct

2. **Delta-based selection**: Uses `select_iron_condor_strikes()` with target delta
3. **OTM validation**: Ensures short_put < underlying < short_call
4. **Risk validation**: Checks max_loss against buying_power * max_risk_pct
5. **MLEG order**: 4-leg atomic order using Alpaca's OrderClass.MLEG

returns: order_id, strategy, strikes, net_credit, max_profit, max_loss,
breakevens, short_delta, quantity, underlying_price, paper mode flag.

---
**Verification (2026-03-05)**:
- Verified implementation in `parrot/finance/tools/alpaca_options.py`.
- Verified delta-based strike selection and MLEG order structure.
- Added and ran `test_place_iron_condor_success` in `tests/test_alpaca_options_toolkit.py` (passed).
- **Enhanced**: Switched to `LimitOrderRequest` for multi-leg orders to mitigate slippage.
- **Enhanced**: Fixed `max_loss` calculation to use actual selected strikes (discrete intervals) instead of requested wing width.
- Verified both Iron Condor and Iron Butterfly with updated tests.

