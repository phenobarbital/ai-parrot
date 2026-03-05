"""Alpaca write-side toolkit for order execution on stocks and ETFs."""
from __future__ import annotations

import asyncio
import math
import uuid
from decimal import Decimal
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
    TimeInForce,
    QueryOrderStatus,
)
from alpaca.common.exceptions import APIError

from ...tools.toolkit import AbstractToolkit
from ...tools.decorators import tool_schema
from ..paper_trading import (
    ExecutionMode,
    PaperTradingMixin,
    SimulatedOrder,
    VirtualPortfolio,
)


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
    time_in_force: str = Field("gtc", description="Time in force: 'gtc' (default), 'day', 'ioc', 'fok'.")


class PlaceStopOrderInput(BaseModel):
    """Place a stop order."""
    symbol: str = Field(..., description="Ticker symbol.")
    side: str = Field(..., description="Order side: 'buy' or 'sell'.")
    qty: float = Field(..., description="Number of shares.", gt=0)
    stop_price: float = Field(..., description="Stop trigger price in USD.", gt=0)
    time_in_force: str = Field("gtc", description="Time in force: 'gtc' (default), 'day', 'ioc', 'fok'.")


class PlaceStopLimitOrderInput(BaseModel):
    """Place a stop-limit order."""
    symbol: str = Field(..., description="Ticker symbol.")
    side: str = Field(..., description="Order side: 'buy' or 'sell'.")
    qty: float = Field(..., description="Number of shares.", gt=0)
    stop_price: float = Field(..., description="Stop trigger price.", gt=0)
    limit_price: float = Field(..., description="Limit price after trigger.", gt=0)
    time_in_force: str = Field("gtc", description="Time in force: 'gtc' (default), 'day', 'ioc', 'fok'.")


class PlaceTrailingStopInput(BaseModel):
    """Place a trailing-stop order."""
    symbol: str = Field(..., description="Ticker symbol.")
    side: str = Field(..., description="Order side: 'buy' or 'sell'.")
    qty: float = Field(..., description="Number of shares.", gt=0)
    trail_percent: Optional[float] = Field(None, description="Trail offset in percent.", gt=0)
    trail_price: Optional[float] = Field(None, description="Trail offset in USD.", gt=0)
    time_in_force: str = Field("gtc", description="Time in force: 'gtc' (default), 'day', 'ioc', 'fok'.")


class PlaceBracketOrderInput(BaseModel):
    """Place a bracket (OTO) order with stop-loss and take-profit legs."""
    symbol: str = Field(..., description="Ticker symbol.")
    side: str = Field(..., description="Order side: 'buy' or 'sell'.")
    qty: float = Field(..., description="Number of shares.", gt=0)
    limit_price: float = Field(..., description="Entry limit price.", gt=0)
    stop_loss_price: float = Field(..., description="Stop-loss trigger price.", gt=0)
    take_profit_price: float = Field(..., description="Take-profit limit price.", gt=0)
    time_in_force: str = Field("gtc", description="Time in force: 'gtc' (default), 'day', 'ioc', 'fok'.")


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


