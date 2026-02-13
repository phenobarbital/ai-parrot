"""Alpaca write-side toolkit for order execution on stocks and ETFs."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from navconfig import config
from navconfig.logging import logging
from pydantic import BaseModel, Field

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    LimitOrderRequest,
    StopOrderRequest,
    StopLimitOrderRequest,
    TrailingStopOrderRequest,
    ReplaceOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import (
    OrderSide,
    OrderType,
    TimeInForce,
    QueryOrderStatus,
)
from alpaca.common.exceptions import APIError

from ...tools.toolkit import AbstractToolkit
from ...tools.decorators import tool_schema


class AlpacaWriteError(RuntimeError):
    """Raised when an Alpaca write operation fails."""


# =============================================================================
# Pydantic input schemas
# =============================================================================

class PlaceLimitOrderInput(BaseModel):
    """Place a limit order for a stock or ETF."""
    symbol: str = Field(..., description="Ticker symbol (e.g. AAPL).")
    side: str = Field(..., description="Order side: 'buy' or 'sell'.")
    qty: float = Field(..., description="Number of shares.", gt=0)
    limit_price: float = Field(..., description="Limit price in USD.", gt=0)
    time_in_force: str = Field("day", description="Time in force: 'day', 'gtc', 'ioc', 'fok'.")


class PlaceStopOrderInput(BaseModel):
    """Place a stop order."""
    symbol: str = Field(..., description="Ticker symbol.")
    side: str = Field(..., description="Order side: 'buy' or 'sell'.")
    qty: float = Field(..., description="Number of shares.", gt=0)
    stop_price: float = Field(..., description="Stop trigger price in USD.", gt=0)
    time_in_force: str = Field("day", description="Time in force.")


class PlaceStopLimitOrderInput(BaseModel):
    """Place a stop-limit order."""
    symbol: str = Field(..., description="Ticker symbol.")
    side: str = Field(..., description="Order side: 'buy' or 'sell'.")
    qty: float = Field(..., description="Number of shares.", gt=0)
    stop_price: float = Field(..., description="Stop trigger price.", gt=0)
    limit_price: float = Field(..., description="Limit price after trigger.", gt=0)
    time_in_force: str = Field("day", description="Time in force.")


class PlaceTrailingStopInput(BaseModel):
    """Place a trailing-stop order."""
    symbol: str = Field(..., description="Ticker symbol.")
    side: str = Field(..., description="Order side: 'buy' or 'sell'.")
    qty: float = Field(..., description="Number of shares.", gt=0)
    trail_percent: Optional[float] = Field(None, description="Trail offset in percent.", gt=0)
    trail_price: Optional[float] = Field(None, description="Trail offset in USD.", gt=0)
    time_in_force: str = Field("day", description="Time in force.")


class PlaceBracketOrderInput(BaseModel):
    """Place a bracket (OTO) order with stop-loss and take-profit legs."""
    symbol: str = Field(..., description="Ticker symbol.")
    side: str = Field(..., description="Order side: 'buy' or 'sell'.")
    qty: float = Field(..., description="Number of shares.", gt=0)
    limit_price: float = Field(..., description="Entry limit price.", gt=0)
    stop_loss_price: float = Field(..., description="Stop-loss trigger price.", gt=0)
    take_profit_price: float = Field(..., description="Take-profit limit price.", gt=0)
    time_in_force: str = Field("day", description="Time in force.")


class CancelOrderInput(BaseModel):
    """Cancel a specific order by ID."""
    order_id: str = Field(..., description="Alpaca order ID to cancel.")


class ReplaceOrderInput(BaseModel):
    """Replace (modify) an existing order."""
    order_id: str = Field(..., description="Alpaca order ID to replace.")
    qty: Optional[float] = Field(None, description="New quantity.", gt=0)
    limit_price: Optional[float] = Field(None, description="New limit price.", gt=0)
    stop_price: Optional[float] = Field(None, description="New stop price.", gt=0)
    time_in_force: Optional[str] = Field(None, description="New time in force.")


class ClosePositionInput(BaseModel):
    """Close a position for a symbol."""
    symbol: str = Field(..., description="Ticker symbol to close.")
    qty: Optional[float] = Field(None, description="Partial close quantity. Omit to close all.")


class GetOrdersInput(BaseModel):
    """Query orders with optional filters."""
    status: str = Field("open", description="Filter: 'open', 'closed', or 'all'.")
    limit: int = Field(50, description="Maximum number of orders to return.", le=500)


class GetPositionInput(BaseModel):
    """Get a specific position by symbol."""
    symbol: str = Field(..., description="Ticker symbol.")


# =============================================================================
# Toolkit
# =============================================================================

_TIF_MAP = {
    "day": TimeInForce.DAY,
    "gtc": TimeInForce.GTC,
    "ioc": TimeInForce.IOC,
    "fok": TimeInForce.FOK,
}

_SIDE_MAP = {
    "buy": OrderSide.BUY,
    "sell": OrderSide.SELL,
}

_STATUS_MAP = {
    "open": QueryOrderStatus.OPEN,
    "closed": QueryOrderStatus.CLOSED,
    "all": QueryOrderStatus.ALL,
}


class AlpacaWriteToolkit(AbstractToolkit):
    """Write-side toolkit for Alpaca (stocks & ETFs)."""

    name: str = "alpaca_write_toolkit"
    description: str = "Execute trading operations on Alpaca: place, cancel, replace orders and manage positions."

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger("AlpacaWriteToolkit")
        self.api_key = config.get("ALPACA_TRADING_API_KEY") or config.get("ALPACA_MARKETS_CLIENT_ID")
        self.api_secret = config.get("ALPACA_TRADING_API_SECRET") or config.get("ALPACA_MARKETS_CLIENT_SECRET")
        self.paper = config.get("ALPACA_PCB_PAPER", section="finance", fallback=True)
        self.base_url = config.get("ALPACA_API_BASE_URL", section="finance", fallback=None)
        self._client: Optional[TradingClient] = None

    @property
    def client(self) -> TradingClient:
        """Lazy-init the TradingClient."""
        if self._client is None:
            if not self.api_key or not self.api_secret:
                raise AlpacaWriteError("ALPACA_TRADING_API_KEY / SECRET not configured.")
            kw: Dict[str, Any] = {}
            if self.base_url:
                kw["url_override"] = self.base_url
            self._client = TradingClient(self.api_key, self.api_secret, paper=self.paper, **kw)
        return self._client

    # ── Order placement ─────────────────────────────────────────

    @tool_schema(PlaceLimitOrderInput)
    async def place_limit_order(
        self, symbol: str, side: str, qty: float, limit_price: float, time_in_force: str = "day"
    ) -> Dict[str, Any]:
        """Place a limit order for a stock or ETF on Alpaca."""
        try:
            req = LimitOrderRequest(
                symbol=symbol.upper(),
                side=_SIDE_MAP[side.lower()],
                qty=qty,
                limit_price=limit_price,
                time_in_force=_TIF_MAP.get(time_in_force.lower(), TimeInForce.DAY),
            )
            order = await asyncio.to_thread(self.client.submit_order, req)
            return {"order_id": str(order.id), "status": str(order.status), "symbol": symbol}
        except APIError as exc:
            raise AlpacaWriteError(f"Alpaca limit order failed: {exc}") from exc

    @tool_schema(PlaceStopOrderInput)
    async def place_stop_order(
        self, symbol: str, side: str, qty: float, stop_price: float, time_in_force: str = "day"
    ) -> Dict[str, Any]:
        """Place a stop order on Alpaca."""
        try:
            req = StopOrderRequest(
                symbol=symbol.upper(),
                side=_SIDE_MAP[side.lower()],
                qty=qty,
                stop_price=stop_price,
                time_in_force=_TIF_MAP.get(time_in_force.lower(), TimeInForce.DAY),
            )
            order = await asyncio.to_thread(self.client.submit_order, req)
            return {"order_id": str(order.id), "status": str(order.status), "symbol": symbol}
        except APIError as exc:
            raise AlpacaWriteError(f"Alpaca stop order failed: {exc}") from exc

    @tool_schema(PlaceStopLimitOrderInput)
    async def place_stop_limit_order(
        self, symbol: str, side: str, qty: float, stop_price: float, limit_price: float, time_in_force: str = "day"
    ) -> Dict[str, Any]:
        """Place a stop-limit order on Alpaca."""
        try:
            req = StopLimitOrderRequest(
                symbol=symbol.upper(),
                side=_SIDE_MAP[side.lower()],
                qty=qty,
                stop_price=stop_price,
                limit_price=limit_price,
                time_in_force=_TIF_MAP.get(time_in_force.lower(), TimeInForce.DAY),
            )
            order = await asyncio.to_thread(self.client.submit_order, req)
            return {"order_id": str(order.id), "status": str(order.status), "symbol": symbol}
        except APIError as exc:
            raise AlpacaWriteError(f"Alpaca stop-limit order failed: {exc}") from exc

    @tool_schema(PlaceTrailingStopInput)
    async def place_trailing_stop_order(
        self, symbol: str, side: str, qty: float,
        trail_percent: Optional[float] = None, trail_price: Optional[float] = None,
        time_in_force: str = "day"
    ) -> Dict[str, Any]:
        """Place a trailing-stop order on Alpaca."""
        if not trail_percent and not trail_price:
            raise AlpacaWriteError("Provide either trail_percent or trail_price.")
        try:
            req = TrailingStopOrderRequest(
                symbol=symbol.upper(),
                side=_SIDE_MAP[side.lower()],
                qty=qty,
                trail_percent=trail_percent,
                trail_price=trail_price,
                time_in_force=_TIF_MAP.get(time_in_force.lower(), TimeInForce.DAY),
            )
            order = await asyncio.to_thread(self.client.submit_order, req)
            return {"order_id": str(order.id), "status": str(order.status), "symbol": symbol}
        except APIError as exc:
            raise AlpacaWriteError(f"Alpaca trailing-stop order failed: {exc}") from exc

    @tool_schema(PlaceBracketOrderInput)
    async def place_bracket_oto_order(
        self, symbol: str, side: str, qty: float,
        limit_price: float, stop_loss_price: float, take_profit_price: float,
        time_in_force: str = "day"
    ) -> Dict[str, Any]:
        """Place a bracket (OTO) order with stop-loss and take-profit legs."""
        try:
            req = LimitOrderRequest(
                symbol=symbol.upper(),
                side=_SIDE_MAP[side.lower()],
                qty=qty,
                limit_price=limit_price,
                time_in_force=_TIF_MAP.get(time_in_force.lower(), TimeInForce.DAY),
                order_class="bracket",
                stop_loss={"stop_price": stop_loss_price},
                take_profit={"limit_price": take_profit_price},
            )
            order = await asyncio.to_thread(self.client.submit_order, req)
            return {
                "order_id": str(order.id),
                "status": str(order.status),
                "symbol": symbol,
                "legs": [str(leg.id) for leg in (order.legs or [])],
            }
        except APIError as exc:
            raise AlpacaWriteError(f"Alpaca bracket order failed: {exc}") from exc

    # ── Order management ────────────────────────────────────────

    @tool_schema(CancelOrderInput)
    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel a specific pending order by its Alpaca order ID."""
        try:
            await asyncio.to_thread(self.client.cancel_order_by_id, order_id)
            return {"cancelled": True, "order_id": order_id}
        except APIError as exc:
            raise AlpacaWriteError(f"Cancel order failed: {exc}") from exc

    async def cancel_all_orders(self) -> Dict[str, Any]:
        """Cancel all open orders on Alpaca."""
        try:
            result = await asyncio.to_thread(self.client.cancel_orders)
            return {"cancelled_count": len(result) if result else 0}
        except APIError as exc:
            raise AlpacaWriteError(f"Cancel all orders failed: {exc}") from exc

    @tool_schema(ReplaceOrderInput)
    async def replace_order(
        self, order_id: str, qty: Optional[float] = None,
        limit_price: Optional[float] = None, stop_price: Optional[float] = None,
        time_in_force: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Replace (modify) an existing order's price or quantity."""
        try:
            kw: Dict[str, Any] = {}
            if qty is not None:
                kw["qty"] = qty
            if limit_price is not None:
                kw["limit_price"] = limit_price
            if stop_price is not None:
                kw["stop_price"] = stop_price
            if time_in_force is not None:
                kw["time_in_force"] = _TIF_MAP.get(time_in_force.lower(), TimeInForce.DAY)
            req = ReplaceOrderRequest(**kw)
            order = await asyncio.to_thread(self.client.replace_order_by_id, order_id, req)
            return {"order_id": str(order.id), "status": str(order.status)}
        except APIError as exc:
            raise AlpacaWriteError(f"Replace order failed: {exc}") from exc

    # ── Position management ─────────────────────────────────────

    @tool_schema(ClosePositionInput)
    async def close_position(self, symbol: str, qty: Optional[float] = None) -> Dict[str, Any]:
        """Close a position (fully or partially) for the given symbol."""
        try:
            kw: Dict[str, Any] = {}
            if qty is not None:
                kw["qty"] = str(qty)
            result = await asyncio.to_thread(self.client.close_position, symbol.upper(), **kw)
            return {"closed": True, "symbol": symbol, "order_id": str(result.id)}
        except APIError as exc:
            raise AlpacaWriteError(f"Close position failed: {exc}") from exc

    async def close_all_positions(self) -> Dict[str, Any]:
        """Close all open positions. Use with extreme caution."""
        try:
            result = await asyncio.to_thread(self.client.close_all_positions, cancel_orders=True)
            return {"closed_count": len(result) if result else 0}
        except APIError as exc:
            raise AlpacaWriteError(f"Close all positions failed: {exc}") from exc

    # ── Read helpers (needed by executors) ──────────────────────

    async def get_account(self) -> Dict[str, Any]:
        """Get the Alpaca trading account summary."""
        try:
            acct = await asyncio.to_thread(self.client.get_account)
            return acct.model_dump()
        except APIError as exc:
            raise AlpacaWriteError(f"Get account failed: {exc}") from exc

    @tool_schema(GetOrdersInput)
    async def get_orders(self, status: str = "open", limit: int = 50) -> List[Dict[str, Any]]:
        """List orders with optional status filter."""
        try:
            req = GetOrdersRequest(
                status=_STATUS_MAP.get(status.lower(), QueryOrderStatus.OPEN),
                limit=limit,
            )
            orders = await asyncio.to_thread(self.client.get_orders, req)
            return [o.model_dump() for o in orders]
        except APIError as exc:
            raise AlpacaWriteError(f"Get orders failed: {exc}") from exc

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions."""
        try:
            positions = await asyncio.to_thread(self.client.get_all_positions)
            return [p.model_dump() for p in positions]
        except APIError as exc:
            raise AlpacaWriteError(f"Get positions failed: {exc}") from exc

    @tool_schema(GetPositionInput)
    async def get_position(self, symbol: str) -> Dict[str, Any]:
        """Get a specific position by symbol."""
        try:
            pos = await asyncio.to_thread(self.client.get_open_position, symbol.upper())
            return pos.model_dump()
        except APIError as exc:
            raise AlpacaWriteError(f"Get position failed: {exc}") from exc
