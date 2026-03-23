"""TWS API backend for IBKR using ib_async.

Implements all IBKRBackend methods using the ib_async library (async-first
fork of ib_insync). Connects to TWS or IB Gateway for real-time market data,
order management, account info, and more.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from navconfig.logging import logging

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
)

try:
    from ib_async import (
        IB,
        Contract,
        Future,
        LimitOrder,
        MarketOrder,
        Option,
        ScannerSubscription,
        Stock,
        StopOrder,
    )
    HAS_IB_ASYNC = True
except ImportError:
    HAS_IB_ASYNC = False
    IB = None  # type: ignore[assignment, misc]


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Convert a float to Decimal, treating NaN/None as None."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return Decimal(str(value))


def _make_ib_contract(spec: ContractSpec) -> Contract:
    """Convert a ContractSpec to an ib_async Contract."""
    sec = spec.sec_type.upper()
    if sec == "STK":
        return Stock(spec.symbol, spec.exchange, spec.currency)
    if sec == "FUT":
        return Future(spec.symbol, exchange=spec.exchange, currency=spec.currency)
    if sec == "OPT":
        return Option(spec.symbol, exchange=spec.exchange, currency=spec.currency)
    # Generic fallback
    c = Contract()
    c.symbol = spec.symbol
    c.secType = spec.sec_type
    c.exchange = spec.exchange
    c.currency = spec.currency
    return c


def _build_order(request: OrderRequest):
    """Convert an OrderRequest to an ib_async Order object."""
    otype = request.order_type
    if otype == "MKT":
        return MarketOrder(
            request.action, request.quantity, tif=request.tif,
        )
    if otype == "LMT":
        return LimitOrder(
            request.action, request.quantity,
            float(request.limit_price or 0),
            tif=request.tif,
        )
    if otype == "STP":
        return StopOrder(
            request.action, request.quantity,
            float(request.stop_price or 0),
            tif=request.tif,
        )
    # STP_LMT — build manually
    order = LimitOrder(
        request.action, request.quantity,
        float(request.limit_price or 0),
        tif=request.tif,
    )
    order.orderType = "STP LMT"
    order.auxPrice = float(request.stop_price or 0)
    return order


def _trade_to_status(trade) -> OrderStatus:
    """Convert an ib_async Trade to an OrderStatus."""
    return OrderStatus(
        order_id=trade.order.orderId,
        symbol=trade.contract.symbol,
        action=trade.order.action,
        quantity=int(trade.order.totalQuantity),
        filled=int(trade.orderStatus.filled),
        remaining=int(trade.orderStatus.remaining),
        avg_fill_price=_to_decimal(trade.orderStatus.avgFillPrice),
        status=trade.orderStatus.status,
    )


class TWSBackend(IBKRBackend):
    """TWS API backend using ib_async."""

    def __init__(self, config: IBKRConfig):
        if not HAS_IB_ASYNC:
            raise ImportError(
                "ib_async is required for TWSBackend. "
                "Install it with: pip install ib_async"
            )
        super().__init__(config)
        self._ib: IB = IB()

    # ── Connection ───────────────────────────────────────────────

    async def connect(self) -> None:
        """Connect to TWS/IB Gateway."""
        await self._ib.connectAsync(
            self.config.host,
            self.config.port,
            clientId=self.config.client_id,
            readonly=self.config.readonly,
        )
        self.logger.info(
            "Connected to TWS at %s:%d (clientId=%d, readonly=%s)",
            self.config.host, self.config.port,
            self.config.client_id, self.config.readonly,
        )

    async def disconnect(self) -> None:
        """Disconnect from TWS/IB Gateway."""
        self._ib.disconnect()
        self.logger.info("Disconnected from TWS")

    async def is_connected(self) -> bool:
        """Check if connected to TWS."""
        return self._ib.isConnected()

    # ── Market Data ──────────────────────────────────────────────

    async def get_quote(self, contract: ContractSpec) -> Quote:
        """Get real-time quote snapshot."""
        ib_contract = _make_ib_contract(contract)
        await self._ib.qualifyContractsAsync(ib_contract)

        ticker = self._ib.reqMktData(ib_contract, snapshot=True)
        try:
            await ticker.updateEvent.wait()
        except Exception:
            pass  # timeout or no data — return what we have

        self._ib.cancelMktData(ib_contract)

        return Quote(
            symbol=contract.symbol,
            last=_to_decimal(ticker.last),
            bid=_to_decimal(ticker.bid),
            ask=_to_decimal(ticker.ask),
            volume=int(ticker.volume) if ticker.volume and not math.isnan(ticker.volume) else None,
            timestamp=ticker.time if hasattr(ticker, 'time') else None,
        )

    async def get_historical_bars(
        self,
        contract: ContractSpec,
        duration: str,
        bar_size: str,
    ) -> list[BarData]:
        """Get historical OHLCV bars."""
        ib_contract = _make_ib_contract(contract)
        await self._ib.qualifyContractsAsync(ib_contract)

        bars = await self._ib.reqHistoricalDataAsync(
            ib_contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=True,
        )

        return [
            BarData(
                timestamp=bar.date if isinstance(bar.date, datetime) else datetime.now(),
                open=Decimal(str(bar.open)),
                high=Decimal(str(bar.high)),
                low=Decimal(str(bar.low)),
                close=Decimal(str(bar.close)),
                volume=int(bar.volume),
            )
            for bar in bars
        ]

    async def get_options_chain(
        self, symbol: str, expiry: Optional[str] = None
    ) -> list[dict]:
        """Get options chain for an underlying symbol."""
        ib_contract = Stock(symbol, "SMART", "USD")
        await self._ib.qualifyContractsAsync(ib_contract)

        params = await self._ib.reqSecDefOptParamsAsync(
            ib_contract.symbol,
            "",
            ib_contract.secType,
            ib_contract.conId,
        )

        results = []
        for p in params:
            expirations = sorted(p.expirations) if p.expirations else []
            if expiry:
                expirations = [e for e in expirations if e == expiry]
            strikes = sorted(p.strikes) if p.strikes else []
            results.append({
                "exchange": p.exchange,
                "underlying_con_id": p.underlyingConId,
                "trading_class": p.tradingClass,
                "multiplier": p.multiplier,
                "expirations": expirations,
                "strikes": [float(s) for s in strikes],
            })
        return results

    async def search_contracts(
        self, pattern: str, sec_type: str = "STK"
    ) -> list[dict]:
        """Search for contracts matching a pattern."""
        descriptions = await self._ib.reqMatchingSymbolsAsync(pattern)
        if not descriptions:
            return []

        results = []
        for desc in descriptions:
            c = desc.contract
            if sec_type and c.secType != sec_type:
                continue
            results.append({
                "symbol": c.symbol,
                "sec_type": c.secType,
                "exchange": c.primaryExchange,
                "currency": c.currency,
            })
        return results

    async def run_scanner(
        self, scan_code: str, num_results: int = 25
    ) -> list[dict]:
        """Run an IBKR market scanner."""
        sub = ScannerSubscription(
            scanCode=scan_code,
            numberOfRows=num_results,
            instrument="STK",
            locationCode="STK.US.MAJOR",
        )
        data = await self._ib.reqScannerDataAsync(sub)
        if not data:
            return []

        return [
            {
                "rank": item.rank,
                "symbol": item.contractDetails.contract.symbol,
            }
            for item in data
        ]

    # ── Order Management ─────────────────────────────────────────

    async def place_order(self, order: OrderRequest) -> OrderStatus:
        """Place a new order."""
        contract = ContractSpec(symbol=order.symbol)
        ib_contract = _make_ib_contract(contract)
        await self._ib.qualifyContractsAsync(ib_contract)

        ib_order = _build_order(order)
        trade = self._ib.placeOrder(ib_contract, ib_order)

        self.logger.info(
            "Order placed: %s %d %s @ %s (orderId=%d)",
            order.action, order.quantity, order.symbol,
            order.limit_price or "MKT", trade.order.orderId,
        )
        return _trade_to_status(trade)

    async def modify_order(self, order_id: int, **changes) -> OrderStatus:
        """Modify an existing open order."""
        # Find the existing trade
        open_trades = self._ib.openTrades()
        trade = None
        for t in open_trades:
            if t.order.orderId == order_id:
                trade = t
                break

        if trade is None:
            raise ValueError(f"No open order found with orderId={order_id}")

        # Apply modifications
        if "quantity" in changes:
            trade.order.totalQuantity = changes["quantity"]
        if "limit_price" in changes:
            trade.order.lmtPrice = float(changes["limit_price"])
        if "stop_price" in changes:
            trade.order.auxPrice = float(changes["stop_price"])
        if "tif" in changes:
            trade.order.tif = changes["tif"]

        modified_trade = self._ib.placeOrder(trade.contract, trade.order)
        self.logger.info("Order %d modified: %s", order_id, changes)
        return _trade_to_status(modified_trade)

    async def cancel_order(self, order_id: int) -> dict:
        """Cancel an open order."""
        # Find the trade by order_id
        open_trades = self._ib.openTrades()
        for t in open_trades:
            if t.order.orderId == order_id:
                self._ib.cancelOrder(t.order)
                self.logger.info("Order %d cancelled", order_id)
                return {"order_id": order_id, "status": "cancel_requested"}

        # If not found in open trades, try cancelling by order object
        from ib_async import Order as IBOrder
        order = IBOrder()
        order.orderId = order_id
        self._ib.cancelOrder(order)
        self.logger.info("Order %d cancel requested", order_id)
        return {"order_id": order_id, "status": "cancel_requested"}

    async def get_open_orders(self) -> list[OrderStatus]:
        """Get all currently open orders."""
        trades = self._ib.openTrades()
        return [_trade_to_status(t) for t in trades]

    # ── Account & Portfolio ──────────────────────────────────────

    async def get_account_summary(self) -> AccountSummary:
        """Get account summary information."""
        values = await self._ib.accountSummaryAsync()

        data: dict[str, Any] = {}
        account_id = ""
        for av in values:
            if not account_id:
                account_id = av.account
            data[av.tag] = av.value

        return AccountSummary(
            account_id=account_id,
            net_liquidation=Decimal(data.get("NetLiquidation", "0")),
            total_cash=Decimal(data.get("TotalCashValue", "0")),
            buying_power=Decimal(data.get("BuyingPower", "0")),
            gross_position_value=Decimal(data.get("GrossPositionValue", "0")),
            unrealized_pnl=Decimal(data.get("UnrealizedPnL", "0")),
            realized_pnl=Decimal(data.get("RealizedPnL", "0")),
        )

    async def get_positions(self) -> list[Position]:
        """Get all current positions."""
        positions = self._ib.positions()
        return [
            Position(
                symbol=p.contract.symbol,
                quantity=int(p.position),
                avg_cost=Decimal(str(p.avgCost)),
                market_value=_to_decimal(getattr(p, 'marketValue', None)),
                unrealized_pnl=_to_decimal(getattr(p, 'unrealizedPNL', None)),
                realized_pnl=_to_decimal(getattr(p, 'realizedPNL', None)),
            )
            for p in positions
        ]

    async def get_pnl(self) -> dict:
        """Get daily P&L breakdown."""
        pnl_list = self._ib.pnl()
        if not pnl_list:
            return {"daily_pnl": 0, "unrealized_pnl": 0, "realized_pnl": 0}

        pnl = pnl_list[0]
        return {
            "daily_pnl": float(getattr(pnl, 'dailyPnL', 0) or 0),
            "unrealized_pnl": float(getattr(pnl, 'unrealizedPnL', 0) or 0),
            "realized_pnl": float(getattr(pnl, 'realizedPnL', 0) or 0),
        }

    async def get_trades(self, days: int = 1) -> list[dict]:
        """Get recent trade executions."""
        fills = await self._ib.reqExecutionsAsync()
        return [
            {
                "symbol": f.contract.symbol,
                "exec_id": f.execution.execId,
                "side": f.execution.side,
                "shares": float(f.execution.shares),
                "price": float(f.execution.price),
                "time": f.execution.time,
            }
            for f in fills
        ]

    # ── Info ─────────────────────────────────────────────────────

    async def get_news(
        self, symbol: Optional[str] = None, num_articles: int = 5
    ) -> list[dict]:
        """Get market news, optionally filtered by symbol."""
        if not symbol:
            return []

        ib_contract = Stock(symbol, "SMART", "USD")
        await self._ib.qualifyContractsAsync(ib_contract)

        articles = await self._ib.reqHistoricalNewsAsync(
            ib_contract.conId,
            providerCodes="",
            startDateTime="",
            endDateTime="",
            totalResults=num_articles,
        )
        if not articles:
            return []

        return [
            {
                "time": str(a.time),
                "provider": a.providerCode,
                "article_id": a.articleId,
                "headline": a.headline,
            }
            for a in articles
        ]

    async def get_fundamentals(self, symbol: str) -> dict:
        """Get fundamental data for a symbol."""
        ib_contract = Stock(symbol, "SMART", "USD")
        await self._ib.qualifyContractsAsync(ib_contract)

        data = await self._ib.reqFundamentalDataAsync(
            ib_contract, reportType="ReportSnapshot",
        )
        return {
            "symbol": symbol,
            "data": data or "",
        }
