"""Kraken write-side toolkit for crypto order execution (Spot & Futures)."""
from __future__ import annotations

import time
import hmac
import hashlib
import base64
from decimal import Decimal
from urllib.parse import urlencode
from typing import Any, Dict, Optional
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

class KrakenWriteToolkit(PaperTradingMixin, AbstractToolkit):
    """Write-side toolkit for Kraken Spot and Futures crypto trading.

    Supports three execution modes:
    - LIVE: Real trading on production APIs (spot_validate=False, futures=production)
    - PAPER: Paper trading (spot_validate=True, futures=demo environment)
    - DRY_RUN: Local simulation using VirtualPortfolio (no API calls)
    """

    name: str = "kraken_write_toolkit"
    description: str = "Execute crypto trading operations on Kraken: place, cancel orders and query balances."

    SPOT_URL = "https://api.kraken.com"
    FUTURES_PROD_URL = "https://futures.kraken.com"
    FUTURES_DEMO_URL = "https://demo-futures.kraken.com"

    def __init__(
        self,
        mode: Optional[ExecutionMode] = None,
        virtual_portfolio: Optional[VirtualPortfolio] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.logger = logging.getLogger("KrakenWriteToolkit")

        # Initialize paper trading mixin
        self._init_paper_trading(mode)
        self._virtual_portfolio = virtual_portfolio

        # Auto-create VirtualPortfolio for DRY_RUN if not provided
        if self._execution_mode == ExecutionMode.DRY_RUN and self._virtual_portfolio is None:
            self._virtual_portfolio = VirtualPortfolio()

        # Spot credentials
        self.spot_api_key = config.get("KRAKEN_API_KEY")
        self.spot_api_secret = config.get("KRAKEN_API_SECRET")

        # Futures credentials
        self.futures_api_key = config.get("KRAKEN_FUTURES_API_KEY")
        self.futures_api_secret = config.get("KRAKEN_FUTURES_API_SECRET")

        # Map execution mode to spot_validate and futures_demo settings
        # PAPER: use validate for spot, demo for futures
        # LIVE: real trading on both
        # DRY_RUN: doesn't matter, bypasses API entirely
        if self._execution_mode == ExecutionMode.LIVE:
            self.spot_validate = False
            self.futures_demo = False
        else:
            # PAPER or DRY_RUN: safe mode
            self.spot_validate = True
            self.futures_demo = True

        self.futures_url = self.FUTURES_DEMO_URL if self.futures_demo else self.FUTURES_PROD_URL

        self._http = HTTPService(headers={"Accept": "application/json"})
        self._http._logger = self.logger

        self.logger.info(
            f"KrakenWriteToolkit initialized: mode={self._execution_mode.value}, "
            f"spot_validate={self.spot_validate}, futures_demo={self.futures_demo}"
        )

    def _add_mode_fields(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Add execution mode fields to a response dict."""
        result["execution_mode"] = self._execution_mode.value
        result["is_simulated"] = self.is_paper_trading
        return result

    async def _dry_run_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float] = None,
        order_type: str = "limit",
        platform: str = "kraken_spot",
        **extra_fields,
    ) -> Dict[str, Any]:
        """Execute an order via VirtualPortfolio in DRY_RUN mode."""
        if self._virtual_portfolio is None:
            raise KrakenWriteError("VirtualPortfolio not initialized for DRY_RUN mode")

        # Create a SimulatedOrder
        sim_order = SimulatedOrder(
            symbol=symbol,
            platform=platform,
            side=side.lower(),
            order_type=order_type,
            quantity=Decimal(str(quantity)),
            limit_price=Decimal(str(price)) if price and order_type == "limit" else None,
            stop_price=Decimal(str(price)) if price and order_type == "stop" else None,
        )

        # Place the order (may fill immediately for market orders)
        current_price = Decimal(str(price)) if price else None
        sim_order = await self._virtual_portfolio.place_order(sim_order, current_price)

        result = {
            "order_id": sim_order.order_id,
            "txid": [sim_order.order_id],  # Kraken returns txid array
            "status": sim_order.status,
            "symbol": symbol,
            "side": side,
            "volume": str(quantity),
            "price": str(price) if price else None,
            "order_type": order_type,
            "platform": platform,
            **extra_fields,
        }

        # Add fill info if filled
        if sim_order.status == "filled" and sim_order.filled_price is not None:
            result["filled"] = str(sim_order.filled_quantity)
            result["avg_fill_price"] = str(sim_order.filled_price)
            if sim_order.filled_at:
                result["fill_time"] = sim_order.filled_at.isoformat()

        return self._add_mode_fields(result)

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
        # Route to VirtualPortfolio in DRY_RUN mode
        if self._execution_mode == ExecutionMode.DRY_RUN:
            return await self._dry_run_order(
                symbol=pair.upper(),
                side=side,
                quantity=float(volume),
                price=float(price),
                order_type="limit",
                platform="kraken_spot",
                pair=pair.upper(),
            )

        validate = validate_only if validate_only is not None else self.spot_validate
        data: Dict[str, Any] = {
            "pair": pair.upper(), "type": side.lower(),
            "ordertype": "limit", "volume": volume, "price": price,
        }
        if validate:
            data["validate"] = True
        result = await self._spot_request("/AddOrder", data)
        return self._add_mode_fields(result)

    @tool_schema(SpotCancelOrderInput)
    async def spot_cancel_order(self, txid: str) -> Dict[str, Any]:
        """Cancel a spot order on Kraken by transaction ID."""
        # Route to VirtualPortfolio in DRY_RUN mode
        if self._execution_mode == ExecutionMode.DRY_RUN:
            if self._virtual_portfolio is None:
                raise KrakenWriteError("VirtualPortfolio not initialized for DRY_RUN mode")
            cancelled = await self._virtual_portfolio.cancel_order(txid)
            return self._add_mode_fields({
                "count": 1 if cancelled else 0,
                "txid": txid,
            })

        result = await self._spot_request("/CancelOrder", {"txid": txid})
        return self._add_mode_fields(result)

    @tool_schema(SpotQueryInput)
    async def spot_get_open_orders(self, trades: bool = False) -> Dict[str, Any]:
        """Get open spot orders on Kraken."""
        # Route to VirtualPortfolio in DRY_RUN mode
        if self._execution_mode == ExecutionMode.DRY_RUN:
            if self._virtual_portfolio is None:
                return self._add_mode_fields({"open": {}})
            orders = self._virtual_portfolio.get_open_orders()
            open_orders = {
                order.order_id: {
                    "status": order.status,
                    "vol": str(order.quantity),
                    "price": str(order.limit_price) if order.limit_price else "0",
                }
                for order in orders
            }
            return self._add_mode_fields({"open": open_orders})

        result = await self._spot_request("/OpenOrders", {"trades": trades})
        return self._add_mode_fields(result)

    async def spot_get_balance(self) -> Dict[str, Any]:
        """Get spot account balances on Kraken."""
        # Route to VirtualPortfolio in DRY_RUN mode
        if self._execution_mode == ExecutionMode.DRY_RUN:
            if self._virtual_portfolio is None:
                return self._add_mode_fields({"USD": "100000"})
            state = self._virtual_portfolio.get_state()
            balances = {"USD": str(state.cash_balance)}
            for pos in state.positions:
                balances[pos.symbol] = str(pos.quantity)
            return self._add_mode_fields(balances)

        result = await self._spot_request("/Balance")
        return self._add_mode_fields(result)

    async def spot_get_trade_balance(self) -> Dict[str, Any]:
        """Get spot trade balance (equity, margin) on Kraken."""
        # Route to VirtualPortfolio in DRY_RUN mode
        if self._execution_mode == ExecutionMode.DRY_RUN:
            if self._virtual_portfolio is None:
                return self._add_mode_fields({"eb": "100000", "tb": "100000"})
            state = self._virtual_portfolio.get_state()
            return self._add_mode_fields({
                "eb": str(state.total_equity),
                "tb": str(state.cash_balance),
                "m": "0",
                "n": "0",
            })

        result = await self._spot_request("/TradeBalance")
        return self._add_mode_fields(result)

    # ── Futures trading ─────────────────────────────────────────

    @tool_schema(FuturesLimitOrderInput)
    async def futures_place_limit_order(
        self, symbol: str, side: str, size: float, limit_price: float,
    ) -> Dict[str, Any]:
        """Place a futures limit order on Kraken."""
        # Route to VirtualPortfolio in DRY_RUN mode
        if self._execution_mode == ExecutionMode.DRY_RUN:
            return await self._dry_run_order(
                symbol=symbol.upper(),
                side=side,
                quantity=size,
                price=limit_price,
                order_type="limit",
                platform="kraken_futures",
            )

        result = await self._futures_request("POST", "/derivatives/api/v3/sendorder", {
            "symbol": symbol.upper(), "side": side.lower(),
            "orderType": "lmt", "size": size, "limitPrice": limit_price,
        })
        return self._add_mode_fields(result)

    @tool_schema(FuturesCancelOrderInput)
    async def futures_cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel a futures order on Kraken."""
        # Route to VirtualPortfolio in DRY_RUN mode
        if self._execution_mode == ExecutionMode.DRY_RUN:
            if self._virtual_portfolio is None:
                raise KrakenWriteError("VirtualPortfolio not initialized for DRY_RUN mode")
            cancelled = await self._virtual_portfolio.cancel_order(order_id)
            return self._add_mode_fields({
                "result": "success" if cancelled else "failed",
                "order_id": order_id,
            })

        result = await self._futures_request("POST", "/derivatives/api/v3/cancelorder", {
            "order_id": order_id,
        })
        return self._add_mode_fields(result)

    async def futures_get_open_positions(self) -> Dict[str, Any]:
        """Get open futures positions on Kraken."""
        # Route to VirtualPortfolio in DRY_RUN mode
        if self._execution_mode == ExecutionMode.DRY_RUN:
            if self._virtual_portfolio is None:
                return self._add_mode_fields({"openPositions": []})
            state = self._virtual_portfolio.get_state()
            positions = [
                {
                    "symbol": pos.symbol,
                    "side": pos.side,
                    "size": float(pos.quantity),
                    "price": float(pos.avg_entry_price),
                }
                for pos in state.positions
                if pos.platform == "kraken_futures"
            ]
            return self._add_mode_fields({"openPositions": positions})

        result = await self._futures_request("GET", "/derivatives/api/v3/openpositions")
        return self._add_mode_fields(result)

    async def futures_get_open_orders(self) -> Dict[str, Any]:
        """Get open futures orders on Kraken."""
        # Route to VirtualPortfolio in DRY_RUN mode
        if self._execution_mode == ExecutionMode.DRY_RUN:
            if self._virtual_portfolio is None:
                return self._add_mode_fields({"openOrders": []})
            orders = self._virtual_portfolio.get_open_orders()
            futures_orders = [
                {
                    "order_id": order.order_id,
                    "symbol": order.symbol,
                    "side": order.side,
                    "size": float(order.quantity),
                    "limitPrice": float(order.limit_price) if order.limit_price else None,
                }
                for order in orders
                if order.platform == "kraken_futures"
            ]
            return self._add_mode_fields({"openOrders": futures_orders})

        result = await self._futures_request("GET", "/derivatives/api/v3/openorders")
        return self._add_mode_fields(result)
