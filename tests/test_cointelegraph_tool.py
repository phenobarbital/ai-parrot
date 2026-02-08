"""Tests for CoinTelegraphTool."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.tools.cointelegraph import CoinTelegraphTool


@pytest.fixture
def cointelegraph_tool():
    """Create a CoinTelegraphTool instance with mocked dependencies."""
    with patch('parrot.interfaces.http.HTTPService.__init__', return_value=None):
        tool = CoinTelegraphTool()
        tool.rss._executor = MagicMock()
        tool.rss._semaphore = AsyncMock()
        tool.rss._variables = {}
        return tool


@pytest.mark.asyncio
async def test_cointelegraph_tool_success(cointelegraph_tool):
    """Test successful fetch of CoinTelegraph RSS with content."""
    mock_result = {
        "title": "CoinTelegraph",
        "url": "https://cointelegraph.com/rss",
        "items": [
            {
                "title": "Bitcoin hits new high",
                "link": "https://cointelegraph.com/news/bitcoin-high",
                "description": "Short description",
                "pubDate": "2024-01-01",
                "content_summary": "Bitcoin reached a new all-time high today as market sentiment improved."
            },
            {
                "title": "Ethereum update",
                "link": "https://cointelegraph.com/news/eth-update",
                "description": "ETH news",
                "pubDate": "2024-01-02",
                "content_summary": "Ethereum developers announced a major network upgrade."
            }
        ]
    }

    cointelegraph_tool.rss.read_rss_with_content = AsyncMock(return_value=mock_result)

    result = await cointelegraph_tool._execute(limit=2)

    assert result['feed'] == 'CoinTelegraph'
    assert result['count'] == 2
    assert len(result['items']) == 2
    assert result['items'][0]['title'] == 'Bitcoin hits new high'
    assert 'content_summary' in result['items'][0]


@pytest.mark.asyncio
async def test_cointelegraph_tool_with_custom_params(cointelegraph_tool):
    """Test tool with custom parameters."""
    mock_result = {
        "title": "CoinTelegraph",
        "url": "https://cointelegraph.com/rss",
        "items": [{"title": "Test", "content_summary": "Summary"}]
    }

    cointelegraph_tool.rss.read_rss_with_content = AsyncMock(return_value=mock_result)

    result = await cointelegraph_tool._execute(
        limit=5,
        max_chars=500,
        output_format='dict'
    )

    # Verify the tool called the interface with correct params
    cointelegraph_tool.rss.read_rss_with_content.assert_called_once_with(
        url="https://cointelegraph.com/rss",
        limit=5,
        max_chars=500,
        output_format='dict'
    )


@pytest.mark.asyncio
async def test_cointelegraph_tool_markdown_format(cointelegraph_tool):
    """Test markdown output format."""
    mock_markdown = """# CoinTelegraph

## [Bitcoin News](https://cointelegraph.com/news/btc)
**Date:** 2024-01-01

Bitcoin summary here.

---
"""

    cointelegraph_tool.rss.read_rss_with_content = AsyncMock(return_value=mock_markdown)

    result = await cointelegraph_tool._execute(output_format='markdown')

    assert isinstance(result, str)
    assert "# CoinTelegraph" in result


@pytest.mark.asyncio
async def test_cointelegraph_tool_empty_result(cointelegraph_tool):
    """Test handling of empty/failed feed fetch."""
    cointelegraph_tool.rss.read_rss_with_content = AsyncMock(return_value=None)

    result = await cointelegraph_tool._execute()

    assert result['count'] == 0
    assert result['items'] == []
    assert 'message' in result


@pytest.mark.asyncio
async def test_cointelegraph_tool_error_handling(cointelegraph_tool):
    """Test error handling."""
    cointelegraph_tool.rss.read_rss_with_content = AsyncMock(
        side_effect=Exception("Network error")
    )

    with pytest.raises(Exception) as exc_info:
        await cointelegraph_tool._execute()

    assert "Network error" in str(exc_info.value)


def test_cointelegraph_tool_schema():
    """Test tool schema and metadata."""
    tool = CoinTelegraphTool()
    
    assert tool.name == "cointelegraph_news"
    assert "cryptocurrency" in tool.description.lower()
    assert tool.RSS_URL == "https://cointelegraph.com/rss"
    
    # Check schema fields
    schema = tool.args_schema.model_json_schema()
    assert 'limit' in schema['properties']
    assert 'max_chars' in schema['properties']
    assert 'output_format' in schema['properties']
