---
type: Wiki Entity
title: IBKRToolkit
id: class:parrot_tools.ibkr.IBKRToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Interactive Brokers trading toolkit for market data, orders, and portfolio
  management.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# IBKRToolkit

Defined in [`parrot_tools.ibkr`](../summaries/mod:parrot_tools.ibkr.md).

```python
class IBKRToolkit(AbstractToolkit)
```

Interactive Brokers trading toolkit for market data, orders, and portfolio management.

Wraps both TWS API and Client Portal REST backends behind a unified
interface. All order operations are gated by a RiskManager.

Args:
    config: IBKR connection configuration.
    risk_config: Risk management guardrails.
    confirmation_callback: Optional async callback for order confirmation.

## Methods

- `async def connect(self) -> None` — Connect to IBKR backend.
- `async def disconnect(self) -> None` — Disconnect from IBKR backend.
- `def get_tools(self) -> List[ToolkitTool]` — Return toolkit tools, excluding order tools when in readonly mode.
- `async def get_quote(self, symbol: str, sec_type: str='STK', exchange: str='SMART', currency: str='USD') -> dict` — Get real-time quote snapshot for a symbol.
- `async def get_historical_bars(self, symbol: str, duration: str='1 D', bar_size: str='1 hour', sec_type: str='STK', exchange: str='SMART', currency: str='USD') -> list[dict]` — Get historical OHLCV bars for a symbol.
- `async def get_options_chain(self, symbol: str, expiry: Optional[str]=None) -> list[dict]` — Get options chain for an underlying symbol.
- `async def search_contracts(self, pattern: str, sec_type: str='STK') -> list[dict]` — Search for contracts matching a pattern.
- `async def run_scanner(self, scan_code: str, num_results: int=25) -> list[dict]` — Run an IBKR market scanner.
- `async def place_order(self, symbol: str, action: str, quantity: int, order_type: str='LMT', limit_price: Optional[float]=None, stop_price: Optional[float]=None, tif: str='DAY') -> dict` — Place a new order (subject to risk checks).
- `async def modify_order(self, order_id: int, quantity: Optional[int]=None, limit_price: Optional[float]=None, stop_price: Optional[float]=None) -> dict` — Modify an existing open order (subject to risk checks).
- `async def cancel_order(self, order_id: int) -> dict` — Cancel an open order.
- `async def get_open_orders(self) -> list[dict]` — Get all currently open orders.
- `async def get_account_summary(self) -> dict` — Get account summary information.
- `async def get_positions(self) -> list[dict]` — Get all current positions.
- `async def get_pnl(self) -> dict` — Get daily P&L breakdown.
- `async def get_trades(self, days: int=1) -> list[dict]` — Get recent trade executions.
- `async def get_news(self, symbol: Optional[str]=None, num_articles: int=5) -> list[dict]` — Get market news, optionally filtered by symbol.
- `async def get_fundamentals(self, symbol: str) -> dict` — Get fundamental data for a symbol.
