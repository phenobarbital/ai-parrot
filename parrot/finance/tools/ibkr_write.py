"""IBKR write-side toolkit for multi-asset order execution via TWS API."""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, List, Optional
from navconfig import config
from navconfig.logging import logging
from pydantic import BaseModel, Field

from ...tools.toolkit import AbstractToolkit
from ...tools.decorators import tool_schema


class IBKRWriteError(RuntimeError):
    """Raised when an IBKR write operation fails."""


# =============================================================================
# Pydantic input schemas
# =============================================================================

class ContractInput(BaseModel):
    """Contract specification for IBKR."""
    symbol: str = Field(..., description="Ticker symbol (e.g. AAPL).")
    sec_type: str = Field("STK", description="Security type: STK, OPT, FUT, CASH, CRYPTO.")
    exchange: str = Field("SMART", description="Exchange (e.g. SMART, NYSE, GLOBEX).")
    currency: str = Field("USD", description="Currency.")


class PlaceLimitOrderInput(BaseModel):
    """Place a limit order on IBKR."""
    symbol: str = Field(..., description="Ticker symbol.")
    sec_type: str = Field("STK", description="Security type.")
    exchange: str = Field("SMART", description="Exchange.")
    currency: str = Field("USD", description="Currency.")
    action: str = Field(..., description="Action: 'BUY' or 'SELL'.")
    quantity: float = Field(..., description="Order quantity.", gt=0)
    limit_price: float = Field(..., description="Limit price.", gt=0)
    tif: str = Field("DAY", description="Time in force: 'DAY', 'GTC', 'IOC', 'FOK'.")


class PlaceStopOrderInput(BaseModel):
    """Place a stop order on IBKR."""
    symbol: str = Field(..., description="Ticker symbol.")
    sec_type: str = Field("STK", description="Security type.")
    exchange: str = Field("SMART", description="Exchange.")
    currency: str = Field("USD", description="Currency.")
    action: str = Field(..., description="Action: 'BUY' or 'SELL'.")
    quantity: float = Field(..., description="Order quantity.", gt=0)
    stop_price: float = Field(..., description="Stop trigger price.", gt=0)
    tif: str = Field("DAY", description="Time in force.")


class PlaceBracketOrderInput(BaseModel):
    """Place a bracket order (parent + stop-loss + take-profit) on IBKR."""
    symbol: str = Field(..., description="Ticker symbol.")
    sec_type: str = Field("STK", description="Security type.")
    exchange: str = Field("SMART", description="Exchange.")
    currency: str = Field("USD", description="Currency.")
    action: str = Field(..., description="Action: 'BUY' or 'SELL'.")
    quantity: float = Field(..., description="Order quantity.", gt=0)
    limit_price: float = Field(..., description="Parent limit price.", gt=0)
    take_profit_price: float = Field(..., description="Take-profit limit price.", gt=0)
    stop_loss_price: float = Field(..., description="Stop-loss trigger price.", gt=0)


class CancelOrderInput(BaseModel):
    """Cancel a specific order."""
    order_id: int = Field(..., description="IBKR order ID.")


class MarketDataInput(BaseModel):
    """Request market data snapshot."""
    symbol: str = Field(..., description="Ticker symbol.")
    sec_type: str = Field("STK", description="Security type.")
    exchange: str = Field("SMART", description="Exchange.")
    currency: str = Field("USD", description="Currency.")


# =============================================================================
# EWrapper + EClient bridge
# =============================================================================

