"""Binance write-side toolkit for crypto order execution (Spot & Futures)."""
from __future__ import annotations

import time
import hmac
import hashlib
import uuid
from decimal import Decimal
from urllib.parse import urlencode
from typing import Any, Dict, List, Optional
from navconfig import config
from navconfig.logging import logging
from pydantic import BaseModel, Field
from ...interfaces.http import HTTPService
from ...tools.toolkit import AbstractToolkit
from ...tools.decorators import tool_schema
from ..paper_trading import (
    ExecutionMode,
    PaperTradingMixin,
    SimulatedOrder,
    VirtualPortfolio,
)


class BinanceWriteError(RuntimeError):
    """Raised when a Binance write operation fails."""


# =============================================================================
# Pydantic input schemas
# =============================================================================

class SpotLimitOrderInput(BaseModel):
    """Place a spot limit order."""
    symbol: str = Field(..., description="Trading pair (e.g. BTCUSDT).")
    side: str = Field(..., description="Order side: 'BUY' or 'SELL'.")
    quantity: float = Field(..., description="Order quantity.", gt=0)
    price: float = Field(..., description="Limit price.", gt=0)
    time_in_force: str = Field("GTC", description="Time in force: 'GTC', 'IOC', 'FOK'.")


class SpotStopLimitOrderInput(BaseModel):
    """Place a spot stop-limit order."""
    symbol: str = Field(..., description="Trading pair.")
    side: str = Field(..., description="Order side: 'BUY' or 'SELL'.")
    quantity: float = Field(..., description="Order quantity.", gt=0)
    price: float = Field(..., description="Limit price.", gt=0)
    stop_price: float = Field(..., description="Stop trigger price.", gt=0)
    time_in_force: str = Field("GTC", description="Time in force.")


class SpotOCOOrderInput(BaseModel):
    """Place a spot OCO (One-Cancels-Other) order."""
    symbol: str = Field(..., description="Trading pair.")
    side: str = Field(..., description="Order side: 'BUY' or 'SELL'.")
    quantity: float = Field(..., description="Order quantity.", gt=0)
    price: float = Field(..., description="Limit price (take-profit leg).", gt=0)
    stop_price: float = Field(..., description="Stop trigger price.", gt=0)
    stop_limit_price: float = Field(..., description="Stop-limit price.", gt=0)


class FuturesLimitOrderInput(BaseModel):
    """Place a futures limit order."""
    symbol: str = Field(..., description="Futures pair (e.g. BTCUSDT).")
    side: str = Field(..., description="Order side: 'BUY' or 'SELL'.")
    quantity: float = Field(..., description="Order quantity.", gt=0)
    price: float = Field(..., description="Limit price.", gt=0)
    time_in_force: str = Field("GTC", description="Time in force.")


class FuturesStopMarketInput(BaseModel):
    """Place a futures stop-market order."""
    symbol: str = Field(..., description="Futures pair.")
    side: str = Field(..., description="Order side: 'BUY' or 'SELL'.")
    quantity: float = Field(..., description="Order quantity.", gt=0)
    stop_price: float = Field(..., description="Stop trigger price.", gt=0)


class CancelOrderInput(BaseModel):
    """Cancel a specific order."""
    symbol: str = Field(..., description="Trading pair.")
    order_id: int = Field(..., description="Binance order ID.")


class SymbolInput(BaseModel):
    """Query by symbol."""
    symbol: str = Field(..., description="Trading pair.")


# =============================================================================
# Toolkit
# =============================================================================

