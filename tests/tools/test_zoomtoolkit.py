import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.tools.zoomtoolkit import ZoomUsToolkit

@pytest.fixture
def zoom_toolkit():
    with patch("parrot.tools.zoomtoolkit.ZoomUsInterface") as mock_interface_cls:
        mock_interface = AsyncMock()
        mock_interface_cls.return_value = mock_interface
        
        toolkit = ZoomUsToolkit(
            account_id="test_acc",
            client_id="test_client",
            client_secret="test_secret"
        )
        return toolkit, mock_interface

@pytest.mark.asyncio
async def test_toolkit_initialization():
    # Test valid init
    with patch("parrot.tools.zoomtoolkit.ZoomUsInterface") as mock_interface_cls:
        toolkit = ZoomUsToolkit(
            account_id="acc",
            client_id="id",
            client_secret="secret"
        )
        mock_interface_cls.assert_called_once_with(
            account_id="acc",
            client_id="id",
            client_secret="secret",
            logger=toolkit.logger
        )

@pytest.mark.asyncio
async def test_get_account_settings_tool(zoom_toolkit):
    toolkit, mock_interface = zoom_toolkit
    
    mock_interface.get_account_settings.return_value = {"settings": "ok"}
    
    result = await toolkit.get_account_settings(option="recording")
    
    assert result == {"settings": "ok"}
    mock_interface.get_account_settings.assert_called_once_with(option="recording")

@pytest.mark.asyncio
async def test_get_account_settings_error(zoom_toolkit):
    toolkit, mock_interface = zoom_toolkit
    
    mock_interface.get_account_settings.side_effect = Exception("API Error")
    
    result = await toolkit.get_account_settings()
    
    assert result == {"error": "API Error"}
