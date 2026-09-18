"""Real StreamHandler ↔ rewritten ServerAgentProxy round-trip (FEAT-573 TASK-3416, spec §4 row 3)."""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from parrot.cli.events import ToolFinished, ToolStarted
from parrot.cli.loaders import ServerAgentProxy
from parrot.handlers.stream import StreamHandler
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage
from parrot.tools.abstract import AbstractTool, ToolResult


class _OkTool(AbstractTool):
    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", result="ok")


class _FakeBot:
    name = "alpha"

    async def ask_stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[Any]:
        yield "Hel"
        await _OkTool(name="MathTool").execute()
        # Give the loop a chance to flush AfterToolCallEvent's fire-and-forget
        # forward-to-global task before the next delta (pattern: TASK-3409
        # test_stream_tool_events.py:36-41).
        await asyncio.sleep(0.01)
        yield "lo"
        yield AIMessage(input=prompt, output="Hello", model="m", provider="p", usage=CompletionUsage())


class _BotManager:
    async def get_bot(self, bot_id: str) -> Any:
        return _FakeBot() if bot_id == "alpha" else None


@pytest.fixture
async def server():
    app = web.Application()
    app["bot_manager"] = _BotManager()
    StreamHandler().configure_routes(app)
    app.router.add_get(
        "/api/v1/bots", lambda r: web.json_response({"agents": [{"name": "alpha", "tags": []}], "total": 1})
    )
    app.router.add_get("/api/v1/chatbots/{name}", lambda r: web.json_response({"chatbot": r.match_info["name"]}))
    srv = TestServer(app)
    await srv.start_server()
    yield srv
    await srv.close()


async def test_server_mode_end_to_end(server):
    proxy = ServerAgentProxy(str(server.make_url("")), token="t")
    try:
        assert [a["name"] for a in await proxy.list_agents()] == ["alpha"]
        bot = await proxy.load("alpha")
        items = [item async for item in bot.ask_stream("hi", session_id="s")]

        deltas = [item for item in items if isinstance(item, str)]
        started = [item for item in items if isinstance(item, ToolStarted)]
        finished = [item for item in items if isinstance(item, ToolFinished)]
        finals = [item for item in items if not isinstance(item, (str, ToolStarted, ToolFinished))]

        assert deltas == ["Hel", "lo"]
        assert len(started) == 1 and len(finished) == 1
        assert started[0].call_id == finished[0].call_id
        assert started[0].tool_name == "MathTool"
        assert finished[0].tool_name == "MathTool"
        assert len(finals) == 1
        assert finals[0].output == "Hello"
    finally:
        await proxy.close()
