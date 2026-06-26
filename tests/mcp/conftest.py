"""Shared fixtures for tests/mcp/ (FEAT-262).

Provides reusable pytest fixtures for MCP OAuth2 tests.
Individual test modules may define additional local fixtures.
"""
from __future__ import annotations

import pytest
from aiohttp import web

from parrot.mcp.oauth2_config import MCPOAuth2Config, MCPOAuth2GrantType
from parrot.mcp.oauth import InMemoryTokenStore


@pytest.fixture
async def mock_oauth2_server(aiohttp_server):
    """Minimal mock OAuth2 authorization server.

    Endpoints:
        GET  /authorize  — redirects with authorization code
        POST /token      — returns access token JSON
    """
    app = web.Application()

    async def authorize(request: web.Request) -> web.Response:
        redirect_uri = request.query.get("redirect_uri", "")
        state = request.query.get("state", "")
        raise web.HTTPFound(f"{redirect_uri}?code=mock-auth-code&state={state}")

    async def token(request: web.Request) -> web.Response:
        data = await request.post()
        grant_type = data.get("grant_type", "")
        if grant_type == "refresh_token":
            return web.json_response({
                "access_token": "refreshed-access-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "new-refresh-token",
                "scope": "read write",
            })
        return web.json_response({
            "access_token": "mock-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "mock-refresh-token",
            "scope": "read write",
        })

    app.router.add_get("/authorize", authorize)
    app.router.add_post("/token", token)
    return await aiohttp_server(app)


@pytest.fixture
def in_memory_token_store():
    """Return a fresh InMemoryTokenStore."""
    return InMemoryTokenStore()


@pytest.fixture
def basic_mcp_oauth2_config():
    """Return a basic authorization code MCPOAuth2Config."""
    return MCPOAuth2Config(
        client_id="test-client",
        auth_url="http://localhost:9999/authorize",
        token_url="http://localhost:9999/token",
        scopes=["read"],
        grant_type=MCPOAuth2GrantType.AUTHORIZATION_CODE,
    )


@pytest.fixture
def client_credentials_mcp_oauth2_config():
    """Return a client credentials MCPOAuth2Config."""
    return MCPOAuth2Config(
        client_id="service-client",
        client_secret="service-secret",
        token_url="http://localhost:9999/token",
        scopes=["mcp"],
        grant_type=MCPOAuth2GrantType.CLIENT_CREDENTIALS,
    )
