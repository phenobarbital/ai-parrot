# Feature Specification: Finance Paper Trading Executors

**Feature ID**: FEAT-022
**Date**: 2026-03-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

AI-Parrot's finance module has a working research and deliberation pipeline that produces
`InvestmentMemo` recommendations. The `ExecutionOrchestrator` routes these to executor agents
that use platform-specific toolkits (`AlpacaWriteToolkit`, `BinanceWriteToolkit`, `IBKRWriteToolkit`,
`KrakenWriteToolkit`). However, the current implementation lacks a **unified paper-trading layer**
that:

1. **Simulates execution** without touching real funds (dry-run mode)
2. **Tracks virtual positions** for backtesting and strategy validation
3. **Standardizes testnet behavior** across all four platforms
4. **Provides execution analytics** (slippage simulation, fill latency)

Users need the ability to safely validate trading strategies before deploying with real capital.
Each platform has different paper-trading capabilities:
- **Alpaca**: Native paper trading account (port-based)
- **Binance**: Testnet environment (separate endpoints)
- **IBKR**: Paper trading account via TWS (port 7497 vs 7496)
- **Kraken**: `validate` flag for spot orders, demo environment for futures

### Goals

- Unified `PaperTradingMode` configuration that applies to all executors
- Each toolkit exposes a consistent `dry_run` / `paper_trading` interface
- Virtual position tracking when platform doesn't provide native paper trading
- Execution reports distinguish between real and simulated fills
- Safe defaults: paper trading enabled by default in development environments

### Non-Goals (explicitly out of scope)

- Full backtesting engine with historical data replay (separate feature)
- P&L attribution and performance reporting (separate feature)
- Multi-account management (paper + live simultaneously)
- Slippage modeling with order book depth analysis
- Latency simulation based on market microstructure

---

## 2. Architectural Design

### Overview

The paper-trading layer operates as a **mode switch** on existing toolkits. When enabled,
toolkits either:
1. Route to platform-native paper trading (Alpaca, IBKR, Binance testnet, Kraken demo)
2. Intercept orders and simulate execution locally (fallback for platforms without paper mode)

A `VirtualPortfolio` component tracks simulated positions when native paper trading isn't
available or when explicit local simulation is requested.

### Component Diagram

```
ExecutionOrchestrator
  │
  ├── ExecutorAgent (Stock)
  │       │
  │       └── AlpacaWriteToolkit
  │               │
  │               ├── [paper=True] → Alpaca Paper API (native)
  │               └── [paper=False] → Alpaca Live API
  │
  ├── ExecutorAgent (Crypto - Binance)
  │       │
  │       └── BinanceWriteToolkit
  │               │
  │               ├── [testnet=True] → Binance Testnet (native)
  │               └── [testnet=False] → Binance Production
  │
  ├── ExecutorAgent (Multi-Asset - IBKR)
  │       │
  │       └── IBKRWriteToolkit
  │               │
  │               ├── [port=7497] → TWS Paper Trading (native)
  │               └── [port=7496] → TWS Live Trading
  │
  ├── ExecutorAgent (Crypto - Kraken)
  │       │
  │       └── KrakenWriteToolkit
  │               │
  │               ├── [spot_validate=True] → Validate-only (dry-run)
  │               ├── [futures_demo=True] → Kraken Futures Demo (native)
  │               └── [Both=False] → Kraken Production
  │
  └── VirtualPortfolio (fallback simulator)
          │
          ├── SimulatedPositions
          ├── SimulatedOrders
          └── SimulatedFills
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AlpacaWriteToolkit` | modify | Add explicit `ensure_paper_mode()` check |
| `BinanceWriteToolkit` | modify | Consolidate testnet configuration |
| `IBKRWriteToolkit` | modify | Add port validation for paper vs live |
| `KrakenWriteToolkit` | modify | Unify `spot_validate` + `futures_demo` into single config |
| `ExecutionOrchestrator` | extend | Add paper-trading mode flag and reporting |
| `ExecutionReportOutput` | extend | Add `is_simulated: bool` field |
| `TradingOrder` | extend | Add `execution_mode: Literal["live", "paper", "dry_run"]` |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from decimal import Decimal
from enum import Enum

