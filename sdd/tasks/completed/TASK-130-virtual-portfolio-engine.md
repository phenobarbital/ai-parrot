# TASK-130: Virtual Portfolio Engine

**Feature**: Finance Paper Trading Executors (FEAT-022)
**Spec**: `sdd/specs/finance-paper-trading.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-6h)
**Depends-on**: TASK-129
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Core simulation engine. Implements local order execution simulation for DRY_RUN mode.
> Tracks virtual positions, generates simulated fills, and calculates P&L.
> Implements Spec Module 2.

---

## Scope

- Implement `VirtualPortfolio` class with:
  - `place_order(order: SimulatedOrder)` — submit order to virtual portfolio
  - `cancel_order(order_id: str)` — cancel pending order
  - `get_positions()` / `get_position(symbol)` — read positions
  - `get_open_orders()` — read pending orders
  - `get_fills(since: datetime)` — read fill history
  - `update_prices(prices: dict)` — update prices and trigger limit fills
  - `get_state()` — full portfolio snapshot
  - `reset()` — reset to initial state
- Market orders fill immediately at current price
- Limit orders fill when `update_prices()` crosses the limit
- Support configurable slippage simulation (basis points)
- Support configurable fill delay (milliseconds)

**NOT in scope**: Persistence (ephemeral state only), partial fills.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/paper_trading/portfolio.py` | CREATE | VirtualPortfolio class |

---

## Implementation Notes

### Key Constraints
- Thread-safe for concurrent order placement (use asyncio locks)
- Cash balance tracking: deduct on buy, add on sell
- Position averaging: FIFO or average cost basis
- Fill delay can use `asyncio.sleep()` if non-zero

### References in Codebase
- `parrot/finance/schemas.py` — PortfolioSnapshot for reference structure
- `parrot/finance/execution.py` — ExecutionDetails for fill structure

---

## Acceptance Criteria

- [x] `place_order()` accepts SimulatedOrder and tracks in pending/filled
- [x] Market orders fill immediately with slippage applied
- [x] Limit orders fill when price update crosses limit
- [x] `cancel_order()` removes pending order and returns True/False
- [x] `get_positions()` returns list of SimulatedPosition
- [x] `get_state()` returns complete VirtualPortfolioState
- [x] Cash balance correctly updated on fills
- [x] Slippage simulation applies correct basis points to fill price

---

## Completion Note

**Implemented**:
- `VirtualPortfolio` class with full order management lifecycle
- Market order immediate fill with slippage
- Limit/stop order pending queue with fill on price cross
- Position tracking with average cost basis
- Cash balance tracking (deduct on buy, add on sell)
- Asyncio lock for thread-safety
- Configurable slippage (0-100 bps) and fill delay (0-5000ms)
- Complete state snapshot via `get_state()`
- Fill history with `get_fills(since=datetime)`
- Reset to initial state

**File Created**:
- `parrot/finance/paper_trading/portfolio.py`
