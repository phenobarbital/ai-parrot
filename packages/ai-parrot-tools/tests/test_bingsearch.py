import pytest
import os
from unittest.mock import patch, AsyncMock
import httpx

from parrot.tools.bingsearch import BingSearchTool, BingSearchArgs


@pytest.fixture
def bing_tool():
    return BingSearchTool()


@pytest.mark.asyncio
async def test_bing_search_missing_key(bing_tool, monkeypatch):
    """Test that the tool returns an error if the subscription key is missing."""
    monkeypatch.delenv("BING_SUBSCRIPTION_KEY", raising=False)
    
    result = await bing_tool.execute(query="test query")
    assert result.success is False
    assert result.status == "error"
    assert "BING_SUBSCRIPTION_KEY environment variable is missing" in result.error


@pytest.mark.asyncio
@patch("parrot.tools.bingsearch.httpx.AsyncClient")
async def test_bing_search_success(mock_client, bing_tool, monkeypatch):
    """Test a successful Bing search API call."""
    monkeypatch.setenv("BING_SUBSCRIPTION_KEY", "test_key")
    
    # Mock the AsyncClient to return a successful response
    mock_instance = AsyncMock()
    from unittest.mock import MagicMock
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "webPages": {
            "totalEstimatedMatches": 2,
            "value": [
                {
                    "name": "Test Site 1",
                    "url": "https://test1.com",
                    "snippet": "Snippet 1"
                },
                {
                    "name": "Test Site 2",
                    "url": "https://test2.com",
                    "snippet": "Snippet 2"
                }
            ]
        }
    }
    
    # the client is used as an async context manager
    mock_instance.__aenter__.return_value = mock_instance
    mock_instance.get.return_value = mock_response
    mock_client.return_value = mock_instance
    
    result = await bing_tool.execute(query="test query")
    
    assert result.success is True
    assert result.status == "success"
    assert len(result.result) == 2
    assert result.result[0]["title"] == "Test Site 1"
    assert result.result[0]["url"] == "https://test1.com"
    assert "total_estimated" in result.metadata
    assert result.metadata["total_estimated"] == 2
    
    # Verify the mock was called correctly
    mock_instance.get.assert_called_once()
    args, kwargs = mock_instance.get.call_args
    assert "https://api.bing.microsoft.com/v7.0/search" in args[0]
    assert kwargs["headers"]["Ocp-Apim-Subscription-Key"] == "test_key"
    assert kwargs["params"]["q"] == "test query"


@pytest.mark.asyncio
@patch("parrot.tools.bingsearch.httpx.AsyncClient")
async def test_bing_search_http_error(mock_client, bing_tool, monkeypatch):
    """Test Bing search API call raising an HTTPError."""
    monkeypatch.setenv("BING_SUBSCRIPTION_KEY", "test_key")
    
    mock_instance = AsyncMock()
    mock_instance.__aenter__.return_value = mock_instance
    
    # Make get() raise an HTTPError
    error = httpx.HTTPError("Bad Request")
    mock_instance.get.side_effect = error
    mock_client.return_value = mock_instance
    
    result = await bing_tool.execute(query="test query")
    
    assert result.success is False
    assert result.status == "error"
    assert "Bing API request failed" in result.error
