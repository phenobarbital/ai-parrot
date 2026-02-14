from typing import Optional, List, Dict, Any
from urllib.parse import urlencode
from pydantic import BaseModel, Field
from navconfig import config
from navconfig.logging import logging
from ..interfaces.http import HTTPService
from .toolkit import AbstractToolkit
from .cache import ToolCache, DEFAULT_TOOL_CACHE_TTL


class FinnhubQuoteResponse(BaseModel):
    c: float = Field(..., description="Current price")
    d: Optional[float] = Field(None, description="Change")
    dp: Optional[float] = Field(None, description="Percent change")
    h: Optional[float] = Field(None, description="High price of the day")
    l: Optional[float] = Field(None, description="Low price of the day")
    o: Optional[float] = Field(None, description="Open price of the day")
    pc: Optional[float] = Field(None, description="Previous close price")


class FinnhubEarningsCalendarInput(BaseModel):
    from_date: str = Field(..., description="From date: YYYY-MM-DD")
    to_date: str = Field(..., description="To date: YYYY-MM-DD")


class FinnhubEarningsCalendarResponse(BaseModel):
    date: Optional[str] = Field(None, description="Date")
    epsActual: Optional[float] = Field(None, description="Actual EPS")
    epsEstimate: Optional[float] = Field(None, description="Estimated EPS")
    hour: Optional[str] = Field(None, description="Hour")
    quarter: Optional[int] = Field(None, description="Quarter")
    revenueActual: Optional[float] = Field(None, description="Actual Revenue")
    revenueEstimate: Optional[float] = Field(None, description="Estimated Revenue")
    symbol: Optional[str] = Field(None, description="Symbol")
    year: Optional[int] = Field(None, description="Year")


class FinnhubInsiderSentimentInput(BaseModel):
    symbol: str = Field(..., description="Symbol")
    from_date: str = Field(..., description="From date: YYYY-MM-DD")
    to_date: str = Field(..., description="To date: YYYY-MM-DD")


class FinnhubInsiderSentimentData(BaseModel):
    symbol: str = Field(..., description="Symbol")
    year: int = Field(..., description="Year")
    month: int = Field(..., description="Month")
    change: float = Field(..., description="Net buying/selling")
    mspr: float = Field(..., description="Monthly Share Purchase Ratio")


class FinnhubInsiderSentimentResponse(BaseModel):
    data: List[FinnhubInsiderSentimentData] = Field(default_factory=list, description="Array of sentiment data")
    symbol: str = Field(..., description="Symbol")


class FinnhubCompanyProfileResponse(BaseModel):
    country: Optional[str] = Field(None, description="Country")
    currency: Optional[str] = Field(None, description="Currency")
    exchange: Optional[str] = Field(None, description="Exchange")
    ipo: Optional[str] = Field(None, description="IPO Date")
    marketCapitalization: Optional[float] = Field(None, description="Market Capitalization")
    name: Optional[str] = Field(None, description="Company Name")
    phone: Optional[str] = Field(None, description="Phone")
    shareOutstanding: Optional[float] = Field(None, description="Share Outstanding")
    ticker: Optional[str] = Field(None, description="Ticker")
    weburl: Optional[str] = Field(None, description="Web URL")
    logo: Optional[str] = Field(None, description="Logo URL")
    finnhubIndustry: Optional[str] = Field(None, description="Finnhub Industry")


