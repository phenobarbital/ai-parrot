"""Binance write-side toolkit for crypto order execution (Spot & Futures)."""
from __future__ import annotations

import time
import hmac
import hashlib
from urllib.parse import urlencode
from typing import Any, Dict, List, Optional
from navconfig import config
from navconfig.logging import logging
from pydantic import BaseModel, Field

from ...interfaces.http import HTTPService
from ...tools.toolkit import AbstractToolkit
from ...tools.decorators import tool_schema


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

class BinanceWriteToolkit(AbstractToolkit):
    """Write-side toolkit for Binance Spot and Futures crypto trading."""

    name: str = "binance_write_toolkit"
    description: str = "Execute crypto trading operations on Binance: place, cancel orders and query positions."

    SPOT_PROD = "https://api.binance.com"
    SPOT_TEST = "https://testnet.binance.vision"
    FUTURES_PROD = "https://fapi.binance.com"
    FUTURES_TEST = "https://testnet.binancefuture.com"

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger("BinanceWriteToolkit")
        self.api_key = api_key or config.get("BINANCE_API_KEY")
        self.api_secret = api_secret or config.get("BINANCE_API_SECRET")
        self.testnet = config.get("BINANCE_TESTNET", fallback=True)
        if isinstance(self.testnet, str):
            self.testnet = self.testnet.lower() in ("true", "1", "yes")

        self.spot_url = self.SPOT_TEST if self.testnet else self.SPOT_PROD
        self.futures_url = self.FUTURES_TEST if self.testnet else self.FUTURES_PROD

        headers: Dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key
        self._http = HTTPService(headers=headers)
        self._http._logger = self.logger

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

    # ── Spot trading ────────────────────────────────────────────

    @tool_schema(SpotLimitOrderInput)
    async def spot_place_limit_order(
        self, symbol: str, side: str, quantity: float, price: float, time_in_force: str = "GTC"
    ) -> Dict[str, Any]:
        """Place a spot limit order on Binance."""
        return await self._request(self.spot_url, "/api/v3/order", {
            "symbol": symbol.upper(), "side": side.upper(), "type": "LIMIT",
            "quantity": str(quantity), "price": str(price),
            "timeInForce": time_in_force.upper(),
        }, signed=True, method="POST")

    @tool_schema(SpotStopLimitOrderInput)
    async def spot_place_stop_limit_order(
        self, symbol: str, side: str, quantity: float, price: float,
        stop_price: float, time_in_force: str = "GTC"
    ) -> Dict[str, Any]:
        """Place a spot stop-limit order on Binance."""
        return await self._request(self.spot_url, "/api/v3/order", {
            "symbol": symbol.upper(), "side": side.upper(), "type": "STOP_LOSS_LIMIT",
            "quantity": str(quantity), "price": str(price),
            "stopPrice": str(stop_price), "timeInForce": time_in_force.upper(),
        }, signed=True, method="POST")

    @tool_schema(SpotOCOOrderInput)
    async def spot_place_oco_order(
        self, symbol: str, side: str, quantity: float,
        price: float, stop_price: float, stop_limit_price: float,
    ) -> Dict[str, Any]:
        """Place a spot OCO (One-Cancels-Other) order on Binance."""
        return await self._request(self.spot_url, "/api/v3/order/oco", {
            "symbol": symbol.upper(), "side": side.upper(),
            "quantity": str(quantity), "price": str(price),
            "stopPrice": str(stop_price), "stopLimitPrice": str(stop_limit_price),
            "stopLimitTimeInForce": "GTC",
        }, signed=True, method="POST")

    @tool_schema(CancelOrderInput)
    async def spot_cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """Cancel a spot order on Binance."""
        return await self._request(self.spot_url, "/api/v3/order", {
            "symbol": symbol.upper(), "orderId": order_id,
        }, signed=True, method="DELETE")

    @tool_schema(SymbolInput)
    async def spot_get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Get open spot orders for a symbol."""
        return await self._request(self.spot_url, "/api/v3/openOrders", {
            "symbol": symbol.upper(),
        }, signed=True)

    async def spot_get_account(self) -> Dict[str, Any]:
        """Get spot account balances."""
        return await self._request(self.spot_url, "/api/v3/account", signed=True)

    # ── Futures trading ─────────────────────────────────────────

    @tool_schema(FuturesLimitOrderInput)
    async def futures_place_limit_order(
        self, symbol: str, side: str, quantity: float, price: float, time_in_force: str = "GTC"
    ) -> Dict[str, Any]:
        """Place a USDT-M futures limit order on Binance."""
        return await self._request(self.futures_url, "/fapi/v1/order", {
            "symbol": symbol.upper(), "side": side.upper(), "type": "LIMIT",
            "quantity": str(quantity), "price": str(price),
            "timeInForce": time_in_force.upper(),
        }, signed=True, method="POST")

    @tool_schema(FuturesStopMarketInput)
    async def futures_place_stop_market_order(
        self, symbol: str, side: str, quantity: float, stop_price: float,
    ) -> Dict[str, Any]:
        """Place a USDT-M futures stop-market order on Binance."""
        return await self._request(self.futures_url, "/fapi/v1/order", {
            "symbol": symbol.upper(), "side": side.upper(), "type": "STOP_MARKET",
            "quantity": str(quantity), "stopPrice": str(stop_price),
        }, signed=True, method="POST")

    @tool_schema(CancelOrderInput)
    async def futures_cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """Cancel a futures order on Binance."""
        return await self._request(self.futures_url, "/fapi/v1/order", {
            "symbol": symbol.upper(), "orderId": order_id,
        }, signed=True, method="DELETE")

    @tool_schema(SymbolInput)
    async def futures_get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Get open futures orders for a symbol."""
        return await self._request(self.futures_url, "/fapi/v1/openOrders", {
            "symbol": symbol.upper(),
        }, signed=True)

    async def futures_get_positions(self) -> List[Dict[str, Any]]:
        """Get all USDT-M futures positions."""
        return await self._request(self.futures_url, "/fapi/v2/positionRisk", signed=True)
