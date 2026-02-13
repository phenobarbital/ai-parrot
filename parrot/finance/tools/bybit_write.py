"""Bybit write-side toolkit for crypto order execution (Unified v5 API)."""
from __future__ import annotations

import time
import hmac
import hashlib
from urllib.parse import urlencode
from typing import Any, Dict, Optional
from navconfig import config
from navconfig.logging import logging
from pydantic import BaseModel, Field

from ...interfaces.http import HTTPService
from ...tools.toolkit import AbstractToolkit
from ...tools.decorators import tool_schema


class BybitWriteError(RuntimeError):
    """Raised when a Bybit write operation fails."""


# =============================================================================
# Pydantic input schemas
# =============================================================================

class PlaceLimitOrderInput(BaseModel):
    """Place a limit order on Bybit."""
    category: str = Field("linear", description="Product type: 'spot', 'linear', or 'inverse'.")
    symbol: str = Field(..., description="Trading pair (e.g. BTCUSDT).")
    side: str = Field(..., description="Order side: 'Buy' or 'Sell'.")
    qty: str = Field(..., description="Order quantity as string.")
    price: str = Field(..., description="Limit price as string.")
    time_in_force: str = Field("GTC", description="Time in force: 'GTC', 'IOC', 'FOK', 'PostOnly'.")


class PlaceMarketOrderInput(BaseModel):
    """Place a market order on Bybit."""
    category: str = Field("linear", description="Product type: 'spot', 'linear', or 'inverse'.")
    symbol: str = Field(..., description="Trading pair.")
    side: str = Field(..., description="Order side: 'Buy' or 'Sell'.")
    qty: str = Field(..., description="Order quantity as string.")


class PlaceStopOrderInput(BaseModel):
    """Place a conditional (stop) order on Bybit."""
    category: str = Field("linear", description="Product type.")
    symbol: str = Field(..., description="Trading pair.")
    side: str = Field(..., description="Order side: 'Buy' or 'Sell'.")
    qty: str = Field(..., description="Order quantity as string.")
    trigger_price: str = Field(..., description="Trigger price as string.")
    order_type: str = Field("Market", description="'Limit' or 'Market' after trigger.")
    price: Optional[str] = Field(None, description="Limit price (required if order_type='Limit').")


class CancelOrderInput(BaseModel):
    """Cancel a specific order."""
    category: str = Field("linear", description="Product type.")
    symbol: str = Field(..., description="Trading pair.")
    order_id: str = Field(..., description="Bybit order ID.")


class CancelAllOrdersInput(BaseModel):
    """Cancel all orders for a category/symbol."""
    category: str = Field("linear", description="Product type.")
    symbol: Optional[str] = Field(None, description="Trading pair (optional).")


class QueryOrdersInput(BaseModel):
    """Query open orders."""
    category: str = Field("linear", description="Product type.")
    symbol: Optional[str] = Field(None, description="Filter by trading pair.")
    limit: int = Field(50, description="Max results.", le=200)


class QueryPositionsInput(BaseModel):
    """Query positions."""
    category: str = Field("linear", description="Product type.")
    symbol: Optional[str] = Field(None, description="Filter by trading pair.")


class WalletBalanceInput(BaseModel):
    """Query wallet balance."""
    account_type: str = Field("UNIFIED", description="Account type: 'UNIFIED', 'CONTRACT', 'SPOT'.")


# =============================================================================
# Toolkit
# =============================================================================

