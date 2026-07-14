---
type: Wiki Entity
title: IBKRBackend
id: class:parrot_tools.ibkr.backend.IBKRBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for IBKR connection backends.
---

# IBKRBackend

Defined in [`parrot_tools.ibkr.backend`](../summaries/mod:parrot_tools.ibkr.backend.md).

```python
class IBKRBackend(ABC)
```

Abstract base class for IBKR connection backends.

Subclasses must implement all abstract methods to provide a complete
IBKR integration via either TWS API or Client Portal REST API.

## Methods

- `async def connect(self) -> None` — Establish connection to IBKR.
- `async def disconnect(self) -> None` — Close connection gracefully.
- `async def is_connected(self) -> bool` — Check if currently connected to IBKR.
- `async def get_quote(self, contract: ContractSpec) -> Quote` — Get real-time quote snapshot for a contract.
- `async def get_historical_bars(self, contract: ContractSpec, duration: str, bar_size: str) -> list[BarData]` — Get historical OHLCV bars for a contract.
- `async def get_options_chain(self, symbol: str, expiry: Optional[str]=None) -> list[dict]` — Get options chain for an underlying symbol.
- `async def search_contracts(self, pattern: str, sec_type: str='STK') -> list[dict]` — Search for contracts matching a pattern.
- `async def run_scanner(self, scan_code: str, num_results: int=25) -> list[dict]` — Run an IBKR market scanner.
- `async def place_order(self, order: OrderRequest) -> OrderStatus` — Place a new order.
- `async def modify_order(self, order_id: int, **changes) -> OrderStatus` — Modify an existing open order.
- `async def cancel_order(self, order_id: int) -> dict` — Cancel an open order.
- `async def get_open_orders(self) -> list[OrderStatus]` — Get all currently open orders.
- `async def get_account_summary(self) -> AccountSummary` — Get account summary information.
- `async def get_positions(self) -> list[Position]` — Get all current positions.
- `async def get_pnl(self) -> dict` — Get daily P&L breakdown.
- `async def get_trades(self, days: int=1) -> list[dict]` — Get recent trade executions.
- `async def get_news(self, symbol: Optional[str]=None, num_articles: int=5) -> list[dict]` — Get market news, optionally filtered by symbol.
- `async def get_fundamentals(self, symbol: str) -> dict` — Get fundamental data for a symbol.
