# TASK-134: IBKR Paper Trading Enhancement

**Feature**: Finance Paper Trading Executors (FEAT-022)
**Spec**: `sdd/specs/finance-paper-trading.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-129, TASK-131
**Assigned-to**: unassigned

---

## Context

> Enhances IBKRWriteToolkit with paper/live port validation.
> IBKR uses different ports for paper (7497) vs live (7496) trading.
> Implements Spec Module 6.

---

## Scope

- Add `PaperTradingMixin` to `IBKRWriteToolkit` inheritance
- Add `mode: ExecutionMode` parameter to `__init__()`, defaulting to PAPER
- Define class constants `PAPER_PORT = 7497`, `LIVE_PORT = 7496`
- Implement `validate_port_matches_mode()` method
- Auto-select port based on mode if not explicitly configured
- Add `execution_mode` field to all order response dicts
- When `mode=DRY_RUN`, bypass TWS connection and delegate to VirtualPortfolio

**NOT in scope**: TWS connection logic changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/ibkr_write.py` | MODIFY | Add mixin and port validation |

---

## Implementation Notes

### Key Constraints
- Port validation: PAPER mode + port 7496 should raise warning/error
- LIVE mode + port 7497 should also raise warning/error
- TWS must be running with correct account type for mode to match
- `validate_port_matches_mode()` called on first connection attempt

### References in Codebase
- Current implementation at `parrot/finance/tools/ibkr_write.py`
- `_ensure_connected()` method for lazy connection
- Port config via `IBKR_PORT` env var

---

## Acceptance Criteria

- [x] `IBKRWriteToolkit` inherits from `PaperTradingMixin`
- [x] Constructor accepts `mode: ExecutionMode` parameter (default PAPER)
- [x] PAPER mode defaults to port 7497
- [x] LIVE mode defaults to port 7496
- [x] `validate_port_matches_mode()` raises on mode/port mismatch
- [x] Order responses include `execution_mode` and `is_simulated` fields
- [x] LIVE mode blocked in dev environment (via PaperTradingMixin.validate_execution_mode())
- [x] DRY_RUN mode uses VirtualPortfolio instead of TWS

---

## Completion Note

**Completed**: 2026-03-04

### Changes Made

1. Added `PaperTradingMixin` inheritance to `IBKRWriteToolkit`
2. Added class constants `PAPER_PORT = 7497`, `LIVE_PORT = 7496`
3. Updated constructor with `mode: ExecutionMode` and `virtual_portfolio: VirtualPortfolio` parameters
4. Auto-selects port based on mode when not explicitly configured
5. Added `validate_port_matches_mode()` method that raises `IBKRWriteError` on mismatch
6. Validation is called on first connection attempt in `_ensure_connected()`
7. All order methods (`place_limit_order`, `place_stop_order`, `place_bracket_order`, `cancel_order`) route to VirtualPortfolio in DRY_RUN mode
8. All responses include `execution_mode` and `is_simulated` fields
9. Query methods (`get_positions`, `get_account_summary`, `request_market_data`) also support DRY_RUN mode

### Testing

- Basic initialization tests pass for PAPER, DRY_RUN, and LIVE modes
- Port validation correctly raises errors on mode/port mismatch
- DRY_RUN orders execute via VirtualPortfolio and return correct fill data
- Linting passes (ruff check)
