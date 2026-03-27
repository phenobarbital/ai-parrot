import pytest
from unittest.mock import MagicMock, patch
import sys

# Mock tradingeconomics before import
sys.modules["tradingeconomics"] = MagicMock()
import tradingeconomics as te

from parrot.tools.tradingeco import TradingEcoToolkit, TradingEcoStock


@pytest.fixture
def mock_te():
    with patch("parrot.tools.tradingeco.te") as mock:
        yield mock

@pytest.fixture
def toolkit(mock_te):
    return TradingEcoToolkit(api_key="test_key")

@pytest.mark.asyncio
async def test_init(mock_te):
    toolkit = TradingEcoToolkit(api_key="test_key")
    mock_te.login.assert_called_with("test_key")

@pytest.mark.asyncio
async def test_te_quotes(toolkit, mock_te):
    mock_data = [{
        "Symbol": "AAPL:US",
        "Ticker": "AAPL",
        "Name": "Apple Inc",
        "Country": "United States",
        "Date": "2023-10-27",
        "Close": 150.0
    }]
    mock_te.getStocksByCountry.return_value = mock_data
    
    result = await toolkit.te_quotes(country="united states")
    
    assert len(result) == 1
    assert isinstance(result[0], TradingEcoStock)
    assert result[0].Symbol == "AAPL:US"
    assert result[0].Close == 150.0
    mock_te.getStocksByCountry.assert_called_with(country="united states", output_type='dict')

@pytest.mark.asyncio
async def test_te_news(toolkit, mock_te):
    mock_data = [{"title": "News 1"}, {"title": "News 2"}]
    mock_te.getNews.return_value = mock_data
    
    result = await toolkit.te_news(country="united states")
    
    assert len(result) == 2
    assert result[0]["title"] == "News 1"
    mock_te.getNews.assert_called_with(country="united states", limit=10, output_type='dict')

@pytest.mark.asyncio
async def test_te_market_forecast(toolkit, mock_te):
    mock_data = [{"Category": "Index", "Forecast": 100}]
    mock_te.getMarketsForecasts.return_value = mock_data
    
    result = await toolkit.te_market_forecast(category="index")
    
    assert len(result) == 1
    assert result[0]["Forecast"] == 100
    mock_te.getMarketsForecasts.assert_called_with(category="index", output_type='dict')

@pytest.mark.asyncio
async def test_te_get_indicator(toolkit, mock_te):
    mock_data = [{"Country": "United States", "Category": "GDP", "Value": 23000}]
    mock_te.getIndicatorData.return_value = mock_data
    
    result = await toolkit.te_get_indicator(country="united states", indicators="gdp")
    
    assert len(result) == 1
    assert result[0]["Value"] == 23000
    mock_te.getIndicatorData.assert_called_with(country="united states", indicators="gdp", output_type='dict')
