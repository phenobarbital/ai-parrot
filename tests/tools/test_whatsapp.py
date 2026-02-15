"""Tests for WhatsAppTool."""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from parrot.tools.messaging.whatsapp import WhatsAppTool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tool():
    """Create a WhatsAppTool with bridge disabled for isolation."""
    return WhatsAppTool(bridge_url="http://test-bridge:8765")


# ---------------------------------------------------------------------------
# Configuration & Validation
# ---------------------------------------------------------------------------

class TestValidation:
    """Tests for input validation and config guards."""

    @pytest.mark.asyncio
    @patch("parrot.tools.messaging.whatsapp.WHATSAPP_BRIDGE_ENABLED", False)
    async def test_bridge_disabled(self, tool):
        """Returns error when bridge is disabled in config."""
        result = await tool._execute(phone="14155552671", message="hi")
        assert result["success"] is False
        assert "disabled" in result["error"]

    @pytest.mark.asyncio
    @patch("parrot.tools.messaging.whatsapp.WHATSAPP_BRIDGE_ENABLED", True)
    async def test_invalid_phone(self, tool):
        """Rejects phone numbers that contain non-digit characters."""
        result = await tool._execute(phone="+1-415-555", message="hi")
        assert result["success"] is False
        assert "digits" in result["error"]

    @pytest.mark.asyncio
    @patch("parrot.tools.messaging.whatsapp.WHATSAPP_BRIDGE_ENABLED", True)
    @patch("parrot.tools.messaging.whatsapp.WHATSAPP_ALLOWED_PHONES", "14155550000,14155550001")
    async def test_phone_not_in_allowlist(self, tool):
        """Rejects phone numbers not in the allowed list."""
        result = await tool._execute(phone="14155559999", message="hi")
        assert result["success"] is False
        assert "not in the allowed list" in result["error"]


# ---------------------------------------------------------------------------
# Bridge Health
# ---------------------------------------------------------------------------

class TestBridgeHealth:
    """Tests for health-check logic."""

    @pytest.mark.asyncio
    @patch("parrot.tools.messaging.whatsapp.WHATSAPP_BRIDGE_ENABLED", True)
    @patch("parrot.tools.messaging.whatsapp.WHATSAPP_ALLOWED_PHONES", None)
    async def test_bridge_unhealthy(self, tool):
        """Returns error when bridge health check fails."""
        with patch.object(tool, "_check_bridge_health", new_callable=AsyncMock) as mock_health:
            mock_health.return_value = {"success": False, "error": "connection refused"}
            result = await tool._execute(phone="14155552671", message="hi")
            assert result["success"] is False
            assert "not available" in result["error"]

    @pytest.mark.asyncio
    @patch("parrot.tools.messaging.whatsapp.WHATSAPP_BRIDGE_ENABLED", True)
    @patch("parrot.tools.messaging.whatsapp.WHATSAPP_ALLOWED_PHONES", None)
    async def test_bridge_not_authenticated(self, tool):
        """Returns error when bridge is healthy but not authenticated."""
        with patch.object(tool, "_check_bridge_health", new_callable=AsyncMock) as mock_health:
            mock_health.return_value = {
                "success": True,
                "data": {"connected": False, "authenticated": False},
            }
            result = await tool._execute(phone="14155552671", message="hi")
            assert result["success"] is False
            assert "not connected" in result["error"]


# ---------------------------------------------------------------------------
# Send Message
# ---------------------------------------------------------------------------

class TestSendMessage:
    """Tests for the actual send path (aiohttp mocked)."""

    def _healthy_bridge(self):
        """Return an AsyncMock that reports a healthy, authenticated bridge."""
        mock = AsyncMock()
        mock.return_value = {
            "success": True,
            "data": {"connected": True, "authenticated": True},
        }
        return mock

    def _mock_session(self, response_data: dict, status: int = 200):
        """Build a properly nested aiohttp.ClientSession mock."""
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.json = AsyncMock(return_value=response_data)

        # post() returns an async context manager (the response)
        post_cm = MagicMock()
        post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        post_cm.__aexit__ = AsyncMock(return_value=False)

        # session itself is an async context manager
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=post_cm)

        return mock_session

    @pytest.mark.asyncio
    @patch("parrot.tools.messaging.whatsapp.WHATSAPP_BRIDGE_ENABLED", True)
    @patch("parrot.tools.messaging.whatsapp.WHATSAPP_ALLOWED_PHONES", None)
    async def test_send_success(self, tool):
        """Happy-path: message sent, returns message_id."""
        mock_session = self._mock_session({
            "success": True,
            "data": {"message_id": "abc123", "timestamp": "2026-02-15T12:00:00Z"},
        })

        with (
            patch.object(tool, "_check_bridge_health", new=self._healthy_bridge()),
            patch("aiohttp.ClientSession", return_value=mock_session),
        ):
            result = await tool._execute(phone="14155552671", message="hello")

        assert result["success"] is True
        assert result["message_id"] == "abc123"
        assert result["phone"] == "14155552671"

    @pytest.mark.asyncio
    @patch("parrot.tools.messaging.whatsapp.WHATSAPP_BRIDGE_ENABLED", True)
    @patch("parrot.tools.messaging.whatsapp.WHATSAPP_ALLOWED_PHONES", None)
    async def test_send_with_media(self, tool):
        """Payload includes media_url when provided."""
        mock_session = self._mock_session({
            "success": True,
            "data": {"message_id": "media1", "timestamp": "2026-02-15T12:00:00Z"},
        })

        with (
            patch.object(tool, "_check_bridge_health", new=self._healthy_bridge()),
            patch("aiohttp.ClientSession", return_value=mock_session),
        ):
            result = await tool._execute(
                phone="14155552671",
                message="chart",
                media_url="https://example.com/chart.png",
            )

        assert result["success"] is True
        # Verify the payload included media_url
        call_kwargs = mock_session.post.call_args
        assert call_kwargs.kwargs.get("json", {}).get("media_url") == "https://example.com/chart.png"

    @pytest.mark.asyncio
    @patch("parrot.tools.messaging.whatsapp.WHATSAPP_BRIDGE_ENABLED", True)
    @patch("parrot.tools.messaging.whatsapp.WHATSAPP_ALLOWED_PHONES", None)
    async def test_send_timeout(self, tool):
        """Returns timeout error on asyncio.TimeoutError."""
        post_cm = MagicMock()
        post_cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError)
        post_cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=post_cm)

        with (
            patch.object(tool, "_check_bridge_health", new=self._healthy_bridge()),
            patch("aiohttp.ClientSession", return_value=mock_session),
        ):
            result = await tool._execute(phone="14155552671", message="hi")

        assert result["success"] is False
        assert "timed out" in result["error"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestSchema:
    """Test tool schema generation."""

    def test_get_schema(self, tool):
        """Schema generation returns expected structure."""
        schema = tool.get_schema()
        assert schema["name"] == "send_whatsapp"
        params = schema["parameters"]
        assert "phone" in params["properties"]
        assert "message" in params["properties"]
        assert "media_url" in params["properties"]
