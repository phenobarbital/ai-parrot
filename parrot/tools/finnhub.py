from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from navconfig import config
from navconfig.logging import logging
from ..interfaces.http import HTTPService
from .toolkit import AbstractToolkit


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

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.api_key = api_key or config.get('FINNHUB_API_KEY')
        if not self.api_key:
             raise ValueError("Finnhub API Key is required. Please provide it or set FINNHUB_API_KEY env variable.")
        self.http_service = HTTPService(accept="application/json")
        # Inject logger into http_service to prevent errors if it tries to log
        self.http_service._logger = self.logger
        self.base_url = "https://finnhub.io/api/v1"

    async def finnhub_get_quote(self, symbol: str) -> FinnhubQuoteResponse:
        """
        Get real-time quote data for US stocks.
        """
        url = f"{self.base_url}/quote"
        params = {
            "symbol": symbol,
            "token": self.api_key
        }
        
        from urllib.parse import urlencode
        full_url = f"{url}?{urlencode(params)}"

        result, error = await self.http_service.async_request(
            url=full_url,
            method="GET"
        )
        if error:
             raise Exception(f"Error fetching quote for {symbol}: {error}")
        
        if isinstance(result, dict):
             return FinnhubQuoteResponse(**result)
        else:
             raise ValueError(f"Unexpected response format: {result}")

    async def finnhub_earnings_calendar(self, from_date: str, to_date: str) -> List[FinnhubEarningsCalendarResponse]:
        """
        Get earnings calendar for a date range.
        """
        url = f"{self.base_url}/calendar/earnings"
        params = {
            "from": from_date,
            "to": to_date,
            "token": self.api_key
        }
        # Construct URL with params manually because HTTPService async_request argument 'data' 
        # is confusingly used for body or params depending on implementation in HTTPService (it uses 'json' or 'data' in request).
        # For GET, aiohttp takes 'params'. HTTPService async_request does NOT expose 'params'.
        # However, it builds URL using self.build_url? No, async_request takes 'url'.
        # I should probably append params to URL manually or use a helper.
        
        # Let's simple append to URL for safety since HTTPService might not handle GET params via 'data' argument effectively for query string.
        # Actually, looking at HTTPService.async_request:
        # url = self.build_url(...) is only for auth_type 'key'.
        # It passes `data` or `json` to session.request.
        # For GET, `data` in aiohttp is NOT query params. `params` argument is used for query params.
        # But HTTPService async_request does not accept `params`.
        # So I MUST append to URL.

        from urllib.parse import urlencode
        query_string = urlencode(params)
        full_url = f"{url}?{query_string}"

        result, error = await self.http_service.async_request(
            url=full_url,
            method="GET"
        )
        
        if error:
            raise Exception(f"Error fetching earnings calendar: {error}")

        if isinstance(result, dict) and "earningsCalendar" in result:
             return [FinnhubEarningsCalendarResponse(**item) for item in result["earningsCalendar"]]
        elif isinstance(result, list): # Sometimes it might return list? 
             # Finnhub docs say: { "earningsCalendar": [ ... ] }
             return [FinnhubEarningsCalendarResponse(**item) for item in result]
        else:
             # Fallback if structure is different
             # Let's assume list if result is list
             if isinstance(result, list):
                 return [FinnhubEarningsCalendarResponse(**item) for item in result]
             raise ValueError(f"Unexpected response format: {result}")

    async def finnhub_insider_sentiment(self, symbol: str, from_date: str, to_date: str) -> FinnhubInsiderSentimentResponse:
        """
        Get insider sentiment data.
        """
        url = f"{self.base_url}/stock/insider-sentiment"
        params = {
            "symbol": symbol,
            "from": from_date,
            "to": to_date,
            "token": self.api_key
        }
        from urllib.parse import urlencode
        full_url = f"{url}?{urlencode(params)}"
        
        result, error = await self.http_service.async_request(
             url=full_url,
             method="GET"
        )
        if error:
             raise Exception(f"Error fetching insider sentiment for {symbol}: {error}")
        
        if isinstance(result, dict):
             return FinnhubInsiderSentimentResponse(**result)
        else:
             raise ValueError(f"Unexpected response format: {result}")

    async def finnhub_company_profile(self, symbol: str) -> FinnhubCompanyProfileResponse:
        """
        Get company profile.
        """
        url = f"{self.base_url}/stock/profile2"
        params = {
            "symbol": symbol,
            "token": self.api_key
        }
        from urllib.parse import urlencode
        full_url = f"{url}?{urlencode(params)}"
        
        result, error = await self.http_service.async_request(
            url=full_url,
            method="GET"
        )
        
        if error:
            raise Exception(f"Error fetching company profile for {symbol}: {error}")
        
        if isinstance(result, dict):
            return FinnhubCompanyProfileResponse(**result)
        else:
            raise ValueError(f"Unexpected response format: {result}")

    async def finnhub_basic_financials(self, symbol: str, metric: str = 'all') -> Dict[str, Any]:
        """
        Get basic financial metrics (P/E, EPS, etc.).
        """
        url = f"{self.base_url}/stock/metric"
        params = {
            "symbol": symbol,
            "metric": metric,
            "token": self.api_key
        }
        from urllib.parse import urlencode
        full_url = f"{url}?{urlencode(params)}"

        result, error = await self.http_service.async_request(
            url=full_url,
            method="GET"
        )

        if error:
            raise Exception(f"Error fetching basic financials for {symbol}: {error}")
        
        return result

    async def finnhub_analyst_recommendations(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Get latest analyst recommendation trends.
        """
        url = f"{self.base_url}/stock/recommendation"
        params = {
            "symbol": symbol,
            "token": self.api_key
        }
        from urllib.parse import urlencode
        full_url = f"{url}?{urlencode(params)}"

        result, error = await self.http_service.async_request(
            url=full_url,
            method="GET"
        )

        if error:
            raise Exception(f"Error fetching analyst recommendations for {symbol}: {error}")
        
        if isinstance(result, list):
            return result
        return []

    async def finnhub_insider_transactions(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Get insider transactions.
        """
        url = f"{self.base_url}/stock/insider-sentiment" # Note: User asked for transactions, but sentiment is what we had. 
        # Let's check if there is a specific transactions endpoint. 
        # API docs: /stock/insider-transactions
        
        url = f"{self.base_url}/stock/insider-transactions"
        params = {
            "symbol": symbol,
            "token": self.api_key
        }
        from urllib.parse import urlencode
        full_url = f"{url}?{urlencode(params)}"
        
        result, error = await self.http_service.async_request(
            url=full_url,
            method="GET"
        )
        
        if error:
             raise Exception(f"Error fetching insider transactions for {symbol}: {error}")
             
        if isinstance(result, dict) and 'data' in result:
            return result['data']
        return []

    async def finnhub_institutional_ownership(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Get institutional ownership.
        """
        url = f"https://finnhub.io/api/v1/stock/institutional-ownership"  # Using full URL to be safe or self.base_url
        url = f"{self.base_url}/stock/institutional-ownership"
        params = {
             "symbol": symbol,
             "token": self.api_key
        }
        from urllib.parse import urlencode
        full_url = f"{url}?{urlencode(params)}"
        
        result, error = await self.http_service.async_request(
            url=full_url,
            method="GET"
        )
        
        if error:
             raise Exception(f"Error fetching institutional ownership for {symbol}: {error}")
             
        if isinstance(result, dict) and 'data' in result:
             return result['data']
        return []

