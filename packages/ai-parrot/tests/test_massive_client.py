"""
Unit tests for MassiveClient wrapper using httpx.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import httpx

from parrot.tools.massive.client import (
    MassiveClient,
    MassiveAPIError,
    MassiveRateLimitError,
    MassiveTransientError,
)


@pytest.fixture
def mock_httpx_request():
    """Mock the httpx.AsyncClient.request method."""
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        yield mock_req


class TestMassiveClientInit:
    """Tests for MassiveClient initialization."""

    def test_init_creates_client(self):
        """Client is created with API key."""
        client = MassiveClient(api_key="test-key")
        assert client.api_key == "test-key"
        assert client._max_retries == 3

    def test_init_custom_retries(self):
        """Custom retry count is respected."""
        client = MassiveClient(api_key="test-key", max_retries=5)
        assert client._max_retries == 5


class TestOptionsChain:
    """Tests for options chain endpoint."""

    @pytest.mark.asyncio
    async def test_options_chain_success(self, mock_httpx_request):
        """Successful options chain fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"ticker": "O:AAPL250321C00185000", "strike_price": 185.0},
                {"ticker": "O:AAPL250321C00190000", "strike_price": 190.0},
            ]
        }
        mock_httpx_request.return_value = mock_response

        async with MassiveClient(api_key="test") as client:
            result = await client.list_snapshot_options_chain("AAPL")

        assert len(result) == 2
        assert result[0]["ticker"] == "O:AAPL250321C00185000"
        
        call_args = mock_httpx_request.call_args
        assert call_args[1]["url"] == "https://api.massive.com/v3/snapshot/options/AAPL"

    @pytest.mark.asyncio
    async def test_options_chain_with_filters(self, mock_httpx_request):
        """Options chain with filter parameters."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        mock_httpx_request.return_value = mock_response

        async with MassiveClient(api_key="test") as client:
            await client.list_snapshot_options_chain(
                "AAPL",
                expiration_date_gte="2026-03-01",
                expiration_date_lte="2026-04-30",
                strike_price_gte=180.0,
                strike_price_lte=200.0,
                contract_type="call",
                limit=100,
            )

        call_args = mock_httpx_request.call_args
        params = call_args[1]["params"]
        assert params["expiration_date_gte"] == "2026-03-01"
        assert params["contract_type"] == "call"
        assert params["limit"] == 100


class TestShortInterest:
    """Tests for short interest endpoint."""

    @pytest.mark.asyncio
    async def test_short_interest_success(self, mock_httpx_request):
        """Successful short interest fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"settlement_date": "2026-02-14", "short_interest": 15000000},
            ]
        }
        mock_httpx_request.return_value = mock_response

        async with MassiveClient(api_key="test") as client:
            result = await client.list_short_interest("GME")

        assert len(result) == 1
        assert result[0]["short_interest"] == 15000000
        assert mock_httpx_request.call_args[1]["url"] == "https://api.massive.com/v3/reference/short_interest"


class TestRetryLogic:
    """Tests for retry logic on transient errors."""

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_on_5xx_error(self, mock_sleep, mock_httpx_request):
        """Retries on 5xx server errors."""
        mock_fail = MagicMock()
        mock_fail.status_code = 503
        
        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = {"results": [{"short_interest": 1000000}]}

        # First fail, then succeed
        mock_httpx_request.side_effect = [
            httpx.HTTPStatusError("503", request=MagicMock(), response=mock_fail),
            mock_success
        ]
        
        async with MassiveClient(api_key="test") as client:
            result = await client.list_short_interest("GME")

        assert len(result) == 1
        assert mock_httpx_request.call_count == 2
        mock_sleep.assert_called_once()

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_raises_after_max_retries(self, mock_sleep, mock_httpx_request):
        """Raises MassiveTransientError after exhausting retries."""
        mock_fail = MagicMock()
        mock_fail.status_code = 500
        
        mock_httpx_request.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=mock_fail
        )
        
        async with MassiveClient(api_key="test", max_retries=2) as client:
            with pytest.raises(MassiveTransientError) as exc_info:
                await client.list_short_interest("GME")

        assert mock_httpx_request.call_count == 3
        assert mock_sleep.call_count == 2


class TestRateLimitHandling:
    """Tests for rate limit (429) handling."""

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_rate_limit_retry(self, mock_sleep, mock_httpx_request):
        """Retries on rate limit."""
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.headers = {"Retry-After": "1"}
        
        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = {"results": [{"short_volume": 5000000}]}

        # Return 429 using response status code
        mock_httpx_request.side_effect = [
            MagicMock(status_code=429, headers={"Retry-After": "1"}),
            mock_success
        ]
        
        async with MassiveClient(api_key="test", rate_limit_wait=1) as client:
            result = await client.list_short_volume("TSLA")

        assert len(result) == 1
        assert mock_httpx_request.call_count == 2
        mock_sleep.assert_called_once_with(1)

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_raises_rate_limit_error_after_retries(self, mock_sleep, mock_httpx_request):
        """Raises MassiveRateLimitError after exhausting retries."""
        mock_httpx_request.return_value = MagicMock(status_code=429, headers={})
        
        async with MassiveClient(api_key="test", max_retries=1, rate_limit_wait=0.1) as client:
            with pytest.raises(MassiveRateLimitError):
                await client.list_short_volume("TSLA")

        assert mock_httpx_request.call_count == 2


class TestNonRetryableErrors:
    """Tests for non-retryable errors."""

    @pytest.mark.asyncio
    async def test_raises_on_4xx_error(self, mock_httpx_request):
        """Does not retry on 4xx client errors (except 429)."""
        mock_fail = MagicMock()
        mock_fail.status_code = 400
        mock_fail.text = "Bad Request"
        
        mock_httpx_request.side_effect = httpx.HTTPStatusError(
            "400", request=MagicMock(), response=mock_fail
        )
        
        async with MassiveClient(api_key="test") as client:
            with pytest.raises(MassiveAPIError):
                await client.list_short_interest("GME")

        assert mock_httpx_request.call_count == 1
