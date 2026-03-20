# Feature Specification: Multi-Executor Integration (Kraken + IBKR)

**Feature ID**: FEAT-026
**Date**: 2026-03-04
**Author**: Jesus Lara
**Status**: draft
**Target version**: next
**Depends on**: FEAT-007 (IBKR Toolkit), FEAT-022 (Paper Trading), FEAT-023 (Options Strategies)

---

## 1. Motivation & Business Requirements

### Problem Statement

The `ExecutionOrchestrator` currently registers only **two** executors:
- `stock_executor` → Alpaca (stocks, ETFs)
- `crypto_executor` → Binance (crypto)

However, the codebase already contains:
- **Kraken**: Full executor agent definition (`create_crypto_executor_kraken()` in `executors.py`) and write toolkit (`KrakenWriteToolkit` in `kraken_write.py` — spot + futures, 484 lines). **Not registered** in the orchestrator.
- **IBKR**: Complete write toolkit (`IBKRWriteToolkit` in `ibkr_write.py` — TWS bridge, limit/stop/bracket orders, positions, account summary, DRY_RUN support, 706 lines). **No executor agent** exists.

The **Portfolio Manager** declares `platforms=[Alpaca, Binance, Kraken]` but:
- Has no IBKR platform access
- Tools are injected externally via `monitor_tools=[]` — if Kraken/IBKR tools aren't passed, the PM has no real access despite the declaration

### Gap Summary

| Component | Kraken | IBKR |
|---|---|---|
| `Platform` enum | ✅ `Platform.KRAKEN` | ✅ `Platform.IBKR` |
| Write toolkit | ✅ `KrakenWriteToolkit` | ✅ `IBKRWriteToolkit` |
| Executor agent definition | ✅ `create_crypto_executor_kraken()` | ❌ Missing |
| Registered in orchestrator | ❌ Not registered | ❌ Not registered |
| PM platform declaration | ✅ Declared | ❌ Not declared |
| PM tools wired | ❌ Not wired | ❌ Not wired |

### Goals

- Register the existing Kraken executor agent in `ExecutionOrchestrator`
- Create an IBKR executor agent with appropriate prompt and constraints
- Add IBKR to the Portfolio Manager's platform list
- Wire Kraken and IBKR tools into the orchestrator and PM
- Create the `EXECUTOR_IBKR` system prompt
- Add `create_ibkr_executor_profile()` to schemas

### Non-Goals (explicitly out of scope)
- Coinbase integration (no toolkit, no enum — separate feature)
- Bybit/Blockchain integration (enum-only, no toolkits)
- Changes to the Kraken or IBKR write toolkits themselves (already complete)
- Options pricing models or Greeks computation (covered by FEAT-023)

---

## 2. Architectural Design

### Overview

The changes add two new execution paths and introduce **configurable multi-routing** so that stock/ETF orders can be sent to multiple executors simultaneously.

```
ExecutionOrchestrator.configure()
  │
  ├── stock_executor (Alpaca)        ← existing (stocks, ETFs)
  ├── crypto_executor (Binance)      ← existing (crypto)
  ├── crypto_executor_kraken (NEW)   ← register existing agent (crypto)
  ├── ibkr_executor (NEW)            ← new agent (stocks, ETFs, options, futures)
  │
  └── portfolio_manager
        platforms: [Alpaca, Binance, Kraken, IBKR]  ← add IBKR
        tools: [alpaca_*, binance_*, kraken_*, ibkr_*]  ← wire all

OrderRouter (enhanced)
  │
  ├── RoutingMode.SINGLE     → pick first executor (current behavior)
  ├── RoutingMode.MULTI      → fan-out to ALL matching executors
  └── RoutingMode.CONFIGURED → per-asset-class routing mode map
```

#### Multi-Routing for Stocks

When `RoutingMode.MULTI` is active for `AssetClass.STOCK`, the `OrderRouter.route()` method returns **multiple routed copies** of the order — one per matching executor (Alpaca + IBKR). The `ExecutionOrchestrator.process_orders()` executes each copy independently.

This is configurable per asset class:
```python
router.set_routing_mode(AssetClass.STOCK, RoutingMode.MULTI)    # both execute
router.set_routing_mode(AssetClass.CRYPTO, RoutingMode.SINGLE)  # first match only
```

### Integration Points

