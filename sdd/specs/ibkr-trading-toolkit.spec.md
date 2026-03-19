# Feature Specification: IBKR Trading Toolkit

**Feature ID**: FEAT-007
**Date**: 2026-02-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

AI-Parrot agents currently have no way to interact with financial markets through
Interactive Brokers (IBKR), one of the most widely used brokerage platforms for
algorithmic and institutional trading. Finance-focused agents need the ability to
retrieve market data, manage orders, monitor portfolios, and execute trading
strategies — all through a tool-based interface that integrates naturally with
AI-Parrot's Agent/ReAct framework.

### Integration with /finance/ ecosystem

IBKR toolkit will be integrated into /parrot/finance ecosystem for autonomous trading, portfolio evaluation and risk management.

### Goals
- Provide a comprehensive `IBKRToolkit` that exposes IBKR functionality as agent tools
- Support **both** TWS API (via `ib_insync`/`ib_async`) and Client Portal REST API backends
- Unified interface: agents use the same tools regardless of backend
- Full trading suite: market data, orders, account info, positions, P&L, contracts, scanner, news, fundamentals
- Built-in risk management guardrails for safe agent-driven trading
- Async-first design consistent with AI-Parrot patterns

### Non-Goals (explicitly out of scope)
- Building a complete trading strategy engine (agents compose strategies themselves)
- Direct FIX protocol support
- Multi-broker abstraction (this is IBKR-specific)
- Backtesting engine (separate feature)
- Real-money trading automation without human-in-the-loop approval (guardrails enforce this)

---

## 2. Architectural Design

### Overview

The toolkit follows the `AbstractToolkit` pattern used throughout AI-Parrot. A unified
`IBKRToolkit` exposes tools to agents, delegating to a backend abstraction that supports
both TWS API and Client Portal API connections. A `RiskManager` component intercepts
order-related actions to enforce configurable safety limits.

### Component Diagram
```
Agent
  │
  ├── IBKRToolkit (AbstractToolkit)
  │       │
  │       ├── Market Data Tools
  │       │     ├── get_quote
  │       │     ├── get_historical_bars
  │       │     ├── get_options_chain
  │       │     ├── search_contracts
  │       │     └── run_scanner
  │       │
  │       ├── Order Management Tools
  │       │     ├── place_order
  │       │     ├── modify_order
  │       │     ├── cancel_order
  │       │     └── get_open_orders
  │       │
  │       ├── Account / Portfolio Tools
  │       │     ├── get_account_summary
  │       │     ├── get_positions
  │       │     ├── get_pnl
  │       │     └── get_trades
  │       │
  │       ├── Info Tools
  │       │     ├── get_news
  │       │     └── get_fundamentals
  │       │
  │       └── RiskManager (interceptor)
  │             ├── max_order_size
  │             ├── max_position_value
  │             ├── daily_loss_limit
  │             └── confirmation_hook
  │
  └── IBKRBackend (ABC)
          ├── TWSBackend (ib_insync/ib_async)
          └── PortalBackend (Client Portal REST API)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | extends | `IBKRToolkit` inherits from `AbstractToolkit` |
| `ToolkitTool` | uses | Each IBKR operation is wrapped as a `ToolkitTool` |
| `Agent` | consumed by | Agents use `IBKRToolkit.get_tools()` in their tool list |
| `Pydantic BaseModel` | uses | All data models (orders, quotes, positions) are Pydantic |
| `navconfig` | uses | Connection config (host, port, client_id) via environment/settings |

### Data Models
```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from decimal import Decimal

class IBKRConfig(BaseModel):
    """Configuration for IBKR connection."""
    backend: Literal["tws", "portal"] = Field("tws", description="Connection backend")
    host: str = Field("127.0.0.1", description="TWS/Gateway host")
    port: int = Field(7497, description="TWS port (7497=paper, 7496=live)")
    client_id: int = Field(1, description="Client ID for TWS connection")
    portal_url: Optional[str] = Field(None, description="Client Portal Gateway URL")
    readonly: bool = Field(False, description="Read-only mode (disables order placement)")

