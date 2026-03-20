# TASK-129: Core Data Models

**Feature**: Finance Paper Trading Executors (FEAT-022)
**Spec**: `sdd/specs/finance-paper-trading.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Foundation task. Defines all Pydantic models for paper-trading mode configuration,
> simulated orders, positions, and fills. These models are used by all other modules.
> Implements Spec Section 2 (Data Models) and Module 1.

---

## Scope

- Create `parrot/finance/paper_trading/` package directory
- Implement `ExecutionMode` enum with values: `LIVE`, `PAPER`, `DRY_RUN`
- Implement `PaperTradingConfig` model with mode, slippage simulation, fill delay, and dev safety
- Implement `SimulatedPosition` model with symbol, platform, side, quantity, prices, PnL
- Implement `SimulatedOrder` model with full order lifecycle fields
- Implement `SimulatedFill` model for fill records
- Implement `VirtualPortfolioState` model as complete portfolio snapshot

**NOT in scope**: Implementation logic (just data models).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/paper_trading/__init__.py` | CREATE | Package init (empty for now) |
| `parrot/finance/paper_trading/models.py` | CREATE | All Pydantic models |

---

## Implementation Notes

### Key Constraints
- Use `Decimal` for all monetary values (not `float`)
- All timestamps should use `datetime` with timezone awareness
- Models must be JSON-serializable for logging/audit
- Follow existing Pydantic patterns in `parrot/finance/schemas.py`

### References in Codebase
- `parrot/finance/schemas.py` — existing finance models (TradingOrder, Position, etc.)
- `parrot/finance/execution.py` — ExecutionReportOutput pattern

---

## Acceptance Criteria

- [x] `ExecutionMode` enum with LIVE, PAPER, DRY_RUN values
- [x] `PaperTradingConfig` validates constraints (slippage 0-100bps, delay 0-5000ms)
- [x] `SimulatedOrder` supports all order types: limit, market, stop, stop_limit
- [x] All models are importable from `parrot.finance.paper_trading.models`
- [x] Models serialize to JSON without errors

---

## Completion Note

**Implemented**:
- Created `parrot/finance/paper_trading/` package
- `ExecutionMode` enum with LIVE, PAPER, DRY_RUN values
- `PaperTradingConfig` with validation: slippage 0-100bps, delay 0-5000ms
- `SimulatedPosition` with P&L calculation methods
- `SimulatedOrder` with fill logic, slippage support, and order type validation
- `SimulatedFill` for execution records
- `VirtualPortfolioState` with equity and P&L properties
- `SimulationDetails` for execution report metadata
- All models use `Decimal` for monetary values and timezone-aware `datetime`
- JSON serialization via Pydantic `model_dump_json()`
