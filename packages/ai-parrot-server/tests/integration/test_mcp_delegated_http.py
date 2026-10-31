"""HTTP-level gate: delegated MCP mode against a local streamable-HTTP endpoint."""

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from parrot.auth.exceptions import AuthorizationRequired
from parrot.mcp.client import MCPClientConfig
from parrot.mcp.integration import MCPClient


class _Endpoint:
    """Records (method, Authorization, session id) for every request."""

    def __init__(self, throttle_once_for: str = "") -> None:
        self.requests: list = []
        self.throttle_once_for = throttle_once_for
        self._throttled = False
        self._counter = 0

    async def handle(self, request: web.Request) -> web.Response:
        body = await request.json()
        method = body.get("method")
        auth = request.headers.get("Authorization")
        self.requests.append((method, auth, request.headers.get("Mcp-Session-Id")))
        if method == "notifications/initialized":
            return web.Response(status=202)
        if method == "tools/call" and auth == self.throttle_once_for and not self._throttled:
            self._throttled = True
            return web.Response(status=429, headers={"Retry-After": "0"})
        headers = {}
        if method == "initialize":
            self._counter += 1
            headers["Mcp-Session-Id"] = f"sess-{self._counter}"
            result = {"protocolVersion": "2024-11-05"}
        elif method == "tools/list":
            result = {"tools": []}
        else:
            result = {"content": [{"type": "text", "text": "ok"}]}
        return web.json_response({"jsonrpc": "2.0", "id": body["id"], "result": result}, headers=headers)

    def calls(self) -> list:
        return [r for r in self.requests if r[0] == "tools/call"]


async def _connect(ep: _Endpoint, **cfg_kwargs):
    app = web.Application()
    app.router.add_post("/mcp", ep.handle)
    server = TestServer(app)
    await server.start_server()
    cfg = MCPClientConfig(name="srv", url=str(server.make_url("/mcp")), transport="http", **cfg_kwargs)
    client = MCPClient(cfg)
    await client.connect()
    return server, client


@pytest.mark.asyncio
async def test_two_principals_isolated_bearers_and_sessions():
    ep = _Endpoint(throttle_once_for="Bearer A")
    server, client = await _connect(ep, inject_broker_credential=True, credential_provider="prov")
    try:
        a = {"Authorization": "Bearer A"}
        b = {"Authorization": "Bearer B"}
        await asyncio.gather(client.call_tool("t", {}, headers=a), client.call_tool("t", {}, headers=b))
        await client.call_tool("t", {}, headers=a)
        by_auth: dict = {}
        for _, auth, sid in ep.calls():
            by_auth.setdefault(auth, set()).add(sid)
        # A: 429 + retry + later call (3 requests), B: 1 request; each principal keeps one session
        assert sum(1 for _, auth, _ in ep.calls() if auth == "Bearer A") == 3
        assert sum(1 for _, auth, _ in ep.calls() if auth == "Bearer B") == 1
        assert set(by_auth) == {"Bearer A", "Bearer B"}
        assert all(len(s) == 1 for s in by_auth.values())
        assert by_auth["Bearer A"] != by_auth["Bearer B"]
    finally:
        await client.disconnect()
        await server.close()


@pytest.mark.asyncio
async def test_missing_credential_makes_no_request():
    ep = _Endpoint()
    server, client = await _connect(ep, inject_broker_credential=True, credential_provider="prov")
    try:
        before = len(ep.requests)
        with pytest.raises(AuthorizationRequired):
            await client.call_tool("t", {}, headers={})
        assert len(ep.requests) == before
    finally:
        await client.disconnect()
        await server.close()


@pytest.mark.asyncio
async def test_m2m_unchanged():
    ep = _Endpoint()
    server, client = await _connect(ep, user_id="m2m", headers={"Authorization": "Bearer M2M"})
    try:
        await client.call_tool("t", {}, headers=None)
        calls = ep.calls()
        assert len(calls) == 1
        assert calls[0][1] == "Bearer M2M"
        assert calls[0][2] == "sess-1"
    finally:
        await client.disconnect()
        await server.close()
