"""Tests for MCP OAuth2 callback route (FEAT-262, TASK-1664)."""
import asyncio
import pytest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from parrot.auth.oauth2_routes import handle_mcp_oauth2_callback, setup_mcp_oauth2_callback
from parrot.mcp.oauth2_state import (
    _pending_mcp_callbacks,
    register_pending_callback,
    resolve_pending_callback,
)


@pytest.fixture(autouse=True)
def clear_pending_callbacks():
    """Clear pending callbacks dict before each test."""
    _pending_mcp_callbacks.clear()
    yield
    _pending_mcp_callbacks.clear()


@pytest.fixture
async def mcp_callback_client(aiohttp_client):
    """Create an aiohttp test client with the MCP callback route."""
    app = web.Application()
    setup_mcp_oauth2_callback(app)
    return await aiohttp_client(app)


class TestMCPOAuth2CallbackRoute:
    """Tests for handle_mcp_oauth2_callback."""

    @pytest.mark.asyncio
    async def test_valid_callback_signals_event(self, mcp_callback_client):
        """Valid code + state signals the pending event."""
        # Register a pending callback
        event, result = register_pending_callback("test-state-123")
        assert not event.is_set()

        resp = await mcp_callback_client.get(
            "/api/auth/oauth2/mcp/callback",
            params={"code": "auth-code-xyz", "state": "test-state-123"},
        )
        assert resp.status == 200

        # Event should be set
        assert event.is_set()
        assert result["code"] == "auth-code-xyz"
        assert result["state"] == "test-state-123"

    @pytest.mark.asyncio
    async def test_valid_callback_returns_html(self, mcp_callback_client):
        """Valid callback returns HTML success page."""
        register_pending_callback("state-abc")
        resp = await mcp_callback_client.get(
            "/api/auth/oauth2/mcp/callback",
            params={"code": "code-123", "state": "state-abc"},
        )
        assert resp.status == 200
        text = await resp.text()
        assert "Authentication complete" in text

    @pytest.mark.asyncio
    async def test_invalid_state_returns_400(self, mcp_callback_client):
        """Unknown state returns 400."""
        resp = await mcp_callback_client.get(
            "/api/auth/oauth2/mcp/callback",
            params={"code": "some-code", "state": "unknown-state"},
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_missing_state_returns_400(self, mcp_callback_client):
        """Missing state parameter returns 400."""
        resp = await mcp_callback_client.get(
            "/api/auth/oauth2/mcp/callback",
            params={"code": "some-code"},
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_missing_code_returns_400(self, mcp_callback_client):
        """Missing code parameter returns 400."""
        register_pending_callback("state-xyz")
        resp = await mcp_callback_client.get(
            "/api/auth/oauth2/mcp/callback",
            params={"state": "state-xyz"},
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_oauth2_error_param_returns_400(self, mcp_callback_client):
        """OAuth2 error param returns 400 with error message."""
        register_pending_callback("state-err")
        resp = await mcp_callback_client.get(
            "/api/auth/oauth2/mcp/callback",
            params={
                "error": "access_denied",
                "error_description": "User denied access",
                "state": "state-err",
            },
        )
        assert resp.status == 400
        text = await resp.text()
        assert "User denied access" in text or "access_denied" in text

    @pytest.mark.asyncio
    async def test_state_consumed_after_callback(self, mcp_callback_client):
        """State entry is removed from dict after successful callback (prevent replay)."""
        register_pending_callback("state-once")
        resp1 = await mcp_callback_client.get(
            "/api/auth/oauth2/mcp/callback",
            params={"code": "code-1", "state": "state-once"},
        )
        assert resp1.status == 200

        # Second call with same state should fail
        resp2 = await mcp_callback_client.get(
            "/api/auth/oauth2/mcp/callback",
            params={"code": "code-2", "state": "state-once"},
        )
        assert resp2.status == 400

    @pytest.mark.asyncio
    async def test_multiple_pending_callbacks(self, mcp_callback_client):
        """Multiple concurrent pending callbacks work independently."""
        event1, result1 = register_pending_callback("state-1")
        event2, result2 = register_pending_callback("state-2")

        # Resolve state-1
        resp1 = await mcp_callback_client.get(
            "/api/auth/oauth2/mcp/callback",
            params={"code": "code-a", "state": "state-1"},
        )
        assert resp1.status == 200
        assert event1.is_set()
        assert not event2.is_set()  # state-2 still pending

        # Resolve state-2
        resp2 = await mcp_callback_client.get(
            "/api/auth/oauth2/mcp/callback",
            params={"code": "code-b", "state": "state-2"},
        )
        assert resp2.status == 200
        assert event2.is_set()


class TestSetupMCPOAuth2Callback:
    """Tests for setup_mcp_oauth2_callback."""

    def test_registers_route(self):
        """setup_mcp_oauth2_callback registers the callback route."""
        app = web.Application()
        setup_mcp_oauth2_callback(app)
        paths = [r.get_info().get("path", "") for r in app.router.routes()]
        assert "/api/auth/oauth2/mcp/callback" in paths

    def test_idempotent(self):
        """Calling setup twice does not duplicate the route (one resource only)."""
        app = web.Application()
        setup_mcp_oauth2_callback(app)
        setup_mcp_oauth2_callback(app)
        # Check at the resource level (one resource per path, even though
        # add_get creates both GET and HEAD routes)
        resource_paths = [r.get_info().get("path", "") for r in app.router.resources()]
        assert resource_paths.count("/api/auth/oauth2/mcp/callback") == 1
