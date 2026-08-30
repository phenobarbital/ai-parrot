"""Interop test: official MCP SDK Streamable HTTP client vs our server.

This is the definitive Claude.ai-compatibility check — the SDK client
(`mcp.client.streamable_http.streamablehttp_client`) speaks the same
transport family Claude Web custom connectors use: it sends
``Accept: application/json, text/event-stream``, echoes ``Mcp-Session-Id``
and ``MCP-Protocol-Version``, and negotiates the protocol revision.

Gated behind the ``mcp`` extra (mirrors the ``requires_aioquic`` pattern):
run with ``uv run --extra mcp pytest ...`` or after ``uv pip install mcp``.
"""
import asyncio

import pytest
from aiohttp import web
from parrot.tools.abstract import AbstractTool
from pydantic import BaseModel, Field

from parrot.mcp.config import MCPServerConfig
from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer

pytest.importorskip("mcp", reason="requires the mcp extra")
pytestmark = pytest.mark.requires_mcp_sdk

from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402


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
async def server_url():
    config = MCPServerConfig(
        name="interop-streamable",
        transport="streamable-http",
        host="127.0.0.1",
        port=0,
    )
    # Mount through start() on a shared app, the way ParrotMCPServer does,
    # so the interop check covers the real route-mounting path too.
    app = web.Application()
    server = StreamableHttpMCPServer(config, parent_app=app)
    server.register_tool(EchoTool())
    await server.start()

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    yield f"http://127.0.0.1:{port}/mcp"
    await server.stop()
    await runner.cleanup()


async def test_official_sdk_client_roundtrip(server_url):
    async with (
        streamablehttp_client(server_url) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        init = await asyncio.wait_for(session.initialize(), timeout=10)
        assert init.serverInfo.name == "interop-streamable"

        tools = await asyncio.wait_for(session.list_tools(), timeout=10)
        assert any(t.name == "echo" for t in tools.tools)

        result = await asyncio.wait_for(
            session.call_tool("echo", {"text": "interop"}), timeout=10
        )
        assert any("interop" in c.text for c in result.content)
