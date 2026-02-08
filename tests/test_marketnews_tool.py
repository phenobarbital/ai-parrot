from typing import Any, Type, Dict
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.tools.marketnews import MarketNewsTool

@pytest.fixture
def market_news_tool():
    # Mock RSSInterface
    with patch('parrot.tools.marketnews.RSSInterface') as mock_rss_cls:
        tool = MarketNewsTool()
        tool.rss = mock_rss_cls.return_value
        return tool

@pytest.mark.asyncio
async def test_market_news_execute_success(market_news_tool):
    # Mock RSS response
    mock_result = {
        "title": "Top Stories",
        "url": "http://test.com",
        "items": [{"title": "News 1"}, {"title": "News 2"}]
    }
    market_news_tool.rss.read_rss = AsyncMock(return_value=mock_result)

    result = await market_news_tool._execute(feed="top_stories", limit=5)

    assert result["feed"] == "top_stories"
    assert result["count"] == 2
    assert result["items"][0]["title"] == "News 1"
    
    # Verify RSS call
    market_news_tool.rss.read_rss.assert_called_with(
        url="https://feeds.content.dowjones.io/public/rss/mw_topstories",
        limit=5,
        output_format='dict'
    )

@pytest.mark.asyncio
async def test_market_news_execute_real_time(market_news_tool):
    mock_result = {"title": "Real Time", "items": []}
    market_news_tool.rss.read_rss = AsyncMock(return_value=mock_result)

    await market_news_tool._execute(feed="real_time")
    
    market_news_tool.rss.read_rss.assert_called_with(
        url="https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
        limit=10,
        output_format='dict'
    )

@pytest.mark.asyncio
async def test_market_news_invalid_feed(market_news_tool):
    with pytest.raises(ValueError) as excinfo:
        await market_news_tool._execute(feed="invalid_feed")
    
    assert "Invalid feed name" in str(excinfo.value)

@pytest.mark.asyncio
async def test_market_news_empty_response(market_news_tool):
    market_news_tool.rss.read_rss = AsyncMock(return_value={})
    
    result = await market_news_tool._execute(feed="top_stories")
    
    assert result["count"] == 0
    assert result["message"] == "Failed to fetch or parse the feed."
