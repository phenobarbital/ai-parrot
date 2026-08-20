"""Regression tests for the UDS stream-size limit.

`AgentDaemonClient.connect()` used to call `asyncio.open_unix_connection()`
without a `limit`, so the StreamReader kept asyncio's 64 KiB default while
the server happily wrote up to `max_line_bytes` (10 MB). Any reply above
64 KiB then made `readuntil(b"\\n")` raise `LimitOverrunError`, killing the
reader task and surfacing on every pending call as
`ConnectionClosed: Connection closed by daemon` -- with the daemon in fact
having answered correctly.

These tests drive a real Unix socket end to end, because the bug lives
precisely in the stream plumbing that a mocked reader/writer would hide.
"""
import asyncio

import pytest

from parrot.integrations.agentd.client import AgentDaemonClient
from parrot.integrations.agentd.protocol import DEFAULT_MAX_LINE_BYTES
from parrot.integrations.agentd.server import JsonRpcUnixServer

#: Comfortably past asyncio's 64 KiB StreamReader default, and in the size
#: range a real agent reply with a structured artifact reaches.
_BIG = 200_000


@pytest.fixture
async def echo_server(tmp_path):
    """A server whose one method echoes back a payload of a requested size."""

    async def big(_session, params):
        return {"blob": "x" * int(params["size"])}

    server = JsonRpcUnixServer(tmp_path / "test.sock", {"big": big})
    await server.start()
    try:
        yield server
    finally:
        await server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [1_000, _BIG])
async def test_replies_survive_the_64kib_stream_default(echo_server, size):
    """A reply larger than 64 KiB must arrive, not close the connection."""
    client = await AgentDaemonClient.connect(echo_server.socket_path)
    try:
        result = await client.call("big", params={"size": size})
    finally:
        await client.close()
    assert len(result["blob"]) == size


@pytest.mark.asyncio
async def test_client_limit_matches_the_protocol_default(echo_server):
    """The client's reader limit is the protocol's, not asyncio's 64 KiB."""
    client = await AgentDaemonClient.connect(echo_server.socket_path)
    try:
        # ``_limit`` is asyncio's own attribute on StreamReader; asserting it
        # pins the contract that made the bug possible in the first place.
        assert client._reader._limit == DEFAULT_MAX_LINE_BYTES
        assert client._reader._limit > asyncio.streams._DEFAULT_LIMIT
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_server_accepts_requests_over_64kib(echo_server):
    """The same limit applies to inbound requests, not just replies."""
    client = await AgentDaemonClient.connect(echo_server.socket_path)
    try:
        # Round-trips a request whose own line is well over 64 KiB.
        result = await client.call("big", params={"size": 1, "pad": "y" * _BIG})
    finally:
        await client.close()
    assert result["blob"] == "x"
