"""Kraken write-side toolkit for crypto order execution (Spot & Futures)."""
from __future__ import annotations

import time
import hmac
import hashlib
import base64
from urllib.parse import urlencode
from typing import Any, Dict, Optional
from navconfig import config
from navconfig.logging import logging
from pydantic import BaseModel, Field

from ...interfaces.http import HTTPService
from ...tools.toolkit import AbstractToolkit
from ...tools.decorators import tool_schema


class KrakenWriteError(RuntimeError):
    """Raised when a Kraken write operation fails."""


# =============================================================================
# Pydantic input schemas
# =============================================================================

class SpotLimitOrderInput(BaseModel):
    """Place a spot limit order on Kraken."""
    pair: str = Field(..., description="Trading pair (e.g. XBTUSD, ETHUSD).")
    side: str = Field(..., description="Order side: 'buy' or 'sell'.")
    volume: str = Field(..., description="Order volume as string.")
    price: str = Field(..., description="Limit price as string.")
    validate_only: Optional[bool] = Field(None, description="Override default validate setting.")


class SpotCancelOrderInput(BaseModel):
    """Cancel a spot order on Kraken."""
    txid: str = Field(..., description="Kraken transaction ID to cancel.")


class SpotQueryInput(BaseModel):
    """Query spot open orders."""
    trades: bool = Field(False, description="Include trades in output.")


class FuturesLimitOrderInput(BaseModel):
    """Place a futures limit order on Kraken."""
    symbol: str = Field(..., description="Futures symbol (e.g. PI_XBTUSD).")
    side: str = Field(..., description="Order side: 'buy' or 'sell'.")
    size: float = Field(..., description="Contract size.", gt=0)
    limit_price: float = Field(..., description="Limit price.", gt=0)


class FuturesCancelOrderInput(BaseModel):
    """Cancel a futures order on Kraken."""
    order_id: str = Field(..., description="Futures order ID.")


# =============================================================================
# Toolkit
# =============================================================================

