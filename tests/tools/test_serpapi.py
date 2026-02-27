import pytest
from unittest.mock import patch, AsyncMock
import httpx

from parrot.tools.serpapi import SerpApiSearchTool, SerpApiSearchArgs


@pytest.fixture
def serpapi_tool():
    return SerpApiSearchTool()


@pytest.mark.asyncio
async def test_serpapi_search_missing_key(serpapi_tool, monkeypatch):
    """Test that the tool returns an error if the API key is missing."""
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    
    result = await serpapi_tool.execute(query="test query")
    assert result.success is False
    assert result.status == "error"
    assert "SERPAPI_API_KEY environment variable is missing" in result.error


@pytest.mark.asyncio
@patch("parrot.tools.serpapi.httpx.AsyncClient")
async def test_serpapi_search_organic_success(mock_client, serpapi_tool, monkeypatch):
    """Test a successful SerpApi call with organic results."""
    monkeypatch.setenv("SERPAPI_API_KEY", "test_key")
    
    mock_instance = AsyncMock()
    from unittest.mock import MagicMock
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "organic_results": [
            {
                "title": "Test Title 1",
                "link": "https://test1.com",
                "snippet": "Test snippet 1"
            },
            {
                "title": "Test Title 2",
                "link": "https://test2.com",
                "snippet": "Test snippet 2"
            }
        ]
    }
    
    mock_instance.__aenter__.return_value = mock_instance
    mock_instance.get.return_value = mock_response
    mock_client.return_value = mock_instance
    
    result = await serpapi_tool.execute(query="test query")
    
    assert result.success is True
    assert result.status == "success"
    assert len(result.result) == 2
    assert result.result[0]["title"] == "Test Title 1"
    assert result.result[0]["url"] == "https://test1.com"
    
    mock_instance.get.assert_called_once()
    args, kwargs = mock_instance.get.call_args
    assert "serpapi.com/search" in args[0]
    assert kwargs["params"]["api_key"] == "test_key"
    assert kwargs["params"]["q"] == "test query"


@pytest.mark.asyncio
@patch("parrot.tools.serpapi.httpx.AsyncClient")
async def test_serpapi_search_answer_box_success(mock_client, serpapi_tool, monkeypatch):
    """Test a successful SerpApi call prioritizing answer_box when organic_results are missing."""
    monkeypatch.setenv("SERPAPI_API_KEY", "test_key")
    
    mock_instance = AsyncMock()
    from unittest.mock import MagicMock
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "answer_box": {
            "answer": "42",
            "link": "https://math.com"
        }
    }
    
    mock_instance.__aenter__.return_value = mock_instance
    mock_instance.get.return_value = mock_response
    mock_client.return_value = mock_instance
    
    result = await serpapi_tool.execute(query="what is the answer to life")
    
    assert result.success is True
    assert result.status == "success"
    assert len(result.result) == 1
    assert result.result[0]["title"] == "Answer Box"
    assert result.result[0]["snippet"] == "42"
    assert result.result[0]["url"] == "https://math.com"


@pytest.mark.asyncio
@patch("parrot.tools.serpapi.httpx.AsyncClient")
async def test_serpapi_search_http_error(mock_client, serpapi_tool, monkeypatch):
    """Test SerpApi search raising an HTTPError."""
    monkeypatch.setenv("SERPAPI_API_KEY", "test_key")
    
    mock_instance = AsyncMock()
    mock_instance.__aenter__.return_value = mock_instance
    
    error = httpx.HTTPError("Service Unavailable")
    mock_instance.get.side_effect = error
    mock_client.return_value = mock_instance
    
    result = await serpapi_tool.execute(query="test query")
    
    assert result.success is False
    assert result.status == "error"
    assert "SerpApi request failed" in result.error
