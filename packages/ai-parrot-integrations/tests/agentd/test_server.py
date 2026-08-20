"""Unit tests for parrot.integrations.agentd.server (TASK-2211).

Uses real temporary Unix domain sockets with a toy dispatch table — no
agent, no client module (TASK-2213 is out of scope here); test clients
talk raw NDJSON over `asyncio.open_unix_connection`.
"""

from __future__ import annotations

import asyncio
import json
import socket
import stat

import pytest
from parrot.integrations.agentd.protocol import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
)
from parrot.integrations.agentd.server import (
    DaemonAlreadyRunning,
    JsonRpcUnixServer,
)


async def _send_request(writer: asyncio.StreamWriter, *, id_, method, params=None) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": id_,
        "method": method,
        "params": params or {},
    }
    writer.write((json.dumps(payload) + "\n").encode("utf-8"))
    await writer.drain()


async def _recv_line(reader: asyncio.StreamReader) -> dict:
    line = await asyncio.wait_for(reader.readuntil(b"\n"), timeout=5)
    return json.loads(line.decode("utf-8"))


async def _ping_handler(session, params):
    return {"pong": True, "echo": params}


async def _boom_handler(session, params):
    raise RuntimeError("boom")


@pytest.fixture
async def server(tmp_path):
    socket_path = tmp_path / "agentd.sock"
    srv = JsonRpcUnixServer(
        socket_path,
        dispatch={"ping": _ping_handler, "boom": _boom_handler},
    )
    await srv.start()
    yield srv
    await srv.close()


class TestServer:
    async def test_roundtrip(self, server):
        reader, writer = await asyncio.open_unix_connection(
            path=str(server.socket_path)
        )
        try:
            await _send_request(writer, id_=1, method="ping", params={"x": 1})
            response = await _recv_line(reader)
        finally:
            writer.close()

        assert response["id"] == 1
        assert response["result"] == {"pong": True, "echo": {"x": 1}}
        assert response.get("error") is None

    async def test_large_request_roundtrip(self, server):
        """Regression: requests larger than asyncio's 64 KiB StreamReader
        default must reach the handler — the server must size its reader to
        `max_line_bytes` (10 MB), not the asyncio default."""
        big_payload = "x" * (128 * 1024)  # > 64 KiB StreamReader default
        reader, writer = await asyncio.open_unix_connection(
            path=str(server.socket_path), limit=server.max_line_bytes
        )
        try:
            await _send_request(
                writer, id_=10, method="ping", params={"blob": big_payload}
            )
            response = await _recv_line(reader)
        finally:
            writer.close()

        assert response["id"] == 10
        assert response["result"] == {"pong": True, "echo": {"blob": big_payload}}

    async def test_unknown_method_32601(self, server):
        reader, writer = await asyncio.open_unix_connection(
            path=str(server.socket_path)
        )
        try:
            await _send_request(writer, id_=2, method="does.not.exist")
            response = await _recv_line(reader)
        finally:
            writer.close()

        assert response["id"] == 2
        assert response["error"]["code"] == METHOD_NOT_FOUND

    async def test_handler_exception_isolated(self, server):
        reader, writer = await asyncio.open_unix_connection(
            path=str(server.socket_path)
        )
        try:
            await _send_request(writer, id_=3, method="boom")
            error_response = await _recv_line(reader)

            # Server (and this same connection) must still be alive.
            await _send_request(writer, id_=4, method="ping")
            ok_response = await _recv_line(reader)
        finally:
            writer.close()

        assert error_response["id"] == 3
        assert error_response["error"]["code"] == INTERNAL_ERROR
        assert "boom" in error_response["error"]["message"]

        assert ok_response["id"] == 4
        assert ok_response["result"]["pong"] is True

    async def test_stale_socket_reboot(self, tmp_path):
        socket_path = tmp_path / "stale.sock"

        # Simulate a dead socket: bind a raw socket and close it without
        # unlinking the path, leaving the file present but unconnectable.
        raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        raw.bind(str(socket_path))
        raw.close()
        assert socket_path.exists()

        srv = JsonRpcUnixServer(socket_path, dispatch={})
        await srv.start()
        try:
            assert socket_path.exists()
        finally:
            await srv.close()

    async def test_live_socket_refuses(self, server):
        second = JsonRpcUnixServer(server.socket_path, dispatch={})

        with pytest.raises(DaemonAlreadyRunning):
            await second.start()

    async def test_permissions(self, server):
        parent_mode = stat.S_IMODE(server.socket_path.parent.stat().st_mode)
        socket_mode = stat.S_IMODE(server.socket_path.stat().st_mode)

        assert parent_mode == 0o700
        assert socket_mode == 0o600

    async def test_event_broker_fanout(self, tmp_path):
        socket_path = tmp_path / "broker.sock"
        dispatch: dict = {}
        srv = JsonRpcUnixServer(socket_path, dispatch=dispatch)

        async def _subscribe(session, params):
            srv.event_broker.subscribe(session)
            return {"subscribed": True}

        dispatch["events.subscribe"] = _subscribe

        await srv.start()
        try:
            reader1, writer1 = await asyncio.open_unix_connection(
                path=str(socket_path)
            )
            reader2, writer2 = await asyncio.open_unix_connection(
                path=str(socket_path)
            )

            await _send_request(writer1, id_=1, method="events.subscribe")
            await _recv_line(reader1)  # ack
            await _send_request(writer2, id_=1, method="events.subscribe")
            await _recv_line(reader2)  # ack

            await srv.event_broker.publish("event.job_executed", {"job_id": "j1"})

            note1 = await _recv_line(reader1)
            note2 = await _recv_line(reader2)
            assert note1["method"] == "event.job_executed"
            assert note2["method"] == "event.job_executed"

            # Disconnect subscriber 1; give the server's read loop a tick to
            # process the EOF and unsubscribe it via _disconnect().
            writer1.close()
            await asyncio.sleep(0.05)

            await srv.event_broker.publish("event.job_executed", {"job_id": "j2"})
            note2_again = await _recv_line(reader2)
            assert note2_again["params"]["job_id"] == "j2"

            writer2.close()
        finally:
            await srv.close()
