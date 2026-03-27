import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.integrations.zoom.client import ZoomUsInterface

@pytest.fixture
def zoom_interface():
    return ZoomUsInterface(
        account_id="test_account",
        client_id="test_client",
        client_secret="test_secret"
    )

@pytest.mark.asyncio
async def test_connect(zoom_interface):
    await zoom_interface.connect()
    assert zoom_interface._session is not None
    await zoom_interface.close()
    assert zoom_interface._session is None

@pytest.mark.asyncio
async def test_get_access_token_success(zoom_interface):
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = {"access_token": "fake_token", "expires_in": 3600}
        mock_post.return_value.__aenter__.return_value = mock_resp

        token = await zoom_interface._get_access_token()
        assert token == "fake_token"
        assert zoom_interface._token == "fake_token"

@pytest.mark.asyncio
async def test_get_access_token_failure(zoom_interface):
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 401
        mock_resp.text.return_value = "Unauthorized"
        mock_post.return_value.__aenter__.return_value = mock_resp

        with pytest.raises(Exception) as excinfo:
            await zoom_interface._get_access_token()
        assert "Failed to get Zoom token: 401" in str(excinfo.value)

@pytest.mark.asyncio
async def test_request_success(zoom_interface):
    # Mock token acquisition
    zoom_interface._token = "valid_token"
    zoom_interface._token_expires_at = 9999999999

    with patch("aiohttp.ClientSession.request") as mock_request:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = {"key": "value"}
        mock_request.return_value.__aenter__.return_value = mock_resp

        result = await zoom_interface.request("GET", "/endpoint")
        assert result == {"key": "value"}
        
        # Verify headers
        call_args = mock_request.call_args
        headers = call_args.kwargs['headers']
        assert headers['Authorization'] == "Bearer valid_token"

@pytest.mark.asyncio
async def test_get_account_settings(zoom_interface):
    # Mock request
    with patch.object(zoom_interface, 'request', new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"settings": "data"}
        
        result = await zoom_interface.get_account_settings(option="security")
        
        assert result == {"settings": "data"}
        mock_req.assert_called_once_with(
            "GET", 
            "/phone/account_settings", 
            params={"option": "security"}
        )
