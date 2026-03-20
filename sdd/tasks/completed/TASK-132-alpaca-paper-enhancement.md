# TASK-132: Alpaca Paper Trading Enhancement

**Feature**: Finance Paper Trading Executors (FEAT-022)
**Spec**: `sdd/specs/finance-paper-trading.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-129, TASK-131
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Enhances AlpacaWriteToolkit with explicit paper-trading mode awareness.
> Alpaca has native paper trading via account type (paper=True).
> Implements Spec Module 4.

---

## Scope

- Add `PaperTradingMixin` to `AlpacaWriteToolkit` inheritance
- Add `mode: ExecutionMode` parameter to `__init__()`, defaulting to PAPER
- Implement `ensure_paper_mode()` async method that verifies account is paper
- Add `execution_mode` field to all order response dicts
- Call `validate_execution_mode()` in constructor
- When `mode=DRY_RUN`, bypass API and delegate to VirtualPortfolio

**NOT in scope**: Changing existing order placement logic (just wrapping).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/alpaca_write.py` | MODIFY | Add mixin and mode handling |

---

## Implementation Notes

### Key Constraints
- `paper` flag in TradingClient controls paper vs live
- `ensure_paper_mode()` should call `get_account()` and check account type
- Existing tests must continue to pass
- Add `is_simulated: bool` to response dicts based on mode

### References in Codebase
- Current implementation at `parrot/finance/tools/alpaca_write.py`
- Alpaca TradingClient paper mode: `TradingClient(api_key, secret, paper=True)`

---

## Acceptance Criteria

- [x] `AlpacaWriteToolkit` inherits from `PaperTradingMixin`
- [x] Constructor accepts `mode: ExecutionMode` parameter (default PAPER)
- [x] `ensure_paper_mode()` verifies paper account connection
- [x] Order responses include `execution_mode` and `is_simulated` fields
- [x] LIVE mode blocked in dev environment
- [x] DRY_RUN mode uses VirtualPortfolio instead of API
- [x] Existing unit tests still pass

---

## Completion Note

**Implemented**:
- Added `PaperTradingMixin` to `AlpacaWriteToolkit` inheritance chain
- Added `mode: ExecutionMode` and `virtual_portfolio: VirtualPortfolio` parameters to constructor
- Called `_init_paper_trading(mode)` in constructor for mode validation
- Auto-creates VirtualPortfolio when DRY_RUN mode is requested
- Implemented `ensure_paper_mode()` to verify paper account type
- Added `_add_mode_fields()` helper to inject execution_mode and is_simulated to responses
- Implemented `_dry_run_order()` for routing orders to VirtualPortfolio
- Updated all order methods (limit, stop, stop-limit, trailing-stop, bracket) with DRY_RUN routing
- Updated cancel_order, cancel_all_orders, replace_order with DRY_RUN handling
- Updated close_position, close_all_positions with DRY_RUN handling
- All responses include `execution_mode` and `is_simulated` fields

**File Modified**:
- `parrot/finance/tools/alpaca_write.py`