| Existing Component | Change Type | Notes |
|---|---|---|
| `ExecutionOrchestrator.configure()` | modify | Register Kraken + IBKR executors |
| `ExecutionOrchestrator.__init__()` | modify | Accept `kraken_tools` and `ibkr_tools` params |
| `ExecutionOrchestrator.process_orders()` | modify | Handle multi-routed orders (list of copies) |
| `OrderRouter` | modify | Add `RoutingMode` enum, `set_routing_mode()`, `route()` returns list |
| `schemas.py` (AssetClass) | modify | Add `FUTURES = "futures"` to enum |
| `schemas.py` (Capability) | modify | Add `PLACE_ORDER_OPTIONS`, `PLACE_ORDER_FUTURES` |
| `prompts.py` | add | New `EXECUTOR_IBKR` prompt |
| `prompts.py` | modify | Add `ibkr_executor` to `MODEL_RECOMMENDATIONS` |
| `schemas.py` | add | New `create_ibkr_executor_profile()` factory |
| `monitoring.py` | modify | Add `Platform.IBKR` to PM platforms |
| `agents/executors.py` | add | New `create_ibkr_executor()` factory |

### Data Models

#### New Enum Values

```python
# schemas.py — AssetClass enum
class AssetClass(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    CRYPTO = "crypto"
    OPTIONS = "options"
    FUTURES = "futures"   # NEW — was missing
    FOREX = "forex"

# schemas.py — Capability enum (new entries)
class Capability(str, Enum):
    ...
    PLACE_ORDER_OPTIONS = "place_order_options"    # NEW
    PLACE_ORDER_FUTURES = "place_order_futures"    # NEW

# schemas.py — RoutingMode enum (NEW)
class RoutingMode(str, Enum):
    """How the OrderRouter dispatches orders to executors."""
    SINGLE = "single"          # First matching executor (default, backward compat)
    MULTI = "multi"            # Fan-out to ALL matching executors
```

#### IBKR Executor Profile

```python
def create_ibkr_executor_profile(
    agent_id: str = "ibkr_executor",
) -> AgentCapabilityProfile:
    """Multi-asset executor via IBKR TWS. Stocks, options, futures."""
    return AgentCapabilityProfile(
        agent_id=agent_id,
        role="ibkr_executor",
        capabilities={
            Capability.READ_MARKET_DATA,
            Capability.READ_PORTFOLIO,
            Capability.PLACE_ORDER_STOCK,     # STK, ETF
            Capability.PLACE_ORDER_OPTIONS,   # OPT
            Capability.PLACE_ORDER_FUTURES,   # FUT
            Capability.CANCEL_ORDER,
            Capability.SET_STOP_LOSS,
            Capability.SET_TAKE_PROFIT,
            Capability.CLOSE_POSITION,
            Capability.SEND_MESSAGE,
            Capability.WRITE_MEMORY,
        },
        platforms=[Platform.IBKR],
        asset_classes=[
            AssetClass.STOCK,
            AssetClass.ETF,
            AssetClass.OPTIONS,
            AssetClass.FUTURES,
        ],
        constraints=ExecutorConstraints(
            max_order_pct=5.0,
            max_order_value_usd=1000.0,
            allowed_order_types=["limit", "stop", "bracket"],
            max_daily_trades=10,
            max_daily_volume_usd=2000.0,
            max_positions=10,
            max_exposure_pct=70.0,
            max_asset_class_exposure_pct=40.0,
            min_consensus=ConsensusLevel.MAJORITY,
            max_daily_loss_pct=5.0,
            max_drawdown_pct=15.0,
        ),
    )
```

#### OrderRouter Enhancement

```python
class OrderRouter:
    def __init__(self):
        self._executor_profiles: dict[str, AgentCapabilityProfile] = {}
        self._routing_table: dict[AssetClass, list[str]] = {}
        # NEW: per-asset-class routing mode (default SINGLE for backward compat)
        self._routing_modes: dict[AssetClass, RoutingMode] = {}

    def set_routing_mode(self, asset_class: AssetClass, mode: RoutingMode) -> None:
        """Configure routing mode for an asset class."""
        self._routing_modes[asset_class] = mode

    def route(self, order: TradingOrder) -> list[TradingOrder]:
        """Route order. Returns list (1 for SINGLE, N for MULTI)."""
        executors = self._routing_table.get(order.asset_class, [])
        mode = self._routing_modes.get(order.asset_class, RoutingMode.SINGLE)

        if mode == RoutingMode.MULTI:
            # Clone order for each executor
            return [self._assign(order.copy(), eid) for eid in executors]
        else:
            # Backward compat: first match
            return [self._assign(order, executors[0])]
```

---

## 3. Module Breakdown

### Module 1: Schema Enhancements

