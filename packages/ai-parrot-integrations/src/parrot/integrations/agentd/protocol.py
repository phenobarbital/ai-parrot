"""JSON-RPC 2.0 / NDJSON wire protocol for the Agent CLI Daemon (agentd).

This module implements the foundation of the daemon wire format described in
``sdd/specs/agent-cli-daemon.spec.md`` §2 ("Wire Protocol"). It provides:

- Pydantic v2 models for JSON-RPC 2.0 requests, responses, errors, and
  notifications.
- Error-code constants (both the JSON-RPC standard range and the
  application-specific range used by agentd).
- Method-name constants for the full RPC surface exposed by the daemon.
- An NDJSON framing codec (``read_message`` / ``write_message``) built on top
  of ``asyncio.StreamReader`` / ``asyncio.StreamWriter``, with a configurable
  maximum line size to avoid unbounded buffering.

No I/O beyond stream helpers lives here; socket accept/dispatch logic is
implemented in ``server.py`` (TASK-2211) and the client in ``client.py``
(TASK-2213).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

__all__ = [
    "AGENT_BUSY",
    "DEFAULT_MAX_LINE_BYTES",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "JSONRPC_VERSION",
    "METHOD_AGENT_INFO",
    "METHOD_AGENT_INVOKE",
    "METHOD_CHAT_COMPLETE",
    "METHOD_CHAT_DELTA",
    "METHOD_CHAT_ERROR",
    "METHOD_CHAT_SEND",
    "METHOD_DAEMON_SHUTDOWN",
    "METHOD_DAEMON_STATUS",
    "METHOD_EVENTS_SUBSCRIBE",
    "METHOD_EVENTS_UNSUBSCRIBE",
    "METHOD_EVENT_JOB_ERROR",
    "METHOD_EVENT_JOB_EXECUTED",
    "METHOD_EVENT_SHUTDOWN",
    "METHOD_NOT_FOUND",
    "METHOD_SCHEDULES_ADD",
    "METHOD_SCHEDULES_LIST",
    "METHOD_SCHEDULES_PAUSE",
    "METHOD_SCHEDULES_REMOVE",
    "METHOD_SCHEDULES_RESUME",
    "METHOD_TOOLS_LIST",
    "PARSE_ERROR",
    "SCHEDULER_UNAVAILABLE",
    "SCHEDULE_NOT_FOUND",
    "UNKNOWN_AGENT_METHOD",
    "MalformedMessageError",
    "OversizedLineError",
    "ProtocolError",
    "RpcError",
    "RpcNotification",
    "RpcRequest",
    "RpcResponse",
    "read_message",
    "write_message",
]

JSONRPC_VERSION: Literal["2.0"] = "2.0"

# --------------------------------------------------------------------------
# Error codes
# --------------------------------------------------------------------------

# JSON-RPC 2.0 standard error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Application-specific error codes (spec §2 "Wire Protocol").
AGENT_BUSY = 1001
UNKNOWN_AGENT_METHOD = 1002
SCHEDULER_UNAVAILABLE = 1003
SCHEDULE_NOT_FOUND = 1004

# --------------------------------------------------------------------------
# Method-name constants (spec §2 "Wire Protocol" table)
# --------------------------------------------------------------------------

METHOD_CHAT_SEND = "chat.send"
METHOD_CHAT_DELTA = "chat.delta"
METHOD_CHAT_COMPLETE = "chat.complete"
METHOD_CHAT_ERROR = "chat.error"
METHOD_AGENT_INFO = "agent.info"
METHOD_AGENT_INVOKE = "agent.invoke"
METHOD_TOOLS_LIST = "tools.list"
METHOD_SCHEDULES_LIST = "schedules.list"
METHOD_SCHEDULES_ADD = "schedules.add"
METHOD_SCHEDULES_PAUSE = "schedules.pause"
METHOD_SCHEDULES_RESUME = "schedules.resume"
METHOD_SCHEDULES_REMOVE = "schedules.remove"
METHOD_EVENTS_SUBSCRIBE = "events.subscribe"
METHOD_EVENTS_UNSUBSCRIBE = "events.unsubscribe"
METHOD_EVENT_JOB_EXECUTED = "event.job_executed"
METHOD_EVENT_JOB_ERROR = "event.job_error"
METHOD_EVENT_SHUTDOWN = "event.shutdown"
METHOD_DAEMON_STATUS = "daemon.status"
METHOD_DAEMON_SHUTDOWN = "daemon.shutdown"


# --------------------------------------------------------------------------
# Pydantic v2 models
# --------------------------------------------------------------------------


class RpcError(BaseModel):
    """JSON-RPC 2.0 error object.

    Attributes:
        code: Numeric error code (JSON-RPC standard or agentd application
            range — see the module-level constants).
        message: Short, human-readable error description.
        data: Optional additional error context (never a traceback — those
            are logged daemon-side only, per spec §2 "Error Handling").
    """

    code: int
    message: str
    data: Any | None = None


class RpcRequest(BaseModel):
    """JSON-RPC 2.0 request object.

    Attributes:
        jsonrpc: Always ``"2.0"``.
        id: Request identifier, echoed back in the matching ``RpcResponse``.
        method: RPC method name (see ``METHOD_*`` constants).
        params: Method parameters, as a mapping.
    """

    jsonrpc: Literal["2.0"] = JSONRPC_VERSION
    id: int | str
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class RpcResponse(BaseModel):
    """JSON-RPC 2.0 response object.

    Exactly one of ``result`` / ``error`` is expected to be set, mirroring
    the JSON-RPC 2.0 spec (enforced by callers, not validated here to keep
    the model permissive for partial/streaming construction).

    Attributes:
        jsonrpc: Always ``"2.0"``.
        id: Echoes the originating request's ``id``.
        result: The method's return value, when successful.
        error: An ``RpcError``, when the call failed.
    """

    jsonrpc: Literal["2.0"] = JSONRPC_VERSION
    id: int | str | None
    result: Any | None = None
    error: RpcError | None = None


class RpcNotification(BaseModel):
    """JSON-RPC 2.0 notification object (no ``id`` — no reply expected).

    Used for server-initiated messages: streaming ``chat.delta``/
    ``chat.complete``/``chat.error``, and fan-out scheduler/daemon events
    (``event.job_executed``, ``event.job_error``, ``event.shutdown``).

    Attributes:
        jsonrpc: Always ``"2.0"``.
        method: Notification method name.
        params: Notification payload, as a mapping.
    """

    jsonrpc: Literal["2.0"] = JSONRPC_VERSION
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# NDJSON framing
# --------------------------------------------------------------------------

#: Default maximum size (in bytes) of a single NDJSON line, before decoding.
DEFAULT_MAX_LINE_BYTES = 10 * 1024 * 1024  # 10 MB


class ProtocolError(Exception):
    """Base class for all agentd wire-protocol errors."""


class OversizedLineError(ProtocolError):
    """Raised when an incoming NDJSON line exceeds the configured limit."""


class MalformedMessageError(ProtocolError):
    """Raised when an incoming line is not valid JSON or not a known shape.

    Attributes:
        rpc_id: The JSON-RPC ``id`` recovered from the malformed payload, if
            any could be salvaged (best-effort), else ``None``.
    """

    def __init__(self, message: str, *, rpc_id: int | str | None = None) -> None:
        super().__init__(message)
        self.rpc_id = rpc_id


AnyRpcMessage = RpcRequest | RpcResponse | RpcNotification


def _parse_message(raw: dict[str, Any]) -> AnyRpcMessage:
    """Classify and validate a decoded JSON object into an RPC model.

    Args:
        raw: The decoded JSON object (a mapping).

    Returns:
        The matching ``RpcRequest``, ``RpcResponse``, or ``RpcNotification``.

    Raises:
        MalformedMessageError: If ``raw`` does not match any known shape.
    """
    has_id = "id" in raw
    is_response = "result" in raw or "error" in raw

    try:
        if is_response:
            return RpcResponse.model_validate(raw)
        if has_id:
            return RpcRequest.model_validate(raw)
        return RpcNotification.model_validate(raw)
    except Exception as exc:
        raise MalformedMessageError(
            f"Malformed JSON-RPC message: {exc}",
            rpc_id=raw.get("id") if isinstance(raw, dict) else None,
        ) from exc


async def read_message(
    reader: asyncio.StreamReader,
    *,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
) -> AnyRpcMessage | None:
    """Read one NDJSON-framed JSON-RPC message from ``reader``.

    Handles both split frames (a single message arriving across multiple
    reads) and coalesced frames (multiple ``\\n``-terminated messages
    delivered in one underlying read) transparently — both are standard
    ``asyncio.StreamReader`` behaviours, since ``readuntil`` buffers until it
    finds the separator regardless of how many underlying reads that takes.

    Args:
        reader: The stream to read a single line from.
        max_line_bytes: Maximum allowed size (bytes) of one line, enforced
            BEFORE JSON parsing to avoid unbounded buffering on hostile or
            broken input.

    Returns:
        The parsed message, or ``None`` on a clean EOF with no data pending.

    Raises:
        OversizedLineError: If the line exceeds ``max_line_bytes``.
        MalformedMessageError: If the line is not valid JSON, or not a
            recognizable JSON-RPC shape.
    """
    try:
        line = await reader.readuntil(b"\n")
    except asyncio.IncompleteReadError as exc:
        # EOF reached; any partial (unterminated) data left is a truncated
        # message unless it's an empty tail.
        if not exc.partial:
            return None
        line = exc.partial
        if len(line) > max_line_bytes:
            raise OversizedLineError(
                f"Line of {len(line)} bytes exceeds limit of {max_line_bytes} bytes"
            ) from exc
        raise MalformedMessageError(
            "Truncated message at EOF (missing trailing newline)"
        ) from exc
    except asyncio.LimitOverrunError as exc:
        # StreamReader's own internal buffer limit was hit before the
        # separator was found — definitely oversized.
        raise OversizedLineError(
            f"Line exceeds StreamReader buffer limit ({exc})"
        ) from exc

    if len(line) > max_line_bytes:
        raise OversizedLineError(
            f"Line of {len(line)} bytes exceeds limit of {max_line_bytes} bytes"
        )

    stripped = line.rstrip(b"\n")
    if not stripped:
        # Blank line (e.g. trailing newline at EOF) — treat as no message.
        return None

    try:
        raw = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise MalformedMessageError(f"Invalid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise MalformedMessageError(
            f"Expected a JSON object, got {type(raw).__name__}"
        )

    return _parse_message(raw)


def write_message(writer: asyncio.StreamWriter, model: AnyRpcMessage) -> None:
    """Serialize ``model`` and write it as one NDJSON line to ``writer``.

    Args:
        writer: The stream to write the encoded line to. Callers are
            responsible for calling ``await writer.drain()`` afterwards to
            respect backpressure.
        model: The ``RpcRequest`` / ``RpcResponse`` / ``RpcNotification`` to
            encode.
    """
    payload = model.model_dump_json(exclude_none=False)
    writer.write(payload.encode("utf-8") + b"\n")
