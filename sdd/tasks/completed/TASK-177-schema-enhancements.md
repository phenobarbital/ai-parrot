# TASK-177: Schema Enhancements (RoutingMode, FUTURES, Capabilities, IBKR Profile)

**Feature**: Multi-Executor Integration (FEAT-026)
**Spec**: `sdd/specs/finance-multi-executor-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Foundation task for multi-executor integration. Adds missing enum values,
> the RoutingMode enum, OrderRouter multi-routing logic, and the IBKR executor
> capability profile. All other tasks in FEAT-026 depend on this.

---

## Scope

- Add `FUTURES = "futures"` to `AssetClass` enum (if missing)
- Add `PLACE_ORDER_OPTIONS = "place_order_options"` and `PLACE_ORDER_FUTURES = "place_order_futures"` to `Capability` enum
- Add `RoutingMode` enum (`SINGLE`, `MULTI`)
- Add `set_routing_mode(asset_class, mode)` method to `OrderRouter`
- Update `OrderRouter.route()` to return `list[TradingOrder]` instead of single order
- Add `create_ibkr_executor_profile()` factory function
- Add `Platform.IBKR` to `create_portfolio_manager_profile()` platforms list

**NOT in scope**: Prompt creation, executor agent factory, orchestrator changes, exports.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/schemas.py` | MODIFY | Add FUTURES, new Capabilities, RoutingMode, update OrderRouter, add IBKR profile factory |

---

## Implementation Notes

### RoutingMode Enum
```python
class RoutingMode(str, Enum):
    """How the OrderRouter dispatches orders to executors."""
    SINGLE = "single"
    MULTI = "multi"
```

### OrderRouter Changes
- Add `_routing_modes: dict[AssetClass, RoutingMode]` to `__init__`
- Add `set_routing_mode()` method
- Update `route()` to return `list[TradingOrder]`:
  - `SINGLE` mode: return `[order]` with first matching executor (backward compat)
  - `MULTI` mode: clone order for each matching executor

### IBKR Profile
- Follow `create_crypto_executor_profile()` pattern
- Platforms: `[Platform.IBKR]`
- Asset classes: `[STOCK, ETF, OPTIONS, FUTURES]`
- Capabilities: `READ_MARKET_DATA`, `READ_PORTFOLIO`, `PLACE_ORDER_STOCK`, `PLACE_ORDER_OPTIONS`, `PLACE_ORDER_FUTURES`, `CANCEL_ORDER`, `SET_STOP_LOSS`, `SET_TAKE_PROFIT`, `CLOSE_POSITION`, `SEND_MESSAGE`, `WRITE_MEMORY`
- Constraints: `max_order_pct=5.0`, `max_order_value_usd=1000.0`, `allowed_order_types=["limit", "stop", "bracket"]`, etc.

---

## Acceptance Criteria

- [ ] `AssetClass.FUTURES` exists with value `"futures"`
- [ ] `Capability.PLACE_ORDER_OPTIONS` and `PLACE_ORDER_FUTURES` exist
- [ ] `RoutingMode` enum exists with `SINGLE` and `MULTI`
- [ ] `OrderRouter.route()` returns `list[TradingOrder]`
- [ ] `OrderRouter.set_routing_mode()` exists and configures per-asset-class routing
- [ ] `create_ibkr_executor_profile()` returns valid profile with correct platforms, asset_classes, capabilities
- [ ] PM profile includes `Platform.IBKR` in platforms
- [ ] Ruff check passes

---

## Agent Instructions

1. Read the spec at `sdd/specs/finance-multi-executor-integration.spec.md` (Sections 2–3)
2. Open `parrot/finance/schemas.py` and locate existing enums and OrderRouter
3. Add enum values, RoutingMode, update OrderRouter, add IBKR profile factory
4. Run `ruff check parrot/finance/schemas.py`
5. Run: `python -c "from parrot.finance.schemas import RoutingMode, create_ibkr_executor_profile; p = create_ibkr_executor_profile(); print('OK:', p.platforms, p.asset_classes)"`
