"""Alpaca Markets Toolkit for retrieving market data."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from navconfig import config
from pydantic import BaseModel, Field

import alpaca.data.historical
from alpaca.data.requests import (
    StockLatestQuoteRequest,
    StockBarsRequest,
    CryptoLatestQuoteRequest,
    CryptoBarsRequest,
)
from alpaca.trading.requests import GetCalendarRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.common.exceptions import APIError

from .toolkit import AbstractToolkit
from .decorators import tool_schema


class AlpacaToolkitError(RuntimeError):
    """Raised when the toolkit cannot satisfy a request."""


class StockQuoteInput(BaseModel):
    """Input for get_stock_quotes."""
    symbol: str = Field(..., description="Stock symbol to query (e.g., AAPL).")


class StockBarsInput(BaseModel):
    """Input for get_stock_bars."""
    symbol: str = Field(..., description="Stock symbol to query (e.g., AAPL).")
    timeframe: str = Field(
        "1Day", 
        description="Timeframe for the bars. Examples: '1Min', '5Min', '15Min', '1Hour', '1Day'."
    )
    start: str = Field(..., description="Start date in ISO format (YYYY-MM-DD).")
    end: Optional[str] = Field(None, description="End date in ISO format (YYYY-MM-DD).")
    limit: Optional[int] = Field(None, description="Maximum number of bars to return.")


class CryptoQuoteInput(BaseModel):
    """Input for get_crypto_quotes."""
    symbol: str = Field(..., description="Crypto symbol to query (e.g., BTC/USD).")


class CryptoBarsInput(BaseModel):
    """Input for get_crypto_bars."""
    symbol: str = Field(..., description="Crypto symbol to query (e.g., BTC/USD).")
    timeframe: str = Field(
        "1Day", 
        description="Timeframe for the bars. Examples: '1Min', '5Min', '15Min', '1Hour', '1Day'."
    )
    start: str = Field(..., description="Start date in ISO format (YYYY-MM-DD).")
    end: Optional[str] = Field(None, description="End date in ISO format (YYYY-MM-DD).")
    limit: Optional[int] = Field(None, description="Maximum number of bars to return.")


class AlpacaMarketsToolkit(AbstractToolkit):
    """Toolkit for accessing Alpaca Markets financial data."""

    name = "alpaca_markets_toolkit"

    def __init__(self, **kwargs):
        """Initialize the Alpaca toolkit."""
        super().__init__(**kwargs)
        
        # Try Trading API credentials first (standard for most users)
        self.api_key = config.get("ALPACA_TRADING_API_KEY") or config.get("ALPACA_MARKETS_CLIENT_ID")
        self.api_secret = config.get("ALPACA_TRADING_API_SECRET") or config.get("ALPACA_MARKETS_CLIENT_SECRET")
        
        # For historical data, we usually don't need paper flag, but let's check config
        self.paper = config.get("ALPACA_PCB_PAPER", section="finance", fallback=True)
        self.base_url = config.get("ALPACA_API_BASE_URL", section="finance", fallback=None)

        if not self.api_key or not self.api_secret:
             # We don't raise here to allow initialization, but methods will fail or need check
             pass

        self._stock_client: Optional[alpaca.data.historical.StockHistoricalDataClient] = None
        self._crypto_client: Optional[alpaca.data.historical.CryptoHistoricalDataClient] = None
        self._trading_client: Optional[TradingClient] = None

    @property
    def stock_client(self) -> alpaca.data.historical.StockHistoricalDataClient:
        if not self._stock_client:
            if not self.api_key or not self.api_secret:
                raise AlpacaToolkitError("Alpaca API credentials not found.")
            kwargs = {}
            if self.base_url:
                kwargs["url_override"] = self.base_url
            self._stock_client = alpaca.data.historical.StockHistoricalDataClient(
                self.api_key, self.api_secret, **kwargs
            )
        return self._stock_client

    @property
    def crypto_client(self) -> alpaca.data.historical.CryptoHistoricalDataClient:
        if not self._crypto_client:
            if not self.api_key or not self.api_secret:
                raise AlpacaToolkitError("Alpaca API credentials not found.")
            kwargs = {}
            if self.base_url:
                kwargs["url_override"] = self.base_url
            self._crypto_client = alpaca.data.historical.CryptoHistoricalDataClient(
                self.api_key, self.api_secret, **kwargs
            )
        return self._crypto_client

    @property
    def trading_client(self) -> TradingClient:
        if not self._trading_client:
            if not self.api_key or not self.api_secret:
                raise AlpacaToolkitError("Alpaca API credentials not found.")
            kwargs = {}
            if self.base_url:
                kwargs["url_override"] = self.base_url
            self._trading_client = TradingClient(
                self.api_key, self.api_secret, paper=self.paper, **kwargs
            )
        return self._trading_client

    def _parse_timeframe(self, timeframe_str: str) -> TimeFrame:
        """Parse a timeframe string into an Alpaca TimeFrame object."""
        timeframe_str = timeframe_str.lower()
        if timeframe_str in ("1min", "1m", "minute"):
            return TimeFrame.Minute
        elif timeframe_str in ("5min", "5m"):
            return TimeFrame(5, TimeFrameUnit.Minute)
        elif timeframe_str in ("15min", "15m"):
            return TimeFrame(15, TimeFrameUnit.Minute)
        elif timeframe_str in ("1hour", "1h", "hour"):
            return TimeFrame.Hour
        elif timeframe_str in ("1day", "1d", "day"):
            return TimeFrame.Day
        
        # Fallback to granular parsing if needed, but for now specific map
        # If user passes "1Day", it matches above.
        raise ValueError(f"Unsupported timeframe: {timeframe_str}")

    @tool_schema(StockQuoteInput)
    async def get_stock_quotes(self, symbol: str) -> Dict[str, Any]:
        """Get the latest quote for a stock symbol."""
        request_params = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        
        try:
            # Run in executor to avoid blocking
            quotes = await asyncio.to_thread(
                self.stock_client.get_stock_latest_quote, request_params
            )
            # data is a dict keyed by symbol
            if symbol in quotes:
                return {
                    "symbol": symbol,
                    "quote": quotes[symbol].model_dump(),
                    "source": "alpaca"
                }
            return {"symbol": symbol, "error": "No quote found"}
        except Exception as e:
            raise AlpacaToolkitError(f"Error fetching stock quote: {e}")

    @tool_schema(StockBarsInput)
    async def get_stock_bars(
        self, 
        symbol: str, 
        timeframe: str, 
        start: str, 
        end: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get historical bars for a stock."""
        try:
            tf = self._parse_timeframe(timeframe)
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end) if end else None
            
            request_params = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start_dt,
                end=end_dt,
                limit=limit
            )
            
            bars = await asyncio.to_thread(
                self.stock_client.get_stock_bars, request_params
            )
            
            # Bars is a BarSet, we can iterate or use .df
            data = bars.df.reset_index().to_dict(orient="records") if not bars.df.empty else []
            
            # Clean timestamps to strings
            for row in data:
                if 'timestamp' in row and isinstance(row['timestamp'], datetime):
                    row['timestamp'] = row['timestamp'].isoformat()
            
            return {
                "symbol": symbol,
                "bars_count": len(data),
                "bars": data,
                "parameters": {"timeframe": timeframe, "start": start, "end": end}
            }
        except Exception as e:
            raise AlpacaToolkitError(f"Error fetching stock bars: {e}")

    @tool_schema(CryptoQuoteInput)
    async def get_crypto_quotes(self, symbol: str) -> Dict[str, Any]:
        """Get the latest quote for a crypto symbol."""
        request_params = CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
        
        try:
            quotes = await asyncio.to_thread(
                self.crypto_client.get_crypto_latest_quote, request_params
            )
            if symbol in quotes:
                return {
                    "symbol": symbol,
                    "quote": quotes[symbol].model_dump(),
                    "source": "alpaca_crypto"
                }
            return {"symbol": symbol, "error": "No quote found"}
        except Exception as e:
            raise AlpacaToolkitError(f"Error fetching crypto quote: {e}")

    @tool_schema(CryptoBarsInput)
    async def get_crypto_bars(
        self, 
        symbol: str, 
        timeframe: str, 
        start: str, 
        end: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get historical bars for a cryptocurrency."""
        try:
            tf = self._parse_timeframe(timeframe)
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end) if end else None
            
            request_params = CryptoBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start_dt,
                end=end_dt,
                limit=limit
            )
            
            bars = await asyncio.to_thread(
                self.crypto_client.get_crypto_bars, request_params
            )
            
            data = bars.df.reset_index().to_dict(orient="records") if not bars.df.empty else []
            
            for row in data:
                if 'timestamp' in row and isinstance(row['timestamp'], datetime):
                    row['timestamp'] = row['timestamp'].isoformat()

            return {
                "symbol": symbol,
                "bars_count": len(data),
                "bars": data,
                "parameters": {"timeframe": timeframe, "start": start, "end": end}
            }
        except Exception as e:
            raise AlpacaToolkitError(f"Error fetching crypto bars: {e}")

    async def get_clock(self) -> Dict[str, Any]:
        """Get the market clock (is open, next open, etc)."""
        try:
            clock = await asyncio.to_thread(self.trading_client.get_clock)
            return clock.model_dump()
        except Exception as e:
            raise AlpacaToolkitError(f"Error fetching market clock: {e}")

    async def get_calendar(self, start: Optional[str] = None, end: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get the market calendar."""
        try:
            filters = {}
            if start:
                filters['start'] = start
            if end:
                filters['end'] = end
                
            # TradingClient.get_calendar signature might vary, usually safe to call without args or with simple date filter
            # Checks for start/end in args if supported, else relies on defaults
            
            req = GetCalendarRequest(start=start, end=end)
            
            cals = await asyncio.to_thread(self.trading_client.get_calendar, req)
            return [c.model_dump() for c in cals]
        except Exception as e:
            raise AlpacaToolkitError(f"Error fetching market calendar: {e}")
