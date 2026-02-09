"""DefiLlama toolkit for retrieving DeFi data."""
import os
import asyncio
from typing import Any, Dict, List, Optional
from defillama_sdk import DefiLlama, DefiLlamaConfig

from .toolkit import AbstractToolkit


class DefiLlamaToolkit(AbstractToolkit):
    """
    DefiLlama Toolkit for accessing DeFi data.
    Exposes modules: TVL, Prices, Stablecoins, Volumes, Fees.
    """

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        """
        Initialize the DefiLlama toolkit.
        
        Args:
            api_key: Optional DefiLlama API key (defaults to DEFILLAMA_API_KEY env var)
        """
        super().__init__(**kwargs)
        self._api_key = api_key or os.environ.get("DEFILLAMA_API_KEY")
        self._client: Optional[DefiLlama] = None

    @property
    def client(self) -> DefiLlama:
        if self._client is None:
            config = None
            if self._api_key:
                config = DefiLlamaConfig(api_key=self._api_key)
            self._client = DefiLlama(config=config)
        return self._client

    async def _run_command(self, module_name: str, command: str, **kwargs) -> Any:
        """Helper to run SDK commands in executor."""
        loop = asyncio.get_running_loop()
        
        def _exec():
            # Get the module instance (e.g., client.tvl, client.prices)
            module = getattr(self.client, module_name, None)
            if not module:
                raise ValueError(f"Module '{module_name}' not found in DefiLlama client.")

            # Get the method from the module
            method = getattr(module, command, None)
            if not method:
                raise ValueError(f"Command '{command}' not found in module '{module_name}'.")

            # Filter None values from kwargs to avoid passing them to methods that don't expect them
            # BUT: some methods might expect None as default? 
            # SDK methods signatures usually have defaults. passing None explicitly might be fine if default is None.
            # However, if I define `protocol: str = None` in my tool method, and pass it as `protocol=None` to SDK method 
            # expecting `protocol: str`, it might fail if it doesn't handle None.
            # Most SDK methods: `def getProtocol(self, protocol: str)`. It expects a string.
            # So I must only pass arguments that are provided (not None).
            
            clean_kwargs = {k: v for k, v in kwargs.items() if v is not None}
            return method(**clean_kwargs)

        return await loop.run_in_executor(None, _exec)

    async def tvl(
        self, 
        command: str, 
        protocol: Optional[str] = None, 
        chain: Optional[str] = None,
        symbol: Optional[str] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None
    ) -> Any:
        """
        Access TVL module.
        
        Commands:
        - getChains()
        - getProtocol(protocol)
        - getHistoricalChainTvl(chain)
        - getTvl(protocol)
        - getInflows(protocol, start_timestamp, end_timestamp)
        - getTokenProtocols(symbol)
        """
        return await self._run_command(
            "tvl", 
            command, 
            protocol=protocol, 
            chain=chain, 
            symbol=symbol,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp
        )

    async def prices(
        self, 
        command: str, 
        coins: Optional[List[str]] = None, 
        timestamp: Optional[int] = None,
        search_width: Optional[str] = None,
        chain: Optional[str] = None
    ) -> Any:
        """
        Access Prices module.
        
        Commands:
        - getCurrentPrices(coins)
        - getHistoricalPrices(timestamp, coins)
        - getBlockAtTimestamp(chain, timestamp)
        """
        # map 'search_width' to 'searchWidth' if needed by SDK?
        # SDK signature: `getHistoricalPrices(..., searchWidth: str = None)`
        # So I need to use correct kwarg name expected by SDK.
        
        # Mapping my args to SDK args
        sdk_kwargs = {}
        if coins is not None: sdk_kwargs['coins'] = coins
        if timestamp is not None: sdk_kwargs['timestamp'] = timestamp
        if search_width is not None: sdk_kwargs['searchWidth'] = search_width
        if chain is not None: sdk_kwargs['chain'] = chain
            
        return await self._run_command("prices", command, **sdk_kwargs)

    async def stablecoins(
        self, 
        command: str, 
        asset: Optional[str] = None, 
        chain: Optional[str] = None,
        stablecoin_id: Optional[int] = None,
        include_prices: Optional[bool] = None
    ) -> Any:
        """
        Access Stablecoins module.
        
        Commands:
        - getStablecoins(includePrices=True/False)
        - getStablecoin(asset)
        - getChains()
        - getDominance(chain, stablecoinId)
        """
        # Map args
        sdk_kwargs = {}
        if asset is not None: sdk_kwargs['asset'] = asset
        if chain is not None: sdk_kwargs['chain'] = chain
        if stablecoin_id is not None: sdk_kwargs['stablecoinId'] = stablecoin_id
        if include_prices is not None: sdk_kwargs['includePrices'] = include_prices

        return await self._run_command("stablecoins", command, **sdk_kwargs)

    async def volumes(
        self, 
        command: str, 
        protocol: Optional[str] = None, 
        chain: Optional[str] = None, 
        options: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Access Volumes module.
        
        Commands:
        - getDexOverview()
        - getDexSummary(protocol)
        - getDexOverviewByChain(chain)
        """
        return await self._run_command("volumes", command, protocol=protocol, chain=chain, options=options)

    async def fees(
        self, 
        command: str, 
        protocol: Optional[str] = None, 
        chain: Optional[str] = None, 
        options: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Access Fees module.
        
        Commands:
        - getOverview()
        - getSummary(protocol)
        - getOverviewByChain(chain)
        """
        return await self._run_command("fees", command, protocol=protocol, chain=chain, options=options)
