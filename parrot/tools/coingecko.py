from typing import Optional, List, Dict, Any
from urllib.parse import urlencode
from navconfig import config
from navconfig.logging import logging
from ..interfaces.http import HTTPService
from .toolkit import AbstractToolkit



class CoingeckoToolkit(AbstractToolkit):
    """
    Toolkit for interacting with the CoinGecko API.
    Provides access to crypto prices, market data, metadata, and trading signals.
    """

    def __init__(self, api_key: Optional[str] = None, demo: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.api_key = api_key or config.get('COINGECKO_API_KEY')
        self.demo = demo

        if self.demo is True:
            self.base_url = "https://api.coingecko.com/api/v3"
            self.header_name = "x-cg-demo-api-key"
        else:
            self.base_url = "https://pro-api.coingecko.com/api/v3"
            self.header_name = "x_cg_pro_api_key"

        headers = {}
        if self.api_key:
            headers[self.header_name] = self.api_key

        self.http_service = HTTPService(headers=headers, accept="application/json")
        self.http_service._logger = self.logger

    async def ping(self) -> Dict[str, str]:
        """
        Check API server status.
        """
        url = f"{self.base_url}/ping"
        result, error = await self.http_service.async_request(url=url, method="GET")
        
        if error:
            raise Exception(f"Error pinging CoinGecko API: {error}")
            
        return result

    async def cg_simple_price(
        self, 
        ids: str, 
        vs_currencies: str, 
        include_market_cap: bool = False,
        include_24hr_vol: bool = False,
        include_24hr_change: bool = False,
        include_last_updated_at: bool = False,
        precision: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get the current price of any cryptocurrencies in any other supported currencies.
        
        Args:
            ids: id of coins, comma-separated if querying more than 1 coin.
            vs_currencies: vs_currency of coins, comma-separated if querying more than 1 vs_currency.
            include_market_cap: true/false to include market_cap.
            include_24hr_vol: true/false to include 24hr_vol.
            include_24hr_change: true/false to include 24hr_change.
            include_last_updated_at: true/false to include last_updated_at of price.
            precision: full or any value between 0-18 to specify decimal place for currency price value.
        """
        url = f"{self.base_url}/simple/price"
        params = {
            "ids": ids,
            "vs_currencies": vs_currencies,
            "include_market_cap": str(include_market_cap).lower(),
            "include_24hr_vol": str(include_24hr_vol).lower(),
            "include_24hr_change": str(include_24hr_change).lower(),
            "include_last_updated_at": str(include_last_updated_at).lower()
        }
        if precision:
            params["precision"] = precision

        full_url = f"{url}?{urlencode(params)}"
        result, error = await self.http_service.async_request(url=full_url, method="GET")

        if error:
            raise Exception(f"Error fetching simple price: {error}")

        if isinstance(result, dict):
            return result
        raise ValueError(f"Unexpected response format: {result}")

    async def cg_coins_list(self, include_platform: bool = False) -> List[Dict[str, Any]]:
        """
        List all supported coins id, name and symbol (no pagination required).
        
        Args:
            include_platform: true/false to include platform contract addresses (eg. 0x...).
        """
        url = f"{self.base_url}/coins/list"
        params = {
            "include_platform": str(include_platform).lower()
        }
        full_url = f"{url}?{urlencode(params)}"
        
        result, error = await self.http_service.async_request(url=full_url, method="GET")

        if error:
            raise Exception(f"Error fetching coins list: {error}")

        if isinstance(result, list):
            return result
        raise ValueError(f"Unexpected response format: {result}")

    async def cg_coins_markets(
        self,
        vs_currency: str,
        ids: Optional[str] = None,
        category: Optional[str] = "layer-1",
        order: str = "market_cap_desc",
        per_page: int = 100,
        page: int = 1,
        sparkline: bool = False,
        price_change_percentage: str = "1h",
        locale: str = "en",
        precision: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List all supported coins price, market cap, volume, and market related data.
        
        Args:
            vs_currency: The target currency of market data (e.g., usd, eur, jpy, etc.)
            ids: The ids of the coin, comma separated query for multiple coins (e.g., bitcoin,ethereum)
            category: filter by coin category.
            order: sort results by field.
            per_page: Total results per page (1...250).
            page: Page through results.
            sparkline: Include sparkline 7 days data.
            price_change_percentage: Include price change percentage in 1h, 24h, 7d, 14d, 30d, 200d, 1y.
            locale: valid locale.
            precision: full or 0-18.
        """
        url = f"{self.base_url}/coins/markets"
        params = {
            "vs_currency": vs_currency,
            "order": order,
            "per_page": per_page,
            "page": page,
            "sparkline": str(sparkline).lower(),
            "price_change_percentage": price_change_percentage,
            "locale": locale
        }
        if ids:
            params["ids"] = ids
        if category:
            params["category"] = category
        if precision:
            params["precision"] = precision

        full_url = f"{url}?{urlencode(params)}"
        result, error = await self.http_service.async_request(url=full_url, method="GET")

        if error:
             raise Exception(f"Error fetching coins markets: {error}")
        
        if isinstance(result, list):
            return result
        raise ValueError(f"Unexpected response format: {result}")

    async def cg_coins_ohlc(
        self, 
        coin_id: str, 
        vs_currency: str, 
        days: str, 
        precision: Optional[str] = None
    ) -> List[List[float]]:
        """
        Get the OHLC chart (Open, High, Low, Close) of a coin based on particular coin ID.
        
        Args:
            coin_id: The coin id (can be obtained from /coins)
            vs_currency: The target currency of market data (e.g., usd, eur, jpy, etc.)
            days: Data up to number of days ago (1, 7, 14, 30, 90, 180, 365, max).
            precision: full or 0-18.
        """
        url = f"{self.base_url}/coins/{coin_id}/ohlc"
        params = {
            "vs_currency": vs_currency,
            "days": days
        }
        if precision:
            params["precision"] = precision
            
        full_url = f"{url}?{urlencode(params)}"
        result, error = await self.http_service.async_request(url=full_url, method="GET")
        
        if error:
            raise Exception(f"Error fetching OHLC data for {coin_id}: {error}")
            
        if isinstance(result, list):
            return result
        raise ValueError(f"Unexpected response format: {result}")

    async def cg_search_trending(self) -> Dict[str, Any]:
        """
        Get trending search coins (Top-7) on CoinGecko in the last 24 hours.
        """
        url = f"{self.base_url}/search/trending"
        result, error = await self.http_service.async_request(url=url, method="GET")
        
        if error:
            raise Exception(f"Error fetching trending search: {error}")
            
        if isinstance(result, dict):
            return result
        raise ValueError(f"Unexpected response format: {result}")
