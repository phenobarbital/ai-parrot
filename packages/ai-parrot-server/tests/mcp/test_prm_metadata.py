"""Unit tests for RFC 9728 protected-resource metadata + 401 `resource_metadata`
(FEAT-477, TASK-2608).
"""
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from parrot.mcp.config import AuthMethod, MCPServerConfig
from parrot.mcp.oauth_server import (
    WELL_KNOWN_PRM_PATH,
    ExternalOAuthValidator,
    _build_protected_resource_metadata,
)
from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer


def _make_app(*, resource_server_url=None, issuer_url="https://auth.example.com", scopes=None):
    app = web.Application()
    config = MCPServerConfig(
        name="test-prm",
        auth_method=AuthMethod.OAUTH2_EXTERNAL,
        oauth2_introspection_endpoint="https://auth.example.com/introspect",
        oauth2_client_id="client",
        oauth2_client_secret="secret",
        oauth2_issuer_url=issuer_url,
        oauth2_resource_server_url=resource_server_url,
        oauth_scope=scopes,
        base_path="/mcp",
    )
    server = StreamableHttpMCPServer(config, parent_app=app)
    server._register_routes(app.router, config.base_path)
    server._add_oauth_routes(app.router)
    return app, server


@pytest.fixture
async def client():
    app, _ = _make_app(resource_server_url="https://h/mcp")
    test_server = TestServer(app)
    test_client = TestClient(test_server)
    await test_client.start_server()
    yield test_client
    await test_client.close()


@pytest.fixture
async def client_no_scopes():
    app, _ = _make_app(resource_server_url="https://h/mcp", scopes=None)
    test_server = TestServer(app)
    test_client = TestClient(test_server)
    await test_client.start_server()
    yield test_client
    await test_client.close()


class TestPRM:
    async def test_prm_document_shape(self, client):
        r = await client.get("/mcp/.well-known/oauth-protected-resource")
        assert r.status == 200
        doc = await r.json()
        assert doc["resource"] and doc["bearer_methods_supported"] == ["header"]
        assert doc["authorization_servers"] == ["https://auth.example.com"]

    async def test_scopes_omitted_when_empty(self, client_no_scopes):
        doc = await (
            await client_no_scopes.get(f"/mcp{WELL_KNOWN_PRM_PATH}")
        ).json()
        assert "scopes_supported" not in doc

    async def test_scopes_included_when_configured(self):
        app, _ = _make_app(resource_server_url="https://h/mcp", scopes=["mcp:read", "mcp:write"])
        test_server = TestServer(app)
        test_client = TestClient(test_server)
        await test_client.start_server()
        try:
            doc = await (await test_client.get(f"/mcp{WELL_KNOWN_PRM_PATH}")).json()
            assert doc["scopes_supported"] == ["mcp:read", "mcp:write"]
        finally:
            await test_client.close()

    async def test_401_carries_resource_metadata(self, client):
        r = await client.post("/mcp", json={})
        assert r.status == 401
        assert "resource_metadata=" in r.headers["WWW-Authenticate"]
        assert WELL_KNOWN_PRM_PATH in r.headers["WWW-Authenticate"]

    async def test_audience_rejects_foreign_token(self, monkeypatch):
        validator_for_agent_a = ExternalOAuthValidator(
            introspection_endpoint="https://auth.example.com/introspect",
            client_id="c",
            client_secret="s",
            resource_server_url="https://h/mcp/agents/a",
        )

        async def fake_get_token_info(self, token):
            return {"active": True, "sub": "user-1", "aud": ["https://h/mcp/agents/b"]}

        monkeypatch.setattr(ExternalOAuthValidator, "get_token_info", fake_get_token_info)
        assert await validator_for_agent_a.validate_token("token-for-agent-b") is None

    def test_fallback_matches_builder_shape(self):
        doc = _build_protected_resource_metadata("https://h/x", ["https://a"], [])
        assert set(doc) == {"resource", "authorization_servers", "bearer_methods_supported"}

    async def test_rfc8414_route_unchanged(self, client):
        r = await client.get("/mcp/.well-known/oauth-authorization-server")
        assert r.status == 200
        doc = await r.json()
        assert "issuer" in doc and "authorization_endpoint" in doc