class RiskConfig(BaseModel):
    """Risk management guardrails."""
    max_order_qty: int = Field(100, description="Max shares/contracts per order")
    max_order_value: Decimal = Field(Decimal("50000"), description="Max notional value per order")
    max_position_value: Decimal = Field(Decimal("200000"), description="Max total position value per symbol")
    daily_loss_limit: Decimal = Field(Decimal("5000"), description="Max daily realized+unrealized loss")
    require_confirmation: bool = Field(True, description="Require human confirmation before orders")

class Quote(BaseModel):
    """Real-time quote data."""
    symbol: str
    last: Optional[Decimal] = None
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    volume: Optional[int] = None
    timestamp: Optional[datetime] = None

class BarData(BaseModel):
    """Historical OHLCV bar."""
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

class OrderRequest(BaseModel):
    """Order placement request."""
    symbol: str
    action: Literal["BUY", "SELL"]
    quantity: int = Field(..., gt=0)
    order_type: Literal["MKT", "LMT", "STP", "STP_LMT"] = "LMT"
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    tif: Literal["DAY", "GTC", "IOC", "FOK"] = "DAY"

class OrderStatus(BaseModel):
    """Order status response."""
    order_id: int
    symbol: str
    action: str
    quantity: int
    filled: int = 0
    remaining: int = 0
    avg_fill_price: Optional[Decimal] = None
    status: str
    timestamp: Optional[datetime] = None

class Position(BaseModel):
    """Account position."""
    symbol: str
    quantity: int
    avg_cost: Decimal
    market_value: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None
    realized_pnl: Optional[Decimal] = None

class AccountSummary(BaseModel):
    """Account summary info."""
    account_id: str
    net_liquidation: Decimal
    total_cash: Decimal
    buying_power: Decimal
    gross_position_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
```

### New Public Interfaces
```python
class IBKRToolkit(AbstractToolkit):
    """Comprehensive IBKR trading toolkit for AI-Parrot agents."""

    def __init__(
        self,
        config: IBKRConfig = None,
        risk_config: RiskConfig = None,
        **kwargs
    ):
        ...

    async def connect(self) -> None:
        """Establish connection to IBKR."""

    async def disconnect(self) -> None:
        """Gracefully disconnect."""

    # Market Data
    async def get_quote(self, symbol: str, sec_type: str = "STK", exchange: str = "SMART") -> Quote:
        """Get real-time quote for a symbol."""

    async def get_historical_bars(
        self, symbol: str, duration: str = "1 D", bar_size: str = "1 hour",
        sec_type: str = "STK"
    ) -> list[BarData]:
        """Get historical OHLCV bars."""

    async def get_options_chain(self, symbol: str, expiry: str = None) -> list[dict]:
        """Get options chain for underlying symbol."""

    async def search_contracts(self, pattern: str, sec_type: str = "STK") -> list[dict]:
        """Search for contracts matching a pattern."""

    async def run_scanner(self, scan_code: str, num_results: int = 25) -> list[dict]:
        """Run an IBKR market scanner."""

    # Order Management
    async def place_order(self, order: OrderRequest) -> OrderStatus:
        """Place a new order (subject to risk checks)."""

    async def modify_order(self, order_id: int, **changes) -> OrderStatus:
        """Modify an existing order."""

    async def cancel_order(self, order_id: int) -> dict:
        """Cancel an open order."""

    async def get_open_orders(self) -> list[OrderStatus]:
        """Get all open orders."""

    # Account & Portfolio
    async def get_account_summary(self) -> AccountSummary:
        """Get account summary."""

    async def get_positions(self) -> list[Position]:
        """Get all current positions."""

    async def get_pnl(self) -> dict:
        """Get daily P&L breakdown."""

    async def get_trades(self, days: int = 1) -> list[dict]:
        """Get recent trade executions."""

    # Info
    async def get_news(self, symbol: str = None, num_articles: int = 5) -> list[dict]:
        """Get market news, optionally filtered by symbol."""

    async def get_fundamentals(self, symbol: str) -> dict:
        """Get fundamental data for a symbol."""
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

