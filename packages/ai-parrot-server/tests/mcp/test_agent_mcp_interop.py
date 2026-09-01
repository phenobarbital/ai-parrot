"""Interop test: official MCP SDK client vs an agent-mounted endpoint.

FEAT-477 TASK-2610. Mirrors `test_streamable_http_interop.py`'s pattern for
the tool-level server, but drives `AgentMCPMount`'s per-agent endpoint —
the exact transport family (and session/SSE semantics) Claude Web custom
connectors and Claude Code use against `/mcp/agents/{name}`.

Gated behind the ``mcp`` extra (``requires_mcp_sdk``, already registered by
PR #1274 — do NOT re-add the marker). Run with
``uv run --extra mcp pytest ...`` or after ``uv pip install mcp``.
"""

import asyncio

import pytest
from aiohttp import web
from parrot.mcp.agent_mount import AgentMCPMount
from parrot.mcp.agent_tools import mcp_tool
from parrot.mcp.config import AgentMCPMountConfig, AuthMethod, MCPServerConfig
from parrot.mcp.oauth_server import APIKeyStore
from pydantic import BaseModel, Field

pytest.importorskip("mcp", reason="requires the mcp extra")
pytestmark = pytest.mark.requires_mcp_sdk

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class ForecastInput(BaseModel):
    q: str = Field(..., description="Forecast query")


class ForecastOutput(BaseModel):
    forecast: str


class _FakeToolManager:
    def list_tools(self) -> list[str]:
        return []

    def get_tool(self, name: str):
        return None


class _FinanceAgent:
    name = "finance"

    def __init__(self):
        self.tool_manager = _FakeToolManager()

    @mcp_tool(
        name="forecast",
        description="Forecast a value",
        args_schema=ForecastInput,
        returns=ForecastOutput,
        scope="finance:read",
    )
    async def forecast(self, q: str) -> dict:
        return {"forecast": f"{q}-forecast"}


class _FakeBotManager:
    def __init__(self, bots: dict):
        self._bots = bots

    def get_bots(self) -> dict:
        return dict(self._bots)


async def _allow_all(pctx, resource: str, required_permissions) -> bool:
    return True


@pytest.fixture
async def agent_endpoint_url():
    api_key_store = APIKeyStore()
    record = api_key_store.issue_key(user_id="dev-user")

    auth_template = MCPServerConfig(auth_method=AuthMethod.API_KEY, api_key_store=api_key_store)
    bot_manager = _FakeBotManager({"finance": _FinanceAgent()})
    cfg = AgentMCPMountConfig(
        agents=["finance"],
        resource_server_url="https://h/mcp/agents/finance",
        default_tenant_id="acme",
    )
    mount = AgentMCPMount(bot_manager, cfg, pbac_resolver=_allow_all, auth_template=auth_template)
    app = web.Application()
    mount.setup(app)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    yield f"http://127.0.0.1:{port}/mcp/agents/finance", record.key
    await runner.cleanup()


async def test_mcp_sdk_interop(agent_endpoint_url):
    """Drive the agent endpoint with the reference MCP client."""
    url, api_key = agent_endpoint_url
    async with (
        streamablehttp_client(url, headers={"X-API-Key": api_key}) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        init = await asyncio.wait_for(session.initialize(), timeout=10)
        assert init.serverInfo is not None

        tools = await asyncio.wait_for(session.list_tools(), timeout=10)
        assert any(t.name == "forecast" for t in tools.tools)

        result = await asyncio.wait_for(session.call_tool("forecast", {"q": "revenue"}), timeout=10)
        assert not result.isError
