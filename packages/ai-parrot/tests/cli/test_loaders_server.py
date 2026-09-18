"""Tests for the canonical-route server proxy (FEAT-573 TASK-3408, spec §3 M9)."""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from parrot.cli.events import ToolFinished, ToolStarted  # provided by TASK-3403
from parrot.cli.loaders import AgentLoadError, ServerAgentProxy, _ServerBotProxy, _iter_sse

TOOL_FRAMES: List[Dict[str, Any]] = [
    {"content": "Hel"},
    {
        "type": "tool_event",
        "data": {"event": "started", "call_id": "span-1", "tool_name": "MathTool", "args_summary": {"x": 1}},
    },
    {
        "type": "tool_event",
        "data": {
            "event": "finished",
            "call_id": "span-1",
            "tool_name": "MathTool",
            "duration_ms": 3.5,
            "result_status": "success",
            "result_size_bytes": 2,
        },
    },
    {"content": "lo"},
    {
        "type": "ai_message",
        "data": {
            "output": "Hello",
            "response": "Hello",
            "tool_calls": [{"id": "1", "name": "MathTool", "arguments": {"x": 1}, "result": "2", "error": None}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        },
    },
]

NO_TOOL_FRAMES: List[Dict[str, Any]] = [
    {"content": "Hi"},
    {"content": "!"},
    {"type": "ai_message", "data": {"output": "Hi!", "response": "Hi!"}},
]


def _make_app(frames: List[Dict[str, Any]], seen: Dict[str, Any]) -> web.Application:
    """Minimal fake server exposing the four canonical routes and recording requests."""

    async def bots(request: web.Request) -> web.Response:
        seen["auth"] = request.headers.get("Authorization")
        return web.json_response({"agents": [{"name": "alpha", "tags": ["x"]}], "total": 1})

    async def chatbot_info(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        return (
            web.json_response({"chatbot": name}) if name == "alpha" else web.json_response({"error": "nf"}, status=404)
        )

    async def talk(request: web.Request) -> web.Response:
        seen["ask_body"] = await request.json()
        return web.json_response({"output": "pong", "response": "pong"})

    async def sse(request: web.Request) -> web.StreamResponse:
        seen["sse_body"] = await request.json()
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        for frame in frames:
            await resp.write(f"data: {json.dumps(frame)}\n\n".encode())
        await resp.write(b"data: [DONE]\n\n")
        await resp.write_eof()
        return resp

    app = web.Application()
    app.router.add_get("/api/v1/bots", bots)
    app.router.add_get("/api/v1/chatbots/{name}", chatbot_info)
    app.router.add_post("/api/v1/agents/chat/{agent_id}", talk)
    app.router.add_post("/bots/{bot_id}/stream/sse", sse)
    return app


async def _make_error_app() -> web.Application:
    """Fake server whose SSE endpoint immediately writes an ``error:`` line."""

    async def sse(request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        await resp.write(b"error: boom\n\n")
        await resp.write_eof()
        return resp

    app = web.Application()
    app.router.add_post("/bots/{bot_id}/stream/sse", sse)
    return app


@pytest.fixture
async def server_env():
    seen: Dict[str, Any] = {}
    server = TestServer(_make_app(TOOL_FRAMES, seen))
    await server.start_server()
    yield server, seen
    await server.close()


class TestServerProxyRoutes:
    async def test_list_load_and_token(self, server_env):
        server, seen = server_env
        proxy = ServerAgentProxy(str(server.make_url("")), token="secret")
        agents = await proxy.list_agents()
        assert agents == [{"name": "alpha", "tags": ["x"]}]
        assert seen["auth"] == "Bearer secret"

        bot = await proxy.load("alpha")
        assert isinstance(bot, _ServerBotProxy)

        with pytest.raises(AgentLoadError):
            await proxy.load("zeta")

        await proxy.close()

    async def test_ask_never_sends_user_id(self, server_env):
        server, seen = server_env
        proxy = ServerAgentProxy(str(server.make_url("")))
        bot = await proxy.load("alpha")
        response = await bot.ask("hi", session_id="s", user_id="ignored")
        assert response.output == "pong"
        assert "user_id" not in seen["ask_body"]
        assert seen["ask_body"]["query"] == "hi"
        await proxy.close()

    async def test_ask_stream_parses_text_tool_and_final(self, server_env):
        server, seen = server_env
        proxy = ServerAgentProxy(str(server.make_url("")))
        bot = await proxy.load("alpha")
        items = [item async for item in bot.ask_stream("hi")]

        assert items[0] == "Hel"
        assert isinstance(items[1], ToolStarted)
        assert items[1].call_id == "span-1"
        assert isinstance(items[2], ToolFinished)
        assert items[2].duration_ms == 3.5
        assert items[3] == "lo"

        final = items[-1]
        assert final.output == "Hello"
        assert final.tool_calls[0].name == "MathTool"
        assert final.usage.total_tokens == 5
        assert "user_id" not in seen["sse_body"]
        await proxy.close()

    async def test_ask_stream_older_server_without_tool_frames(self):
        seen: Dict[str, Any] = {}
        server = TestServer(_make_app(NO_TOOL_FRAMES, seen))
        await server.start_server()
        try:
            proxy = ServerAgentProxy(str(server.make_url("")))
            bot = await proxy.load("alpha")
            items = [item async for item in bot.ask_stream("hi")]
            assert items[0] == "Hi"
            assert items[1] == "!"
            final = items[-1]
            assert final.output == "Hi!"
            await proxy.close()
        finally:
            await server.close()

    async def test_error_line_raises(self):
        server = TestServer(await _make_error_app())
        await server.start_server()
        try:
            proxy = ServerAgentProxy(str(server.make_url("")))
            bot = _ServerBotProxy("alpha", str(server.make_url("")), proxy._get_session())
            with pytest.raises(AgentLoadError):
                async for _ in bot.ask_stream("hi"):
                    pass
            await proxy.close()
        finally:
            await server.close()

    def test_no_phantom_routes_left(self):
        import inspect

        import parrot.cli.loaders as mod

        assert "/api/agent" not in inspect.getsource(mod)  # AC16


class TestIterSSE:
    async def test_iter_sse_ignores_comments_and_unknown_fields(self):
        """`_iter_sse` should join `data:` lines and ignore comment/other fields."""

        class _FakeContent:
            def __init__(self, lines: List[bytes]) -> None:
                self._lines = lines

            def __aiter__(self):
                return self

            async def __anext__(self) -> bytes:
                if not self._lines:
                    raise StopAsyncIteration
                return self._lines.pop(0)

        class _FakeResp:
            def __init__(self, lines: List[bytes]) -> None:
                self.content = _FakeContent(lines)

        lines = [
            b": this is a comment\n",
            b"event: message\n",
            b'data: {"content": "a"}\n',
            b'data: {"content": "b"}\n',
            b"\n",
            b"data: [DONE]\n",
            b"\n",
        ]
        events = [event async for event in _iter_sse(_FakeResp(lines))]
        assert events == ['{"content": "a"}\n{"content": "b"}', "[DONE]"]
