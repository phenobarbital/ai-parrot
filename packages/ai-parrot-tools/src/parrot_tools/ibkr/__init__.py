"""IBKR Trading Toolkit for AI-Parrot agents.

Provides a unified toolkit for market data, order management, account info,
and portfolio operations through Interactive Brokers. Supports both TWS API
and Client Portal REST API backends with built-in risk management.

Usage:
    from parrot.tools.ibkr import IBKRToolkit, IBKRConfig, RiskConfig

    toolkit = IBKRToolkit(
        config=IBKRConfig(backend="tws", port=7497),
        risk_config=RiskConfig(max_order_qty=100),
    )

    async with toolkit:
        tools = toolkit.get_tools()
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from ..toolkit import AbstractToolkit, ToolkitTool
from .backend import IBKRBackend
from .models import (
    AccountSummary,
    BarData,
    ContractSpec,
    IBKRConfig,
    OrderRequest,
    OrderStatus,
    Position,
    Quote,
    RiskConfig,
)
from .portal_backend import PortalBackend
from .risk import RiskCheckResult, RiskManager
from .tws_backend import TWSBackend

# Order-mutating tool names excluded in readonly mode
_ORDER_TOOLS = frozenset({"place_order", "modify_order", "cancel_order"})


class IBKRToolkit(AbstractToolkit):
    """Interactive Brokers trading toolkit for market data, orders, and portfolio management.

    Wraps both TWS API and Client Portal REST backends behind a unified
    interface. All order operations are gated by a RiskManager.

    Args:
        config: IBKR connection configuration.
        risk_config: Risk management guardrails.
        confirmation_callback: Optional async callback for order confirmation.
    """

    def __init__(
        self,
        config: Optional[IBKRConfig] = None,
        risk_config: Optional[RiskConfig] = None,
        confirmation_callback=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.config = config or IBKRConfig()
        self._risk = RiskManager(
            config=risk_config or RiskConfig(),
            confirmation_callback=confirmation_callback,
        )

        # Select backend based on config
        if self.config.backend == "portal":
            self._backend: IBKRBackend = PortalBackend(self.config)
        else:
            self._backend = TWSBackend(self.config)

    # ── Connection lifecycle ─────────────────────────────────────

    async def connect(self) -> None:
        """Connect to IBKR backend."""
        await self._backend.connect()

    async def disconnect(self) -> None:
        """Disconnect from IBKR backend."""
        await self._backend.disconnect()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()

    # ── Tool exposure ────────────────────────────────────────────

    def get_tools(self) -> List[ToolkitTool]:
        """Return toolkit tools, excluding order tools when in readonly mode."""
        tools = super().get_tools()
        if self.config.readonly:
            tools = [t for t in tools if t.name not in _ORDER_TOOLS]
            # Rebuild cache to match filtered list
            self._tool_cache = {t.name: t for t in tools}
        return tools

    # ── Market Data tools ────────────────────────────────────────

    async def get_quote(self, symbol: str, sec_type: str = "STK",
                        exchange: str = "SMART", currency: str = "USD") -> dict:
        """Get real-time quote snapshot for a symbol.

        Args:
            symbol: Ticker symbol (e.g. AAPL, ES, BTC).
            sec_type: Security type: STK, OPT, FUT, CASH, CRYPTO.
            exchange: Exchange (e.g. SMART, NYSE, GLOBEX).
            currency: Currency (default USD).

        Returns:
            Quote with last, bid, ask, volume.
        """
        contract = ContractSpec(
            symbol=symbol, sec_type=sec_type,
            exchange=exchange, currency=currency,
        )
        quote = await self._backend.get_quote(contract)
        return quote.model_dump()

    async def get_historical_bars(
        self, symbol: str, duration: str = "1 D",
        bar_size: str = "1 hour", sec_type: str = "STK",
        exchange: str = "SMART", currency: str = "USD",
    ) -> list[dict]:
        """Get historical OHLCV bars for a symbol.

        Args:
            symbol: Ticker symbol.
            duration: Time duration (e.g. '1 D', '1 W', '1 M').
            bar_size: Bar size (e.g. '1 min', '5 mins', '1 hour', '1 day').
            sec_type: Security type.
            exchange: Exchange.
            currency: Currency.

        Returns:
            List of OHLCV bars.
        """
        contract = ContractSpec(
            symbol=symbol, sec_type=sec_type,
            exchange=exchange, currency=currency,
        )
        bars = await self._backend.get_historical_bars(contract, duration, bar_size)
        return [b.model_dump() for b in bars]

    async def get_options_chain(
        self, symbol: str, expiry: Optional[str] = None
    ) -> list[dict]:
        """Get options chain for an underlying symbol.

        Args:
            symbol: Underlying ticker symbol.
            expiry: Optional expiration date filter (YYYYMMDD).

        Returns:
            Options chain data.
        """
        return await self._backend.get_options_chain(symbol, expiry)

    async def search_contracts(
        self, pattern: str, sec_type: str = "STK"
    ) -> list[dict]:
        """Search for contracts matching a pattern.

        Args:
            pattern: Symbol or name search pattern.
            sec_type: Security type filter.

        Returns:
            List of matching contracts.
        """
        return await self._backend.search_contracts(pattern, sec_type)

    async def run_scanner(
        self, scan_code: str, num_results: int = 25
    ) -> list[dict]:
        """Run an IBKR market scanner.

        Args:
            scan_code: Scanner code (e.g. TOP_PERC_GAIN, HOT_BY_PRICE).
            num_results: Number of results to return.

        Returns:
            Scanner results.
        """
        return await self._backend.run_scanner(scan_code, num_results)

    # ── Order Management tools ───────────────────────────────────

    async def place_order(
        self, symbol: str, action: str, quantity: int,
        order_type: str = "LMT", limit_price: Optional[float] = None,
        stop_price: Optional[float] = None, tif: str = "DAY",
    ) -> dict:
        """Place a new order (subject to risk checks).

        Args:
            symbol: Ticker symbol.
            action: BUY or SELL.
            quantity: Order quantity.
            order_type: Order type: MKT, LMT, STP, or STP_LMT.
            limit_price: Limit price (required for LMT and STP_LMT).
            stop_price: Stop price (required for STP and STP_LMT).
            tif: Time in force: DAY, GTC, IOC, or FOK.

        Returns:
            Order status with order_id.
        """
        order = OrderRequest(
            symbol=symbol, action=action, quantity=quantity,
            order_type=order_type,
            limit_price=Decimal(str(limit_price)) if limit_price is not None else None,
            stop_price=Decimal(str(stop_price)) if stop_price is not None else None,
            tif=tif,
        )

        # Get current positions and price for risk checks
        positions = await self._backend.get_positions()
        current_price = Decimal(str(limit_price)) if limit_price else None

        risk_result = await self._risk.validate_order(
            order, current_positions=positions, current_price=current_price,
        )
        if not risk_result.passed:
            raise ValueError(f"Risk check failed: {risk_result.reason}")

        status = await self._backend.place_order(order)
        return status.model_dump()

    async def modify_order(
        self, order_id: int, quantity: Optional[int] = None,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> dict:
        """Modify an existing open order (subject to risk checks).

        Args:
            order_id: The order ID to modify.
            quantity: New quantity (optional).
            limit_price: New limit price (optional).
            stop_price: New stop price (optional).

        Returns:
            Updated order status.
        """
        changes = {}
        if quantity is not None:
            changes["quantity"] = quantity
        if limit_price is not None:
            changes["limit_price"] = Decimal(str(limit_price))
        if stop_price is not None:
            changes["stop_price"] = Decimal(str(stop_price))

        status = await self._backend.modify_order(order_id, **changes)
        return status.model_dump()

    async def cancel_order(self, order_id: int) -> dict:
        """Cancel an open order.

        Args:
            order_id: The order ID to cancel.

        Returns:
            Cancellation result.
        """
        return await self._backend.cancel_order(order_id)

    async def get_open_orders(self) -> list[dict]:
        """Get all currently open orders.

        Returns:
            List of open order statuses.
        """
        orders = await self._backend.get_open_orders()
        return [o.model_dump() for o in orders]

    # ── Account & Portfolio tools ────────────────────────────────

    async def get_account_summary(self) -> dict:
        """Get account summary information.

        Returns:
            Account summary with net liquidation, cash, buying power, P&L.
        """
        summary = await self._backend.get_account_summary()
        return summary.model_dump()

    async def get_positions(self) -> list[dict]:
        """Get all current positions.

        Returns:
            List of positions with symbol, quantity, cost, P&L.
        """
        positions = await self._backend.get_positions()
        return [p.model_dump() for p in positions]

    async def get_pnl(self) -> dict:
        """Get daily P&L breakdown.

        Returns:
            Daily, unrealized, and realized P&L.
        """
        return await self._backend.get_pnl()

    async def get_trades(self, days: int = 1) -> list[dict]:
        """Get recent trade executions.

        Args:
            days: Number of days to look back.

        Returns:
            List of recent trades.
        """
        return await self._backend.get_trades(days)

    # ── Info tools ───────────────────────────────────────────────

    async def get_news(
        self, symbol: Optional[str] = None, num_articles: int = 5
    ) -> list[dict]:
        """Get market news, optionally filtered by symbol.

        Args:
            symbol: Optional symbol to filter news.
            num_articles: Number of articles to retrieve.

        Returns:
            List of news articles.
        """
        return await self._backend.get_news(symbol, num_articles)

    async def get_fundamentals(self, symbol: str) -> dict:
        """Get fundamental data for a symbol.

        Args:
            symbol: Ticker symbol.

        Returns:
            Fundamental data including financials.
        """
        return await self._backend.get_fundamentals(symbol)


__all__ = [
    "IBKRToolkit",
    "IBKRConfig",
    "RiskConfig",
    "RiskManager",
    "RiskCheckResult",
    "ContractSpec",
    "Quote",
    "BarData",
    "OrderRequest",
    "OrderStatus",
    "Position",
    "AccountSummary",
    "IBKRBackend",
    "TWSBackend",
    "PortalBackend",
]
