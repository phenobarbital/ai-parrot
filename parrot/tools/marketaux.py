from typing import Optional, List, Dict, Any, Union
import json
from urllib.parse import urlencode
from pydantic import BaseModel, Field
from navconfig import config
from navconfig.logging import logging
from ..interfaces.http import HTTPService
from .toolkit import AbstractToolkit
from .decorators import tool_schema


class MarketauxSentimentArgs(BaseModel):
    sentiment_gte: float = Field(..., description="Sentiment score threshold. 0 = neutral, < 0 = negative, > 0 = positive. Use this to filter news by sentiment.")
    symbols: Optional[str] = Field(None, description="Comma separated symbols/tickers, e.g. TSLA,AMZN,MSFT")
    filter_entities: bool = Field(True, description="Filter entities to include only those relevant to the query.")
    language: str = Field("en", description="Language code (default: en)")
    limit: int = Field(10, description="Limit results (1-100)", ge=1, le=100)
    page: int = Field(1, description="Page number", ge=1)


class MarketauxToolkit(AbstractToolkit):
    """
    Toolkit for interacting with the Marketaux API.
    Provides access to financial news, sentiment analysis, and market data.
    """

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.api_key = api_key or config.get('MARKETAUX_API_KEY')
        
        if not self.api_key:
            self.logger.warning("MARKETAUX_API_KEY is not set. API calls may fail.")

        self.base_url = "https://api.marketaux.com/v1"
        self.http_service = HTTPService(accept="application/json")
        self.http_service._logger = self.logger

    @tool_schema(MarketauxSentimentArgs, description="Get news based on sentiment score.")
    async def ma_sentiment_news(
        self, 
        sentiment_gte: float, 
        symbols: Optional[str] = None, 
        filter_entities: bool = True, 
        language: str = "en", 
        limit: int = 10, 
        page: int = 1
    ) -> Dict[str, Any]:
        """
        Get news and sentiment data filtered by a minimum sentiment score.
        
        Args:
            sentiment_gte: Sentiment score threshold. 0 = neutral, < 0 = negative, > 0 = positive.
            symbols: Comma separated symbols/tickers, e.g. TSLA,AMZN,MSFT.
            filter_entities: Filter entities to include only those relevant.
            language: Language code (default: en).
            limit: Limit results.
            page: Page number.
        """
        url = f"{self.base_url}/news/all"
        params = {
            "api_token": self.api_key,
            "sentiment_gte": sentiment_gte,
            "language": language,
            "filter_entities": str(filter_entities).lower(),
            "limit": limit,
            "page": page
        }
        
        if symbols:
            params["symbols"] = symbols

        full_url = f"{url}?{urlencode(params)}"
        result, error = await self.http_service.async_request(url=full_url, method="GET")

        if error:
            raise Exception(f"Error fetching Marketaux sentiment news: {error}")

        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                pass

        if isinstance(result, dict):
            return result
        raise ValueError(f"Unexpected response format: {result}")
