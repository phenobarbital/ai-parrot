"""Unit tests for MCP delegated (per-call principal) mode."""

import pytest

from parrot.auth.exceptions import AuthorizationRequired
from parrot.mcp.client import MCPClientConfig, MCPConnectionError
from parrot.mcp.integration import MCPClient, MCPToolProxy, create_oauth_mcp_server


def _delegated_cfg(transport: str = "http") -> MCPClientConfig:
    return MCPClientConfig(
        name="srv",
        url="http://localhost:1/mcp",
        transport=transport,
        inject_broker_credential=True,
        credential_provider="prov",
    )


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list = []

    async def call_tool(self, name, arguments, **kwargs):
        self.calls.append((name, arguments, kwargs))
        return "ok"


def _client(cfg: MCPClientConfig) -> MCPClient:
    client = MCPClient(cfg)
    client._session = _FakeSession()
    client._connected = True
    return client


def test_mcp_user_id_optional_injects_broker():
    cfg = create_oauth_mcp_server(
        name="d",
        url="http://x/mcp",
        client_id="c",
        auth_url="http://a",
        token_url="http://t",
        credential_provider="prov",
    )
    assert cfg.user_id is None
    assert cfg.inject_broker_credential is True
    assert cfg.credential_provider == "prov"
    proxy = MCPToolProxy({"name": "t"}, MCPClient(cfg), "d")
    assert proxy.credential_provider == "prov"


def test_bound_user_id_is_not_delegated():
    cfg = create_oauth_mcp_server(
        name="b",
        url="http://x/mcp",
        user_id="u1",
        client_id="c",
        auth_url="http://a",
        token_url="http://t",
    )
    assert cfg.inject_broker_credential is False
    assert cfg.credential_provider is None


def test_delegated_without_provider_rejected():
    with pytest.raises(ValueError):
        create_oauth_mcp_server(name="d", url="http://x/mcp", client_id="c", auth_url="http://a", token_url="http://t")


@pytest.mark.asyncio
async def test_delegated_forwards_headers():
    client = _client(_delegated_cfg())
    assert await client.call_tool("t", {"a": 1}, headers={"Authorization": "Bearer X"}) == "ok"
    assert client._session.calls == [("t", {"a": 1}, {"headers": {"Authorization": "Bearer X"}})]


@pytest.mark.asyncio
async def test_delegated_missing_authorization_fails_closed():
    client = _client(_delegated_cfg())
    with pytest.raises(AuthorizationRequired):
        await client.call_tool("t", {}, headers={})
    with pytest.raises(AuthorizationRequired):
        await client.call_tool("t", {})
    assert client._session.calls == []


@pytest.mark.asyncio
async def test_delegated_non_http_transport_raises():
    client = _client(_delegated_cfg(transport="sse"))
    with pytest.raises(MCPConnectionError):
        await client.call_tool("t", {}, headers={"Authorization": "Bearer X"})
    assert client._session.calls == []


@pytest.mark.asyncio
async def test_non_delegated_call_unchanged():
    cfg = MCPClientConfig(name="m", url="http://localhost:1/mcp", transport="http", user_id="m2m")
    client = _client(cfg)
    await client.call_tool("t", {}, headers={"Authorization": "Bearer X"})
    assert client._session.calls == [("t", {}, {})]


@pytest.mark.asyncio
async def test_proxy_missing_credential_raises_before_session_call():
    client = _client(_delegated_cfg())
    proxy = MCPToolProxy({"name": "t"}, client, "srv")
    with pytest.raises(AuthorizationRequired):
        await proxy._execute()
    assert client._session.calls == []