class ExecutionMode(str, Enum):
    """Execution environment mode."""
    LIVE = "live"           # Real trading with real funds
    PAPER = "paper"         # Platform-native paper trading (Alpaca, IBKR, Binance testnet)
    DRY_RUN = "dry_run"     # Local simulation only (no API calls for orders)


class PaperTradingConfig(BaseModel):
    """Global paper-trading configuration."""
    mode: ExecutionMode = Field(
        ExecutionMode.PAPER,
        description="Execution mode for all toolkits",
    )
    simulate_slippage_bps: int = Field(
        0,
        description="Basis points of slippage to simulate (0 = no simulation)",
        ge=0,
        le=100,
    )
    simulate_fill_delay_ms: int = Field(
        0,
        description="Milliseconds of fill delay to simulate (0 = instant)",
        ge=0,
        le=5000,
    )
    fail_on_live_in_dev: bool = Field(
        True,
        description="Raise error if mode=LIVE in development environment",
    )


class SimulatedPosition(BaseModel):
    """Virtual position tracked in dry-run mode."""
    symbol: str
    platform: str
    side: Literal["long", "short"]
    quantity: Decimal
    avg_entry_price: Decimal
    current_price: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None
    opened_at: datetime
    last_updated: datetime


class SimulatedOrder(BaseModel):
    """Virtual order in dry-run mode."""
    order_id: str  # UUID generated locally
    symbol: str
    platform: str
    side: Literal["buy", "sell"]
    order_type: Literal["limit", "market", "stop", "stop_limit"]
    quantity: Decimal
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    status: Literal["pending", "filled", "cancelled", "rejected"]
    filled_quantity: Decimal = Decimal("0")
    filled_price: Optional[Decimal] = None
    created_at: datetime
    filled_at: Optional[datetime] = None


class SimulatedFill(BaseModel):
    """Fill record for a simulated order."""
    fill_id: str
    order_id: str
    symbol: str
    platform: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    slippage_bps: int = 0
    timestamp: datetime


class VirtualPortfolioState(BaseModel):
    """Snapshot of the virtual portfolio."""
    cash_balance: Decimal = Field(default=Decimal("100000"))  # Default paper balance
    positions: list[SimulatedPosition] = Field(default_factory=list)
    pending_orders: list[SimulatedOrder] = Field(default_factory=list)
    filled_orders: list[SimulatedOrder] = Field(default_factory=list)
    fills: list[SimulatedFill] = Field(default_factory=list)
    last_updated: datetime = Field(default_factory=datetime.utcnow)
```

### New Public Interfaces

```python
class VirtualPortfolio:
    """Local simulation engine for dry-run mode."""

    def __init__(
        self,
        initial_cash: Decimal = Decimal("100000"),
        slippage_bps: int = 0,
        fill_delay_ms: int = 0,
    ):
        ...

    def place_order(self, order: SimulatedOrder) -> SimulatedOrder:
        """Submit an order to the virtual portfolio."""

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""

    def get_positions(self) -> list[SimulatedPosition]:
        """Get all current positions."""

    def get_position(self, symbol: str) -> SimulatedPosition | None:
        """Get position for a specific symbol."""

    def get_open_orders(self) -> list[SimulatedOrder]:
        """Get all pending orders."""

    def get_fills(self, since: datetime | None = None) -> list[SimulatedFill]:
        """Get fill history."""

    def update_prices(self, prices: dict[str, Decimal]) -> None:
        """Update current prices and trigger limit order fills."""

    def get_state(self) -> VirtualPortfolioState:
        """Get complete portfolio snapshot."""

    def reset(self) -> None:
        """Reset portfolio to initial state."""


class PaperTradingMixin:
    """Mixin for toolkits to add paper-trading awareness."""

    @property
    def execution_mode(self) -> ExecutionMode:
        """Return current execution mode."""

    @property
    def is_paper_trading(self) -> bool:
        """True if in paper or dry-run mode."""

    def validate_execution_mode(self) -> None:
        """Raise error if LIVE mode in dev environment."""