### Module 1: Data Models
- **Path**: `parrot/tools/ibkr/models.py`
- **Responsibility**: All Pydantic models (IBKRConfig, RiskConfig, Quote, BarData, OrderRequest, OrderStatus, Position, AccountSummary)
- **Depends on**: None

### Module 2: Backend Abstraction
- **Path**: `parrot/tools/ibkr/backend.py`
- **Responsibility**: `IBKRBackend` abstract base class defining the interface all backends must implement
- **Depends on**: Module 1

### Module 3: TWS Backend
- **Path**: `parrot/tools/ibkr/tws_backend.py`
- **Responsibility**: TWS API implementation using `ib_insync` (or `ib_async`). Handles connection lifecycle, contract resolution, data requests, and order routing via TWS/IB Gateway
- **Depends on**: Module 1, Module 2

### Module 4: Client Portal Backend
- **Path**: `parrot/tools/ibkr/portal_backend.py`
- **Responsibility**: Client Portal REST API implementation using `aiohttp`. Handles authentication, session management, and all REST endpoints
- **Depends on**: Module 1, Module 2

### Module 5: Risk Manager
- **Path**: `parrot/tools/ibkr/risk.py`
- **Responsibility**: Pre-trade risk checks — validates orders against configurable limits (max qty, max value, position limits, daily loss). Provides confirmation hook mechanism for human-in-the-loop approval
- **Depends on**: Module 1

### Module 6: IBKRToolkit (Main Toolkit)
- **Path**: `parrot/tools/ibkr/__init__.py`
- **Responsibility**: The `IBKRToolkit` class inheriting `AbstractToolkit`. Wires together backend + risk manager, exposes all methods as tools via `get_tools()`
- **Depends on**: Module 1, 2, 3, 4, 5

### Module 7: Demo Agent
- **Path**: `examples/ibkr_trading_agent.py`
- **Responsibility**: A working example agent that uses `IBKRToolkit` to demonstrate market data retrieval, portfolio monitoring, and order placement with guardrails
- **Depends on**: Module 6

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_models_validation` | Module 1 | Validates all Pydantic models with valid/invalid data |
| `test_order_request_constraints` | Module 1 | Ensures OrderRequest enforces qty > 0 and valid order types |
| `test_risk_config_defaults` | Module 1 | Verifies default risk limits |
| `test_backend_abc` | Module 2 | Verifies abstract backend cannot be instantiated directly |
| `test_tws_connect_disconnect` | Module 3 | Mocked TWS connection lifecycle |
| `test_tws_get_quote` | Module 3 | Mocked quote retrieval via TWS |
| `test_tws_place_order` | Module 3 | Mocked order placement via TWS |
| `test_portal_auth` | Module 4 | Mocked portal authentication |
| `test_portal_get_quote` | Module 4 | Mocked quote retrieval via REST |
| `test_risk_order_size_limit` | Module 5 | Order exceeding max qty is rejected |
| `test_risk_order_value_limit` | Module 5 | Order exceeding max notional is rejected |
| `test_risk_daily_loss_limit` | Module 5 | Trading halted when daily loss exceeded |
| `test_risk_confirmation_hook` | Module 5 | Confirmation callback is invoked before order |
| `test_toolkit_get_tools` | Module 6 | All expected tools are returned by `get_tools()` |
| `test_toolkit_readonly_mode` | Module 6 | Order tools are disabled in readonly mode |

### Integration Tests
| Test | Description |
|---|---|
| `test_paper_trading_quote` | Connects to IBKR paper account and retrieves a real quote |
| `test_paper_trading_order_lifecycle` | Places, modifies, and cancels an order on paper account |
| `test_paper_account_summary` | Retrieves account summary from paper account |
| `test_agent_with_ibkr_toolkit` | Agent uses IBKRToolkit to answer "What is AAPL's current price?" |

### Test Data / Fixtures
```python
import pytest
from parrot.tools.ibkr.models import IBKRConfig, RiskConfig, OrderRequest

