from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from navconfig import config
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from parrot.interfaces.http import HTTPService


class CMCFearGreedInput(AbstractToolArgsSchema):
    start: Optional[int] = Field(
        default=None,
        description="Integer specifying the starting point of the data retrieval."
    )
    limit: Optional[int] = Field(
        default=10,
        le=10,
        description="Integer specifying the number of records to return (default is 10, max is 10)."
    )

class CMCFearGreedEntry(BaseModel):
    timestamp: str
    value: int
    value_classification: str

class CMCFearGreedData(BaseModel):
    total_count: Optional[str] = None
    data: List[CMCFearGreedEntry]

class CMCFearGreedTool(AbstractTool):
    """
    Tool for fetching the CoinMarketCap Fear & Greed Index.
    
    The CMC Fear and Greed Index can be used in several ways:
      • Market Sentiment Analysis: By observing the current value of the index, you can gauge the overall mood of the cryptocurrency market. For example, a high value suggests that investors are overly greedy, which may indicate that the market is overheated and due for a correction. Conversely, a low value may suggest that fear is driving prices down, potentially creating buying opportunities.
      • Contrarian Strategy: Some investors use the index as part of a contrarian investment strategy. The idea is to "be fearful when others are greedy and greedy when others are fearful." If the index shows extreme greed, it might be a signal to consider selling assets, while extreme fear could indicate a buying opportunity.
      • Complementary Analysis: Use the index alongside other analytical tools and indicators to make more informed decisions. It’s important to remember that the index is a tool for gauging sentiment and should not be used in isolation.
    """
    name: str = "cmc_fear_greed"
    description: str = "Fetches the CoinMarketCap Fear & Greed Index history."
    args_schema: type[BaseModel] = CMCFearGreedInput
    
    BASE_URL: str = "https://pro-api.coinmarketcap.com/v3/fear-and-greed/historical"

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key or config.get('COINMARKETCAP_API_KEY')
        
        headers = {
            "Accept": "application/json"
        }
        if self.api_key:
             headers["X-CMC_PRO_API_KEY"] = self.api_key
             
        self.http_service = HTTPService(
            headers=headers,
            rotate_ua=True
        )
        self.http_service._logger = self.logger

    async def _execute(
        self,
        start: Optional[int] = None,
        limit: int = 10,
        **kwargs
    ) -> CMCFearGreedData:
        """
        Execute the CMC Fear & Greed Tool.
        """
        from urllib.parse import urlencode

        params = {}
        if start is not None:
            params['start'] = start
        
        # Enforce max limit of 10
        if limit > 10:
            limit = 10
        params['limit'] = limit

        # Construct URL with query parameters
        if params:
            url = f"{self.BASE_URL}?{urlencode(params)}"
        else:
            url = self.BASE_URL

        try:
            result, error = await self.http_service.async_request(
                url=url,
                method="GET"
            )
            
            if error:
                 raise Exception(f"Error fetching data from CMC: {error}")

            if not isinstance(result, dict):
                 # Try parsing if it's a string
                 if isinstance(result, str):
                     import json
                     try:
                         result = json.loads(result)
                     except json.JSONDecodeError:
                         raise ValueError(f"Invalid JSON response: {result}")
                 else:
                     raise ValueError(f"Unexpected response type: {type(result)}")

            # Extract data
            data = result.get('data', [])
            status = result.get('status', {})
            
            entries = []
            for item in data:
                entry = CMCFearGreedEntry(
                    timestamp=item.get('timestamp'),
                    value=int(item.get('value')),
                    value_classification=item.get('value_classification')
                )
                entries.append(entry)
                
            return CMCFearGreedData(
                total_count=str(status.get('total_count', len(entries))),
                data=entries
            )

        except Exception as e:
            self.logger.error(f"Error in CMCFearGreedTool: {e}")
            raise e
