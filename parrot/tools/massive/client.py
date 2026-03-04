"""
Async REST client for Massive (ex-Polygon.io).

Directly connects to https://api.massive.com using httpx, 
providing retry logic and rate limit handling.
"""

import asyncio
import re
from typing import Any

import httpx
from navconfig.logging import logging


class MassiveAPIError(Exception):
    """Base error for Massive API calls."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class MassiveRateLimitError(MassiveAPIError):
    """Rate limit exceeded (429)."""

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message, status_code=429)
        self.retry_after = retry_after or 60


class MassiveTransientError(MassiveAPIError):
    """Transient error (5xx, timeouts)."""
    pass


class MassiveClient:
    """
    Async REST client for Massive API with retry and rate limit handling.

    Usage:
        client = MassiveClient(api_key="your-key")
        chain = await client.list_snapshot_options_chain("AAPL")
    """

    BASE_URL = "https://api.massive.com"

    # Retry configuration
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_BACKOFF_BASE = 2  # Exponential backoff: 1s, 2s, 4s
    DEFAULT_RATE_LIMIT_WAIT = 60  # Default wait for 429 without Retry-After

    # Error patterns for classification
    TRANSIENT_PATTERNS = [
        r"5\d{2}",  # 5xx status codes
        r"timeout",
        r"connection.*error",
        r"connection.*refused",
        r"connection.*reset",
        r"temporarily unavailable",
    ]
    RATE_LIMIT_PATTERNS = [
        r"429",
        r"rate.*limit",
        r"too many requests",
        r"quota.*exceeded",
    ]

    def __init__(
        self,
        api_key: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
        rate_limit_wait: int = DEFAULT_RATE_LIMIT_WAIT,
    ):
        """
        Initialize Massive client.

        Args:
            api_key: Massive API key
            max_retries: Maximum retry attempts for transient errors
            rate_limit_wait: Default wait time (seconds) for rate limit without Retry-After
        """
        self.api_key = api_key
        self._max_retries = max_retries
        self._rate_limit_wait = rate_limit_wait
        self.logger = logging.getLogger(__name__)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    # -------------------------------------------------------------------------
    # Options Chain Endpoints
    # -------------------------------------------------------------------------

    async def list_snapshot_options_chain(
        self,
        underlying: str,
        expiration_date_gte: str | None = None,
        expiration_date_lte: str | None = None,
        strike_price_gte: float | None = None,
        strike_price_lte: float | None = None,
        contract_type: str | None = None,
        limit: int = 250,
    ) -> list[Any]:
        """Fetch options chain snapshot with Greeks and IV."""
        params = self._build_params(
            underlyingAsset=underlying,
            expiration_date_gte=expiration_date_gte,
            expiration_date_lte=expiration_date_lte,
            strike_price_gte=strike_price_gte,
            strike_price_lte=strike_price_lte,
            contract_type=contract_type,
            limit=limit,
        )
        # v3/snapshot/options/{ticker}? Ex: Polygon is v3/snapshot/options/{underlying}
        # In Massive spec, options chain snapshot is returned as an array of contracts
        return await self._call_with_retry(
            "GET", 
            f"/v3/snapshot/options/{underlying}",
            params=params,
        )

    # -------------------------------------------------------------------------
    # Short Interest Endpoints
    # -------------------------------------------------------------------------

    async def list_short_interest(
        self,
        symbol: str,
        limit: int = 10,
        order: str = "desc",
    ) -> list[Any]:
        """Fetch FINRA short interest data."""
        params = self._build_params(ticker=symbol, limit=limit, order=order)
        # Assuming vX/reference/short_interest or similar, aligning with docs
        # Note: If massive has a specific path for SI, it should be adjusted.
        return await self._call_with_retry(
            "GET",
            "/v3/reference/short_interest",
            params=params,
        )

    # -------------------------------------------------------------------------
    # Short Volume Endpoints
    # -------------------------------------------------------------------------

    async def list_short_volume(
        self,
        symbol: str,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 30,
    ) -> list[Any]:
        """Fetch daily FINRA short volume data."""
        params = self._build_params(
            ticker=symbol,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        return await self._call_with_retry(
            "GET",
            "/v3/reference/short_volume",
            params=params,
        )

    # -------------------------------------------------------------------------
    # Benzinga Earnings Endpoints
    # -------------------------------------------------------------------------

    async def get_benzinga_earnings(
        self,
        symbol: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        importance: int | None = None,
        limit: int = 50,
    ) -> list[Any]:
        """Fetch Benzinga earnings data."""
        params = self._build_params(
            ticker=symbol,
            date_from=date_from,
            date_to=date_to,
            importance=importance,
            limit=limit,
        )
        return await self._call_with_retry(
            "GET",
            "/v1/benzinga/earnings",
            params=params,
        )

    # -------------------------------------------------------------------------
    # Benzinga Analyst Ratings Endpoints
    # -------------------------------------------------------------------------

    async def get_benzinga_analyst_ratings(
        self,
        symbol: str,
        action: str | None = None,
        date_from: str | None = None,
        limit: int = 20,
    ) -> list[Any]:
        """Fetch Benzinga analyst ratings."""
        params = self._build_params(
            ticker=symbol,
            action=action,
            date_from=date_from,
            limit=limit,
        )
        return await self._call_with_retry(
            "GET",
            "/v1/benzinga/analyst_ratings",
            params=params,
        )

    async def get_benzinga_consensus_ratings(
        self,
        symbol: str,
    ) -> dict[str, Any]:
        """Fetch Benzinga consensus ratings."""
        params = self._build_params(ticker=symbol)
        return await self._call_with_retry(
            "GET",
            "/v1/benzinga/consensus_ratings",
            params=params,
        )

    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------

    def _build_params(self, **kwargs) -> dict[str, Any]:
        """Build params dict, filtering out None values."""
        return {k: v for k, v in kwargs.items() if v is not None}

    async def _call_with_retry(
        self,
        method: str,
        path: str,
        max_retries: int | None = None,
        **kwargs,
    ) -> Any:
        """
        Execute httpx request with retry and rate limit handling.
        """
        retries = max_retries or self._max_retries
        url = f"{self.BASE_URL}{path}"
        
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.api_key}"
        
        last_error = None

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(retries + 1):
                try:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        **kwargs
                    )
                    
                    if response.status_code == 429:
                        retry_after = response.headers.get("Retry-After")
                        wait_time = int(retry_after) if retry_after else self._rate_limit_wait
                        if attempt < retries:
                            self.logger.warning(
                                f"Rate limit hit, waiting {wait_time}s (attempt {attempt + 1}/{retries + 1})"
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        raise MassiveRateLimitError(
                            f"Rate limit exceeded after {retries + 1} attempts",
                            retry_after=retry_after,
                        )

                    response.raise_for_status()
                    
                    data = response.json()
                    # typically REST returns { "results": [...] } or { "status": "OK", "results": ... }
                    if "results" in data:
                        return data["results"]
                    return data
                    
                except httpx.HTTPStatusError as e:
                    status = e.response.status_code
                    last_error = e
                    if status >= 500:
                        if attempt < retries:
                            wait_time = self.DEFAULT_RETRY_BACKOFF_BASE ** attempt
                            self.logger.warning(
                                f"Transient error {status}: {e}, retrying in {wait_time}s "
                                f"(attempt {attempt + 1}/{retries + 1})"
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        raise MassiveTransientError(f"Transient error: {e}", status_code=status)
                    else:
                        raise MassiveAPIError(f"HTTP Error {status}: {e.response.text}", status_code=status)

                except httpx.RequestError as e:
                    last_error = e
                    error_str = str(e).lower()
                    if self._is_transient_error(error_str):
                        if attempt < retries:
                            wait_time = self.DEFAULT_RETRY_BACKOFF_BASE ** attempt
                            self.logger.warning(
                                f"Transient error: {e}, retrying in {wait_time}s "
                                f"(attempt {attempt + 1}/{retries + 1})"
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        raise MassiveTransientError(f"Network error after {retries + 1} attempts: {e}")
                    raise MassiveAPIError(f"Network error: {e}")

        # Should not reach here, but just in case
        raise last_error or MassiveAPIError("Unknown error")

    def _is_transient_error(self, error_str: str) -> bool:
        """Check if error is transient and retryable."""
        for pattern in self.TRANSIENT_PATTERNS:
            if re.search(pattern, error_str, re.IGNORECASE):
                return True
        return False
