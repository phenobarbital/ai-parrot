"""
FredAPITool for interacting with Federal Reserve Economic Data (FRED) API.
"""
from typing import Dict, Any, Optional, Type
from urllib.parse import urlencode
from navconfig import config
from pydantic import Field, BaseModel
from ..interfaces.http import HTTPService
from .abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from .cache import ToolCache, DEFAULT_TOOL_CACHE_TTL


class FredToolArgsSchema(AbstractToolArgsSchema):
    """Schema for FredAPITool arguments."""
    series_id: str = Field(
        description="The ID of the series to fetch (e.g., 'FEDFUNDS', 'GDP')."
    )
    endpoint: str = Field(
        default="series/observations",
        description="The API endpoint to call. Defaults to 'series/observations'."
    )
    api_key: Optional[str] = Field(
        default=None,
        description="FRED API Key. If not provided, uses FRED_API_KEY env var."
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Start date for data fetching (YYYY-MM-DD)."
    )
    end_date: Optional[str] = Field(
        default=None,
        description="End date for data fetching (YYYY-MM-DD)."
    )
    params: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional parameters for the API call."
    )


class FredAPITool(AbstractTool):
    """
    Tool for fetching economic data from the Federal Reserve Economic Data (FRED) API.

    This tool uses the requests-based HTTPService to interact with the FRED API
    in an async manner, avoiding blocking calls.

    Common endpoints:
    - series/observations: Get data for a specific series.
    - releases/dates: Get release dates.
    """
    name: str = "fred_api"
    description: str = "Fetches economic data and indicators from the Federal Reserve Economic Data (FRED) API."
    args_schema: Type[BaseModel] = FredToolArgsSchema
    
    BASE_URL: str = "https://api.stlouisfed.org/fred"

    def __init__(self, cache_ttl: int = DEFAULT_TOOL_CACHE_TTL, **kwargs):
        super().__init__(**kwargs)
        self.http_service = HTTPService(base_url=self.BASE_URL, **kwargs)
        self._cache = ToolCache(prefix="tool_cache", ttl=cache_ttl)

    async def _execute(
        self,
        series_id: str,
        endpoint: str = "series/observations",
        api_key: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> ToolResult:
        """
        Execute the FRED API request.

        Args:
            series_id: The ID of the series to fetch.
            endpoint: The API endpoint to call.
            api_key: FRED API Key.
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            params: Additional parameters.

        Returns:
            ToolResult containing the API response.
        """
        try:
            # 1. Resolve API Key
            api_key = api_key or config.get("FRED_API_KEY")
            if not api_key:
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    error=(
                        "FRED API Key not found. "
                        "Please provide it or set FRED_API_KEY env var."
                    ),
                )

            # 2. Build cache-safe parameters (exclude api_key)
            cache_params = {
                "series_id": series_id,
                "endpoint": endpoint,
            }
            if start_date:
                cache_params["start_date"] = start_date
            if end_date:
                cache_params["end_date"] = end_date
            if params:
                cache_params["extra"] = params

            # 3. Check cache
            cached = await self._cache.get(
                "fred_api", endpoint, **cache_params
            )
            if cached is not None:
                self.logger.debug(
                    "FRED cache hit for %s/%s", endpoint, series_id
                )
                return ToolResult(
                    success=True,
                    status="success",
                    result=cached,
                    metadata={
                        "series_id": series_id,
                        "endpoint": endpoint,
                        "source": "FRED",
                        "cached": True,
                    },
                )

            # 4. Build Request Parameters
            request_params = {
                "api_key": api_key,
                "file_type": "json",
                "series_id": series_id,
            }
            if start_date:
                request_params["observation_start"] = start_date
            if end_date:
                request_params["observation_end"] = end_date
            if params:
                request_params.update(params)

            # 5. Construct URL
            url = f"{self.BASE_URL}/{endpoint}"
            if request_params:
                query_string = urlencode(request_params)
                url = f"{url}?{query_string}"

            # 6. Make Request using HTTPService
            response, error = await self.http_service.request(
                url=url,
                method="GET",
            )

            if error:
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    error=str(error),
                    metadata={
                        "url": url, "series_id": series_id
                    },
                )

            # 7. Store in cache
            data = response
            await self._cache.set(
                "fred_api", endpoint, data, **cache_params
            )

            return ToolResult(
                success=True,
                status="success",
                result=data,
                metadata={
                    "series_id": series_id,
                    "endpoint": endpoint,
                    "source": "FRED",
                },
            )

        except Exception as e:
            self.logger.error(f"Error executing FredAPITool: {e}")
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Exception during execution: {str(e)}",
            )