class KrakenWriteToolkit(AbstractToolkit):
    """Write-side toolkit for Kraken Spot and Futures crypto trading."""

    name: str = "kraken_write_toolkit"
    description: str = "Execute crypto trading operations on Kraken: place, cancel orders and query balances."

    SPOT_URL = "https://api.kraken.com"
    FUTURES_PROD_URL = "https://futures.kraken.com"
    FUTURES_DEMO_URL = "https://demo-futures.kraken.com"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger("KrakenWriteToolkit")

        # Spot credentials
        self.spot_api_key = config.get("KRAKEN_API_KEY")
        self.spot_api_secret = config.get("KRAKEN_API_SECRET")
        self.spot_validate = config.get("KRAKEN_SPOT_VALIDATE", fallback=True)
        if isinstance(self.spot_validate, str):
            self.spot_validate = self.spot_validate.lower() in ("true", "1", "yes")

        # Futures credentials
        self.futures_api_key = config.get("KRAKEN_FUTURES_API_KEY")
        self.futures_api_secret = config.get("KRAKEN_FUTURES_API_SECRET")
        self.futures_demo = config.get("KRAKEN_FUTURES_DEMO", fallback=True)
        if isinstance(self.futures_demo, str):
            self.futures_demo = self.futures_demo.lower() in ("true", "1", "yes")

        self.futures_url = self.FUTURES_DEMO_URL if self.futures_demo else self.FUTURES_PROD_URL

        self._http = HTTPService(headers={"Accept": "application/json"})
        self._http._logger = self.logger

    def _spot_sign(self, urlpath: str, data: Dict[str, Any]) -> Dict[str, str]:
        """Generate Kraken Spot API signature headers."""
        if not self.spot_api_key or not self.spot_api_secret:
            raise KrakenWriteError("KRAKEN_API_KEY / SECRET not configured.")
        nonce = str(int(time.time() * 1000))
        data["nonce"] = nonce
        postdata = urlencode(data)
        encoded = (nonce + postdata).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()
        secret = base64.b64decode(self.spot_api_secret)
        mac = hmac.new(secret, message, hashlib.sha512)
        sigdigest = base64.b64encode(mac.digest()).decode()
        return {
            "API-Key": self.spot_api_key,
            "API-Sign": sigdigest,
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _futures_sign(self, endpoint: str, postdata: str = "") -> Dict[str, str]:
        """Generate Kraken Futures API signature headers."""
        if not self.futures_api_key or not self.futures_api_secret:
            raise KrakenWriteError("KRAKEN_FUTURES_API_KEY / SECRET not configured.")
        nonce = str(int(time.time() * 1000))
        sha256_hash = hashlib.sha256((postdata + nonce + endpoint).encode()).digest()
        secret = base64.b64decode(self.futures_api_secret)
        mac = hmac.new(secret, sha256_hash, hashlib.sha512)
        sigdigest = base64.b64encode(mac.digest()).decode()
        return {
            "APIKey": self.futures_api_key,
            "Nonce": nonce,
            "Authent": sigdigest,
        }

    async def _spot_request(
        self, endpoint: str, data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Signed POST to Kraken Spot REST API."""
        import json as _json
        if data is None:
            data = {}
        urlpath = f"/0/private{endpoint}"
        sig_headers = self._spot_sign(urlpath, data)
        url = f"{self.SPOT_URL}{urlpath}"

        # Set auth headers on the HTTP service instance before request
        old_headers = dict(self._http.headers)
        self._http.headers.update(sig_headers)
        try:
            result, error = await self._http.async_request(
                url=url, method="POST", data=urlencode(data)
            )
        finally:
            self._http.headers = old_headers

        if error:
            raise KrakenWriteError(f"Kraken Spot API error on {endpoint}: {error}")
        if isinstance(result, str):
            try:
                result = _json.loads(result)
            except (ValueError, _json.JSONDecodeError):
                pass
        if isinstance(result, dict) and result.get("error"):
            errors = result["error"]
            if errors:
                raise KrakenWriteError(f"Kraken Spot: {errors}")
        return result.get("result", result) if isinstance(result, dict) else result

    async def _futures_request(
        self, method: str, endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Signed request to Kraken Futures REST API."""
        import json as _json
        if params is None:
            params = {}

        old_headers = dict(self._http.headers)
        try:
            if method == "GET":
                query = urlencode(params) if params else ""
                sig_headers = self._futures_sign(endpoint, query)
                self._http.headers.update(sig_headers)
                url = f"{self.futures_url}{endpoint}"
                if query:
                    url = f"{url}?{query}"
                result, error = await self._http.async_request(url=url, method="GET")
            else:
                postdata = urlencode(params) if params else ""
                sig_headers = self._futures_sign(endpoint, postdata)
                sig_headers["Content-Type"] = "application/x-www-form-urlencoded"
                self._http.headers.update(sig_headers)
                url = f"{self.futures_url}{endpoint}"
                result, error = await self._http.async_request(
                    url=url, method="POST", data=postdata
                )
        finally:
            self._http.headers = old_headers

        if error:
            raise KrakenWriteError(f"Kraken Futures error on {endpoint}: {error}")
        if isinstance(result, str):
            try:
                result = _json.loads(result)
            except (ValueError, _json.JSONDecodeError):
                pass
        if isinstance(result, dict) and result.get("error"):
            raise KrakenWriteError(f"Kraken Futures: {result['error']}")
        return result.get("result", result) if isinstance(result, dict) else result

    # ── Spot trading ────────────────────────────────────────────

    @tool_schema(SpotLimitOrderInput)
    async def spot_place_limit_order(
        self, pair: str, side: str, volume: str, price: str,
        validate_only: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Place a spot limit order on Kraken."""
        validate = validate_only if validate_only is not None else self.spot_validate
        data: Dict[str, Any] = {
            "pair": pair.upper(), "type": side.lower(),
            "ordertype": "limit", "volume": volume, "price": price,
        }
        if validate:
            data["validate"] = True
        return await self._spot_request("/AddOrder", data)

    @tool_schema(SpotCancelOrderInput)
    async def spot_cancel_order(self, txid: str) -> Dict[str, Any]:
        """Cancel a spot order on Kraken by transaction ID."""
        return await self._spot_request("/CancelOrder", {"txid": txid})

    @tool_schema(SpotQueryInput)
    async def spot_get_open_orders(self, trades: bool = False) -> Dict[str, Any]:
        """Get open spot orders on Kraken."""
        return await self._spot_request("/OpenOrders", {"trades": trades})

    async def spot_get_balance(self) -> Dict[str, Any]:
        """Get spot account balances on Kraken."""
        return await self._spot_request("/Balance")

    async def spot_get_trade_balance(self) -> Dict[str, Any]:
        """Get spot trade balance (equity, margin) on Kraken."""
        return await self._spot_request("/TradeBalance")

    # ── Futures trading ─────────────────────────────────────────

    @tool_schema(FuturesLimitOrderInput)
    async def futures_place_limit_order(
        self, symbol: str, side: str, size: float, limit_price: float,
    ) -> Dict[str, Any]:
        """Place a futures limit order on Kraken."""
        return await self._futures_request("POST", "/derivatives/api/v3/sendorder", {
            "symbol": symbol.upper(), "side": side.lower(),
            "orderType": "lmt", "size": size, "limitPrice": limit_price,
        })

    @tool_schema(FuturesCancelOrderInput)
    async def futures_cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel a futures order on Kraken."""
        return await self._futures_request("POST", "/derivatives/api/v3/cancelorder", {
            "order_id": order_id,
        })

    async def futures_get_open_positions(self) -> Dict[str, Any]:
        """Get open futures positions on Kraken."""
        return await self._futures_request("GET", "/derivatives/api/v3/openpositions")

    async def futures_get_open_orders(self) -> Dict[str, Any]:
        """Get open futures orders on Kraken."""
        return await self._futures_request("GET", "/derivatives/api/v3/openorders")
