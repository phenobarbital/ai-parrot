
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, date
from parrot.tools.alpaca import AlpacaMarketsToolkit, StockQuoteInput, StockBarsInput

@pytest.fixture
def mock_alpaca_clients():
    with patch("parrot.tools.alpaca.alpaca.data.historical.StockHistoricalDataClient") as mock_stock, \
         patch("parrot.tools.alpaca.alpaca.data.historical.CryptoHistoricalDataClient") as mock_crypto, \
         patch("parrot.tools.alpaca.TradingClient") as mock_trading:
        
        yield mock_stock, mock_crypto, mock_trading

@pytest.fixture
def toolkit(mock_alpaca_clients):
    with patch("parrot.tools.alpaca.config.get") as mock_config:
        mock_config.return_value = "dummy"
        return AlpacaMarketsToolkit()

@pytest.mark.asyncio
async def test_get_stock_quotes(toolkit, mock_alpaca_clients):
    mock_stock, _, _ = mock_alpaca_clients
    mock_client_instance = mock_stock.return_value
    
    # Mock return value
    mock_quote = MagicMock()
    mock_quote.model_dump.return_value = {"symbol": "AAPL", "ask_price": 150.0}
    mock_client_instance.get_stock_latest_quote.return_value = {"AAPL": mock_quote}
    
    result = await toolkit.get_stock_quotes(symbol="AAPL")
    
    assert result["symbol"] == "AAPL"
    assert result["quote"]["ask_price"] == 150.0
    mock_client_instance.get_stock_latest_quote.assert_called_once()

@pytest.mark.asyncio
async def test_get_stock_bars(toolkit, mock_alpaca_clients):
    mock_stock, _, _ = mock_alpaca_clients
    mock_client_instance = mock_stock.return_value
    
    # Mock return value
    mock_bars = MagicMock()
    mock_bars.df.empty = False
    
    # Create a dummy dataframe-like structure or just mock the to_dict part if possible, 
    # but the code uses bars.df.reset_index().to_dict()
    # It's easier to mock the whole logic or just the return of get_stock_bars
    
    import pandas as pd
    mock_df = pd.DataFrame([{
        "timestamp": datetime(2023, 1, 1),
        "open": 100,
        "high": 110,
        "low": 90,
        "close": 105,
        "volume": 1000
    }])
    mock_bars.df = mock_df
    
    mock_client_instance.get_stock_bars.return_value = mock_bars
    
    result = await toolkit.get_stock_bars(
        symbol="AAPL", 
        timeframe="1Day", 
        start="2023-01-01"
    )
    
    assert result["symbol"] == "AAPL"
    assert result["bars_count"] == 1
    assert result["bars"][0]["open"] == 100
    # Timestamp converted to string
    assert isinstance(result["bars"][0]["timestamp"], str)

@pytest.mark.asyncio
async def test_parse_timeframe(toolkit):
    from alpaca.data.timeframe import TimeFrame
    
    tf_day = toolkit._parse_timeframe("1Day")
    assert tf_day.amount == TimeFrame.Day.amount
    assert tf_day.unit == TimeFrame.Day.unit
    
    tf_min = toolkit._parse_timeframe("1Min")
    assert tf_min.amount == TimeFrame.Minute.amount
    assert tf_min.unit == TimeFrame.Minute.unit
    
    with pytest.raises(ValueError):
        toolkit._parse_timeframe("InvalidTF")