class FinnhubToolkit(AbstractToolkit):
    """
    Toolkit for interacting with the Finnhub API.
    Provides access to stock quotes, earnings calendar, insider sentiment, and company profiles.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_ttl: int = DEFAULT_TOOL_CACHE_TTL,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.api_key = api_key or config.get('FINNHUB_API_KEY')
        if not self.api_key:
            raise ValueError(
                "Finnhub API Key is required. "
                "Please provide it or set FINNHUB_API_KEY env variable."
            )
        self.http_service = HTTPService(accept="application/json")
        self.http_service._logger = self.logger
        self.base_url = "https://finnhub.io/api/v1"
        self._cache = ToolCache(prefix="tool_cache", ttl=cache_ttl)

    async def _cached_get(
        self,
        method: str,
        path: str,
        params: Dict[str, Any],
    ) -> Any:
        """Execute a GET request with Redis caching.

        Args:
            method: Logical method name for cache key generation.
            path: API path relative to base_url.
            params: Query parameters (token is added automatically).

        Returns:
            Parsed JSON response (dict or list).

        Raises:
            Exception: When the HTTP request fails.
        """
        # Build cache key params excluding the API token
        cache_params = {
            k: v for k, v in params.items() if k != "token"
        }

        cached = await self._cache.get("finnhub", method, **cache_params)
        if cached is not None:
            self.logger.debug("Finnhub cache hit for %s", method)
            return cached

        # Ensure token is present for the actual request
        params["token"] = self.api_key
        full_url = f"{self.base_url}/{path}?{urlencode(params)}"

        result, error = await self.http_service.async_request(
            url=full_url,
            method="GET",
        )
        if error:
            raise Exception(
                f"Error in Finnhub {method}: {error}"
            )

        # Store raw result in cache
        await self._cache.set("finnhub", method, result, **cache_params)
        return result

    async def finnhub_get_quote(self, symbol: str) -> FinnhubQuoteResponse:
        """Get real-time quote data for US stocks."""
        result = await self._cached_get(
            "get_quote", "quote", {"symbol": symbol}
        )
        if isinstance(result, dict):
            return FinnhubQuoteResponse(**result)
        raise ValueError(f"Unexpected response format: {result}")

    async def finnhub_earnings_calendar(
        self, from_date: str, to_date: str
    ) -> List[FinnhubEarningsCalendarResponse]:
        """Get earnings calendar for a date range."""
        result = await self._cached_get(
            "earnings_calendar",
            "calendar/earnings",
            {"from": from_date, "to": to_date},
        )
        if isinstance(result, dict) and "earningsCalendar" in result:
            return [
                FinnhubEarningsCalendarResponse(**item)
                for item in result["earningsCalendar"]
            ]
        if isinstance(result, list):
            return [
                FinnhubEarningsCalendarResponse(**item)
                for item in result
            ]
        raise ValueError(f"Unexpected response format: {result}")

    async def finnhub_insider_sentiment(
        self, symbol: str, from_date: str, to_date: str
    ) -> FinnhubInsiderSentimentResponse:
        """Get insider sentiment data."""
        result = await self._cached_get(
            "insider_sentiment",
            "stock/insider-sentiment",
            {"symbol": symbol, "from": from_date, "to": to_date},
        )
        if isinstance(result, dict):
            return FinnhubInsiderSentimentResponse(**result)
        raise ValueError(f"Unexpected response format: {result}")

    async def finnhub_company_profile(
        self, symbol: str
    ) -> FinnhubCompanyProfileResponse:
        """Get company profile."""
        result = await self._cached_get(
            "company_profile",
            "stock/profile2",
            {"symbol": symbol},
        )
        if isinstance(result, dict):
            return FinnhubCompanyProfileResponse(**result)
        raise ValueError(f"Unexpected response format: {result}")

    async def finnhub_basic_financials(
        self, symbol: str, metric: str = 'all'
    ) -> Dict[str, Any]:
        """Get basic financial metrics (P/E, EPS, etc.)."""
        return await self._cached_get(
            "basic_financials",
            "stock/metric",
            {"symbol": symbol, "metric": metric},
        )

    async def finnhub_analyst_recommendations(
        self, symbol: str
    ) -> List[Dict[str, Any]]:
        """Get latest analyst recommendation trends."""
        result = await self._cached_get(
            "analyst_recommendations",
            "stock/recommendation",
            {"symbol": symbol},
        )
        if isinstance(result, list):
            return result
        return []

    async def finnhub_insider_transactions(
        self, symbol: str
    ) -> List[Dict[str, Any]]:
        """Get insider transactions."""
        result = await self._cached_get(
            "insider_transactions",
            "stock/insider-transactions",
            {"symbol": symbol},
        )
        if isinstance(result, dict) and 'data' in result:
            return result['data']
        return []

    async def finnhub_institutional_ownership(
        self, symbol: str
    ) -> List[Dict[str, Any]]:
        """Get institutional ownership."""
        result = await self._cached_get(
            "institutional_ownership",
            "stock/institutional-ownership",
            {"symbol": symbol},
        )
        if isinstance(result, dict) and 'data' in result:
            return result['data']
        return []

