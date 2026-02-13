"""Prediction Market Toolkit — read-only intelligence from Polymarket and Kalshi.

Provides probability signals from prediction markets for use by research
crews.  All methods are read-only; no orders are placed.

Polymarket CLOB API (public, no auth for reads):
    https://clob.polymarket.com

Kalshi public trade API:
    https://api.elections.kalshi.com/trade-api/v2
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from navconfig import config
from navconfig.logging import logging

from ..interfaces.http import HTTPService
from .toolkit import AbstractToolkit


class PredictionMarketToolkit(AbstractToolkit):
    """Read-only toolkit for prediction-market data (Polymarket + Kalshi)."""

    name = "prediction_market_toolkit"

    def __init__(
        self,
        polymarket_host: Optional[str] = None,
        kalshi_host: Optional[str] = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)

        self.polymarket_url = (
            polymarket_host
            or config.get(
                "POLYMARKET_CLOB_URL",
                fallback="https://clob.polymarket.com",
            )
        )
        self.kalshi_url = (
            kalshi_host
            or config.get(
                "KALSHI_API_URL",
                fallback="https://api.elections.kalshi.com/trade-api/v2",
            )
        )

        self._poly_http = HTTPService(
            headers={"Accept": "application/json"},
            accept="application/json",
        )
        self._poly_http._logger = self.logger

        self._kalshi_http = HTTPService(
            headers={"Accept": "application/json"},
            accept="application/json",
        )
        self._kalshi_http._logger = self.logger

    # ── Polymarket ───────────────────────────────────────────────

    async def pm_polymarket_markets(
        self,
        next_cursor: str = "LQ==",
        limit: int = 25,
        active: bool = True,
        closed: bool = False,
    ) -> Dict[str, Any]:
        """List prediction markets on Polymarket.

        Args:
            next_cursor: Pagination cursor (default first page).
            limit: Number of markets to return (max 100).
            active: Include only active markets.
            closed: Include closed markets.
        """
        params: dict[str, str] = {
            "next_cursor": next_cursor,
            "limit": str(min(limit, 100)),
        }
        if active:
            params["active"] = "true"
        if closed:
            params["closed"] = "true"

        url = f"{self.polymarket_url}/markets?{urlencode(params)}"
        result, error = await self._poly_http.async_request(
            url=url, method="GET",
        )
        if error:
            raise RuntimeError(f"Polymarket markets error: {error}")
        if isinstance(result, dict):
            return result
        raise ValueError(f"Unexpected response: {result}")

    async def pm_polymarket_market_price(
        self,
        token_id: str,
    ) -> Dict[str, Any]:
        """Get current mid-price / probability for a Polymarket token.

        Args:
            token_id: The condition token ID of the market outcome.
        """
        url = f"{self.polymarket_url}/price?token_id={token_id}"
        result, error = await self._poly_http.async_request(
            url=url, method="GET",
        )
        if error:
            raise RuntimeError(f"Polymarket price error: {error}")
        if isinstance(result, dict):
            return result
        raise ValueError(f"Unexpected response: {result}")

    async def pm_polymarket_orderbook(
        self,
        token_id: str,
    ) -> Dict[str, Any]:
        """Get orderbook depth for a Polymarket market.

        Args:
            token_id: The condition token ID of the market outcome.
        """
        url = f"{self.polymarket_url}/book?token_id={token_id}"
        result, error = await self._poly_http.async_request(
            url=url, method="GET",
        )
        if error:
            raise RuntimeError(f"Polymarket orderbook error: {error}")
        if isinstance(result, dict):
            return result
        raise ValueError(f"Unexpected response: {result}")

    # ── Kalshi ────────────────────────────────────────────────────

    async def pm_kalshi_events(
        self,
        limit: int = 25,
        status: str = "open",
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List events and active markets on Kalshi.

        Args:
            limit: Number of events to return (max 100).
            status: Filter by status (open, closed, settled).
            cursor: Pagination cursor for next page.
        """
        params: dict[str, str] = {
            "limit": str(min(limit, 100)),
            "status": status,
        }
        if cursor:
            params["cursor"] = cursor

        url = f"{self.kalshi_url}/events?{urlencode(params)}"
        result, error = await self._kalshi_http.async_request(
            url=url, method="GET",
        )
        if error:
            raise RuntimeError(f"Kalshi events error: {error}")
        if isinstance(result, dict):
            return result
        raise ValueError(f"Unexpected response: {result}")

    async def pm_kalshi_market_price(
        self,
        ticker: str,
    ) -> Dict[str, Any]:
        """Get current yes/no price for a Kalshi market.

        Args:
            ticker: The market ticker (e.g. 'FED-23DEC-T4.75').
        """
        url = f"{self.kalshi_url}/markets/{ticker}"
        result, error = await self._kalshi_http.async_request(
            url=url, method="GET",
        )
        if error:
            raise RuntimeError(f"Kalshi market error: {error}")
        if isinstance(result, dict):
            return result
        raise ValueError(f"Unexpected response: {result}")

    # ── Unified ──────────────────────────────────────────────────

    async def pm_get_market_probabilities(
        self,
        query: str = "",
        limit: int = 10,
    ) -> Dict[str, Any]:
        """Fetch top probability signals from both Polymarket and Kalshi.

        Returns a combined summary suitable for research-crew consumption.

        Args:
            query: Optional search term to filter markets.
            limit: Max markets per platform to return.
        """
        results: Dict[str, Any] = {
            "polymarket": [],
            "kalshi": [],
            "errors": [],
        }

        # ── Polymarket ───────────────────────────────────────────
        try:
            poly_data = await self.pm_polymarket_markets(
                limit=limit, active=True,
            )
            markets = poly_data.get("data", poly_data.get("markets", []))
            if query:
                markets = [
                    m for m in markets
                    if query.lower() in str(m).lower()
                ]
            results["polymarket"] = markets[:limit]
        except Exception as exc:
            self.logger.warning("Polymarket fetch failed: %s", exc)
            results["errors"].append(f"polymarket: {exc}")

        # ── Kalshi ───────────────────────────────────────────────
        try:
            kalshi_data = await self.pm_kalshi_events(
                limit=limit, status="open",
            )
            events = kalshi_data.get("events", [])
            if query:
                events = [
                    e for e in events
                    if query.lower() in str(e).lower()
                ]
            results["kalshi"] = events[:limit]
        except Exception as exc:
            self.logger.warning("Kalshi fetch failed: %s", exc)
            results["errors"].append(f"kalshi: {exc}")

        return results
