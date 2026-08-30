"""Integration between the MCP transports and the clients that consume them.

Two seams the per-transport suites do not cover:

- ai-parrot's own ``HttpMCPSession`` against ai-parrot's own Streamable
  HTTP server. The client advertises ``text/event-stream`` in ``Accept``,
  so the server answers request-bearing POSTs with SSE — the client has to
  read that back rather than treat it as an error.
- ``ParrotMCPServer`` mounting several HTTP-like transports on one shared
  aiohttp application. They all claim ``POST {base_path}``, and aiohttp
  routes a duplicate to whichever was registered first instead of
  complaining, so the collision has to be caught in configuration.
"""
import logging

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from parrot.mcp.client import MCPClientConfig
from parrot.tools.abstract import AbstractTool
from pydantic import BaseModel, Field

from parrot.mcp.config import MCPServerConfig, TransportConfig
from parrot.mcp.parrot_server import ParrotMCPServer
from parrot.mcp.transports.http import HttpMCPSession
from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer


class EchoInput(BaseModel):
    text: str = Field(..., description="Text to echo")


class EchoTool(AbstractTool):
    """Echo input back"""
    name = "echo"
    description = "Echo input back"
    args_schema = EchoInput

    async def _execute(self, text: str) -> str:
        return text


@pytest.fixture
async def streamable_url():
    """A running Streamable HTTP server; yields its endpoint URL."""
    config = MCPServerConfig(
        name="integration",
        transport="streamable-http",
        host="127.0.0.1",
        port=0,
    )
    server = StreamableHttpMCPServer(config)
    server.register_tool(EchoTool())
    server._register_routes(server.app.router, config.base_path)

    runner = web.AppRunner(server.app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    yield f"http://127.0.0.1:{port}/mcp"
    await server.stop()
    await runner.cleanup()


class TestOwnClientAgainstStreamableServer:
    async def test_client_reads_sse_post_responses(self, streamable_url):
        """list_tools/call_tool must work, not raise on the SSE body.

        The client sends ``Accept: application/json, text/event-stream``, so
        a Streamable HTTP server is entitled to answer with a stream.
        """
        session = HttpMCPSession(
            MCPClientConfig(name="c", url=streamable_url, transport="http"),
            logging.getLogger("test-mcp-client"),
        )
        try:
            await session.connect()
            tools = await session.list_tools()
            assert any(getattr(t, "name", None) == "echo" for t in tools)

            result = await session.call_tool("echo", {"text": "roundtrip"})
            assert any(
                "roundtrip" in getattr(item, "text", "")
                for item in result.content
            )
        finally:
            await session.disconnect()

    async def test_client_captures_and_echoes_the_session_id(
        self, streamable_url
    ):
        session = HttpMCPSession(
            MCPClientConfig(name="c", url=streamable_url, transport="http"),
            logging.getLogger("test-mcp-client"),
        )
        try:
            await session.connect()
            assert session._mcp_session_id, "session id must be captured"
            assert session._protocol_version == "2024-11-05"
        finally:
            await session.disconnect()
        assert session._mcp_session_id is None, "disconnect must clear it"


def make_parrot_server(transports) -> ParrotMCPServer:
    server = ParrotMCPServer(transports=transports, host="127.0.0.1", port=0)

    async def _tools():
        return [EchoTool()]

    server._load_configured_tools = _tools
    server._add_auth_exclusions = lambda paths: None
    return server


class TestParrotMCPServerMounting:
    async def test_colliding_base_paths_are_refused(self):
        """Two HTTP-like transports on one path would silently shadow."""
        app = web.Application()
        mcp = make_parrot_server(["http", "sse"])
        with pytest.raises(ValueError, match="base_path"):
            await mcp.on_startup(app)
        await mcp.on_shutdown(app)

    async def test_streamable_and_http_collide_too(self):
        app = web.Application()
        mcp = make_parrot_server(["http", "streamable-http"])
        with pytest.raises(ValueError, match="TransportConfig"):
            await mcp.on_startup(app)
        await mcp.on_shutdown(app)

    async def test_distinct_base_paths_mount_side_by_side(self):
        app = web.Application()
        mcp = make_parrot_server(
            {
                "http": TransportConfig(
                    transport="http", host="127.0.0.1", port=0
                ),
                "streamable-http": TransportConfig(
                    transport="streamable-http",
                    host="127.0.0.1",
                    port=0,
                    base_path="/mcp/stream",
                ),
            }
        )
        await mcp.on_startup(app)
        try:
            assert set(mcp.servers) == {"http", "streamable-http"}
            test_server = TestServer(app)
            await test_server.start_server()
            client = test_server.make_url("")
            assert client is not None

            body = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0"},
                },
            }
            import aiohttp

            async with aiohttp.ClientSession() as http:
                async with http.post(
                    str(test_server.make_url("/mcp")), json=body
                ) as plain:
                    assert plain.status == 200
                    # The plain http transport mints no session id.
                    assert plain.headers.get("Mcp-Session-Id") is None

                async with http.post(
                    str(test_server.make_url("/mcp/stream")), json=body
                ) as stream:
                    assert stream.status == 200
                    assert stream.headers.get("Mcp-Session-Id")

            await test_server.close()
        finally:
            await mcp.on_shutdown(app)