# Extended toolkit interfaces
class AlpacaWriteToolkit(AbstractToolkit, PaperTradingMixin):
    """Enhanced with explicit paper-trading mode."""

    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.PAPER,
        **kwargs
    ):
        ...

    async def ensure_paper_mode(self) -> None:
        """Verify connection is to paper account, raise if live."""


class BinanceWriteToolkit(AbstractToolkit, PaperTradingMixin):
    """Enhanced with unified testnet configuration."""

    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.PAPER,
        **kwargs
    ):
        ...


class IBKRWriteToolkit(AbstractToolkit, PaperTradingMixin):
    """Enhanced with paper/live port validation."""

    PAPER_PORT = 7497
    LIVE_PORT = 7496

    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.PAPER,
        **kwargs
    ):
        ...

    async def validate_port_matches_mode(self) -> None:
        """Verify TWS port matches expected mode."""


class KrakenWriteToolkit(AbstractToolkit, PaperTradingMixin):
    """Enhanced with unified validate/demo configuration."""

    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.PAPER,
        **kwargs
    ):
        ...
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

### Module 1: Core Data Models

- **Path**: `parrot/finance/paper_trading/models.py`
- **Responsibility**: `ExecutionMode`, `PaperTradingConfig`, `SimulatedPosition`, `SimulatedOrder`, `SimulatedFill`, `VirtualPortfolioState`
- **Depends on**: None

### Module 2: Virtual Portfolio Engine

- **Path**: `parrot/finance/paper_trading/portfolio.py`
- **Responsibility**: `VirtualPortfolio` class — local simulation of order execution, position tracking, and fill generation
- **Depends on**: Module 1

### Module 3: Paper Trading Mixin

- **Path**: `parrot/finance/paper_trading/mixin.py`
- **Responsibility**: `PaperTradingMixin` base class that provides `execution_mode`, `is_paper_trading`, and `validate_execution_mode` methods
- **Depends on**: Module 1

### Module 4: Alpaca Paper Trading Enhancement

- **Path**: `parrot/finance/tools/alpaca_write.py` (modify)
- **Responsibility**: Add `PaperTradingMixin`, add `ensure_paper_mode()` method, default to paper mode, add `execution_mode` to tool responses
- **Depends on**: Modules 1, 3

### Module 5: Binance Testnet Enhancement

- **Path**: `parrot/finance/tools/binance_write.py` (modify)
- **Responsibility**: Add `PaperTradingMixin`, consolidate testnet config, add `execution_mode` to tool responses
- **Depends on**: Modules 1, 3

### Module 6: IBKR Paper Trading Enhancement

- **Path**: `parrot/finance/tools/ibkr_write.py` (modify)
- **Responsibility**: Add `PaperTradingMixin`, add `validate_port_matches_mode()`, default to paper port
- **Depends on**: Modules 1, 3

### Module 7: Kraken Demo Mode Enhancement

- **Path**: `parrot/finance/tools/kraken_write.py` (modify)
- **Responsibility**: Add `PaperTradingMixin`, unify `spot_validate` + `futures_demo` into single `mode` config
- **Depends on**: Modules 1, 3

### Module 8: Execution Report Enhancement

- **Path**: `parrot/finance/execution.py` (modify)
- **Responsibility**: Add `is_simulated: bool` and `execution_mode: str` fields to `ExecutionReportOutput`
- **Depends on**: Module 1

### Module 9: Orchestrator Paper Mode

- **Path**: `parrot/finance/execution.py` (modify)
- **Responsibility**: Add `PaperTradingConfig` to `ExecutionOrchestrator`, validate mode before dispatch, add dry-run fallback
- **Depends on**: Modules 1, 2, 8

### Module 10: Package Init and Exports