- **Path**: `parrot/finance/schemas.py` (modify)
- **Responsibility**:
  - Add `FUTURES = "futures"` to `AssetClass` enum
  - Add `PLACE_ORDER_OPTIONS` and `PLACE_ORDER_FUTURES` to `Capability` enum
  - Add `RoutingMode` enum (`SINGLE`, `MULTI`)
  - Add `set_routing_mode()` and update `route()` signature to return `list[TradingOrder]` in `OrderRouter`
  - Add `create_ibkr_executor_profile()` factory
  - Add `Platform.IBKR` to `create_portfolio_manager_profile()` platforms
- **Depends on**: None

### Module 2: IBKR Executor Prompt

- **Path**: `parrot/finance/prompts.py` (modify)
- **Responsibility**: Add `EXECUTOR_IBKR` system prompt and `ibkr_executor` entry in `MODEL_RECOMMENDATIONS`. Prompt covers IBKR-specific tools: `place_limit_order`, `place_stop_order`, `place_bracket_order`, `cancel_order`, `get_positions`, `get_account_summary`, `request_market_data`
- **Pattern**: Follow `EXECUTOR_STOCK` structure, adapted for IBKR multi-asset (STK, OPT, FUT)
- **Depends on**: Module 1

### Module 3: IBKR Executor Agent Factory

- **Path**: `parrot/finance/agents/executors.py` (modify)
- **Responsibility**: Add `create_ibkr_executor()` function, add to `create_all_executors()`
- **Depends on**: Modules 1, 2

### Module 4: Orchestrator Multi-Executor Registration

- **Path**: `parrot/finance/execution.py` (modify)
- **Responsibility**:
  - Add `kraken_tools` and `ibkr_tools` parameters to `__init__()`
  - Register Kraken executor in `configure()` using existing `create_crypto_executor_profile(platform=Platform.KRAKEN)`
  - Register IBKR executor in `configure()` using new `create_ibkr_executor_profile()`
  - Update `process_orders()` to handle `route()` returning `list[TradingOrder]`
  - Configure default routing modes (MULTI for STOCK, SINGLE for CRYPTO)
  - Update docstring to list all 4 executors
- **Depends on**: Modules 1, 2, 3

### Module 5: Portfolio Manager Platform Update

- **Path**: `parrot/finance/agents/monitoring.py` (modify)
- **Responsibility**: Add `Platform.IBKR` to PM's platforms list
- **Depends on**: Module 1

### Module 6: Exports Update

- **Path**: `parrot/finance/agents/__init__.py` and `parrot/finance/__init__.py` (modify)
- **Responsibility**: Export `create_ibkr_executor`, `create_ibkr_executor_profile`, `RoutingMode`
- **Depends on**: Modules 1, 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_futures_asset_class_enum` | Module 1 | `AssetClass.FUTURES` exists with value `"futures"` |
| `test_options_futures_capabilities` | Module 1 | `PLACE_ORDER_OPTIONS` and `PLACE_ORDER_FUTURES` exist in Capability |
| `test_routing_mode_enum` | Module 1 | `RoutingMode.SINGLE` and `RoutingMode.MULTI` exist |
| `test_router_single_mode` | Module 1 | SINGLE mode returns list with 1 routed order (backward compat) |
| `test_router_multi_mode` | Module 1 | MULTI mode returns N routed orders (one per executor) |
| `test_router_multi_clones_order` | Module 1 | Each routed copy has distinct `assigned_executor` |
| `test_ibkr_executor_profile_constraints` | Module 1 | Verify profile has correct platforms, asset_classes, and constraints |
| `test_ibkr_executor_profile_capabilities` | Module 1 | IBKR capabilities include PLACE_ORDER_STOCK, OPTIONS, FUTURES |
| `test_ibkr_executor_profile_asset_classes` | Module 1 | IBKR profile covers STOCK, ETF, OPTIONS, FUTURES |
| `test_create_ibkr_executor_agent` | Module 3 | Verify agent has correct name, agent_id, prompt, use_tools=True |
| `test_create_all_executors_includes_ibkr` | Module 3 | `create_all_executors()` returns ibkr key |
| `test_pm_profile_includes_ibkr` | Module 5 | `create_portfolio_manager_profile().platforms` includes IBKR |
| `test_orchestrator_accepts_kraken_tools` | Module 4 | Constructor accepts `kraken_tools` param |
| `test_orchestrator_accepts_ibkr_tools` | Module 4 | Constructor accepts `ibkr_tools` param |
| `test_orchestrator_multi_route_stocks` | Module 4 | Stock order produces reports from both Alpaca and IBKR |

### Verification Commands

```bash
# Run all finance-related tests
cd /home/jesuslara/proyectos/navigator/ai-parrot
source .venv/bin/activate
pytest tests/ -k "executor or portfolio_manager or orchestrat" -v --no-header 2>&1 | head -80

