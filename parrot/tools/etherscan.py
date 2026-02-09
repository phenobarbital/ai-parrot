import logging
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode

from pydantic import BaseModel, Field
from parrot.tools import AbstractToolkit
from parrot.tools.decorators import tool_schema
from navconfig import config
from parrot.interfaces.http import HTTPService


class ETHGasOracleInput(BaseModel):
    pass


class ETHSupplyInput(BaseModel):
    pass


class ETHPriceInput(BaseModel):
    pass


class ETHAccountBalanceInput(BaseModel):
    address: str = Field(..., description="The Ethereum address to check the balance of")
    tag: str = Field("latest", description="The block tag ('latest', 'pending', 'earliest')")


class EtherscanToolkit(AbstractToolkit):
    """
    Toolkit for interacting with the Etherscan API.
    Provides methods to access Ethereum blockchain data, including gas prices, supply, and account balances.
    """
    
    BASE_URL = "https://api.etherscan.io/v2/api"

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.api_key = api_key or config.get('ETHERSCAN_API_KEY')
        
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "deflate, gzip"
        }
             
        self.http_service = HTTPService(
            headers=headers,
            rotate_ua=True
        )
        self.http_service._logger = self.logger

    async def _request(self, module: str, action: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Helper to make requests to Etherscan API."""
        if not self.api_key:
            raise ValueError("ETHERSCAN_API_KEY is required for Etherscan API requests.")

        if params is None:
            params = {}
            
        params['chainid'] = 1  # Ethereum Mainnet
        params['module'] = module
        params['action'] = action
        params['apikey'] = self.api_key
        
        # Remove None values
        params = {k: v for k, v in params.items() if v is not None}
        
        url = f"{self.BASE_URL}?{urlencode(params)}"
            
        result, error = await self.http_service.async_request(url=url, method="GET")
        
        if error:
             if isinstance(result, str):
                import json
                try:
                    result = json.loads(result)
                except Exception:
                    pass
             raise Exception(f"HTTP Error from Etherscan: {error}")

        if isinstance(result, str):
            import json
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                raise ValueError(f"Invalid JSON response: {result}")
        
        if isinstance(result, dict):
            # Etherscan specific error check
            # 'status': '1' is OK, '0' is Error
            if result.get('status') == '0':
                 message = result.get('message', 'Unknown Error')
                 result_data = result.get('result', '')
                 # V2 migration might return 'NOTOK' message if we did something wrong, catch it
                 if message == 'NOTOK':
                     raise Exception(f"Etherscan API Error: {message} - {result_data}")
                 
                 raise Exception(f"Etherscan API Error: {message} - {result_data}")
            return result.get('result')
            
        return result

    @tool_schema(ETHGasOracleInput)
    async def eth_gas_oracle(self) -> Dict[str, Any]:
        """
        Get the current Safe, Propose and Fast gas prices.
        """
        return await self._request("gastracker", "gasoracle")

    @tool_schema(ETHSupplyInput)
    async def eth_supply(self) -> str:
        """
        Get the total supply of Ether.
        """
        return await self._request("stats", "ethsupply")

    @tool_schema(ETHPriceInput)
    async def eth_last_price(self) -> Dict[str, Any]:
        """
        Get the latest price of Ether (in USD and BTC).
        """
        return await self._request("stats", "ethprice")

    @tool_schema(ETHAccountBalanceInput)
    async def eth_account_balance(self, address: str, tag: str = "latest") -> str:
        """
        Get the Ether balance of a specific address.
        """
        params = {"address": address, "tag": tag}
        return await self._request("account", "balance", params)