class BinanceWriteToolkit(PaperTradingMixin, AbstractToolkit):
    """Write-side toolkit for Binance Spot and Futures crypto trading.

    Supports three execution modes:
        - LIVE: Production Binance endpoints
        - PAPER: Binance testnet endpoints (default)
        - DRY_RUN: Local simulation via VirtualPortfolio
    """

    name: str = "binance_write_toolkit"
    description: str = "Execute crypto trading operations on Binance: place, cancel orders and query positions."

    SPOT_PROD = "https://api.binance.com"
    SPOT_TEST = "https://testnet.binance.vision"
    FUTURES_PROD = "https://fapi.binance.com"
    FUTURES_TEST = "https://testnet.binancefuture.com"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        mode: Optional[ExecutionMode] = None,
        virtual_portfolio: Optional[VirtualPortfolio] = None,
        **kwargs,
    ):
        """Initialize BinanceWriteToolkit.

        Args:
            api_key: Binance API key (falls back to BINANCE_API_KEY env var).
            api_secret: Binance API secret (falls back to BINANCE_API_SECRET env var).
            mode: Execution mode. Defaults to PAPER if not specified.
                  PAPER mode uses testnet endpoints.
            virtual_portfolio: VirtualPortfolio instance for DRY_RUN mode.
            **kwargs: Passed to AbstractToolkit.
        """
        super().__init__(**kwargs)
        self.logger = logging.getLogger("BinanceWriteToolkit")
        self.api_key = api_key or config.get("BINANCE_API_KEY")
        self.api_secret = api_secret or config.get("BINANCE_API_SECRET")

        # Initialize paper trading mixin
        self._init_paper_trading(mode)

        # VirtualPortfolio for DRY_RUN mode
        self._virtual_portfolio = virtual_portfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio is None:
            self._virtual_portfolio = VirtualPortfolio()
            self.logger.info("Created VirtualPortfolio for DRY_RUN mode")

        # Map execution mode to testnet flag
        # PAPER -> testnet=True, LIVE -> testnet=False, DRY_RUN -> testnet=True (doesn't matter)
        self.testnet = self._execution_mode != ExecutionMode.LIVE

        self.spot_url = self.SPOT_TEST if self.testnet else self.SPOT_PROD
        self.futures_url = self.FUTURES_TEST if self.testnet else self.FUTURES_PROD

        headers: Dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key
        self._http = HTTPService(headers=headers)
        self._http._logger = self.logger

        self.logger.info(
            "BinanceWriteToolkit initialized: mode=%s, testnet=%s, spot_url=%s",
            self._execution_mode.value, self.testnet, self.spot_url
        )

    def _sign(self, params: Dict[str, Any]) -> str:
        """HMAC-SHA256 signature for signed endpoints."""
        if not self.api_secret:
            raise BinanceWriteError("BINANCE_API_SECRET is required for signed requests.")
        query = urlencode(sorted(params.items()))
        return hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()

    async def _request(
        self, base_url: str, endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False, method: str = "GET",
    ) -> Any:
        """Internal HTTP request helper."""
        if params is None:
            params = {}
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = self._sign(params)

        url = f"{base_url}{endpoint}"
        kw: Dict[str, Any] = {"method": method}
        if method == "GET":
            if params:
                url = f"{url}?{urlencode(params)}"
            kw["url"] = url
        else:
            kw["url"] = url
            kw["data"] = params

        result, error = await self._http.async_request(**kw)
        if error:
            raise BinanceWriteError(f"Binance API error on {endpoint}: {error}")
        if isinstance(result, str):
            import json
            try:
                return json.loads(result)
            except (json.JSONDecodeError, ValueError):
                pass
        return result

    def _add_mode_fields(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Add execution_mode and is_simulated fields to response dict."""
        response["execution_mode"] = self._execution_mode.value
        response["is_simulated"] = self.is_paper_trading
        return response

    async def _dry_run_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        market: str = "spot",
    ) -> Dict[str, Any]:
        """Execute an order via VirtualPortfolio in DRY_RUN mode."""
        if not self._virtual_portfolio:
            raise BinanceWriteError("VirtualPortfolio not initialized for DRY_RUN mode")

        order_id = str(uuid.uuid4())
        simulated_order = SimulatedOrder(
            order_id=order_id,
            symbol=symbol.upper(),
            platform=f"binance_{market}",
            side="buy" if side.upper() == "BUY" else "sell",
            order_type=order_type.lower(),
            quantity=Decimal(str(quantity)),
            limit_price=Decimal(str(price)) if price else None,
            stop_price=Decimal(str(stop_price)) if stop_price else None,
        )

        # Use price or stop_price for simulation
        current_price = Decimal(str(price or stop_price or 100.0))

        filled_order = await self._virtual_portfolio.place_order(
            simulated_order, current_price
        )

        self.logger.info(
            "[DRY_RUN] Simulated %s %s order: %s %s @ %s",
            market, order_type, side, symbol, price or stop_price or "market"
        )

        return self._add_mode_fields({
            "orderId": filled_order.order_id,
            "symbol": symbol.upper(),
            "status": filled_order.status.upper(),
            "side": side.upper(),
            "type": order_type.upper(),
            "origQty": str(quantity),
            "executedQty": str(filled_order.filled_quantity) if filled_order.filled_quantity else "0",
            "price": str(price) if price else "0",
            "fills": [{
                "price": str(filled_order.filled_price) if filled_order.filled_price else "0",
                "qty": str(filled_order.filled_quantity) if filled_order.filled_quantity else "0",
            }] if filled_order.status == "filled" else [],
        })

    # ── Spot trading ────────────────────────────────────────────

    @tool_schema(SpotLimitOrderInput)
    async def spot_place_limit_order(
        self, symbol: str, side: str, quantity: float, price: float, time_in_force: str = "GTC"
    ) -> Dict[str, Any]:
        """Place a spot limit order on Binance."""
        # DRY_RUN: Route to VirtualPortfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            return await self._dry_run_order(
                symbol=symbol, side=side, quantity=quantity,
                order_type="limit", price=price, market="spot",
            )

        result = await self._request(self.spot_url, "/api/v3/order", {
            "symbol": symbol.upper(), "side": side.upper(), "type": "LIMIT",
            "quantity": str(quantity), "price": str(price),
            "timeInForce": time_in_force.upper(),
        }, signed=True, method="POST")
        return self._add_mode_fields(result)

    @tool_schema(SpotStopLimitOrderInput)
    async def spot_place_stop_limit_order(
        self, symbol: str, side: str, quantity: float, price: float,
        stop_price: float, time_in_force: str = "GTC"
    ) -> Dict[str, Any]:
        """Place a spot stop-limit order on Binance."""
        # DRY_RUN: Route to VirtualPortfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            return await self._dry_run_order(
                symbol=symbol, side=side, quantity=quantity,
                order_type="stop_limit", price=price, stop_price=stop_price, market="spot",
            )

        result = await self._request(self.spot_url, "/api/v3/order", {
            "symbol": symbol.upper(), "side": side.upper(), "type": "STOP_LOSS_LIMIT",
            "quantity": str(quantity), "price": str(price),
            "stopPrice": str(stop_price), "timeInForce": time_in_force.upper(),
        }, signed=True, method="POST")
        return self._add_mode_fields(result)

    @tool_schema(SpotOCOOrderInput)
    async def spot_place_oco_order(
        self, symbol: str, side: str, quantity: float,
        price: float, stop_price: float, stop_limit_price: float,
    ) -> Dict[str, Any]:
        """Place a spot OCO (One-Cancels-Other) order on Binance."""
        # DRY_RUN: Route to VirtualPortfolio (simulate as single limit order)
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            return await self._dry_run_order(
                symbol=symbol, side=side, quantity=quantity,
                order_type="limit", price=price, market="spot",
            )

        result = await self._request(self.spot_url, "/api/v3/order/oco", {
            "symbol": symbol.upper(), "side": side.upper(),
            "quantity": str(quantity), "price": str(price),
            "stopPrice": str(stop_price), "stopLimitPrice": str(stop_limit_price),
            "stopLimitTimeInForce": "GTC",
        }, signed=True, method="POST")
        return self._add_mode_fields(result)

    @tool_schema(CancelOrderInput)
    async def spot_cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """Cancel a spot order on Binance."""
        # DRY_RUN: Cancel in VirtualPortfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            cancelled = await self._virtual_portfolio.cancel_order(str(order_id))
            return self._add_mode_fields({
                "symbol": symbol.upper(),
                "orderId": order_id,
                "status": "CANCELED" if cancelled else "NOT_FOUND",
            })

        result = await self._request(self.spot_url, "/api/v3/order", {
            "symbol": symbol.upper(), "orderId": order_id,
        }, signed=True, method="DELETE")
        return self._add_mode_fields(result)

    @tool_schema(SymbolInput)
    async def spot_get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Get open spot orders for a symbol."""
        # DRY_RUN: Return orders from VirtualPortfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            open_orders = self._virtual_portfolio.get_open_orders()
            return [
                self._add_mode_fields({
                    "orderId": o.order_id,
                    "symbol": o.symbol,
                    "side": o.side.upper(),
                    "type": o.order_type.upper(),
                    "origQty": str(o.quantity),
                    "status": o.status.upper(),
                })
                for o in open_orders if o.symbol.upper() == symbol.upper()
            ]

        return await self._request(self.spot_url, "/api/v3/openOrders", {
            "symbol": symbol.upper(),
        }, signed=True)

    async def spot_get_account(self) -> Dict[str, Any]:
        """Get spot account balances."""
        # DRY_RUN: Return virtual portfolio state
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            state = self._virtual_portfolio.get_state()
            return self._add_mode_fields({
                "balances": [
                    {"asset": "USDT", "free": str(state.cash_balance), "locked": "0"},
                ] + [
                    {"asset": p.symbol, "free": str(p.quantity), "locked": "0"}
                    for p in state.positions
                ],
            })

        return await self._request(self.spot_url, "/api/v3/account", signed=True)

    # ── Futures trading ─────────────────────────────────────────

    @tool_schema(FuturesLimitOrderInput)
    async def futures_place_limit_order(
        self, symbol: str, side: str, quantity: float, price: float, time_in_force: str = "GTC"
    ) -> Dict[str, Any]:
        """Place a USDT-M futures limit order on Binance."""
        # DRY_RUN: Route to VirtualPortfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            return await self._dry_run_order(
                symbol=symbol, side=side, quantity=quantity,
                order_type="limit", price=price, market="futures",
            )

        result = await self._request(self.futures_url, "/fapi/v1/order", {
            "symbol": symbol.upper(), "side": side.upper(), "type": "LIMIT",
            "quantity": str(quantity), "price": str(price),
            "timeInForce": time_in_force.upper(),
        }, signed=True, method="POST")
        return self._add_mode_fields(result)

    @tool_schema(FuturesStopMarketInput)
    async def futures_place_stop_market_order(
        self, symbol: str, side: str, quantity: float, stop_price: float,
    ) -> Dict[str, Any]:
        """Place a USDT-M futures stop-market order on Binance."""
        # DRY_RUN: Route to VirtualPortfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            return await self._dry_run_order(
                symbol=symbol, side=side, quantity=quantity,
                order_type="stop", stop_price=stop_price, market="futures",
            )

        result = await self._request(self.futures_url, "/fapi/v1/order", {
            "symbol": symbol.upper(), "side": side.upper(), "type": "STOP_MARKET",
            "quantity": str(quantity), "stopPrice": str(stop_price),
        }, signed=True, method="POST")
        return self._add_mode_fields(result)

    @tool_schema(CancelOrderInput)
    async def futures_cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """Cancel a futures order on Binance."""
        # DRY_RUN: Cancel in VirtualPortfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            cancelled = await self._virtual_portfolio.cancel_order(str(order_id))
            return self._add_mode_fields({
                "symbol": symbol.upper(),
                "orderId": order_id,
                "status": "CANCELED" if cancelled else "NOT_FOUND",
            })

        result = await self._request(self.futures_url, "/fapi/v1/order", {
            "symbol": symbol.upper(), "orderId": order_id,
        }, signed=True, method="DELETE")
        return self._add_mode_fields(result)

    @tool_schema(SymbolInput)
    async def futures_get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Get open futures orders for a symbol."""
        # DRY_RUN: Return orders from VirtualPortfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            open_orders = self._virtual_portfolio.get_open_orders()
            return [
                self._add_mode_fields({
                    "orderId": o.order_id,
                    "symbol": o.symbol,
                    "side": o.side.upper(),
                    "type": o.order_type.upper(),
                    "origQty": str(o.quantity),
                    "status": o.status.upper(),
                })
                for o in open_orders if o.symbol.upper() == symbol.upper()
            ]

        return await self._request(self.futures_url, "/fapi/v1/openOrders", {
            "symbol": symbol.upper(),
        }, signed=True)

    async def futures_get_positions(self) -> List[Dict[str, Any]]:
        """Get all USDT-M futures positions."""
        # DRY_RUN: Return positions from VirtualPortfolio
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            positions = self._virtual_portfolio.get_positions()
            return [
                self._add_mode_fields({
                    "symbol": p.symbol,
                    "positionAmt": str(p.quantity) if p.side == "long" else str(-p.quantity),
                    "entryPrice": str(p.avg_entry_price),
                    "unrealizedProfit": str(p.unrealized_pnl or 0),
                })
                for p in positions
            ]

        return await self._request(self.futures_url, "/fapi/v2/positionRisk", signed=True)
