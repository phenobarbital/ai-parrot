"""Unit tests for HttpMCPSession per-call headers and principal-partitioned sessions."""
import logging

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from parrot.mcp.client import MCPClientConfig, MCPRateLimitError
from parrot.mcp.transports.http import HttpMCPSession


class _Recorder:
    """Fake streamable-HTTP MCP server recording every request's headers."""

    def __init__(self, fail_first_call: bool = False) -> None:
        self.requests: list = []
        self.fail_first_call = fail_first_call
        self._counter = 0
        self._failed = False

    async def handle(self, request: web.Request) -> web.Response:
        body = await request.json()
        method = body.get("method")
        headers = dict(request.headers)
        self.requests.append((method, headers))
        if method == "notifications/initialized":
            return web.Response(status=202)
        if method == "tools/call" and self.fail_first_call and not self._failed:
            self._failed = True
            return web.Response(status=429, headers={"Retry-After": "0"})
        resp_headers = {}
        if method == "initialize":
            self._counter += 1
            resp_headers["Mcp-Session-Id"] = f"sess-{self._counter}"
            result = {"protocolVersion": "2024-11-05"}
        else:
            result = {"content": [{"type": "text", "text": "ok"}]}
        return web.json_response({"jsonrpc": "2.0", "id": body["id"], "result": result}, headers=resp_headers)


async def _make(rec: _Recorder):
    app = web.Application()
    app.router.add_post("/mcp", rec.handle)
    server = TestServer(app)
    await server.start_server()
    cfg = MCPClientConfig(name="t", url=str(server.make_url("/mcp")), transport="http")
    session = HttpMCPSession(cfg, logging.getLogger("test"))
    await session.connect()
    return server, session


def _calls(rec: _Recorder):
    return [h for m, h in rec.requests if m == "tools/call"]


@pytest.mark.asyncio
async def test_per_call_bearer_and_partitioned_sessions():
    rec = _Recorder()
    server, session = await _make(rec)
    try:
        base_before = dict(session._base_headers)
        a = {"Authorization": "Bearer A"}
        b = {"Authorization": "Bearer B"}
        await session.call_tool("t", {}, headers=a)
        await session.call_tool("t", {}, headers=b)
        await session.call_tool("t", {}, headers=a)
        await session.call_tool("t", {})
        calls = _calls(rec)
        assert calls[0]["Authorization"] == "Bearer A"
        assert calls[1]["Authorization"] == "Bearer B"
        assert calls[0]["Mcp-Session-Id"] != calls[1]["Mcp-Session-Id"]
        assert calls[2]["Mcp-Session-Id"] == calls[0]["Mcp-Session-Id"]
        # default partition: original session id, no per-call bearer
        assert calls[3]["Mcp-Session-Id"] == "sess-1"
        assert "Authorization" not in calls[3]
        # one handshake per partition (default + A + B)
        assert sum(1 for m, _ in rec.requests if m == "initialize") == 3
        assert session._base_headers == base_before
        assert a == {"Authorization": "Bearer A"}
    finally:
        await session.disconnect()
        await server.close()


@pytest.mark.asyncio
async def test_retry_keeps_per_call_headers():
    rec = _Recorder(fail_first_call=True)
    server, session = await _make(rec)
    try:
        hdr = {"Authorization": "Bearer R"}
        with pytest.raises(MCPRateLimitError):
            await session.call_tool("t", {}, headers=hdr)
        await session.call_tool("t", {}, headers=hdr)
        calls = _calls(rec)
        assert len(calls) == 2
        assert all(c["Authorization"] == "Bearer R" for c in calls)
        assert calls[0]["Mcp-Session-Id"] == calls[1]["Mcp-Session-Id"]
    finally:
        await session.disconnect()
        await server.close()
