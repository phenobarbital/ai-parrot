"""Unit tests for parrot.integrations.agentd.client (TASK-2213).

Uses a scripted raw asyncio UDS server replaying canned NDJSON exchanges --
deliberately NOT `JsonRpcUnixServer` (TASK-2211), so this task stays
parallel-safe against it and exercises only the client's own framing,
demux, retry, and error-mapping logic.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest
from parrot.integrations.agentd.client import (
    AgentDaemonClient,
    ConnectionClosed,
    DaemonNotRunning,
    RpcRemoteError,
)


class _Harness:
    """Scripted-server test harness.

    Attributes:
        socket_path: The UDS path the fake server is listening on.
        script: Maps an incoming request's `method` to a callable
            `(request_dict) -> list[dict] | None` producing raw NDJSON
            payloads to write back, in order (empty/None -> no reply).
        connections: Every accepted connection's `StreamWriter`, in
            acceptance order -- lets tests push notifications directly.
    """

    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.script: dict = {}
        self.connections: list[asyncio.StreamWriter] = []


@pytest.fixture
async def scripted_server(tmp_path):
    socket_path = tmp_path / "scripted.sock"
    harness = _Harness(socket_path)

    async def _handle(reader, writer):
        harness.connections.append(writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                request = json.loads(line.decode("utf-8"))
                handler = harness.script.get(request.get("method"))
                if handler is None:
                    continue
                for out in handler(request) or []:
                    writer.write((json.dumps(out) + "\n").encode("utf-8"))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    server = await asyncio.start_unix_server(_handle, path=str(socket_path))

    yield harness

    server.close()
    await server.wait_closed()


def _write_notification(writer, method, stream_id, **params):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": {"stream_id": stream_id, **params},
    }
    writer.write((json.dumps(payload) + "\n").encode("utf-8"))


class TestClient:
    async def test_call_roundtrip(self, scripted_server):
        def ping_handler(request):
            return [
                {"jsonrpc": "2.0", "id": request["id"], "result": {"pong": True}}
            ]

        scripted_server.script["ping"] = ping_handler

        client = await AgentDaemonClient.connect(scripted_server.socket_path)
        try:
            result = await client.call("ping", x=1)
        finally:
            await client.close()

        assert result == {"pong": True}

    async def test_error_mapping(self, scripted_server):
        def bad_handler(request):
            return [
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "error": {"code": -32601, "message": "nope"},
                }
            ]

        scripted_server.script["bad"] = bad_handler

        client = await AgentDaemonClient.connect(scripted_server.socket_path)
        try:
            with pytest.raises(RpcRemoteError) as excinfo:
                await client.call("bad")
        finally:
            await client.close()

        assert excinfo.value.code == -32601
        assert excinfo.value.message == "nope"

    async def test_stream_demux_interleaved(self, scripted_server):
        counter = {"n": 0}

        def chat_send_handler(request):
            counter["n"] += 1
            stream_id = f"s{counter['n']}"
            return [
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": {"stream_id": stream_id},
                }
            ]

        scripted_server.script["chat.send"] = chat_send_handler

        client = await AgentDaemonClient.connect(scripted_server.socket_path)
        try:
            agen1 = client.stream("prompt-1")
            agen2 = client.stream("prompt-2")

            # Drive both chat.send round-trips (ack); each __anext__() then
            # blocks on its own queue.get() until we push notifications.
            next1 = asyncio.ensure_future(agen1.__anext__())
            next2 = asyncio.ensure_future(agen2.__anext__())
            await asyncio.sleep(0.05)

            writer = scripted_server.connections[0]
            _write_notification(writer, "chat.delta", "s1", text="hello-1")
            _write_notification(writer, "chat.delta", "s2", text="hello-2")
            _write_notification(writer, "chat.delta", "s1", text="-more-1")
            _write_notification(
                writer, "chat.complete", "s2", response="done-2", usage={}
            )
            _write_notification(
                writer, "chat.complete", "s1", response="done-1", usage={}
            )
            await writer.drain()

            event1a = await next1
            event2a = await next2
            assert event1a.kind == "delta" and event1a.text == "hello-1"
            assert event2a.kind == "delta" and event2a.text == "hello-2"

            event1b = await agen1.__anext__()
            assert event1b.kind == "delta" and event1b.text == "-more-1"

            event1c = await agen1.__anext__()
            assert event1c.kind == "complete" and event1c.response == "done-1"

            event2b = await agen2.__anext__()
            assert event2b.kind == "complete" and event2b.response == "done-2"

            with pytest.raises(StopAsyncIteration):
                await agen1.__anext__()
            with pytest.raises(StopAsyncIteration):
                await agen2.__anext__()
        finally:
            await client.close()

    async def test_retry_then_daemon_not_running(self, tmp_path):
        socket_path = tmp_path / "nobody-here.sock"

        with pytest.raises(DaemonNotRunning) as excinfo:
            await AgentDaemonClient.connect(socket_path, retries=2, backoff=0.01)

        assert str(socket_path) in str(excinfo.value)

    async def test_close_with_pending(self, scripted_server):
        scripted_server.script["stall"] = lambda request: []  # never responds

        client = await AgentDaemonClient.connect(scripted_server.socket_path)
        call_task = asyncio.ensure_future(client.call("stall"))
        await asyncio.sleep(0.05)

        await client.close()

        with pytest.raises(ConnectionClosed):
            await call_task

    async def test_event_callback_receives_events(self, scripted_server):
        received = []

        def subscribe_handler(request):
            return [
                {"jsonrpc": "2.0", "id": request["id"], "result": {"ok": True}}
            ]

        scripted_server.script["events.subscribe"] = subscribe_handler

        client = await AgentDaemonClient.connect(scripted_server.socket_path)
        try:
            await client.subscribe_events(lambda method, params: received.append((method, params)))

            writer = scripted_server.connections[0]
            writer.write(
                (
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "method": "event.job_executed",
                            "params": {"job_id": "j1"},
                        }
                    )
                    + "\n"
                ).encode("utf-8")
            )
            await writer.drain()
            await asyncio.sleep(0.05)
        finally:
            await client.close()

        assert received == [("event.job_executed", {"job_id": "j1"})]
