import logging
import asyncio
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode
import logging

from pydantic import BaseModel, Field
from parrot.tools import AbstractToolkit
from parrot.tools.decorators import tool_schema
from navconfig import config
from parrot.interfaces.http import HTTPService


class CMCGlobalMetricsInput(BaseModel):
    pass


class CMCListingsInput(BaseModel):
    start: int = Field(1, description="Offset start (1-based text)")
    limit: int = Field(100, description="Number of results to return")
    convert: str = Field("USD", description="Currency to convert metrics to")
    sort: str = Field("market_cap", description="Field to sort by")
    sort_dir: str = Field("desc", description="Sort direction (asc/desc)")


class CMCInfoInput(BaseModel):
    symbol: str = Field(..., description="Comma-separated list of cryptocurrency symbols (e.g. 'BTC,ETH')")


class CMCQuotesInput(BaseModel):
    symbol: str = Field(..., description="Comma-separated list of cryptocurrency symbols (e.g. 'BTC,ETH')")
    convert: str = Field("USD", description="Currency to convert metrics to")


class CMCExchangeListingsInput(BaseModel):
    limit: int = Field(100, description="Number of results to return")
    sort: str = Field("volume_24h", description="Field to sort by")
    sort_dir: str = Field("desc", description="Sort direction (asc/desc)")


class CMCToolkit(AbstractToolkit):
    """
    Toolkit for interacting with the CoinMarketCap API.
    Provides methods to access global market metrics, cryptocurrency listings, and metadata.
    """
    
    BASE_URL = "https://pro-api.coinmarketcap.com"

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)
        # Try finding key in multiple env vars, defaulting to CMC_API_KEY
        self.api_key = api_key or config.get('CMC_API_KEY') or config.get('COINMARKETCAP_API_KEY')
        
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "deflate, gzip"
        }
        if self.api_key:
            headers["X-CMC_PRO_API_KEY"] = self.api_key
             
        self.http_service = HTTPService(
            headers=headers,
            rotate_ua=True
        )
        self.http_service._logger = self.logger

    async def _request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Helper to make requests to CMC API."""
        url = f"{self.BASE_URL}{endpoint}"
        if params:
            # remove None values
            params = {k: v for k, v in params.items() if v is not None}
            url = f"{url}?{urlencode(params)}"
            
        result, error = await self.http_service.async_request(url=url, method="GET")
        
        if error:
            # CMC returns errors in {status: {error_message: ...}} format usually
            if isinstance(result, str):
                import json
                try:
                    result = json.loads(result)
                except Exception:
                    pass

            if isinstance(result, dict) and 'status' in result and 'error_message' in result['status']:
                if result['status']['error_message']:
                    raise Exception(f"CMC API Error: {result['status']['error_message']}")
            raise Exception(f"HTTP Error: {error}")

        if isinstance(result, str):
            import json
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                raise ValueError(f"Invalid JSON response: {result}")
            
        return result

    @tool_schema(CMCGlobalMetricsInput)
    async def cmc_global_metrics(self) -> Dict[str, Any]:
        """
        Get global cryptocurrency market metrics.
        Includes total market cap, volume, BTC dominance, etc.
        """
        return await self._request("/v1/global-metrics/quotes/latest")

    @tool_schema(CMCListingsInput)
    async def cmc_cryptocurrency_listings(
        self, 
        start: int = 1, 
        limit: int = 100, 
        convert: str = "USD",
        sort: str = "market_cap",
        sort_dir: str = "desc"
    ) -> Dict[str, Any]:
        """
        Get a list of cryptocurrencies with latest market data.
        """
        params = {
            "start": start,
            "limit": limit,
            "convert": convert,
            "sort": sort,
            "sort_dir": sort_dir
        }
        return await self._request("/v1/cryptocurrency/listings/latest", params)

    @tool_schema(CMCInfoInput)
    async def cmc_cryptocurrency_info(self, symbol: str) -> Dict[str, Any]:
        """
        Get metadata (logo, website, description) for cryptocurrencies.
        Args:
            symbol: Comma-separated list of cryptocurrency symbols (e.g. "BTC,ETH")
        """
        params = {"symbol": symbol}
        return await self._request("/v1/cryptocurrency/info", params)

    @tool_schema(CMCQuotesInput)
    async def cmc_cryptocurrency_quotes(self, symbol: str, convert: str = "USD") -> Dict[str, Any]:
        """
        Get latest market quotes for specific cryptocurrencies.
        Args:
            symbol: Comma-separated list of cryptocurrency symbols (e.g. "BTC,ETH")
        """
        params = {"symbol": symbol, "convert": convert}
        return await self._request("/v1/cryptocurrency/quotes/latest", params)

    @tool_schema(CMCExchangeListingsInput)
    async def cmc_exchange_listings(self, limit: int = 100, sort: str = "volume_24h", sort_dir: str = "desc") -> Dict[str, Any]:
        """
        Get a list of exchanges with latest market data.
        """
        params = {
            "limit": limit,
            "sort": sort,
            "sort_dir": sort_dir
        }
        return await self._request("/v1/exchange/listings/latest", params)
