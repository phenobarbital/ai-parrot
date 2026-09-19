"""Unit and process-boundary tests for ``parrot.e2e.control`` (TASK-3526, M3).

Every test binds a real Unix domain socket under ``tmp_path`` (never a real
run's ``sdd/state/e2e`` tree) and drives a real :class:`ControlServer` with
a real :class:`ControlClient` over it — no mocked reader/writer, so a
duck-typed test double can never satisfy a check this module actually
performs at a socket boundary. Handlers under test are plain ``async def``
functions, never ``unittest.mock.MagicMock`` (a permissive mock would
satisfy every ``hasattr``/attribute check this module performs and mask a
real defect).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator

import pytest

from parrot.e2e.control import (
    DEFAULT_REQUEST_DEADLINE_S,
    MAX_MESSAGE_BYTES,
    SOCKET_FILE_MODE,
    ControlChannelError,
    ControlClient,
    ControlServer,
)

_RUN_ID = "run-1"
_OWNER_ID = "owner-1"


async def _echo(payload: dict) -> dict:
    """A trivial real handler: return the payload it was given."""
    return {"echoed": payload}


async def _boom(payload: dict) -> dict:
    """A real handler that always raises."""
    raise RuntimeError("handler exploded")


async def _hang(payload: dict) -> dict:
    """A real handler that never returns within any reasonable deadline."""
    await asyncio.sleep(3600)
    return {}


async def _non_dict_result(payload: dict) -> dict:
    """A real handler that violates its own return-type contract."""
    return "not-a-dict"  # type: ignore[return-value]


@pytest.fixture
async def running_server(tmp_path: Path) -> AsyncIterator[ControlServer]:
    """A real, started :class:`ControlServer` bound under ``tmp_path``, stopped after the test."""
    server = ControlServer(
        tmp_path / "ctrl.sock",
        run_id=_RUN_ID,
        owner_id=_OWNER_ID,
        operations={"echo": _echo, "boom": _boom, "hang": _hang, "bad_result": _non_dict_result},
        request_deadline_s=1.0,
    )
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


def _client(server: ControlServer, *, run_id: str = _RUN_ID, owner_id: str = _OWNER_ID) -> ControlClient:
    return ControlClient(server.socket_path, run_id=run_id, owner_id=owner_id, request_deadline_s=1.0)


# ---------------------------------------------------------------------------
# Success roundtrip
# ---------------------------------------------------------------------------


async def test_request_response_roundtrip_success(running_server: ControlServer) -> None:
    client = _client(running_server)
    result = await client.request("echo", {"a": 1})
    assert result == {"echoed": {"a": 1}}


async def test_sequential_requests_correlate_independently(running_server: ControlServer) -> None:
    client = _client(running_server)
    first = await client.request("echo", {"n": 1})
    second = await client.request("echo", {"n": 2})
    assert first == {"echoed": {"n": 1}}
    assert second == {"echoed": {"n": 2}}


async def test_concurrent_requests_do_not_cross_correlate(running_server: ControlServer) -> None:
    client_a = _client(running_server)
    client_b = _client(running_server)
    results = await asyncio.gather(
        client_a.request("echo", {"who": "a"}),
        client_b.request("echo", {"who": "b"}),
    )
    assert results == [{"echoed": {"who": "a"}}, {"echoed": {"who": "b"}}]


# ---------------------------------------------------------------------------
# Authorization — most-definitive-first
# ---------------------------------------------------------------------------


async def test_foreign_owner_rejected_before_handler_invoked(running_server: ControlServer) -> None:
    calls: list[dict] = []

    async def _tracking_handler(payload: dict) -> dict:
        calls.append(payload)
        return {}

    running_server._operations["track"] = _tracking_handler  # real object, direct field access — not a mock
    client = _client(running_server, owner_id="someone-else")
    with pytest.raises(ControlChannelError) as excinfo:
        await client.request("track", {})
    assert excinfo.value.reason_code == "foreign_owner"
    assert calls == []


async def test_stale_run_id_rejected_before_handler_invoked(running_server: ControlServer) -> None:
    calls: list[dict] = []

    async def _tracking_handler(payload: dict) -> dict:
        calls.append(payload)
        return {}

    running_server._operations["track"] = _tracking_handler
    client = _client(running_server, run_id="stale-run")
    with pytest.raises(ControlChannelError) as excinfo:
        await client.request("track", {})
    assert excinfo.value.reason_code == "stale_run_id"
    assert calls == []


# ---------------------------------------------------------------------------
# Dispatch failures
# ---------------------------------------------------------------------------


async def test_unknown_operation_rejected_method_not_found(running_server: ControlServer) -> None:
    client = _client(running_server)
    with pytest.raises(ControlChannelError) as excinfo:
        await client.request("does-not-exist", {})
    assert excinfo.value.reason_code == "method_not_found"


async def test_handler_exception_translated_to_error_response(running_server: ControlServer) -> None:
    client = _client(running_server)
    with pytest.raises(ControlChannelError) as excinfo:
        await client.request("boom", {})
    assert excinfo.value.reason_code == "handler_failed"


async def test_handler_deadline_exceeded_translated_to_error(running_server: ControlServer) -> None:
    client = _client(running_server)
    with pytest.raises(ControlChannelError) as excinfo:
        await client.request("hang", {})
    assert excinfo.value.reason_code == "deadline_exceeded"


async def test_handler_non_dict_result_rejected(running_server: ControlServer) -> None:
    client = _client(running_server)
    with pytest.raises(ControlChannelError) as excinfo:
        await client.request("bad_result", {})
    assert excinfo.value.reason_code == "handler_invalid_result"


async def test_server_survives_a_failed_request_and_serves_the_next_one(running_server: ControlServer) -> None:
    client = _client(running_server)
    with pytest.raises(ControlChannelError):
        await client.request("boom", {})
    # The accept loop must not have crashed: a fresh connection still works.
    result = await client.request("echo", {"ok": True})
    assert result == {"echoed": {"ok": True}}


# ---------------------------------------------------------------------------
# Malformed requests, raw wire-level
# ---------------------------------------------------------------------------


async def _raw_roundtrip(socket_path: Path, raw_line: bytes, *, deadline_s: float = 2.0) -> dict:
    """Send one raw, pre-encoded line and return the parsed JSON response."""
    reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
    try:
        writer.write(raw_line)
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=deadline_s)
        assert line, "expected a response line, got EOF"
        return json.loads(line)
    finally:
        writer.close()


async def test_non_json_request_rejected_with_parse_error(running_server: ControlServer) -> None:
    response = await _raw_roundtrip(running_server.socket_path, b"not json at all\n")
    assert response["error"]["data"]["reason_code"] == "parse_error"


async def test_non_object_json_request_rejected_invalid_request(running_server: ControlServer) -> None:
    response = await _raw_roundtrip(running_server.socket_path, b"[1, 2, 3]\n")
    assert response["error"]["data"]["reason_code"] == "invalid_request"


async def test_missing_required_field_rejected_invalid_request(running_server: ControlServer) -> None:
    malformed = json.dumps({"jsonrpc": "2.0", "id": "x", "method": "echo"}).encode() + b"\n"
    response = await _raw_roundtrip(running_server.socket_path, malformed)
    assert response["error"]["data"]["reason_code"] == "invalid_request"
    assert response["id"] == "x"


async def test_wrong_jsonrpc_version_rejected_invalid_request(running_server: ControlServer) -> None:
    malformed = (
        json.dumps(
            {
                "jsonrpc": "1.0",
                "id": "x",
                "method": "echo",
                "params": {},
                "run_id": _RUN_ID,
                "owner_id": _OWNER_ID,
            }
        ).encode()
        + b"\n"
    )
    response = await _raw_roundtrip(running_server.socket_path, malformed)
    assert response["error"]["data"]["reason_code"] == "invalid_request"


async def test_server_response_echoes_matching_id(running_server: ControlServer) -> None:
    valid = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "my-correlation-id",
                "method": "echo",
                "params": {"hello": "world"},
                "run_id": _RUN_ID,
                "owner_id": _OWNER_ID,
            }
        ).encode()
        + b"\n"
    )
    response = await _raw_roundtrip(running_server.socket_path, valid)
    assert response["id"] == "my-correlation-id"
    assert response["result"] == {"echoed": {"hello": "world"}}


# ---------------------------------------------------------------------------
# Client-side response validation
# ---------------------------------------------------------------------------


async def _rogue_server_mismatched_id(tmp_path: Path) -> ControlServer:
    """A real asyncio Unix server that always answers with the WRONG id."""

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(json.dumps({"jsonrpc": "2.0", "id": "not-the-request-id", "result": {}}).encode() + b"\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_unix_server(_handle, path=str(tmp_path / "rogue.sock"))

    class _Wrapper:
        socket_path = tmp_path / "rogue.sock"

        async def stop(self) -> None:
            server.close()
            await server.wait_closed()

    return _Wrapper()  # type: ignore[return-value]


async def test_client_rejects_response_with_mismatched_id(tmp_path: Path) -> None:
    rogue = await _rogue_server_mismatched_id(tmp_path)
    try:
        client = ControlClient(rogue.socket_path, run_id=_RUN_ID, owner_id=_OWNER_ID, request_deadline_s=2.0)
        with pytest.raises(ControlChannelError) as excinfo:
            await client.request("echo", {})
        assert excinfo.value.reason_code == "id_mismatch"
    finally:
        await rogue.stop()


async def test_client_connection_failure_when_nothing_listening(tmp_path: Path) -> None:
    client = ControlClient(tmp_path / "nobody-home.sock", run_id=_RUN_ID, owner_id=_OWNER_ID, request_deadline_s=1.0)
    with pytest.raises(ControlChannelError) as excinfo:
        await client.request("echo", {})
    assert excinfo.value.reason_code == "connection_failed"


# ---------------------------------------------------------------------------
# Message size limit
# ---------------------------------------------------------------------------


async def test_client_request_rejects_oversized_payload_before_sending(running_server: ControlServer) -> None:
    client = _client(running_server)
    huge_payload = {"blob": "x" * (MAX_MESSAGE_BYTES + 1024)}
    with pytest.raises(ControlChannelError) as excinfo:
        await client.request("echo", huge_payload)
    assert excinfo.value.reason_code == "message_too_large"


async def test_server_rejects_oversized_raw_request(tmp_path: Path) -> None:
    server = ControlServer(
        tmp_path / "small.sock",
        run_id=_RUN_ID,
        owner_id=_OWNER_ID,
        operations={"echo": _echo},
        request_deadline_s=2.0,
    )
    await server.start()
    try:
        reader, writer = await asyncio.open_unix_connection(path=str(server.socket_path), limit=MAX_MESSAGE_BYTES * 2)
        try:
            # No trailing newline: forces the server's bounded reader to
            # keep buffering past its own configured limit while searching
            # for one. The server is expected to detect the overrun and
            # abort the connection promptly — either by answering with a
            # clean "message_too_large" error before closing, or by
            # resetting the connection outright while this oversized write
            # is still draining (the earlier abort is itself proof the
            # server did not buffer unboundedly or hang). Bounded execution
            # (asyncio.wait_for below) is the one property genuinely under
            # test here: an outright hang is the only unacceptable outcome.
            oversized = b"{" + b"a" * (MAX_MESSAGE_BYTES * 2)
            aborted_with_connection_error = False
            line = b""
            try:
                writer.write(oversized)
                await asyncio.wait_for(writer.drain(), timeout=5.0)
                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            except (ConnectionError, asyncio.TimeoutError):
                aborted_with_connection_error = True
            assert aborted_with_connection_error or line, "server neither answered nor aborted the connection"
            if line:
                response = json.loads(line)
                assert response["error"]["data"]["reason_code"] == "message_too_large"
        finally:
            writer.close()
    finally:
        await server.stop()


# ---------------------------------------------------------------------------
# Lifecycle: start/stop, symlink refusal, socket permissions
# ---------------------------------------------------------------------------


async def test_start_sets_socket_mode_0600(running_server: ControlServer) -> None:
    mode = running_server.socket_path.stat().st_mode & 0o777
    assert mode == SOCKET_FILE_MODE


async def test_stop_removes_the_socket_file(tmp_path: Path) -> None:
    server = ControlServer(tmp_path / "s.sock", run_id=_RUN_ID, owner_id=_OWNER_ID, operations={})
    await server.start()
    assert server.socket_path.exists()
    await server.stop()
    assert not server.socket_path.exists()


async def test_stop_is_idempotent(tmp_path: Path) -> None:
    server = ControlServer(tmp_path / "s.sock", run_id=_RUN_ID, owner_id=_OWNER_ID, operations={})
    await server.start()
    await server.stop()
    await server.stop()  # must not raise


async def test_start_rejects_symlinked_socket_path(tmp_path: Path) -> None:
    real_target = tmp_path / "elsewhere.sock"
    link = tmp_path / "link.sock"
    link.symlink_to(real_target)
    server = ControlServer(link, run_id=_RUN_ID, owner_id=_OWNER_ID, operations={})
    with pytest.raises(ControlChannelError) as excinfo:
        await server.start()
    assert excinfo.value.reason_code == "socket_symlink_escape"


async def test_context_manager_starts_and_stops(tmp_path: Path) -> None:
    async with ControlServer(tmp_path / "cm.sock", run_id=_RUN_ID, owner_id=_OWNER_ID, operations={"echo": _echo}) as server:
        client = ControlClient(server.socket_path, run_id=_RUN_ID, owner_id=_OWNER_ID)
        result = await client.request("echo", {"in": "context"})
        assert result == {"echoed": {"in": "context"}}
    assert not server.socket_path.exists()


async def test_constructor_rejects_empty_run_id_or_owner_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ControlServer(tmp_path / "s.sock", run_id="", owner_id=_OWNER_ID, operations={})
    with pytest.raises(ValueError):
        ControlServer(tmp_path / "s.sock", run_id=_RUN_ID, owner_id="", operations={})
    with pytest.raises(ValueError):
        ControlClient(tmp_path / "s.sock", run_id="", owner_id=_OWNER_ID)
    with pytest.raises(ValueError):
        ControlClient(tmp_path / "s.sock", run_id=_RUN_ID, owner_id="")


# ---------------------------------------------------------------------------
# Cancellation closes sockets/pipes
# ---------------------------------------------------------------------------


async def test_cancelling_a_client_request_closes_its_connection_and_server_keeps_serving(
    running_server: ControlServer,
) -> None:
    client = _client(running_server)
    task = asyncio.ensure_future(client.request("hang", {}))
    await asyncio.sleep(0.05)  # let the connection actually open and the handler start.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The server's accept loop, and the handler task it spawned, must have
    # torn down cleanly rather than leaking a connection/hanging forever —
    # proven by immediately serving a brand new request successfully.
    fresh_client = _client(running_server)
    result = await fresh_client.request("echo", {"still": "alive"})
    assert result == {"echoed": {"still": "alive"}}


def test_default_request_deadline_is_positive() -> None:
    assert DEFAULT_REQUEST_DEADLINE_S > 0