class FakeSseResponse:
    """Minimal stand-in for an aiohttp response carrying an SSE body."""

    def __init__(self, body: str):
        self._lines = [
            (line + "\n").encode("utf-8") for line in body.split("\n")
        ]

    @property
    def content(self):
        async def _iter():
            for line in self._lines:
                yield line

        return _iter()


class TestClientSseParsing:
    def make_session(self):
        return HttpMCPSession(
            MCPClientConfig(name="c", url="http://x/mcp", transport="http"),
            logging.getLogger("test-mcp-client"),
        )

    async def test_reads_a_batched_sse_payload(self):
        """One `data:` field may carry a batch of JSON-RPC responses."""
        session = self.make_session()
        body = (
            'id: s:1\n'
            'event: message\n'
            'data: [{"jsonrpc":"2.0","id":1,"result":{"a":1}},'
            '{"jsonrpc":"2.0","id":2,"result":{"b":2}}]\n'
            '\n'
        )
        message = await session._read_sse_response(FakeSseResponse(body), 2)
        assert message["result"] == {"b": 2}

    async def test_skips_comments_and_unrelated_messages(self):
        session = self.make_session()
        body = (
            ': keep-alive\n'
            '\n'
            'id: s:1\n'
            'event: message\n'
            'data: {"jsonrpc":"2.0","method":"notifications/progress"}\n'
            '\n'
            'id: s:2\n'
            'event: message\n'
            'data: {"jsonrpc":"2.0","id":9,"result":{"ok":true}}\n'
            '\n'
        )
        message = await session._read_sse_response(FakeSseResponse(body), 9)
        assert message["result"] == {"ok": True}

    async def test_stream_ending_without_the_response_raises(self):
        from parrot.mcp.client import MCPConnectionError

        session = self.make_session()
        body = (
            'id: s:1\n'
            'event: message\n'
            'data: {"jsonrpc":"2.0","id":1,"result":{}}\n'
            '\n'
        )
        with pytest.raises(MCPConnectionError, match="ended without"):
            await session._read_sse_response(FakeSseResponse(body), 42)


class TestStartupValidation:
    async def test_conflict_is_caught_before_anything_starts(self):
        """A misconfiguration must not leave half the transports mounted."""
        app = web.Application()
        mcp = make_parrot_server(["http", "sse"])
        with pytest.raises(ValueError, match="base_path"):
            await mcp.on_startup(app)
        assert mcp.servers == {}, "no transport may be left running"
        assert not [r for r in app.router.routes()], "no routes registered"