class AlpacaWriteToolkit(PaperTradingMixin, AbstractToolkit):
    """Write-side toolkit for Alpaca (stocks & ETFs).

    Supports three execution modes:
        - LIVE: Real trading with real money
        - PAPER: Alpaca's native paper trading (default)
        - DRY_RUN: Local simulation via VirtualPortfolio
    """

    name: str = "alpaca_write_toolkit"
    description: str = "Execute trading operations on Alpaca: place, cancel, replace orders and manage positions."

    def __init__(
        self,
        mode: Optional[ExecutionMode] = None,
        virtual_portfolio: Optional[VirtualPortfolio] = None,
        **kwargs,
    ):
        """Initialize AlpacaWriteToolkit.

        Args:
            mode: Execution mode. Defaults to PAPER if not specified.
            virtual_portfolio: VirtualPortfolio instance for DRY_RUN mode.
                If DRY_RUN is requested but no portfolio provided, one is created.
            **kwargs: Passed to AbstractToolkit.
        """
        super().__init__(**kwargs)
        self.logger = logging.getLogger("AlpacaWriteToolkit")
        self.api_key = config.get("ALPACA_TRADING_API_KEY") or config.get("ALPACA_MARKETS_CLIENT_ID")
        self.api_secret = config.get("ALPACA_TRADING_API_SECRET") or config.get("ALPACA_MARKETS_CLIENT_SECRET")
        self.paper = config.get("ALPACA_PCB_PAPER", section="finance", fallback=True)
        self.base_url = config.get("ALPACA_API_BASE_URL", section="finance", fallback=None)
        self._client: Optional[TradingClient] = None

        # Initialize paper trading mixin
        self._init_paper_trading(mode)

        # VirtualPortfolio for DRY_RUN mode
        self._virtual_portfolio = virtual_portfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio is None:
            self._virtual_portfolio = VirtualPortfolio()
            self.logger.info("Created VirtualPortfolio for DRY_RUN mode")

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

    async def ensure_paper_mode(self) -> bool:
        """Verify that the connected Alpaca account is a paper trading account.

        Returns:
            True if paper account is confirmed.

        Raises:
            AlpacaWriteError: If account type cannot be verified or is not paper.
        """
        if self._execution_mode == ExecutionMode.DRY_RUN:
            # DRY_RUN doesn't connect to Alpaca at all
            self.logger.info("DRY_RUN mode - no Alpaca account verification needed")
            return True

        try:
            acct = await asyncio.to_thread(self.client.get_account)
            # Alpaca paper accounts have account_number starting with 'PA'
            # or the account_type field indicates paper
            is_paper = (
                getattr(acct, 'account_number', '').startswith('PA')
                or getattr(acct, 'status', '') == 'PAPER_ONLY'
                or self.paper  # Trust the client config
            )
            if self._execution_mode == ExecutionMode.PAPER and not is_paper:
                raise AlpacaWriteError(
                    "PAPER mode requested but connected to LIVE account. "
                    "Set ALPACA_PCB_PAPER=true or use paper API credentials."
                )
            self.logger.info(
                "Alpaca account verified: paper=%s, mode=%s",
                is_paper, self._execution_mode.value
            )
            return is_paper
        except APIError as exc:
            raise AlpacaWriteError(f"Failed to verify account type: {exc}") from exc

    def _add_mode_fields(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Add execution_mode and is_simulated fields to response dict."""
        response["execution_mode"] = self._execution_mode.value
        response["is_simulated"] = self.is_paper_trading
        return response

    async def _dry_run_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute an order via VirtualPortfolio in DRY_RUN mode."""
        if not self._virtual_portfolio:
            raise AlpacaWriteError("VirtualPortfolio not initialized for DRY_RUN mode")

        order_id = str(uuid.uuid4())
        simulated_order = SimulatedOrder(
            order_id=order_id,
            symbol=symbol.upper(),
            platform="alpaca",
            side="buy" if side.lower() == "buy" else "sell",
            order_type=order_type,
            quantity=Decimal(str(qty)),
            limit_price=Decimal(str(limit_price)) if limit_price else None,
            stop_price=Decimal(str(stop_price)) if stop_price else None,
        )

        # Use limit_price or a default market price for simulation
        current_price = Decimal(str(limit_price or 100.0))

        filled_order = await self._virtual_portfolio.place_order(
            simulated_order, current_price
        )

        self.logger.info(
            "[DRY_RUN] Simulated %s order: %s %s @ %s",
            order_type, side, symbol, limit_price or "market"
        )

        return self._add_mode_fields({
            "order_id": filled_order.order_id,
            "status": filled_order.status,
            "symbol": symbol.upper(),
            "filled_price": float(filled_order.filled_price) if filled_order.filled_price else None,
            "filled_quantity": float(filled_order.filled_quantity) if filled_order.filled_quantity else None,
        })

    # ── Order placement ─────────────────────────────────────────

    @tool_schema(PlaceLimitOrderInput)
    async def place_limit_order(
        self, symbol: str, side: str, qty: float, limit_price: float, time_in_force: str = "gtc"
    ) -> Dict[str, Any]:
        """Place a limit order for a stock or ETF on Alpaca."""
        # DRY_RUN: Route to VirtualPortfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            return await self._dry_run_order(
                symbol=symbol, side=side, qty=qty,
                order_type="limit", limit_price=limit_price,
            )

        try:
            req = LimitOrderRequest(
                symbol=symbol.upper(),
                side=_SIDE_MAP[side.lower()],
                qty=qty,
                limit_price=limit_price,
                time_in_force=_TIF_MAP.get(time_in_force.lower(), TimeInForce.GTC),
            )
            order = await asyncio.to_thread(self.client.submit_order, req)
            return self._add_mode_fields({
                "order_id": str(order.id), "status": str(order.status), "symbol": symbol
            })
        except APIError as exc:
            raise AlpacaWriteError(f"Alpaca limit order failed: {exc}") from exc

    @tool_schema(PlaceStopOrderInput)
    async def place_stop_order(
        self, symbol: str, side: str, qty: float, stop_price: float, time_in_force: str = "gtc"
    ) -> Dict[str, Any]:
        """Place a stop order on Alpaca."""
        # DRY_RUN: Route to VirtualPortfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            return await self._dry_run_order(
                symbol=symbol, side=side, qty=qty,
                order_type="stop", stop_price=stop_price,
            )

        try:
            req = StopOrderRequest(
                symbol=symbol.upper(),
                side=_SIDE_MAP[side.lower()],
                qty=qty,
                stop_price=stop_price,
                time_in_force=_TIF_MAP.get(time_in_force.lower(), TimeInForce.GTC),
            )
            order = await asyncio.to_thread(self.client.submit_order, req)
            return self._add_mode_fields({
                "order_id": str(order.id), "status": str(order.status), "symbol": symbol
            })
        except APIError as exc:
            err_str = str(exc)
            # Wash-trade: opposite-side order already exists for this symbol.
            # Return structured error so the agent can cancel the conflicting
            # order or switch to a bracket order instead of crashing.
            if "wash trade" in err_str.lower() or "40310000" in err_str:
                self.logger.warning(
                    "Wash trade detected for %s stop order — "
                    "an opposite-side order already exists. "
                    "Use a bracket (OTO) order instead.",
                    symbol,
                )
                return self._add_mode_fields({
                    "error": "wash_trade_detected",
                    "symbol": symbol,
                    "message": (
                        f"Stop order rejected: an opposite-side order already "
                        f"exists for {symbol}. Use place_bracket_oto_order to "
                        f"combine entry + stop-loss in a single order, or "
                        f"cancel the existing order first."
                    ),
                    "raw_error": err_str,
                })
            raise AlpacaWriteError(f"Alpaca stop order failed: {exc}") from exc

    @tool_schema(PlaceStopLimitOrderInput)
    async def place_stop_limit_order(
        self, symbol: str, side: str, qty: float, stop_price: float, limit_price: float, time_in_force: str = "gtc"
    ) -> Dict[str, Any]:
        """Place a stop-limit order on Alpaca."""
        # DRY_RUN: Route to VirtualPortfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            return await self._dry_run_order(
                symbol=symbol, side=side, qty=qty,
                order_type="stop_limit", stop_price=stop_price, limit_price=limit_price,
            )

        try:
            req = StopLimitOrderRequest(
                symbol=symbol.upper(),
                side=_SIDE_MAP[side.lower()],
                qty=qty,
                stop_price=stop_price,
                limit_price=limit_price,
                time_in_force=_TIF_MAP.get(time_in_force.lower(), TimeInForce.GTC),
            )
            order = await asyncio.to_thread(self.client.submit_order, req)
            return self._add_mode_fields({
                "order_id": str(order.id), "status": str(order.status), "symbol": symbol
            })
        except APIError as exc:
            raise AlpacaWriteError(f"Alpaca stop-limit order failed: {exc}") from exc

    @tool_schema(PlaceTrailingStopInput)
    async def place_trailing_stop_order(
        self, symbol: str, side: str, qty: float,
        trail_percent: Optional[float] = None, trail_price: Optional[float] = None,
        time_in_force: str = "gtc"
    ) -> Dict[str, Any]:
        """Place a trailing-stop order on Alpaca."""
        if not trail_percent and not trail_price:
            raise AlpacaWriteError("Provide either trail_percent or trail_price.")

        # DRY_RUN: Route to VirtualPortfolio (simulated as stop order)
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            # For trailing stop, use trail_price as stop_price for simulation
            stop_price = trail_price or 100.0  # Default if only percent given
            return await self._dry_run_order(
                symbol=symbol, side=side, qty=qty,
                order_type="stop", stop_price=stop_price,
            )

        try:
            req = TrailingStopOrderRequest(
                symbol=symbol.upper(),
                side=_SIDE_MAP[side.lower()],
                qty=qty,
                trail_percent=trail_percent,
                trail_price=trail_price,
                time_in_force=_TIF_MAP.get(time_in_force.lower(), TimeInForce.GTC),
            )
            order = await asyncio.to_thread(self.client.submit_order, req)
            return self._add_mode_fields({
                "order_id": str(order.id), "status": str(order.status), "symbol": symbol
            })
        except APIError as exc:
            raise AlpacaWriteError(f"Alpaca trailing-stop order failed: {exc}") from exc

    @tool_schema(PlaceBracketOrderInput)
    async def place_bracket_oto_order(
        self, symbol: str, side: str, qty: float,
        limit_price: float, stop_loss_price: float, take_profit_price: float,
        time_in_force: str = "gtc"
    ) -> Dict[str, Any]:
        """Place a bracket (OTO) order with stop-loss and take-profit legs."""
        # DRY_RUN: Route to VirtualPortfolio (simulated as single limit order)
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            result = await self._dry_run_order(
                symbol=symbol, side=side, qty=qty,
                order_type="limit", limit_price=limit_price,
            )
            # Add empty legs for bracket simulation
            result["legs"] = []
            return result

        try:
            # Alpaca requires whole shares for bracket/complex orders.
            int_qty = max(1, math.floor(qty)) if qty != int(qty) else int(qty)
            if int_qty != qty:
                self.logger.info(
                    "Bracket order: rounded fractional qty %.4f → %d for %s",
                    qty, int_qty, symbol,
                )
            req = LimitOrderRequest(
                symbol=symbol.upper(),
                side=_SIDE_MAP[side.lower()],
                qty=int_qty,
                limit_price=limit_price,
                time_in_force=_TIF_MAP.get(time_in_force.lower(), TimeInForce.GTC),
                order_class="bracket",
                stop_loss={"stop_price": stop_loss_price},
                take_profit={"limit_price": take_profit_price},
            )
            order = await asyncio.to_thread(self.client.submit_order, req)
            return self._add_mode_fields({
                "order_id": str(order.id),
                "status": str(order.status),
                "symbol": symbol,
                "qty_requested": qty,
                "qty_submitted": int_qty,
                "legs": [str(leg.id) for leg in (order.legs or [])],
            })
        except APIError as exc:
            raise AlpacaWriteError(f"Alpaca bracket order failed: {exc}") from exc

    # ── Order management ────────────────────────────────────────

    @tool_schema(CancelOrderInput)
    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel a specific pending order by its Alpaca order ID."""
        # DRY_RUN: Cancel in VirtualPortfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            cancelled = await self._virtual_portfolio.cancel_order(order_id)
            return self._add_mode_fields({
                "cancelled": cancelled, "order_id": order_id
            })

        try:
            await asyncio.to_thread(self.client.cancel_order_by_id, order_id)
            return self._add_mode_fields({"cancelled": True, "order_id": order_id})
        except APIError as exc:
            raise AlpacaWriteError(f"Cancel order failed: {exc}") from exc

    async def cancel_all_orders(self) -> Dict[str, Any]:
        """Cancel all open orders on Alpaca."""
        # DRY_RUN: Cancel all in VirtualPortfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            open_orders = self._virtual_portfolio.get_open_orders()
            cancelled_count = 0
            for order in open_orders:
                if await self._virtual_portfolio.cancel_order(order.order_id):
                    cancelled_count += 1
            return self._add_mode_fields({"cancelled_count": cancelled_count})

        try:
            result = await asyncio.to_thread(self.client.cancel_orders)
            return self._add_mode_fields({
                "cancelled_count": len(result) if result else 0
            })
        except APIError as exc:
            raise AlpacaWriteError(f"Cancel all orders failed: {exc}") from exc

    @tool_schema(ReplaceOrderInput)
    async def replace_order(
        self, order_id: str, qty: Optional[float] = None,
        limit_price: Optional[float] = None, stop_price: Optional[float] = None,
        time_in_force: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Replace (modify) an existing order's price or quantity."""
        # DRY_RUN: Not supported in VirtualPortfolio simulation
        if self._execution_mode == ExecutionMode.DRY_RUN:
            return self._add_mode_fields({
                "order_id": order_id,
                "status": "replace_not_supported_in_dry_run",
                "message": "Order replacement not supported in DRY_RUN mode",
            })

        try:
            kw: Dict[str, Any] = {}
            if qty is not None:
                kw["qty"] = qty
            if limit_price is not None:
                kw["limit_price"] = limit_price
            if stop_price is not None:
                kw["stop_price"] = stop_price
            if time_in_force is not None:
                kw["time_in_force"] = _TIF_MAP.get(time_in_force.lower(), TimeInForce.GTC)
            req = ReplaceOrderRequest(**kw)
            order = await asyncio.to_thread(self.client.replace_order_by_id, order_id, req)
            return self._add_mode_fields({
                "order_id": str(order.id), "status": str(order.status)
            })
        except APIError as exc:
            raise AlpacaWriteError(f"Replace order failed: {exc}") from exc

    # ── Position management ─────────────────────────────────────

    @tool_schema(ClosePositionInput)
    async def close_position(self, symbol: str, qty: Optional[float] = None) -> Dict[str, Any]:
        """Close a position (fully or partially) for the given symbol."""
        # DRY_RUN: Simulate position close via sell order
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            position = self._virtual_portfolio.get_position(symbol.upper())
            if position:
                close_qty = qty or float(position.quantity)
                result = await self._dry_run_order(
                    symbol=symbol, side="sell", qty=close_qty, order_type="market"
                )
                result["closed"] = True
                return result
            return self._add_mode_fields({
                "closed": False, "symbol": symbol, "message": "No position to close"
            })

        try:
            kw: Dict[str, Any] = {}
            if qty is not None:
                kw["qty"] = str(qty)
            result = await asyncio.to_thread(self.client.close_position, symbol.upper(), **kw)
            return self._add_mode_fields({
                "closed": True, "symbol": symbol, "order_id": str(result.id)
            })
        except APIError as exc:
            raise AlpacaWriteError(f"Close position failed: {exc}") from exc

    async def close_all_positions(self) -> Dict[str, Any]:
        """Close all open positions. Use with extreme caution."""
        # DRY_RUN: Close all virtual positions
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            positions = self._virtual_portfolio.get_positions()
            closed_count = 0
            for pos in positions:
                await self._dry_run_order(
                    symbol=pos.symbol, side="sell", qty=float(pos.quantity), order_type="market"
                )
                closed_count += 1
            return self._add_mode_fields({"closed_count": closed_count})

        try:
            result = await asyncio.to_thread(self.client.close_all_positions, cancel_orders=True)
            return self._add_mode_fields({"closed_count": len(result) if result else 0})
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