@pytest.fixture
def paper_config():
    return IBKRConfig(
        backend="tws",
        host="127.0.0.1",
        port=7497,  # paper trading port
        client_id=99,
    )

@pytest.fixture
def strict_risk_config():
    return RiskConfig(
        max_order_qty=10,
        max_order_value=5000,
        daily_loss_limit=1000,
        require_confirmation=False,  # disable for automated tests
    )

@pytest.fixture
def sample_order():
    return OrderRequest(
        symbol="AAPL",
        action="BUY",
        quantity=5,
        order_type="LMT",
        limit_price=150.00,
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All Pydantic data models defined and validated
- [ ] `IBKRBackend` abstract base class with full interface
- [ ] `TWSBackend` implementation using `ib_insync` — all methods functional
- [ ] `PortalBackend` implementation using `aiohttp` — all methods functional
- [ ] `RiskManager` enforces all configured limits and confirmation hooks
- [ ] `IBKRToolkit` exposes all tools via `get_tools()` compatible with `Agent`
- [ ] Readonly mode disables all order-mutating tools
- [ ] All unit tests pass: `pytest tests/tools/test_ibkr/ -v`
- [ ] Integration tests pass against IBKR paper trading account
- [ ] Demo agent (`examples/ibkr_trading_agent.py`) works end-to-end
- [ ] No blocking I/O — fully async
- [ ] All tools have descriptive docstrings (used as LLM tool descriptions)
- [ ] No API keys or secrets in code — all config via environment variables

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Use `AbstractToolkit` pattern from `parrot/tools/toolkit.py`
- See `parrot/tools/openapi_toolkit.py` for reference toolkit implementation
- See `parrot/tools/o365/` for multi-file toolkit package structure
- Pydantic models for all structured data
- Async-first: use `aiohttp` for HTTP, `ib_insync` with asyncio integration
- Comprehensive logging with `self.logger`

### Known Risks / Gotchas
- **ib_insync event loop**: `ib_insync` uses its own event loop integration. Must ensure compatibility with AI-Parrot's asyncio loop. Consider using `ib_insync.IB` with `asyncio` mode or the newer `ib_async` fork
- **TWS connection limits**: TWS allows limited concurrent API connections (max ~8 client IDs). Toolkit should handle connection failures gracefully
- **Client Portal session**: Portal API sessions expire and need periodic re-authentication. Backend must handle session refresh
- **Order execution latency**: Real-time order status updates come asynchronously via TWS callbacks. Backend must bridge callback-style to async/await
- **Paper vs live ports**: TWS paper trading uses port 7497, live uses 7496. Config must make this explicit to avoid accidental live trading

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `ib_insync` | `>=0.9.86` | TWS API wrapper with asyncio support |
| `aiohttp` | `>=3.9` | HTTP client for Client Portal REST API |
| `pydantic` | `>=2.0` | Data models (already in project) |

---

## 7. Open Questions

> Questions that must be resolved before or during implementation.

- [ ] Should we use `ib_insync` or the newer `ib_async` fork? — *Owner: ib_async for clearly async-first integration.
- [ ] Does the Client Portal API require a separate gateway process, or can we embed authentication? — *Owner: embed authentication.
- [ ] Should the confirmation hook be a callback function or integrate with AI-Parrot's event system? — *Owner: a callback function.
- [ ] Do we need streaming/real-time data push (WebSocket-style), or is polling sufficient for agent use? — *Owner: polling is sufficient.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-19 | Jesus Lara | Initial draft |
