"""`StdioMCPServer` request concurrency and host-side cancellation.

Before this change the server awaited every request inline in its read loop,
so one slow ``tools/call`` (a merge, a 300 s ``coder_wait``) delayed every
call queued behind it — read-only ones included — until the MCP host's idle
timeout (30 minutes by default) killed them one by one.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any, Iterator

import pytest
from pydantic import BaseModel, Field

from parrot.mcp.local_server import StdioMCPServer
from parrot.mcp.server_base import LocalServerConfig
from parrot.tools.abstract import AbstractTool


class SleepInput(BaseModel):
    seconds: float = Field(..., description="How long to sleep")
    label: str = Field(default="", description="Echoed back")


class SleepTool(AbstractTool):
    """Sleep, then echo the label."""

    name = "sleep"
    description = "Sleep then echo"
    args_schema = SleepInput

    async def _execute(self, seconds: float, label: str = "") -> str:
        await asyncio.sleep(seconds)
        return label


class _FakeStdin:
    """Feeds scripted lines, then EOF, to the server's blocking ``readline``."""

    def __init__(self, lines: list[str]) -> None:
        self._lines: Iterator[str] = iter(lines)

    def readline(self) -> str:
        return next(self._lines, "")


def _rpc(method: str, request_id: Any = None, **params: Any) -> str:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
    if request_id is not None:
        msg["id"] = request_id
    return json.dumps(msg) + "\n"


def _call(request_id: int, **arguments: Any) -> str:
    return _rpc("tools/call", request_id, name="sleep", arguments=arguments)


async def _serve(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], lines: list[str]) -> list[dict]:
    server = StdioMCPServer(LocalServerConfig(name="test"))
    server.register_tool(SleepTool())
    monkeypatch.setattr(sys, "stdin", _FakeStdin(lines))
    await server.start()
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


@pytest.mark.asyncio
async def test_fast_call_is_not_queued_behind_a_slow_one(monkeypatch, capsys) -> None:
    lines = [_call(1, seconds=0.6, label="slow"), _call(2, seconds=0.0, label="fast")]
    t0 = time.monotonic()
    responses = await _serve(monkeypatch, capsys, lines)
    elapsed = time.monotonic() - t0

    assert [r["id"] for r in responses] == [2, 1], "responses arrive in completion order, not arrival order"
    assert responses[0]["result"]["content"][0]["text"] == "fast"
    assert elapsed < 2.0


@pytest.mark.asyncio
async def test_host_cancellation_frees_the_handler(monkeypatch, capsys) -> None:
    lines = [
        _call(5, seconds=30.0, label="stuck"),
        _rpc("notifications/cancelled", requestId=5, reason="idle timeout"),
    ]
    t0 = time.monotonic()
    responses = await _serve(monkeypatch, capsys, lines)
    elapsed = time.monotonic() - t0

    assert responses == [], "a cancelled request gets no response"
    assert elapsed < 5.0, "the cancelled handler must not run to completion"


@pytest.mark.asyncio
async def test_cancellation_for_unknown_request_is_ignored(monkeypatch, capsys) -> None:
    lines = [_rpc("notifications/cancelled", requestId=999), _call(1, seconds=0.0, label="ok")]
    responses = await _serve(monkeypatch, capsys, lines)
    assert [r["id"] for r in responses] == [1]


@pytest.mark.asyncio
async def test_ping_and_unknown_notifications(monkeypatch, capsys) -> None:
    lines = [_rpc("ping", 7), _rpc("notifications/roots/list_changed")]
    responses = await _serve(monkeypatch, capsys, lines)
    assert responses == [{"jsonrpc": "2.0", "id": 7, "result": {}}]


@pytest.mark.asyncio
async def test_drain_cancels_calls_still_running_after_grace(monkeypatch, capsys) -> None:
    server = StdioMCPServer(LocalServerConfig(name="test"))
    server.drain_timeout_s = 0.2
    server.register_tool(SleepTool())
    monkeypatch.setattr(sys, "stdin", _FakeStdin([_call(1, seconds=30.0, label="never")]))
    t0 = time.monotonic()
    await server.start()
    assert time.monotonic() - t0 < 5.0
    assert capsys.readouterr().out == ""
    assert not server._inflight


@pytest.mark.asyncio
async def test_stop_cancels_inflight_calls() -> None:
    server = StdioMCPServer(LocalServerConfig(name="test"))
    server.register_tool(SleepTool())
    await server._admit(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "sleep", "arguments": {"seconds": 30}}}
    )
    assert len(server._inflight) == 1
    await server.stop()
    assert server._running is False
    assert not server._inflight
