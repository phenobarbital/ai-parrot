import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from parrot.tools.cryptoquant import CryptoQuantToolkit

@pytest.fixture
def toolkit():
    return CryptoQuantToolkit(api_key="test_key")

@pytest.fixture
def mock_http_service(toolkit):
    toolkit.http_service = MagicMock()
    toolkit.http_service.async_request = AsyncMock()
    return toolkit.http_service

@pytest.mark.asyncio
async def test_cq_discovery_endpoints(toolkit, mock_http_service):
    # Mock response
    mock_response = {
        "status": {
            "code": 200,
            "message": "success"
        },
        "result": {
            "data": [
                {
                    "path": "/v1/btc/status/entity-list",
                    "parameters": [
                        {
                            "type": [
                                "exchange",
                                "miner"
                            ]
                        }
                    ]
                }
            ]
        }
    }
    mock_http_service.async_request.return_value = (mock_response, None)

    result = await toolkit.cq_discovery_endpoints()
    
    assert result == mock_response
    mock_http_service.async_request.assert_called_once_with(
        url="https://api.cryptoquant.com/v1/discovery/endpoints",
        method="GET"
    )

@pytest.mark.asyncio
async def test_cq_price_ohlcv(toolkit, mock_http_service):
    # Mock response
    mock_response = {
        "status": {"code": 200, "message": "success"},
        "result": {
             "data": [
                 {"date": "2023-01-01", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000}
             ]
        }
    }
    mock_http_service.async_request.return_value = (mock_response, None)

    await toolkit.cq_price_ohlcv(token="doge", window="day", limit=2)

    # Check that URL parameters are correctly encoded
    expected_url_part = "https://api.cryptoquant.com/v1/alt/market-data/price-ohlcv"
    call_args = mock_http_service.async_request.call_args
    assert call_args is not None
    url_arg = call_args.kwargs.get('url') or call_args.args[0]
    
    assert expected_url_part in url_arg
    assert "token=doge" in url_arg
    assert "window=day" in url_arg
    assert "limit=2" in url_arg

if __name__ == "__main__":
    asyncio.run(test_cq_discovery_endpoints(CryptoQuantToolkit(api_key="test"), MagicMock()))
