"""SSE tool_event frames are emitted per request and never leak across requests (FEAT-573 TASK-3409)."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, List

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from parrot.handlers.stream import StreamHandler
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage
from parrot.tools.abstract import AbstractTool, ToolResult

pytestmark = pytest.mark.asyncio


class _OkTool(AbstractTool):
    async def _execute(self, **kwargs) -> ToolResult:
        await asyncio.sleep(0.01)
        return ToolResult(status="success", result="ok")


class _FakeBot:
    """ask_stream: delta, tool execution (emits Before/After), delta, final AIMessage."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def ask_stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[Any]:
        yield "Hel"
        await _OkTool(name=f"tool-{self.name}").execute()
        # Simulate the LLM round-trip latency that always separates a tool
        # result from the model's next tokens in production — real enough
        # for the event loop to flush the AfterToolCallEvent's fire-and-forget
        # forward-to-global task (created by AbstractTool.execute()) before
        # the next delta is produced.
        await asyncio.sleep(0.01)
        yield "lo"
        yield AIMessage(
            input=prompt,
            output="Hello",
            model="m",
            provider="p",
            usage=CompletionUsage(),
        )


class _TextOnlyBot:
    """ask_stream: delta, delta, final AIMessage — no tool activity at all."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def ask_stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[Any]:
        yield "Hel"
        yield "lo"
        yield AIMessage(
            input=prompt,
            output="Hello",
            model="m",
            provider="p",
            usage=CompletionUsage(),
        )


class _BotManager:
    def __init__(self, bots: dict) -> None:
        self._bots = bots

    async def get_bot(self, bot_id: str) -> Any:
        return self._bots.get(bot_id)


def _parse_frames(body: str) -> List[Any]:
    """Return the decoded `data:` payloads in order ('[DONE]' kept as a string)."""
    out: List[Any] = []
    for block in body.split("\n\n"):
        if block.startswith("data: "):
            payload = block[6:]
            out.append(payload if payload == "[DONE]" else json.loads(payload))
    return out


@pytest.fixture
async def client():
    app = web.Application()
    app["bot_manager"] = _BotManager(
        {
            "a": _FakeBot("a"),
            "b": _FakeBot("b"),
            "text-only": _TextOnlyBot("text-only"),
        }
    )
    handler = StreamHandler()
    handler.configure_routes(app)  # verified: stream.py registers POST /bots/{bot_id}/stream/sse
    async with TestClient(TestServer(app)) as c:
        yield c


class TestToolEventFrames:
    async def test_frame_order_with_tool(self, client):
        resp = await client.post("/bots/a/stream/sse", json={"prompt": "hi"})
        frames = _parse_frames(await resp.text())

        assert frames[0] == {"content": "Hel"}

        started = frames[1]
        assert started["type"] == "tool_event"
        assert started["data"]["event"] == "started"
        assert started["data"]["tool_name"] == "tool-a"

        finished = frames[2]
        assert finished["type"] == "tool_event"
        assert finished["data"]["event"] == "finished"
        assert finished["data"]["tool_name"] == "tool-a"
        assert finished["data"]["call_id"] == started["data"]["call_id"]

        assert frames[3] == {"content": "lo"}

        ai_message_frame = frames[4]
        assert ai_message_frame["type"] == "ai_message"

        assert frames[5] == "[DONE]"

    async def test_two_concurrent_requests_do_not_leak(self, client):
        ra, rb = await asyncio.gather(
            client.post("/bots/a/stream/sse", json={"prompt": "hi"}),
            client.post("/bots/b/stream/sse", json={"prompt": "hi"}),
        )
        frames_a = _parse_frames(await ra.text())
        frames_b = _parse_frames(await rb.text())

        tool_events_a = [f for f in frames_a if isinstance(f, dict) and f.get("type") == "tool_event"]
        tool_events_b = [f for f in frames_b if isinstance(f, dict) and f.get("type") == "tool_event"]

        assert len(tool_events_a) == 2  # started + finished
        assert len(tool_events_b) == 2
        assert all(e["data"]["tool_name"] == "tool-a" for e in tool_events_a)
        assert all(e["data"]["tool_name"] == "tool-b" for e in tool_events_b)

    async def test_text_only_bot_unchanged(self, client):
        resp = await client.post("/bots/text-only/stream/sse", json={"prompt": "hi"})
        frames = _parse_frames(await resp.text())

        assert frames == [
            {"content": "Hel"},
            {"content": "lo"},
            frames[2],
            "[DONE]",
        ]
        assert frames[2]["type"] == "ai_message"
        assert not any(isinstance(f, dict) and f.get("type") == "tool_event" for f in frames)