try:
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper
    from ibapi.contract import Contract
    from ibapi.order import Order

    class _IBKRBridge(EWrapper, EClient):
        """Minimal EWrapper/EClient bridge for async order execution."""

        def __init__(self) -> None:
            EWrapper.__init__(self)
            EClient.__init__(self, wrapper=self)
            self._order_futures: Dict[int, asyncio.Future] = {}
            self._position_data: List[Dict[str, Any]] = []
            self._account_data: Dict[str, Any] = {}
            self._position_future: Optional[asyncio.Future] = None
            self._account_future: Optional[asyncio.Future] = None
            self._market_data: Dict[int, Dict[str, Any]] = {}
            self._market_futures: Dict[int, asyncio.Future] = {}
            self._loop: Optional[asyncio.AbstractEventLoop] = None
            self._next_order_id: Optional[int] = None
            self.logger = logging.getLogger("IBKRBridge")

        def nextValidId(self, orderId: int) -> None:
            """Receive next valid order ID from TWS."""
            self._next_order_id = orderId
            self.logger.debug(f"Next valid order ID: {orderId}")

        def orderStatus(
            self, orderId: int, status: str, filled: float, remaining: float,
            avgFillPrice: float, permId: int, parentId: int, lastFillPrice: float,
            clientId: int, whyHeld: str, mktCapPrice: float = 0.0,
        ) -> None:
            """Receive order status update."""
            future = self._order_futures.get(orderId)
            if future and not future.done() and self._loop:
                self._loop.call_soon_threadsafe(
                    future.set_result,
                    {"order_id": orderId, "status": status, "filled": filled,
                     "remaining": remaining, "avg_fill_price": avgFillPrice},
                )

        def position(self, account: str, contract: Contract, position: float, avgCost: float) -> None:
            """Receive position data."""
            self._position_data.append({
                "account": account, "symbol": contract.symbol,
                "sec_type": contract.secType, "exchange": contract.exchange,
                "position": position, "avg_cost": avgCost,
            })

        def positionEnd(self) -> None:
            """Position data complete."""
            if self._position_future and not self._position_future.done() and self._loop:
                self._loop.call_soon_threadsafe(
                    self._position_future.set_result, list(self._position_data)
                )

        def updateAccountValue(
            self, key: str, val: str, currency: str, accountName: str,
        ) -> None:
            """Receive account summary values."""
            self._account_data[key] = {"value": val, "currency": currency}

        def accountDownloadEnd(self, accountName: str) -> None:
            """Account data complete."""
            if self._account_future and not self._account_future.done() and self._loop:
                self._loop.call_soon_threadsafe(
                    self._account_future.set_result, dict(self._account_data)
                )

        def tickPrice(self, reqId: int, tickType: int, price: float, attrib: Any) -> None:
            """Receive market data tick."""
            if reqId not in self._market_data:
                self._market_data[reqId] = {}
            tick_names = {1: "bid", 2: "ask", 4: "last", 6: "high", 7: "low", 9: "close"}
            name = tick_names.get(tickType, f"tick_{tickType}")
            self._market_data[reqId][name] = price

        def tickSnapshotEnd(self, reqId: int) -> None:
            """Market data snapshot complete."""
            future = self._market_futures.get(reqId)
            if future and not future.done() and self._loop:
                self._loop.call_soon_threadsafe(
                    future.set_result, self._market_data.get(reqId, {})
                )

        def error(self, reqId: int, errorCode: int, errorString: str, advancedOrderRejectJson: str = "") -> None:
            """Handle TWS errors."""
            self.logger.warning(f"IBKR error reqId={reqId} code={errorCode}: {errorString}")
            # Resolve pending futures on fatal errors
            if errorCode in (201, 202, 203, 321, 322):
                future = self._order_futures.get(reqId)
                if future and not future.done() and self._loop:
                    self._loop.call_soon_threadsafe(
                        future.set_exception,
                        IBKRWriteError(f"IBKR order error {errorCode}: {errorString}"),
                    )

    HAS_IBAPI = True
except ImportError:
    HAS_IBAPI = False
    _IBKRBridge = None  # type: ignore[assignment, misc]


# =============================================================================
# Toolkit
# =============================================================================

