"""Private supervisor control and stdio RPC channel (FEAT-581, M3).

Implements the spec §2 "Process Lifecycle and Worktree Isolation" contract:

    For stdio, a private Unix control socket mediates request/response
    exchange; requests are serialized and checked for matching JSON-RPC
    IDs. Never expose raw stdio through a PID file.

and the frozen wire shape from the TASK-3517 research spike
(``sdd/state/FEAT-581/research/lifecycle.md`` §3.2(a)/§5 item 8): a
newline-delimited JSON-RPC 2.0 envelope over a Unix domain socket (mode
0600, in a mode-0700 run directory — see :mod:`parrot.e2e.state`), every
request/response correlated by its ``"id"``.

This module owns exactly the *channel*, not what travels through it:

- :class:`ControlServer` accepts connections for one run and dispatches an
  incoming ``method`` to a caller-supplied handler mapping — it has no
  knowledge of what "start"/"status"/"stop"/"stdio" *do*. The concrete
  :class:`parrot.e2e.supervisor.E2ESupervisor` (a separate, not-yet-landed
  M3 task) wires its own operations into that mapping.
- :class:`ControlClient` sends one request and returns its ``result``.

Every request is checked, most-definitive-first, before any handler ever
runs: malformed envelope shape, then a stale ``run_id``, then a foreign
``owner_id`` — a duck-typed or partially-populated request can never reach
a handler by accident. Every read (server and client alike) goes through
:func:`asyncio.wait_for`; the legacy ``tests/mcp/test_mcp_local_e2e.py``
``_recv`` helper's blocking ``readline()`` (flagged as a real gap by the
TASK-3517 spike, §6 item 3) is deliberately not reproduced here.

This module never re-derives access to a child's stdio from its PID or a
PID file — mediating a "stdio" operation means forwarding an already-open
pipe a handler itself retains; this module holds no process handles of its
own. Nor does it ever place a secret on a CLI argv: a :class:`ControlClient`
is constructed from a socket path, run ID and owner ID, the same values the
spec's M5 pytest bridge says are "supplied in env by the runner" (§3 "M5"),
never encoded into a spawned command line.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Awaitable, Callable, Mapping, Optional

from pydantic import JsonValue

from parrot.e2e.errors import E2EConfigError

__all__ = [
    "MAX_MESSAGE_BYTES",
    "SOCKET_FILE_MODE",
    "DEFAULT_REQUEST_DEADLINE_S",
    "ControlHandler",
    "ControlChannelError",
    "ControlServer",
    "ControlClient",
]

logger = logging.getLogger(__name__)

_JSONRPC_VERSION = "2.0"

# A defensive per-message byte ceiling for this control channel. The spec
# does not fix an exact number for control-socket messages — that is the
# unrelated Live Provider Budget's 16384-byte serialized-text cap (spec §2
# "Live Provider Budget"). This bound is this module's own choice: generous
# enough for a tunneled MCP `tools/list`-sized response, small enough that
# a malicious or buggy peer cannot force unbounded buffering.
MAX_MESSAGE_BYTES = 1_048_576  # 1 MiB

# Mode-0600 socket in a mode-0700 run directory, per spec §2.
SOCKET_FILE_MODE = 0o600

DEFAULT_REQUEST_DEADLINE_S = 30.0

# JSON-RPC 2.0 reserved codes.
_ERR_PARSE = -32700
_ERR_INVALID_REQUEST = -32600
_ERR_METHOD_NOT_FOUND = -32601
# Implementation-defined server-error range (-32000..-32099 per JSON-RPC 2.0).
_ERR_FOREIGN_OWNER = -32001
_ERR_STALE_RUN = -32002
_ERR_MESSAGE_TOO_LARGE = -32003
_ERR_DEADLINE_EXCEEDED = -32004
_ERR_HANDLER_FAILURE = -32005

ControlHandler = Callable[[dict[str, JsonValue]], Awaitable[dict[str, JsonValue]]]


class ControlChannelError(E2EConfigError):
    """Malformed control-channel request/response, foreign owner or stale run ID.

    Subclasses :class:`parrot.e2e.errors.E2EConfigError` (exit code 2, spec
    §2) — every failure this module raises happens before any target
    protocol logic runs, the same class of error that exit code already
    covers. This module defines no exit-code mapping of its own.

    Attributes:
        code: The JSON-RPC error code (reserved range or this module's own
            implementation-defined range) recorded in an error envelope's
            ``error.code``.
    """

    def __init__(self, message: str, *, reason_code: Optional[str] = None, code: int = _ERR_HANDLER_FAILURE) -> None:
        """Initialize the error.

        Args:
            message: Human-readable description of the failure.
            reason_code: Machine-readable reason code (also carried in the
                JSON-RPC error envelope's ``error.data.reason_code``).
            code: The JSON-RPC error code for this failure.
        """
        super().__init__(message, reason_code=reason_code)
        self.code = code


def _new_id() -> str:
    """Return a fresh, opaque JSON-RPC request ID."""
    return uuid.uuid4().hex


def _encode(message: dict[str, JsonValue]) -> bytes:
    """Serialize one JSON-RPC envelope as a single newline-terminated line.

    Args:
        message: The JSON-RPC envelope to serialize.

    Returns:
        The UTF-8-encoded, newline-terminated line.

    Raises:
        ControlChannelError: If the serialized line would exceed
            :data:`MAX_MESSAGE_BYTES`.
    """
    line = json.dumps(message, separators=(",", ":")) + "\n"
    encoded = line.encode("utf-8")
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ControlChannelError(
            f"control message exceeds the {MAX_MESSAGE_BYTES}-byte limit ({len(encoded)} bytes)",
            reason_code="message_too_large",
            code=_ERR_MESSAGE_TOO_LARGE,
        )
    return encoded


async def _read_line(reader: asyncio.StreamReader, *, deadline_s: float) -> bytes:
    """Read one newline-terminated message, bounded by size and a real deadline.

    Never a blocking ``readline()`` — every read here goes through
    :func:`asyncio.wait_for`, unlike the legacy
    ``tests/mcp/test_mcp_local_e2e.py`` ``_recv`` helper (flagged by the
    TASK-3517 research spike, §6 item 3, as accepting a ``timeout`` it never
    actually enforces).

    Args:
        reader: The stream to read one line from.
        deadline_s: Maximum seconds to wait for a complete line.

    Returns:
        The raw line, including its trailing newline, or ``b""`` at a clean
        EOF (no data was sent at all).

    Raises:
        ControlChannelError: If the deadline elapses, or the line (or the
            reader's internal buffering while searching for one) exceeds
            :data:`MAX_MESSAGE_BYTES`.
    """
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=deadline_s)
    except asyncio.TimeoutError as exc:
        raise ControlChannelError(
            "control channel read deadline exceeded",
            reason_code="deadline_exceeded",
            code=_ERR_DEADLINE_EXCEEDED,
        ) from exc
    except (asyncio.LimitOverrunError, ValueError) as exc:
        raise ControlChannelError(
            f"control message exceeds the {MAX_MESSAGE_BYTES}-byte limit",
            reason_code="message_too_large",
            code=_ERR_MESSAGE_TOO_LARGE,
        ) from exc
    if len(line) > MAX_MESSAGE_BYTES:
        raise ControlChannelError(
            f"control message exceeds the {MAX_MESSAGE_BYTES}-byte limit ({len(line)} bytes)",
            reason_code="message_too_large",
            code=_ERR_MESSAGE_TOO_LARGE,
        )
    return line


class ControlClient:
    """Client for one run's private control channel (spec §2, frozen wire shape).

    Every :meth:`request` opens one connection, sends one JSON-RPC request,
    waits for its correlated response and closes — serialized exchange, per
    spec §2 ("requests are serialized"). The connection's writer is always
    closed on return, on a server-reported error, and on cancellation.
    """

    def __init__(
        self,
        socket_path: Path,
        *,
        run_id: str,
        owner_id: str,
        request_deadline_s: float = DEFAULT_REQUEST_DEADLINE_S,
    ) -> None:
        """Initialize the client.

        Args:
            socket_path: Path to the run's private Unix control socket
                (normally supplied via an environment variable, per spec §3
                "M5", never a CLI argv token).
            run_id: This run's stable ID; every request is stamped with it
                so a stale client from a previous run is refused, not
                silently served.
            owner_id: This caller's own identity; the server refuses a
                request whose ``owner_id`` disagrees with its own.
            request_deadline_s: Maximum seconds to wait for a connection,
                for the write to drain, and for one response.

        Raises:
            ValueError: If ``run_id`` or ``owner_id`` is empty.
        """
        if not run_id:
            raise ValueError("run_id must be nonempty")
        if not owner_id:
            raise ValueError("owner_id must be nonempty")
        self._socket_path = socket_path
        self._run_id = run_id
        self._owner_id = owner_id
        self._request_deadline_s = request_deadline_s
        self.logger = logging.getLogger(__name__)

    async def request(self, operation: str, payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Send one JSON-RPC request and return its ``result`` payload.

        Args:
            operation: The control operation name (JSON-RPC ``method``,
                e.g. ``"start"``/``"status"``/``"stop"``/``"stdio"``).
            payload: Operation-specific parameters (JSON-RPC ``params``).

        Returns:
            The handler's ``result`` payload, as returned by the server.

        Raises:
            ControlChannelError: On a connection failure, a malformed or
                ID-mismatched response, a size or deadline violation, or a
                server-reported error (foreign owner, stale run, unknown
                operation, or the operation handler's own failure).
        """
        if not operation:
            raise ControlChannelError(
                "operation must be nonempty", reason_code="invalid_request", code=_ERR_INVALID_REQUEST
            )
        request_id = _new_id()
        envelope: dict[str, JsonValue] = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": request_id,
            "method": operation,
            "params": payload,
            "run_id": self._run_id,
            "owner_id": self._owner_id,
        }
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(path=str(self._socket_path), limit=MAX_MESSAGE_BYTES),
                timeout=self._request_deadline_s,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise ControlChannelError(
                f"could not connect to control socket: {self._socket_path}: {exc}",
                reason_code="connection_failed",
                code=_ERR_HANDLER_FAILURE,
            ) from exc

        try:
            writer.write(_encode(envelope))
            try:
                await asyncio.wait_for(writer.drain(), timeout=self._request_deadline_s)
            except asyncio.TimeoutError as exc:
                raise ControlChannelError(
                    "control channel write deadline exceeded",
                    reason_code="deadline_exceeded",
                    code=_ERR_DEADLINE_EXCEEDED,
                ) from exc

            line = await _read_line(reader, deadline_s=self._request_deadline_s)
            if not line:
                raise ControlChannelError(
                    "control server closed the connection without a response",
                    reason_code="connection_closed",
                    code=_ERR_HANDLER_FAILURE,
                )
            return self._parse_response(line, expected_id=request_id)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    @staticmethod
    def _parse_response(line: bytes, *, expected_id: str) -> dict[str, JsonValue]:
        """Validate and unwrap one JSON-RPC response line.

        Args:
            line: The raw response line (including its trailing newline).
            expected_id: The request ID this response must echo back.

        Returns:
            The response's ``result`` object.

        Raises:
            ControlChannelError: If the line is not valid JSON, is not a
                JSON-RPC 2.0 envelope, carries a mismatched ``id``, reports
                a server-side ``error``, or omits a ``result`` object.
        """
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ControlChannelError(
                f"non-JSON control response: {line!r}", reason_code="response_malformed", code=_ERR_PARSE
            ) from exc

        if not isinstance(response, dict) or response.get("jsonrpc") != _JSONRPC_VERSION:
            raise ControlChannelError(
                f"malformed control response envelope: {response!r}",
                reason_code="response_malformed",
                code=_ERR_INVALID_REQUEST,
            )

        # Definitive correlation check first: an ID mismatch invalidates the
        # response regardless of whether it otherwise looks well-formed.
        if response.get("id") != expected_id:
            raise ControlChannelError(
                f"control response ID mismatch: expected {expected_id!r}, got {response.get('id')!r}",
                reason_code="id_mismatch",
                code=_ERR_INVALID_REQUEST,
            )

        if "error" in response:
            error = response["error"] if isinstance(response.get("error"), dict) else {}
            data = error.get("data") if isinstance(error.get("data"), dict) else {}
            raise ControlChannelError(
                str(error.get("message", "control operation failed")),
                reason_code=str(data.get("reason_code") or "operation_failed"),
                code=int(error.get("code", _ERR_HANDLER_FAILURE)),
            )

        result = response.get("result")
        if not isinstance(result, dict):
            raise ControlChannelError(
                f"control response missing a result object: {response!r}",
                reason_code="response_malformed",
                code=_ERR_INVALID_REQUEST,
            )
        return result


class ControlServer:
    """Server for one run's private control channel (spec §2, frozen wire shape).

    One instance mediates exactly one run's owner-bound requests over a
    private Unix socket. :meth:`start` binds the socket (mode 0600,
    immediately accepting connections in the background — no separate
    "serve forever" call is needed); :meth:`stop` closes it and removes the
    socket file, idempotently.

    Every accepted request is checked, most-definitive-first, before its
    ``method`` is ever dispatched: envelope shape, then ``run_id`` (a stale
    client from a previous run), then ``owner_id`` (a foreign caller) — an
    unauthorized or malformed request never reaches a handler.
    """

    def __init__(
        self,
        socket_path: Path,
        *,
        run_id: str,
        owner_id: str,
        operations: Mapping[str, ControlHandler],
        request_deadline_s: float = DEFAULT_REQUEST_DEADLINE_S,
    ) -> None:
        """Initialize the server.

        Args:
            socket_path: Path this channel's Unix socket is bound at (a
                mode-0700 run directory is the caller's responsibility, see
                :func:`parrot.e2e.state.run_dir`).
            run_id: This run's stable ID; requests naming a different one
                are refused as stale.
            owner_id: This run's recorded owner; requests naming a
                different one are refused as foreign.
            operations: Mapping of operation name (JSON-RPC ``method``) to
                an async handler. This server has no built-in operations of
                its own — an unrecognised ``method`` is always rejected.
            request_deadline_s: Maximum seconds allowed for one request's
                read and for its handler's own execution.

        Raises:
            ValueError: If ``run_id`` or ``owner_id`` is empty.
        """
        if not run_id:
            raise ValueError("run_id must be nonempty")
        if not owner_id:
            raise ValueError("owner_id must be nonempty")
        self._socket_path = socket_path
        self._run_id = run_id
        self._owner_id = owner_id
        self._operations = dict(operations)
        self._request_deadline_s = request_deadline_s
        self._server: Optional[asyncio.AbstractServer] = None
        self.logger = logging.getLogger(__name__)

    @property
    def socket_path(self) -> Path:
        """The path this channel's Unix socket is (or will be) bound at."""
        return self._socket_path

    async def start(self) -> None:
        """Bind the private Unix socket (mode 0600) and begin accepting connections.

        Raises:
            ControlChannelError: If ``socket_path`` is a symlink (refused,
                never traversed/replaced through) or the socket cannot be
                bound.
        """
        if self._socket_path.is_symlink():
            raise ControlChannelError(
                f"refusing to bind a control socket over a symlink: {self._socket_path}",
                reason_code="socket_symlink_escape",
                code=_ERR_INVALID_REQUEST,
            )
        if self._socket_path.exists():
            # A stale socket file from a previous crashed run at the same
            # path would otherwise fail the bind with "address already in
            # use"; this run's own state/ownership already gated whether
            # reusing this path is safe (out of this module's scope).
            self._socket_path.unlink()
        try:
            self._server = await asyncio.start_unix_server(
                self._handle_connection, path=str(self._socket_path), limit=MAX_MESSAGE_BYTES
            )
        except OSError as exc:
            raise ControlChannelError(
                f"could not bind control socket: {self._socket_path}: {exc}",
                reason_code="socket_bind_failed",
                code=_ERR_HANDLER_FAILURE,
            ) from exc
        os.chmod(self._socket_path, SOCKET_FILE_MODE)

    async def stop(self) -> None:
        """Stop accepting connections and remove the socket file.

        Idempotent and safe to call from a cancellation/``finally`` handler:
        calling it more than once, or before :meth:`start`, never raises.
        """
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None
        with contextlib.suppress(OSError):
            self._socket_path.unlink()

    async def __aenter__(self) -> "ControlServer":
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Serve exactly one request/response exchange on this connection, then close.

        Never lets a malformed request, an unauthorized owner/run, or a
        handler exception escape to crash the accept loop; every such
        failure is translated into one JSON-RPC error envelope. The
        connection's writer is always closed, including on cancellation.
        """
        try:
            await self._process_one_request(reader, writer)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger.exception("unhandled control-channel connection error")
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _process_one_request(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Read, validate, authorize, dispatch and answer exactly one request."""
        try:
            line = await _read_line(reader, deadline_s=self._request_deadline_s)
        except ControlChannelError as exc:
            await self._respond_error(writer, None, exc)
            return
        if not line:
            return  # peer closed without sending anything; nothing to answer.

        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            await self._respond_error(
                writer,
                None,
                ControlChannelError(f"invalid JSON: {exc}", reason_code="parse_error", code=_ERR_PARSE),
            )
            return

        if not isinstance(message, dict):
            await self._respond_error(
                writer,
                None,
                ControlChannelError(
                    "request must be a JSON object", reason_code="invalid_request", code=_ERR_INVALID_REQUEST
                ),
            )
            return

        request_id = message.get("id")
        try:
            self._validate_envelope(message)
        except ControlChannelError as exc:
            await self._respond_error(writer, request_id, exc)
            return

        # Most-definitive-first: a stale run_id, then a foreign owner_id,
        # are both refused before the operation's own handler is ever
        # invoked.
        if message["run_id"] != self._run_id:
            await self._respond_error(
                writer,
                request_id,
                ControlChannelError(
                    f"stale run_id: {message['run_id']!r} does not match this channel's run {self._run_id!r}",
                    reason_code="stale_run_id",
                    code=_ERR_STALE_RUN,
                ),
            )
            return
        if message["owner_id"] != self._owner_id:
            await self._respond_error(
                writer,
                request_id,
                ControlChannelError(
                    f"foreign owner: {message['owner_id']!r} does not match this channel's owner {self._owner_id!r}",
                    reason_code="foreign_owner",
                    code=_ERR_FOREIGN_OWNER,
                ),
            )
            return

        operation = message["method"]
        handler = self._operations.get(operation)
        if handler is None:
            await self._respond_error(
                writer,
                request_id,
                ControlChannelError(
                    f"unknown control operation: {operation!r}",
                    reason_code="method_not_found",
                    code=_ERR_METHOD_NOT_FOUND,
                ),
            )
            return

        params = message["params"]
        try:
            result = await asyncio.wait_for(handler(params), timeout=self._request_deadline_s)
        except asyncio.TimeoutError:
            await self._respond_error(
                writer,
                request_id,
                ControlChannelError(
                    "control operation deadline exceeded",
                    reason_code="deadline_exceeded",
                    code=_ERR_DEADLINE_EXCEEDED,
                ),
            )
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - translated into one error envelope, never crashes the accept loop.
            self.logger.exception("control operation %r failed", operation)
            await self._respond_error(
                writer,
                request_id,
                ControlChannelError(
                    f"control operation {operation!r} failed: {exc}",
                    reason_code="handler_failed",
                    code=_ERR_HANDLER_FAILURE,
                ),
            )
            return

        if not isinstance(result, dict):
            await self._respond_error(
                writer,
                request_id,
                ControlChannelError(
                    f"handler for {operation!r} returned a non-dict result",
                    reason_code="handler_invalid_result",
                    code=_ERR_HANDLER_FAILURE,
                ),
            )
            return

        await self._respond_result(writer, request_id, result)

    @staticmethod
    def _validate_envelope(message: dict[str, JsonValue]) -> None:
        """Validate the minimal JSON-RPC 2.0 + owner-bound envelope shape.

        Args:
            message: The parsed request object.

        Raises:
            ControlChannelError: If any required field is missing or the
                wrong type.
        """
        if message.get("jsonrpc") != _JSONRPC_VERSION:
            raise ControlChannelError(
                "missing or wrong 'jsonrpc' version", reason_code="invalid_request", code=_ERR_INVALID_REQUEST
            )
        if message.get("id") is None:
            raise ControlChannelError("missing 'id'", reason_code="invalid_request", code=_ERR_INVALID_REQUEST)
        if not isinstance(message.get("method"), str) or not message["method"]:
            raise ControlChannelError(
                "missing or invalid 'method'", reason_code="invalid_request", code=_ERR_INVALID_REQUEST
            )
        if not isinstance(message.get("params"), dict):
            raise ControlChannelError(
                "missing or invalid 'params'", reason_code="invalid_request", code=_ERR_INVALID_REQUEST
            )
        if not isinstance(message.get("run_id"), str) or not message["run_id"]:
            raise ControlChannelError(
                "missing or invalid 'run_id'", reason_code="invalid_request", code=_ERR_INVALID_REQUEST
            )
        if not isinstance(message.get("owner_id"), str) or not message["owner_id"]:
            raise ControlChannelError(
                "missing or invalid 'owner_id'", reason_code="invalid_request", code=_ERR_INVALID_REQUEST
            )

    async def _respond_result(
        self, writer: asyncio.StreamWriter, request_id: JsonValue, result: dict[str, JsonValue]
    ) -> None:
        """Write a successful JSON-RPC response envelope."""
        envelope: dict[str, JsonValue] = {"jsonrpc": _JSONRPC_VERSION, "id": request_id, "result": result}
        await self._write(writer, envelope)

    async def _respond_error(
        self, writer: asyncio.StreamWriter, request_id: Optional[JsonValue], error: ControlChannelError
    ) -> None:
        """Write a JSON-RPC error response envelope."""
        envelope: dict[str, JsonValue] = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": error.code, "message": str(error), "data": {"reason_code": error.reason_code}},
        }
        await self._write(writer, envelope)

    async def _write(self, writer: asyncio.StreamWriter, envelope: dict[str, JsonValue]) -> None:
        """Encode and send one envelope, bounded by this channel's deadline.

        A peer that has already vanished (connection reset/broken pipe) is
        only logged, never raised — the request already has no one left to
        answer.
        """
        try:
            encoded = _encode(envelope)
        except ControlChannelError:
            # The handler's own result was too large to encode; downgrade
            # to a small, always-encodable error envelope instead of ever
            # sending a truncated/invalid line.
            encoded = _encode(
                {
                    "jsonrpc": _JSONRPC_VERSION,
                    "id": envelope.get("id"),
                    "error": {
                        "code": _ERR_MESSAGE_TOO_LARGE,
                        "message": "control response too large to encode",
                        "data": {"reason_code": "message_too_large"},
                    },
                }
            )
        writer.write(encoded)
        with contextlib.suppress(ConnectionError, OSError, asyncio.TimeoutError):
            await asyncio.wait_for(writer.drain(), timeout=self._request_deadline_s)
