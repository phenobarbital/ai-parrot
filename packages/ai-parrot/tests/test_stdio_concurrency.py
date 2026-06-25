"""Regression test for the stdio MCP transport concurrency bug.

When several tool calls share a single ``StdioMCPSession`` (as the agent
loop does when the LLM emits parallel tool calls), two coroutines used to
call ``readline()`` on the same stdout ``StreamReader`` at once, which
asyncio rejects with::

    readuntil() called while another coroutine is already waiting for
    incoming data

``StdioMCPSession`` now serializes the request/response cycle with an
``asyncio.Lock``; this test drives two concurrent requests over a real
``StreamReader`` and asserts both complete cleanly.
"""
import asyncio
import json
import logging

import pytest

from parrot.mcp.transports.stdio import StdioMCPSession


class _FakeStdin:
    """Captures requests and lets a fake server answer them out of band."""

    def __init__(self, reader: asyncio.StreamReader):
        self._reader = reader
        self.requests: list[dict] = []

    def write(self, data: bytes) -> None:
        request = json.loads(data.decode("utf-8"))
        self.requests.append(request)

    async def drain(self) -> None:
        # Answer the just-written request. A tiny yield maximises the chance
        # that the two coroutines interleave their read phase.
        await asyncio.sleep(0)
        request = self.requests[-1]
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"echo": request["method"]},
        }
        self._reader.feed_data((json.dumps(response) + "\n").encode("utf-8"))


def _make_session() -> StdioMCPSession:
    config = type(
        "Cfg", (), {"name": "fake", "timeout": 5.0}
    )()
    session = StdioMCPSession(config, logging.getLogger("test.stdio"))
    reader = asyncio.StreamReader()
    session._stdout = reader
    session._stdin = _FakeStdin(reader)
    session._process = type("Proc", (), {"returncode": None})()
    session._initialized = True
    return session


@pytest.mark.asyncio
async def test_concurrent_send_request_does_not_collide():
    session = _make_session()

    results = await asyncio.gather(
        session._send_request("alpha"),
        session._send_request("beta"),
    )

    echoed = sorted(r["echo"] for r in results)
    assert echoed == ["alpha", "beta"]
