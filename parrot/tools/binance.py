import time
import hmac
import hashlib
from urllib.parse import urlencode
from typing import Optional, List, Dict, Any
from navconfig import config
from navconfig.logging import logging
from ..interfaces.http import HTTPService
from .toolkit import AbstractToolkit


class BinanceToolkit(AbstractToolkit):
    """
    Toolkit for interacting with the Binance API (Spot and Futures).
    Provides access to market data, funding rates, open interest, and key derivatives metrics.
    Documentation: https://binance-docs.github.io/apidocs/spot/en/
                   https://binance-docs.github.io/apidocs/futures/en/
    """
    name: str = "binance_toolkit"
    description: str = "Toolkit for Binance Spot and Futures API."

    SPOT_URL = "https://api.binance.com"
    FUTURES_URL = "https://fapi.binance.com"

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.api_key = api_key or config.get('BINANCE_API_KEY')
        self.api_secret = api_secret or config.get('BINANCE_API_SECRET')
        
        headers = {
            "Accept": "application/json"
        }
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key

        self.http_service = HTTPService(headers=headers)
        self.http_service._logger = self.logger

    def _sign(self, params: Dict[str, Any]) -> str:
        """Sign request parameters for private endpoints."""
        if not self.api_secret:
            raise ValueError("BINANCE_API_SECRET is required for signed requests.")
        
        # Sort params as query string
        query_string = urlencode(dict(sorted(params.items())))
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature

    async def _request(
        self, 
        base_url: str, 
        endpoint: str, 
        params: Dict[str, Any] = None, 
        signed: bool = False, 
        method: str = "GET"
    ) -> Any:
        """Internal request helper."""
        if params is None:
            params = {}
            
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._sign(params)

        url = f"{base_url}{endpoint}"
        
        request_kwargs = {"method": method}

        if method == "GET":
            if params:
                url = f"{url}?{urlencode(params)}"
            request_kwargs["url"] = url
        else:
            request_kwargs["url"] = url
            request_kwargs["data"] = params

        result, error = await self.http_service.async_request(**request_kwargs)

        if error:
            raise Exception(f"Binance API Error on {endpoint}: {error}")
            
        if isinstance(result, (dict, list)):
            return result
        
        # Try parsing string manually if HTTPService didn't
        if isinstance(result, str):
            import json
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                pass
        return result

    # --- Spot Market Data ---

    async def get_spot_price(self, symbol: str) -> Dict[str, Any]:
        """
        Get latest spot price.
        Endpoint: /api/v3/ticker/price
        """
        return await self._request(
            self.SPOT_URL, 
            "/api/v3/ticker/price", 
            {"symbol": symbol.upper()}
        )

    async def get_spot_klines(self, symbol: str, interval: str = "1d", limit: int = 100) -> List[List[Any]]:
        """
        Get spot OHLCV klines.
        Endpoint: /api/v3/klines
        """
        return await self._request(
            self.SPOT_URL,
            "/api/v3/klines",
            {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        )

    async def get_exchange_info(self) -> Dict[str, Any]:
        """
        Get current exchange trading rules and symbol information.
        Endpoint: /api/v3/exchangeInfo
        """
        return await self._request(self.SPOT_URL, "/api/v3/exchangeInfo")

    # --- Futures Market Data (Key for Finance Swarm) ---

    async def get_futures_price(self, symbol: str) -> Dict[str, Any]:
        """
        Get latest futures price.
        Endpoint: /fapi/v1/ticker/price
        """
        return await self._request(
            self.FUTURES_URL,
            "/fapi/v1/ticker/price",
            {"symbol": symbol.upper()}
        )

    async def get_funding_rate(self, symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get funding rate history.
        Endpoint: /fapi/v1/fundingRate
        """
        return await self._request(
            self.FUTURES_URL,
            "/fapi/v1/fundingRate",
            {"symbol": symbol.upper(), "limit": limit}
        )
    
    async def get_premium_index(self, symbol: str = None) -> List[Dict[str, Any]]:
        """
        Get Mark Price and Funding Rate.
        Endpoint: /fapi/v1/premiumIndex
        """
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return await self._request(self.FUTURES_URL, "/fapi/v1/premiumIndex", params)

    async def get_open_interest(self, symbol: str) -> Dict[str, Any]:
        """
        Get Open Interest for a symbol.
        Endpoint: /fapi/v1/openInterest
        """
        return await self._request(
            self.FUTURES_URL,
            "/fapi/v1/openInterest",
            {"symbol": symbol.upper()}
        )

    async def get_open_interest_stats(self, symbol: str, period: str = "1h", limit: int = 30) -> List[Dict[str, Any]]:
        """
        Get Open Interest Statistics.
        Endpoint: /futures/data/openInterestHist
        """
        return await self._request(
            self.FUTURES_URL,
            "/futures/data/openInterestHist",
            {"symbol": symbol.upper(), "period": period, "limit": limit}
        )

    async def get_top_long_short_ratio_accounts(self, symbol: str, period: str = "1h", limit: int = 30) -> List[Dict[str, Any]]:
        """
        Get Top Trader Long/Short Ratio (Accounts).
        Endpoint: /futures/data/topLongShortAccountRatio
        """
        return await self._request(
            self.FUTURES_URL,
            "/futures/data/topLongShortAccountRatio",
            {"symbol": symbol.upper(), "period": period, "limit": limit}
        )

    async def get_top_long_short_ratio_positions(self, symbol: str, period: str = "1h", limit: int = 30) -> List[Dict[str, Any]]:
        """
        Get Top Trader Long/Short Ratio (Positions).
        Endpoint: /futures/data/topLongShortPositionRatio
        """
        return await self._request(
            self.FUTURES_URL,
            "/futures/data/topLongShortPositionRatio",
            {"symbol": symbol.upper(), "period": period, "limit": limit}
        )

    async def get_global_long_short_ratio(self, symbol: str, period: str = "1h", limit: int = 30) -> List[Dict[str, Any]]:
        """
        Get Long/Short Ratio.
        Endpoint: /futures/data/globalLongShortAccountRatio
        """
        return await self._request(
            self.FUTURES_URL,
            "/futures/data/globalLongShortAccountRatio",
            {"symbol": symbol.upper(), "period": period, "limit": limit}
        )

    async def get_taker_volume(self, symbol: str, period: str = "1h", limit: int = 30) -> List[Dict[str, Any]]:
        """
        Get Taker Buy/Sell Volume.
        Endpoint: /futures/data/takerlongshortRatio
        """
        return await self._request(
            self.FUTURES_URL,
            "/futures/data/takerlongshortRatio",
            {"symbol": symbol.upper(), "period": period, "limit": limit}
        )
