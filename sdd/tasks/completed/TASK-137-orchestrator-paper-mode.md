# TASK-137: Orchestrator Paper Mode

**Feature**: Finance Paper Trading Executors (FEAT-022)
**Spec**: `sdd/specs/finance-paper-trading.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-129, TASK-130, TASK-136
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Extends ExecutionOrchestrator to accept PaperTradingConfig and route orders accordingly.
> Provides DRY_RUN fallback using VirtualPortfolio when toolkits don't support native paper mode.
> Implements Spec Module 9.

---

## Scope

- Add `paper_config: PaperTradingConfig | None` parameter to `ExecutionOrchestrator.__init__()`
- Pass execution mode to toolkit initialization
- In DRY_RUN mode, create shared `VirtualPortfolio` instance
- Route orders to VirtualPortfolio when mode is DRY_RUN
- Populate `is_simulated` and `execution_mode` in ExecutionReportOutput
- Add logging for mode transitions and simulated executions

**NOT in scope**: Changing existing order routing logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/execution.py` | MODIFY | Add paper_config to orchestrator |

---

## Implementation Notes

### Key Constraints
- VirtualPortfolio shared across all executors in DRY_RUN mode
- Price updates for limit order fills need integration with read toolkits
- Audit logging for mode should include timestamp and order details
- `run_trading_pipeline()` should accept `paper_config` parameter

### References in Codebase
- `parrot/finance/execution.py` — ExecutionOrchestrator class
- `run_trading_pipeline()` function at end of file

---

## Acceptance Criteria

- [x] `ExecutionOrchestrator` accepts `paper_config` parameter
- [x] DRY_RUN mode creates VirtualPortfolio instance
- [x] Orders routed to VirtualPortfolio in DRY_RUN mode
- [x] ExecutionReportOutput populated with `is_simulated=True` for paper/dry_run
- [x] `run_trading_pipeline()` accepts and passes through `paper_config`
- [x] Logging indicates execution mode for each order
- [x] Existing tests still pass

---

## Completion Note

**Implemented**:
- Added `paper_config: PaperTradingConfig | None` parameter to `ExecutionOrchestrator.__init__()`
- Added `_paper_config` and `_virtual_portfolio` instance variables
- Added `execution_mode` and `is_simulated` properties
- Created `VirtualPortfolio` instance when mode is `DRY_RUN`
- Added `_execute_order_dry_run()` method to handle orders via VirtualPortfolio
- Updated `_build_error_report()` and `_build_rejected_report()` to include simulation fields
- Added `paper_config` parameter to `run_trading_pipeline()` function
- Added execution mode logging in `configure()` method
- Added execution mode info to pipeline result dict

**File Modified**:
- `parrot/finance/execution.py` — added paper_config support to orchestrator