class BybitWriteToolkit(AbstractToolkit):
    """Write-side toolkit for Bybit crypto trading (Unified v5 API)."""

    name: str = "bybit_write_toolkit"
    description: str = "Execute crypto trading operations on Bybit: place, cancel orders and query positions."

    PROD_URL = "https://api.bybit.com"
    TEST_URL = "https://api-testnet.bybit.com"

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger("BybitWriteToolkit")
        self.api_key = api_key or config.get("BYBIT_API_KEY")
        self.api_secret = api_secret or config.get("BYBIT_API_SECRET")
        self.testnet = config.get("BYBIT_TESTNET", fallback=True)
        if isinstance(self.testnet, str):
            self.testnet = self.testnet.lower() in ("true", "1", "yes")

        self.base_url = self.TEST_URL if self.testnet else self.PROD_URL
        self._http = HTTPService(headers={"Content-Type": "application/json"})
        self._http._logger = self.logger

    def _sign(self, timestamp: str, payload: str) -> str:
        """HMAC-SHA256 signature for Bybit v5 API."""
        if not self.api_key or not self.api_secret:
            raise BybitWriteError("BYBIT_API_KEY / SECRET not configured.")
        recv_window = "5000"
        param_str = f"{timestamp}{self.api_key}{recv_window}{payload}"
        return hmac.new(
            self.api_secret.encode(), param_str.encode(), hashlib.sha256
        ).hexdigest()

    def _auth_headers(self, timestamp: str, signature: str) -> Dict[str, str]:
        """Build Bybit v5 authentication headers."""
        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": "5000",
        }

    async def _request(
        self, method: str, endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Signed HTTP request to Bybit v5 API."""
        import json as _json

        if params is None:
            params = {}
        timestamp = str(int(time.time() * 1000))

        old_headers = dict(self._http.headers)
        try:
            if method == "GET":
                query = urlencode(params) if params else ""
                signature = self._sign(timestamp, query)
                self._http.headers.update(self._auth_headers(timestamp, signature))
                url = f"{self.base_url}{endpoint}"
                if query:
                    url = f"{url}?{query}"
                result, error = await self._http.async_request(url=url, method="GET")
            else:
                body = _json.dumps(params)
                signature = self._sign(timestamp, body)
                auth = self._auth_headers(timestamp, signature)
                auth["Content-Type"] = "application/json"
                self._http.headers.update(auth)
                url = f"{self.base_url}{endpoint}"
                result, error = await self._http.async_request(
                    url=url, method="POST", data=body
                )
        finally:
            self._http.headers = old_headers

        if error:
            raise BybitWriteError(f"Bybit API error on {endpoint}: {error}")
        if isinstance(result, str):
            try:
                result = _json.loads(result)
            except (ValueError, _json.JSONDecodeError):
                pass
        # Bybit v5 wraps responses in {"retCode": 0, "result": {...}}
        if isinstance(result, dict) and result.get("retCode", 0) != 0:
            raise BybitWriteError(
                f"Bybit retCode={result.get('retCode')}: {result.get('retMsg', 'unknown')}"
            )
        return result.get("result", result) if isinstance(result, dict) else result

    # ── Order placement ─────────────────────────────────────────

    @tool_schema(PlaceLimitOrderInput)
    async def place_limit_order(
        self, category: str, symbol: str, side: str, qty: str, price: str,
        time_in_force: str = "GTC",
    ) -> Dict[str, Any]:
        """Place a limit order on Bybit (spot, linear, or inverse)."""
        return await self._request("POST", "/v5/order/create", {
            "category": category, "symbol": symbol.upper(),
            "side": side.capitalize(), "orderType": "Limit",
            "qty": qty, "price": price, "timeInForce": time_in_force,
        })

    @tool_schema(PlaceMarketOrderInput)
    async def place_market_order(
        self, category: str, symbol: str, side: str, qty: str,
    ) -> Dict[str, Any]:
        """Place a market order on Bybit."""
        return await self._request("POST", "/v5/order/create", {
            "category": category, "symbol": symbol.upper(),
            "side": side.capitalize(), "orderType": "Market", "qty": qty,
        })

    @tool_schema(PlaceStopOrderInput)
    async def place_stop_order(
        self, category: str, symbol: str, side: str, qty: str,
        trigger_price: str, order_type: str = "Market", price: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Place a conditional (stop) order on Bybit."""
        params: Dict[str, Any] = {
            "category": category, "symbol": symbol.upper(),
            "side": side.capitalize(), "orderType": order_type,
            "qty": qty, "triggerPrice": trigger_price,
        }
        if price:
            params["price"] = price
        return await self._request("POST", "/v5/order/create", params)

    # ── Order management ────────────────────────────────────────

    @tool_schema(CancelOrderInput)
    async def cancel_order(self, category: str, symbol: str, order_id: str) -> Dict[str, Any]:
        """Cancel a specific order on Bybit."""
        return await self._request("POST", "/v5/order/cancel", {
            "category": category, "symbol": symbol.upper(), "orderId": order_id,
        })

    @tool_schema(CancelAllOrdersInput)
    async def cancel_all_orders(self, category: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Cancel all orders for a category (optionally filtered by symbol)."""
        params: Dict[str, Any] = {"category": category}
        if symbol:
            params["symbol"] = symbol.upper()
        return await self._request("POST", "/v5/order/cancel-all", params)

    # ── Queries ─────────────────────────────────────────────────

    @tool_schema(QueryOrdersInput)
    async def get_open_orders(
        self, category: str, symbol: Optional[str] = None, limit: int = 50,
    ) -> Dict[str, Any]:
        """Get open orders on Bybit."""
        params: Dict[str, Any] = {"category": category, "limit": limit}
        if symbol:
            params["symbol"] = symbol.upper()
        return await self._request("GET", "/v5/order/realtime", params)

    @tool_schema(QueryPositionsInput)
    async def get_positions(
        self, category: str, symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get open positions on Bybit."""
        params: Dict[str, Any] = {"category": category}
        if symbol:
            params["symbol"] = symbol.upper()
        return await self._request("GET", "/v5/position/list", params)

    @tool_schema(WalletBalanceInput)
    async def get_wallet_balance(self, account_type: str = "UNIFIED") -> Dict[str, Any]:
        """Get wallet balance on Bybit."""
        return await self._request("GET", "/v5/account/wallet-balance", {
            "accountType": account_type.upper(),
        })