class IBKRWriteToolkit(AbstractToolkit):
    """Write-side toolkit for Interactive Brokers (multi-asset via TWS API)."""

    name: str = "ibkr_write_toolkit"
    description: str = "Execute multi-asset trading operations on IBKR via TWS API."

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger("IBKRWriteToolkit")
        self.host = config.get("IBKR_HOST", fallback="127.0.0.1")
        self.port = int(config.get("IBKR_PORT", fallback=7497))
        self.client_id = int(config.get("IBKR_CLIENT_ID", fallback=1))
        self._bridge: Optional[_IBKRBridge] = None  # type: ignore[assignment]
        self._reader_thread: Optional[threading.Thread] = None
        self._req_id_counter: int = 1000

    def _ensure_connected(self) -> _IBKRBridge:  # type: ignore[return]
        """Lazy-connect to TWS/IB Gateway."""
        if not HAS_IBAPI:
            raise IBKRWriteError(
                "ibapi is not installed. Install from https://interactivebrokers.github.io/"
            )
        if self._bridge is None or not self._bridge.isConnected():
            bridge = _IBKRBridge()
            bridge._loop = asyncio.get_event_loop()
            bridge.connect(self.host, self.port, self.client_id)
            thread = threading.Thread(target=bridge.run, daemon=True, name="ibkr-reader")
            thread.start()
            self._bridge = bridge
            self._reader_thread = thread
            # Wait for nextValidId
            timeout = 10
            while bridge._next_order_id is None and timeout > 0:
                import time
                time.sleep(0.1)
                timeout -= 0.1
            if bridge._next_order_id is None:
                raise IBKRWriteError("Failed to receive nextValidId from TWS.")
            self.logger.info(f"Connected to IBKR at {self.host}:{self.port}")
        return self._bridge

    def _next_req_id(self) -> int:
        """Get the next request ID."""
        self._req_id_counter += 1
        return self._req_id_counter

    def _next_order_id(self) -> int:
        """Get the next valid order ID from TWS."""
        bridge = self._ensure_connected()
        oid = bridge._next_order_id
        bridge._next_order_id += 1  # type: ignore[operator]
        return oid  # type: ignore[return-value]

    @staticmethod
    def _make_contract(symbol: str, sec_type: str = "STK",
                       exchange: str = "SMART", currency: str = "USD") -> Contract:
        """Create an IBKR Contract object."""
        contract = Contract()
        contract.symbol = symbol.upper()
        contract.secType = sec_type.upper()
        contract.exchange = exchange.upper()
        contract.currency = currency.upper()
        return contract

    @staticmethod
    def _make_order(action: str, quantity: float, order_type: str = "LMT",
                    limit_price: float = 0.0, stop_price: float = 0.0,
                    tif: str = "DAY", transmit: bool = True,
                    parent_id: int = 0) -> Order:
        """Create an IBKR Order object."""
        order = Order()
        order.action = action.upper()
        order.totalQuantity = quantity
        order.orderType = order_type
        order.tif = tif.upper()
        order.transmit = transmit
        if limit_price > 0:
            order.lmtPrice = limit_price
        if stop_price > 0:
            order.auxPrice = stop_price
        if parent_id > 0:
            order.parentId = parent_id
        return order

    # ── Order placement ─────────────────────────────────────────

    @tool_schema(PlaceLimitOrderInput)
    async def place_limit_order(
        self, symbol: str, sec_type: str, exchange: str, currency: str,
        action: str, quantity: float, limit_price: float, tif: str = "DAY",
    ) -> Dict[str, Any]:
        """Place a limit order on IBKR."""
        bridge = self._ensure_connected()
        contract = self._make_contract(symbol, sec_type, exchange, currency)
        order = self._make_order(action, quantity, "LMT", limit_price=limit_price, tif=tif)
        oid = self._next_order_id()

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        bridge._order_futures[oid] = future
        await asyncio.to_thread(bridge.placeOrder, oid, contract, order)

        try:
            result = await asyncio.wait_for(future, timeout=30)
        except asyncio.TimeoutError:
            result = {"order_id": oid, "status": "submitted", "note": "No immediate fill confirmation."}
        finally:
            bridge._order_futures.pop(oid, None)
        return result

    @tool_schema(PlaceStopOrderInput)
    async def place_stop_order(
        self, symbol: str, sec_type: str, exchange: str, currency: str,
        action: str, quantity: float, stop_price: float, tif: str = "DAY",
    ) -> Dict[str, Any]:
        """Place a stop order on IBKR."""
        bridge = self._ensure_connected()
        contract = self._make_contract(symbol, sec_type, exchange, currency)
        order = self._make_order(action, quantity, "STP", stop_price=stop_price, tif=tif)
        oid = self._next_order_id()

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        bridge._order_futures[oid] = future
        await asyncio.to_thread(bridge.placeOrder, oid, contract, order)

        try:
            result = await asyncio.wait_for(future, timeout=30)
        except asyncio.TimeoutError:
            result = {"order_id": oid, "status": "submitted"}
        finally:
            bridge._order_futures.pop(oid, None)
        return result

    @tool_schema(PlaceBracketOrderInput)
    async def place_bracket_order(
        self, symbol: str, sec_type: str, exchange: str, currency: str,
        action: str, quantity: float, limit_price: float,
        take_profit_price: float, stop_loss_price: float,
    ) -> Dict[str, Any]:
        """Place a bracket order (parent + take-profit + stop-loss) on IBKR."""
        bridge = self._ensure_connected()
        contract = self._make_contract(symbol, sec_type, exchange, currency)
        reverse_action = "SELL" if action.upper() == "BUY" else "BUY"

        parent_id = self._next_order_id()
        tp_id = self._next_order_id()
        sl_id = self._next_order_id()

        # Parent: transmit=False (held until children submitted)
        parent = self._make_order(action, quantity, "LMT",
                                  limit_price=limit_price, transmit=False)
        # Take-profit: transmit=False
        tp = self._make_order(reverse_action, quantity, "LMT",
                              limit_price=take_profit_price, transmit=False, parent_id=parent_id)
        # Stop-loss: transmit=True (triggers atomic submission of all three)
        sl = self._make_order(reverse_action, quantity, "STP",
                              stop_price=stop_loss_price, transmit=True, parent_id=parent_id)

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        bridge._order_futures[parent_id] = future

        await asyncio.to_thread(bridge.placeOrder, parent_id, contract, parent)
        await asyncio.to_thread(bridge.placeOrder, tp_id, contract, tp)
        await asyncio.to_thread(bridge.placeOrder, sl_id, contract, sl)

        try:
            result = await asyncio.wait_for(future, timeout=30)
        except asyncio.TimeoutError:
            result = {"parent_id": parent_id, "status": "submitted"}
        finally:
            bridge._order_futures.pop(parent_id, None)

        return {
            "parent_id": parent_id, "take_profit_id": tp_id, "stop_loss_id": sl_id,
            **result,
        }

    # ── Order management ────────────────────────────────────────

    @tool_schema(CancelOrderInput)
    async def cancel_order(self, order_id: int) -> Dict[str, Any]:
        """Cancel a specific order on IBKR."""
        bridge = self._ensure_connected()
        await asyncio.to_thread(bridge.cancelOrder, order_id, "")
        return {"cancelled": True, "order_id": order_id}

    # ── Queries ─────────────────────────────────────────────────

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get all positions from IBKR."""
        bridge = self._ensure_connected()
        bridge._position_data = []
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        bridge._position_future = future

        await asyncio.to_thread(bridge.reqPositions)
        try:
            result = await asyncio.wait_for(future, timeout=15)
        except asyncio.TimeoutError:
            result = list(bridge._position_data)
        finally:
            bridge._position_future = None
        return result

    async def get_account_summary(self) -> Dict[str, Any]:
        """Get account summary from IBKR."""
        bridge = self._ensure_connected()
        bridge._account_data = {}
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        bridge._account_future = future
        req_id = self._next_req_id()

        tags = "NetLiquidation,TotalCashValue,BuyingPower,GrossPositionValue,MaintMarginReq"
        await asyncio.to_thread(bridge.reqAccountSummary, req_id, "All", tags)
        try:
            result = await asyncio.wait_for(future, timeout=15)
        except asyncio.TimeoutError:
            result = dict(bridge._account_data)
        finally:
            bridge._account_future = None
            await asyncio.to_thread(bridge.cancelAccountSummary, req_id)
        return result

    @tool_schema(MarketDataInput)
    async def request_market_data(
        self, symbol: str, sec_type: str = "STK", exchange: str = "SMART",
        currency: str = "USD",
    ) -> Dict[str, Any]:
        """Request a market data snapshot from IBKR."""
        bridge = self._ensure_connected()
        contract = self._make_contract(symbol, sec_type, exchange, currency)
        req_id = self._next_req_id()

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        bridge._market_futures[req_id] = future

        # snapshot=True, regulatorySnapshot=False
        await asyncio.to_thread(
            bridge.reqMktData, req_id, contract, "", True, False, []
        )
        try:
            result = await asyncio.wait_for(future, timeout=10)
        except asyncio.TimeoutError:
            result = bridge._market_data.get(req_id, {})
        finally:
            bridge._market_futures.pop(req_id, None)

        return {"symbol": symbol, **result}

    def disconnect(self) -> None:
        """Disconnect from TWS/IB Gateway."""
        if self._bridge and self._bridge.isConnected():
            self._bridge.disconnect()
            self.logger.info("Disconnected from IBKR.")