- **Path**: `parrot/finance/paper_trading/__init__.py`
- **Responsibility**: Export all public interfaces
- **Depends on**: Modules 1, 2, 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_execution_mode_enum` | Module 1 | Verify ExecutionMode values and serialization |
| `test_paper_trading_config_defaults` | Module 1 | Verify default config is PAPER mode |
| `test_simulated_order_lifecycle` | Module 1 | Validate SimulatedOrder state transitions |
| `test_virtual_portfolio_place_order` | Module 2 | Place order and verify pending state |
| `test_virtual_portfolio_fill_market_order` | Module 2 | Market order fills immediately at current price |
| `test_virtual_portfolio_fill_limit_order` | Module 2 | Limit order fills when price crosses |
| `test_virtual_portfolio_slippage` | Module 2 | Slippage applied correctly to fills |
| `test_virtual_portfolio_position_tracking` | Module 2 | Positions updated after fills |
| `test_virtual_portfolio_pnl_calculation` | Module 2 | Unrealized P&L calculated correctly |
| `test_mixin_execution_mode_property` | Module 3 | Mixin returns correct mode |
| `test_mixin_is_paper_trading` | Module 3 | Returns True for PAPER and DRY_RUN |
| `test_mixin_validate_live_in_dev` | Module 3 | Raises error for LIVE in dev env |
| `test_alpaca_paper_mode_default` | Module 4 | Default mode is PAPER |
| `test_alpaca_ensure_paper_mode` | Module 4 | Method verifies paper account connection |
| `test_alpaca_response_includes_mode` | Module 4 | Order responses include execution_mode |
| `test_binance_testnet_default` | Module 5 | Default mode routes to testnet |
| `test_binance_response_includes_mode` | Module 5 | Order responses include execution_mode |
| `test_ibkr_paper_port_default` | Module 6 | Default port is 7497 (paper) |
| `test_ibkr_validate_port_matches_mode` | Module 6 | Raises if mode/port mismatch |
| `test_kraken_validate_default` | Module 7 | Default spot_validate is True |
| `test_kraken_demo_default` | Module 7 | Default futures_demo is True |
| `test_execution_report_simulated_field` | Module 8 | Report includes is_simulated |
| `test_orchestrator_paper_config` | Module 9 | Orchestrator accepts PaperTradingConfig |
| `test_orchestrator_dry_run_fallback` | Module 9 | DRY_RUN uses VirtualPortfolio |

### Integration Tests

| Test | Description |
|---|---|
| `test_alpaca_paper_order_e2e` | Place/fill/cancel order on Alpaca paper account |
| `test_binance_testnet_order_e2e` | Place/fill/cancel order on Binance testnet |
| `test_ibkr_paper_order_e2e` | Place/fill/cancel order on IBKR paper (requires TWS) |
| `test_kraken_validate_order_e2e` | Place validate-only order on Kraken |
| `test_dry_run_full_pipeline` | Run complete pipeline in DRY_RUN mode |
| `test_orchestrator_mixed_modes` | Different toolkits with different modes |

### Test Data / Fixtures

```python
import pytest
from decimal import Decimal
from parrot.finance.paper_trading.models import (
    ExecutionMode,
    PaperTradingConfig,
    SimulatedOrder,
)

@pytest.fixture
def paper_config():
    return PaperTradingConfig(
        mode=ExecutionMode.PAPER,
        simulate_slippage_bps=5,
        simulate_fill_delay_ms=100,
    )

@pytest.fixture
def dry_run_config():
    return PaperTradingConfig(
        mode=ExecutionMode.DRY_RUN,
        simulate_slippage_bps=10,
        simulate_fill_delay_ms=0,
    )

@pytest.fixture
def sample_buy_order():
    return SimulatedOrder(
        order_id="test-001",
        symbol="AAPL",
        platform="alpaca",
        side="buy",
        order_type="limit",
        quantity=Decimal("10"),
        limit_price=Decimal("150.00"),
        status="pending",
        created_at=datetime.utcnow(),
    )

