from typing import Optional, List, Dict, Any
from urllib.parse import urlencode
from navconfig import config
from navconfig.logging import logging
from ..interfaces.http import HTTPService
from .toolkit import AbstractToolkit


class CryptoQuantToolkit(AbstractToolkit):
    """
    Toolkit for interacting with the CryptoQuant API.
    Provides access to on-chain data, exchange flows, and miner data.
    Documentation: https://cryptoquant.com/docs
    """

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.api_key = api_key or config.get('CRYPTOQUANT_API_KEY')
        self.base_url = "https://api.cryptoquant.com/v1"

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        # Initialize HTTP Service
        self.http_service = HTTPService(headers=headers, accept="application/json")
        self.http_service._logger = self.logger

    async def cq_discovery_endpoints(self) -> Dict[str, Any]:
        """
        Discover available endpoints and their parameters.
        URL: https://api.cryptoquant.com/v1/discovery/endpoints
        """
        url = f"{self.base_url}/discovery/endpoints"
        result, error = await self.http_service.async_request(url=url, method="GET")

        if error:
            raise Exception(f"Error fetching discovery endpoints: {error}")

        if isinstance(result, dict):
            return result
        raise ValueError(f"Unexpected response format: {result}")

    async def cq_price_ohlcv(
        self,
        token: str,
        window: str = "day",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get OHLCV (Open, High, Low, Close, Volume) price data for alternative tokens.
        URL: https://api.cryptoquant.com/v1/alt/market-data/price-ohlcv
        
        Args:
            token: The token symbol (e.g., 'doge', 'ada', 'trx', etc.)
            window: Time window (e.g., 'day', 'hour', 'block')
            from_date: Start date in YYYYMMDD format
            to_date: End date in YYYYMMDD format
            limit: Limit number of records
        """
        url = f"{self.base_url}/alt/market-data/price-ohlcv"
        params = {
            "token": token,
            "window": window
        }
        
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if limit:
            params["limit"] = str(limit)

        full_url = f"{url}?{urlencode(params)}"
        result, error = await self.http_service.async_request(url=full_url, method="GET")

        if error:
            raise Exception(f"Error fetching OHLCV data for {token}: {error}")

        if isinstance(result, dict):
            return result
        raise ValueError(f"Unexpected response format: {result}")
    async def cq_exchange_flows(
        self,
        exchange: str,
        token: str = "btc",
        window: str = "day",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get Exchange Flows (Inflow, Outflow, Netflow) for a specific exchange.
        URL: https://api.cryptoquant.com/v1/{token}/exchange-flows/{exchange}
        """
        url = f"{self.base_url}/{token}/exchange-flows/{exchange}"
        params = {"window": window}
        
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if limit:
            params["limit"] = str(limit)

        full_url = f"{url}?{urlencode(params)}"
        result, error = await self.http_service.async_request(url=full_url, method="GET")

        if error:
            raise Exception(f"Error fetching Exchange Flows for {exchange}: {error}")

        if isinstance(result, dict):
            return result
        raise ValueError(f"Unexpected response format: {result}")

    async def cq_miner_flows(
        self,
        token: str = "btc",
        window: str = "day",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get Miner Flows (Total Miner to Exchange Flow, etc).
        URL: https://api.cryptoquant.com/v1/{token}/miner-flows/all
        """
        url = f"{self.base_url}/{token}/miner-flows/all"
        params = {"window": window}
        
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if limit:
            params["limit"] = str(limit)

        full_url = f"{url}?{urlencode(params)}"
        result, error = await self.http_service.async_request(url=full_url, method="GET")

        if error:
            raise Exception(f"Error fetching Miner Flows: {error}")

        if isinstance(result, dict):
            return result
        raise ValueError(f"Unexpected response format: {result}")

    async def cq_market_indicator(
        self,
        indicator: str,
        token: str = "btc",
        window: str = "day",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get Market Indicators (e.g. mvrv, sopr, etc if available via specific endpoints).
        Note: The actual endpoint path depends on the specific indicator logic in CryptoQuant API.
        This is a generic wrapper assuming structure /v1/{token}/market-indicator/{indicator}.
        Monitor for 404s if indicator name is invalid.
        """
        url = f"{self.base_url}/{token}/market-indicator/{indicator}"
        params = {"window": window}
        
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if limit:
            params["limit"] = str(limit)

        full_url = f"{url}?{urlencode(params)}"
        result, error = await self.http_service.async_request(url=full_url, method="GET")

        if error:
            raise Exception(f"Error fetching Market Indicator {indicator}: {error}")

        if isinstance(result, dict):
            return result
        raise ValueError(f"Unexpected response format: {result}")