# Run import check (no runtime errors)
python -c "from parrot.finance.agents.executors import create_ibkr_executor, create_all_executors; print('OK:', list(create_all_executors().keys()))"
python -c "from parrot.finance.schemas import create_ibkr_executor_profile; p = create_ibkr_executor_profile(); print('IBKR profile:', p.platforms, p.asset_classes)"
python -c "from parrot.finance.schemas import create_portfolio_manager_profile; p = create_portfolio_manager_profile(); print('PM platforms:', p.platforms)"
```

### Manual Verification
- Reviewer should confirm `EXECUTOR_IBKR` prompt is consistent with `EXECUTOR_STOCK` / `EXECUTOR_CRYPTO` in structure and safety constraints

---

## 5. Acceptance Criteria

- [ ] `AssetClass.FUTURES` exists in enum
- [ ] `Capability.PLACE_ORDER_OPTIONS` and `PLACE_ORDER_FUTURES` exist in enum
- [ ] `RoutingMode` enum exists with `SINGLE` and `MULTI` values
- [ ] `OrderRouter.route()` returns `list[TradingOrder]`
- [ ] `OrderRouter.set_routing_mode()` allows per-asset-class multi-routing
- [ ] Multi-routing for STOCK sends order to both Alpaca and IBKR executors
- [ ] `EXECUTOR_IBKR` prompt exists in `prompts.py` with tool instructions for IBKR (STK, OPT, FUT)
- [ ] `ibkr_executor` entry exists in `MODEL_RECOMMENDATIONS`
- [ ] `create_ibkr_executor_profile()` exists in `schemas.py` with OPTIONS + FUTURES asset classes
- [ ] `create_ibkr_executor()` exists in `executors.py`
- [ ] `create_all_executors()` includes `ibkr` key
- [ ] `ExecutionOrchestrator.__init__()` accepts `kraken_tools` and `ibkr_tools`
- [ ] `ExecutionOrchestrator.configure()` registers 4 executors: stock, crypto(binance), crypto(kraken), ibkr
- [ ] `ExecutionOrchestrator.process_orders()` handles multi-routed order lists
- [ ] Portfolio Manager declares `platforms=[Alpaca, Binance, Kraken, IBKR]`
- [ ] All imports resolve without errors
- [ ] Existing tests continue to pass

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- `EXECUTOR_IBKR` follows same XML-tagged structure as `EXECUTOR_STOCK`
- IBKR executor uses `EXECUTOR_IBKR` prompt (not `EXECUTOR_STOCK`) because IBKR tools differ from Alpaca tools
- Kraken executor reuses existing `EXECUTOR_CRYPTO` prompt (already done in `executors.py`)
- `OrderRouter` auto-discovers executors via `register_executor(profile)` — no router changes needed

### Known Risks / Gotchas
- **Multi-routing cost**: MULTI mode for stocks means each stock order produces TWO executions (Alpaca + IBKR). Capital allocation per order should account for this — the same 5% allocation gets split or duplicated across platforms
- **OrderRouter signature change**: `route()` now returns `list[TradingOrder]` instead of a single order. All callers (`process_orders`) must be updated. This is a **breaking change** within the module
- **IBKR options**: The `IBKRWriteToolkit` currently supports STK orders (limit, stop, bracket). Options and futures order placement may require additional tool methods (e.g., `place_options_order`) in a follow-up to `ibkr_write.py` if the current `sec_type` parameter doesn't suffice
- **Monitor tools accumulation**: PM receives tools from all platforms via `monitor_tools`. Callers must pass the union of all platform read tools

---

## 7. Open Questions

- [x] Should OrderRouter have platform affinity (prefer Alpaca for stocks, IBKR as fallback)? — *Answer: No. Use configurable `RoutingMode.MULTI` to send to BOTH simultaneously*
- [x] Should IBKR executor support options/futures asset classes initially, or add later? — *Answer: Include in this iteration*
- [ ] Should multi-routed stock orders split the position size (2.5% each) or duplicate it (5% each)? — *Owner: TBD*: duplicate it.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-04 | Jesus Lara | Initial draft |
| 0.2 | 2026-03-04 | Jesus Lara | Add multi-routing, IBKR options/futures, FUTURES enum |