@pytest.fixture
def sample_crypto_order():
    return SimulatedOrder(
        order_id="test-002",
        symbol="BTCUSDT",
        platform="binance",
        side="buy",
        order_type="limit",
        quantity=Decimal("0.1"),
        limit_price=Decimal("50000.00"),
        status="pending",
        created_at=datetime.utcnow(),
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All Pydantic data models defined in `paper_trading/models.py`
- [ ] `VirtualPortfolio` can place, fill, and cancel simulated orders
- [ ] `VirtualPortfolio` correctly tracks positions and calculates P&L
- [ ] `PaperTradingMixin` added to all four toolkits (Alpaca, Binance, IBKR, Kraken)
- [ ] `AlpacaWriteToolkit` defaults to paper mode and includes `ensure_paper_mode()`
- [ ] `BinanceWriteToolkit` defaults to testnet mode
- [ ] `IBKRWriteToolkit` defaults to paper port (7497) and validates port/mode match
- [ ] `KrakenWriteToolkit` defaults to validate=True and futures_demo=True
- [ ] `ExecutionReportOutput` includes `is_simulated` and `execution_mode` fields
- [ ] `ExecutionOrchestrator` accepts `PaperTradingConfig` and routes accordingly
- [ ] DRY_RUN mode bypasses all API calls and uses `VirtualPortfolio`
- [ ] All unit tests pass: `pytest tests/finance/test_paper_trading/ -v`
- [ ] Integration tests pass for each platform's paper/testnet environment
- [ ] No real orders placed when in PAPER or DRY_RUN mode
- [ ] Live mode blocked by default in non-production environments

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Use `AbstractToolkit` pattern from `parrot/tools/toolkit.py`
- See existing `*_write.py` toolkits for decorator patterns
- Pydantic models for all structured data
- Async-first: all API interactions via `asyncio.to_thread()` or async HTTP
- Environment-based configuration via `navconfig`

### Known Risks / Gotchas

- **Alpaca paper account**: Requires separate paper trading API keys (same credentials work for both, but account mode is server-side)
- **Binance testnet**: Testnet balances are not real; symbols and liquidity may differ from production
- **IBKR connection state**: TWS must be running and logged into paper trading account; cannot dynamically switch paper/live
- **Kraken validate mode**: Spot orders return success but are NOT placed; no fill simulation — for true simulation need `VirtualPortfolio`
- **Kraken futures demo**: Separate demo environment with separate credentials
- **Price updates in DRY_RUN**: Need external price feed to trigger limit order fills; integrate with existing read toolkits

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `alpaca-py` | `>=0.10` | Alpaca trading client (already in project) |
| `aiohttp` | `>=3.9` | HTTP client for Binance/Kraken (already in project) |
| `ibapi` | `>=10.19` | IBKR TWS API (already optional dependency) |
| `pydantic` | `>=2.0` | Data models (already in project) |

### Configuration Examples

```bash
# Environment variables for paper trading

# Global mode (overrides individual toolkit defaults)
PAPER_TRADING_MODE=paper  # or "live" or "dry_run"

# Alpaca
ALPACA_PCB_PAPER=true  # Use paper trading

# Binance
BINANCE_TESTNET=true  # Use testnet endpoints

# IBKR
IBKR_PORT=7497  # Paper trading port (7496 = live)

# Kraken
KRAKEN_SPOT_VALIDATE=true  # Validate-only for spot
KRAKEN_FUTURES_DEMO=true   # Use demo environment for futures
```

---

## 7. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Should `VirtualPortfolio` persist state across sessions (Redis/file), or be ephemeral? — *Answer: Ephemeral for now; persistence is a follow-up feature*
- [x] Should dry-run fills happen instantly or respect `simulate_fill_delay_ms`? — *Answer: Respect the delay to simulate realistic latency*
- [x] How to handle partial fills in simulation? — *Answer: Market orders fill fully; limit orders fill fully when price crosses*
- [ ] Should we add a `--live` CLI flag to override paper mode? — *Owner: TBD*: Yes
- [ ] Do we need audit logging for mode switches? — *Owner: TBD*: Yes

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-04 | Jesus Lara | Initial draft |
