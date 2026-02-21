"""IBKR Client Portal REST API backend.

Implements IBKRBackend using aiohttp to communicate with the IBKR Client
Portal Gateway. Handles authentication, session keepalive, and automatic
re-authentication on 401 responses.

All monetary fields are converted from JSON floats to Decimal for precision.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import aiohttp

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


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Safely convert a JSON value to Decimal."""
    if value is None:
        return None
    return Decimal(str(value))


class PortalBackend(IBKRBackend):
    """IBKR Client Portal REST API backend.

    Connects to the Client Portal Gateway via HTTP. Handles self-signed
    SSL certificates and automatic session refresh on 401 responses.

    Args:
        config: IBKR configuration with portal_url set.
    """

    def __init__(self, config: IBKRConfig) -> None:
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None
        self._base_url: str = config.portal_url or "https://localhost:5000/v1/api"
        self._authenticated: bool = False
        self._account_id: Optional[str] = None

    # ── Connection ───────────────────────────────────────────────

    async def connect(self) -> None:
        """Establish connection and authenticate with Client Portal."""
        self._session = aiohttp.ClientSession(
            base_url=self._base_url,
            connector=aiohttp.TCPConnector(ssl=False),
        )
        await self._authenticate()
        self.logger.info("Connected to IBKR Client Portal at %s", self._base_url)

    async def disconnect(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            self._authenticated = False
            self.logger.info("Disconnected from IBKR Client Portal.")

    async def is_connected(self) -> bool:
        """Check if session is active and authenticated."""
        if self._session is None or self._session.closed:
            return False
        try:
            data = await self._request("POST", "/iserver/auth/status")
            self._authenticated = data.get("authenticated", False)
            return self._authenticated
        except Exception:
            return False

    # ── Market Data ──────────────────────────────────────────────

    async def get_quote(self, contract: ContractSpec) -> Quote:
        """Get real-time quote snapshot for a contract."""
        conid = await self._resolve_conid(contract)
        data = await self._request(
            "GET",
            "/iserver/marketdata/snapshot",
            params={"conids": str(conid), "fields": "55,31,84,86,7282"},
        )
        # Portal returns a list; take the first item
        item = data[0] if isinstance(data, list) and data else {}
        return Quote(
            symbol=item.get("55", contract.symbol),
            last=_to_decimal(item.get("31")),
            bid=_to_decimal(item.get("84")),
            ask=_to_decimal(item.get("86")),
            volume=int(item["7282"]) if item.get("7282") else None,
            timestamp=datetime.now(timezone.utc),
        )

    async def get_historical_bars(
        self,
        contract: ContractSpec,
        duration: str,
        bar_size: str,
    ) -> list[BarData]:
        """Get historical OHLCV bars for a contract."""
        conid = await self._resolve_conid(contract)
        data = await self._request(
            "GET",
            "/iserver/marketdata/history",
            params={
                "conid": str(conid),
                "period": duration,
                "bar": bar_size,
            },
        )
        bars_data = data.get("data", []) if isinstance(data, dict) else []
        bars = []
        for bar in bars_data:
            bars.append(
                BarData(
                    timestamp=datetime.fromtimestamp(
                        bar["t"] / 1000, tz=timezone.utc
                    ),
                    open=Decimal(str(bar["o"])),
                    high=Decimal(str(bar["h"])),
                    low=Decimal(str(bar["l"])),
                    close=Decimal(str(bar["c"])),
                    volume=int(bar.get("v", 0)),
                )
            )
        return bars

    async def get_options_chain(
        self, symbol: str, expiry: Optional[str] = None
    ) -> list[dict]:
        """Get options chain for an underlying symbol."""
        params: dict[str, str] = {"symbol": symbol}
        if expiry:
            params["expiry"] = expiry
        data = await self._request(
            "GET", "/iserver/secdef/strikes", params=params
        )
        return data if isinstance(data, list) else [data]

    async def search_contracts(
        self, pattern: str, sec_type: str = "STK"
    ) -> list[dict]:
        """Search for contracts matching a pattern."""
        data = await self._request(
            "GET",
            "/iserver/secdef/search",
            params={"symbol": pattern, "secType": sec_type},
        )
        return data if isinstance(data, list) else []

    async def run_scanner(
        self, scan_code: str, num_results: int = 25
    ) -> list[dict]:
        """Run an IBKR market scanner."""
        payload = {
            "instrument": "STK",
            "type": scan_code,
            "location": "STK.US.MAJOR",
            "size": str(num_results),
        }
        data = await self._request(
            "POST", "/iserver/scanner/run", json=payload
        )
        return data if isinstance(data, list) else []

    # ── Order Management ─────────────────────────────────────────

    async def place_order(self, order: OrderRequest) -> OrderStatus:
        """Place a new order via Client Portal."""
        account_id = await self._get_account_id()
        conid = await self._resolve_conid(
            ContractSpec(symbol=order.symbol)
        )
        payload = {
            "orders": [
                {
                    "conid": conid,
                    "orderType": order.order_type,
                    "side": order.action,
                    "quantity": order.quantity,
                    "tif": order.tif,
                }
            ]
        }
        if order.limit_price is not None:
            payload["orders"][0]["price"] = float(order.limit_price)
        if order.stop_price is not None:
            payload["orders"][0]["auxPrice"] = float(order.stop_price)

        self.logger.debug(
            "Placing order: %s %s %s qty=%d",
            order.action, order.symbol, order.order_type, order.quantity,
        )
        data = await self._request(
            "POST",
            f"/iserver/account/{account_id}/orders",
            json=payload,
        )
        # Portal may return a list of order responses
        order_data = data[0] if isinstance(data, list) and data else data
        return OrderStatus(
            order_id=int(order_data.get("order_id", 0)),
            symbol=order.symbol,
            action=order.action,
            quantity=order.quantity,
            status=order_data.get("order_status", "Submitted"),
        )

    async def modify_order(self, order_id: int, **changes) -> OrderStatus:
        """Modify an existing open order."""
        account_id = await self._get_account_id()
        self.logger.debug("Modifying order %d: %s", order_id, changes)
        data = await self._request(
            "POST",
            f"/iserver/account/{account_id}/order/{order_id}",
            json=changes,
        )
        order_data = data[0] if isinstance(data, list) and data else data
        return OrderStatus(
            order_id=order_id,
            symbol=order_data.get("symbol", ""),
            action=order_data.get("side", ""),
            quantity=int(order_data.get("quantity", 0)),
            status=order_data.get("order_status", "Modified"),
        )

    async def cancel_order(self, order_id: int) -> dict:
        """Cancel an open order."""
        account_id = await self._get_account_id()
        self.logger.debug("Cancelling order %d", order_id)
        data = await self._request(
            "DELETE",
            f"/iserver/account/{account_id}/order/{order_id}",
        )
        return data if isinstance(data, dict) else {"order_id": order_id, "msg": str(data)}

    async def get_open_orders(self) -> list[OrderStatus]:
        """Get all currently open orders."""
        data = await self._request("GET", "/iserver/account/orders")
        orders_data = data.get("orders", []) if isinstance(data, dict) else data
        if not isinstance(orders_data, list):
            orders_data = []
        result = []
        for o in orders_data:
            result.append(
                OrderStatus(
                    order_id=int(o.get("orderId", 0)),
                    symbol=o.get("ticker", ""),
                    action=o.get("side", ""),
                    quantity=int(o.get("totalSize", 0)),
                    filled=int(o.get("filledQuantity", 0)),
                    remaining=int(o.get("remainingQuantity", 0)),
                    avg_fill_price=_to_decimal(o.get("avgPrice")),
                    status=o.get("status", "Unknown"),
                )
            )
        return result

    # ── Account & Portfolio ──────────────────────────────────────

    async def get_account_summary(self) -> AccountSummary:
        """Get account summary information."""
        account_id = await self._get_account_id()
        data = await self._request(
            "GET", f"/portfolio/{account_id}/summary"
        )
        return AccountSummary(
            account_id=account_id,
            net_liquidation=Decimal(
                str(data.get("netliquidation", {}).get("amount", 0))
            ),
            total_cash=Decimal(
                str(data.get("totalcashvalue", {}).get("amount", 0))
            ),
            buying_power=Decimal(
                str(data.get("buyingpower", {}).get("amount", 0))
            ),
            gross_position_value=Decimal(
                str(data.get("grosspositionvalue", {}).get("amount", 0))
            ),
            unrealized_pnl=Decimal(
                str(data.get("unrealizedpnl", {}).get("amount", 0))
            ),
            realized_pnl=Decimal(
                str(data.get("realizedpnl", {}).get("amount", 0))
            ),
        )

    async def get_positions(self) -> list[Position]:
        """Get all current positions."""
        account_id = await self._get_account_id()
        data = await self._request(
            "GET", f"/portfolio/{account_id}/positions/0"
        )
        if not isinstance(data, list):
            data = []
        positions = []
        for p in data:
            positions.append(
                Position(
                    symbol=p.get("ticker", p.get("contractDesc", "")),
                    quantity=int(p.get("position", 0)),
                    avg_cost=Decimal(str(p.get("avgCost", 0))),
                    market_value=_to_decimal(p.get("mktValue")),
                    unrealized_pnl=_to_decimal(p.get("unrealizedPnl")),
                    realized_pnl=_to_decimal(p.get("realizedPnl")),
                )
            )
        return positions

    async def get_pnl(self) -> dict:
        """Get daily P&L breakdown."""
        account_id = await self._get_account_id()
        data = await self._request(
            "GET", f"/iserver/account/pnl/partitioned"
        )
        # Extract the account-specific P&L from partitioned response
        acct_pnl = data.get(account_id, data) if isinstance(data, dict) else data
        return acct_pnl if isinstance(acct_pnl, dict) else {"raw": acct_pnl}

    async def get_trades(self, days: int = 1) -> list[dict]:
        """Get recent trade executions."""
        data = await self._request(
            "GET",
            "/iserver/account/trades",
            params={"days": str(days)},
        )
        return data if isinstance(data, list) else []

    # ── Info ─────────────────────────────────────────────────────

    async def get_news(
        self, symbol: Optional[str] = None, num_articles: int = 5
    ) -> list[dict]:
        """Get market news, optionally filtered by symbol."""
        params: dict[str, str] = {"count": str(num_articles)}
        if symbol:
            params["symbol"] = symbol
        data = await self._request(
            "GET", "/iserver/news/briefing", params=params
        )
        return data if isinstance(data, list) else []

    async def get_fundamentals(self, symbol: str) -> dict:
        """Get fundamental data for a symbol."""
        conid = await self._resolve_conid(ContractSpec(symbol=symbol))
        data = await self._request(
            "GET",
            "/iserver/fundamentals",
            params={"conid": str(conid), "type": "mini"},
        )
        return data if isinstance(data, dict) else {"raw": data}

    # ── Authentication & Session ─────────────────────────────────

    async def _authenticate(self) -> None:
        """Check auth status and trigger SSO if needed."""
        if self._session is None:
            raise RuntimeError("Session not initialized. Call connect() first.")
        async with self._session.post("/iserver/auth/status") as resp:
            data = await resp.json()
            self._authenticated = data.get("authenticated", False)
        if not self._authenticated:
            self.logger.info("Not authenticated, initiating SSO...")
            async with self._session.post("/iserver/auth/ssodh/init") as resp:
                data = await resp.json()
                self._authenticated = data.get("authenticated", False)
            if self._authenticated:
                self.logger.info("SSO authentication successful.")
            else:
                self.logger.warning(
                    "SSO authentication did not confirm. "
                    "Manual login to Client Portal may be required."
                )

    async def _tickle(self) -> None:
        """Keepalive ping to prevent session timeout."""
        if self._session is None:
            return
        try:
            await self._request("POST", "/tickle")
        except Exception as exc:
            self.logger.debug("Tickle failed: %s", exc)

    # ── HTTP helpers ─────────────────────────────────────────────

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> Any:
        """Make an authenticated HTTP request with auto-refresh on 401.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.).
            path: API path relative to base_url.
            **kwargs: Passed through to aiohttp request.

        Returns:
            Parsed JSON response.

        Raises:
            RuntimeError: If session is not initialized.
            aiohttp.ClientResponseError: On non-recoverable HTTP errors.
        """
        if self._session is None:
            raise RuntimeError("Session not initialized. Call connect() first.")

        self.logger.debug("%s %s", method, path)
        async with self._session.request(method, path, **kwargs) as resp:
            if resp.status == 401:
                self.logger.info("Got 401, re-authenticating...")
                await self._authenticate()
                async with self._session.request(
                    method, path, **kwargs
                ) as retry_resp:
                    retry_resp.raise_for_status()
                    return await retry_resp.json()
            resp.raise_for_status()
            return await resp.json()

    async def _get_account_id(self) -> str:
        """Get the account ID, fetching from portal if not cached."""
        if self._account_id:
            return self._account_id
        data = await self._request("GET", "/portfolio/accounts")
        if isinstance(data, list) and data:
            self._account_id = data[0].get("accountId", data[0].get("id", ""))
        else:
            raise RuntimeError("Could not retrieve account ID from portal.")
        self.logger.debug("Resolved account ID: %s", self._account_id)
        return self._account_id

    async def _resolve_conid(self, contract: ContractSpec) -> int:
        """Resolve a ContractSpec to a portal conid.

        Args:
            contract: The contract specification to resolve.

        Returns:
            The numeric contract ID used by Client Portal API.
        """
        data = await self._request(
            "GET",
            "/iserver/secdef/search",
            params={"symbol": contract.symbol, "secType": contract.sec_type},
        )
        if isinstance(data, list) and data:
            return int(data[0].get("conid", 0))
        raise ValueError(
            f"Could not resolve conid for {contract.symbol} ({contract.sec_type})"
        )
