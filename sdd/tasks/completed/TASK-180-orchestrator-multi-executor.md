# TASK-180: Orchestrator Multi-Executor Registration

**Feature**: Multi-Executor Integration (FEAT-026)
**Spec**: `sdd/specs/finance-multi-executor-integration.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-177, TASK-178, TASK-179
**Assigned-to**: claude-session
**Completed**: 2026-03-05

---

## Context

> Register Kraken and IBKR executors in `ExecutionOrchestrator`, accept new
> tool parameters, and update `process_orders()` to handle multi-routed
> order lists from `OrderRouter.route()`.

---

## Scope

- Add `kraken_tools` and `ibkr_tools` parameters to `ExecutionOrchestrator.__init__()`
- Register Kraken executor in `configure()` using existing `create_crypto_executor_kraken()`
- Register IBKR executor in `configure()` using `create_ibkr_executor()`
- Update `process_orders()` to handle `route()` returning `list[TradingOrder]`
- Configure default routing modes: `MULTI` for `STOCK`, `SINGLE` for `CRYPTO`
- Update class docstring to list all 4 executors

**NOT in scope**: Schema changes, prompt creation, agent factory, toolkit modifications.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/execution.py` | MODIFY | Register Kraken + IBKR, handle multi-routing |

---

## Implementation Notes

### Breaking Change: `route()` Return Type
`OrderRouter.route()` now returns `list[TradingOrder]` instead of a single order.
All callers in `process_orders()` must iterate over the list.

### Default Routing
```python
router.set_routing_mode(AssetClass.STOCK, RoutingMode.MULTI)
router.set_routing_mode(AssetClass.CRYPTO, RoutingMode.SINGLE)
```

### Executor Registration Pattern
Follow existing `stock_executor` and `crypto_executor` registration:
```python
agents["crypto_executor_kraken"] = create_crypto_executor_kraken(tools=self._kraken_tools)
agents["ibkr_executor"] = create_ibkr_executor(tools=self._ibkr_tools)
```

---

## Acceptance Criteria

- [x] `__init__()` accepts `kraken_tools` and `ibkr_tools` params
- [x] `configure()` registers 4 executors: stock, crypto(binance), crypto(kraken), ibkr
- [x] `process_orders()` handles multi-routed order lists
- [x] Default routing: MULTI for STOCK, SINGLE for CRYPTO
- [x] Ruff check passes (only pre-existing E402 unrelated to this task)

---

## Agent Instructions

1. Read `parrot/finance/execution.py` fully — understand `configure()` and `process_orders()`
2. Add constructor params for `kraken_tools` and `ibkr_tools`
3. Register both new executors in `configure()`
4. Update `process_orders()` to iterate over `route()` results
5. Set default routing modes
6. Run `ruff check parrot/finance/execution.py`

---

## Completion Note

**Completed**: 2026-03-05
**Implemented by**: claude-session

### Summary

Registered Kraken and IBKR executors in `ExecutionOrchestrator` for multi-platform trading:

### Changes to `parrot/finance/execution.py`

1. **Imports**: Added `AssetClass`, `Platform`, `RoutingMode`, `create_ibkr_executor_profile`, `EXECUTOR_IBKR`

2. **`__init__()`**: Added `kraken_tools` and `ibkr_tools` parameters with storage

3. **`configure()`**: Registers 4 executors now:
   - Stock Executor (Alpaca)
   - Crypto Executor (Binance)
   - Crypto Executor (Kraken) - NEW
   - IBKR Executor - NEW

4. **Default routing modes**:
   - `STOCK`: `RoutingMode.MULTI` (orders go to both Alpaca and IBKR)
   - `CRYPTO`: `RoutingMode.SINGLE` (orders go to one exchange only)

5. **`process_orders()`**: Updated to iterate over `route()` list:
   ```python
   routed_orders = self._router.route(order)
   for routed_order in routed_orders:
       # execute each routed order
   ```

6. **Docstring**: Updated to list all 4 executors and routing modes

### Verification

```bash
ruff check parrot/finance/execution.py
# 1 error: E402 (pre-existing, unrelated to this task)
```
