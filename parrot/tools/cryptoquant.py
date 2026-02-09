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
        flow_type: str = "netflow",
        window: str = "day",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get Exchange Flows.
        URL: https://api.cryptoquant.com/v1/{token}/exchange-flows/{flow_type}
        
        Args:
            exchange: Exchange name (e.g., 'binance', 'all_exchange')
            token: Token symbol (default 'btc')
            flow_type: Type of flow ('netflow', 'inflow', 'outflow')
            window: Time window ('block', 'day', 'hour')
        """
        url = f"{self.base_url}/{token}/exchange-flows/{flow_type}"
        params = {
            "exchange": exchange,
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
            raise Exception(f"Error fetching Exchange Flows ({flow_type}) for {exchange}: {error}")

        if isinstance(result, dict):
            return result
        raise ValueError(f"Unexpected response format: {result}")

    async def cq_miner_flows(
        self,
        miner: str = "all_miner",
        token: str = "btc",
        flow_type: str = "netflow",
        window: str = "day",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get Miner Flows.
        URL: https://api.cryptoquant.com/v1/{token}/miner-flows/{flow_type}
        
        Args:
            miner: Miner name (e.g., 'all_miner', 'antpool')
            token: Token symbol (default 'btc')
            flow_type: Type of flow ('netflow', 'inflow', 'outflow')
            window: Time window ('block', 'day', 'hour')
        """
        url = f"{self.base_url}/{token}/miner-flows/{flow_type}"
        params = {
            "miner": miner,
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
            raise Exception(f"Error fetching Miner Flows ({flow_type}) for {miner}: {error}")

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
        Get Market Indicators.
        URL: https://api.cryptoquant.com/v1/{token}/market-indicator/{indicator}
        
        Args:
            indicator: Indicator name (e.g., 'mvrv', 'sopr', 'stock-to-flow')
            token: Token symbol (default 'btc')
            window: Time window ('block', 'day', 'hour')
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
