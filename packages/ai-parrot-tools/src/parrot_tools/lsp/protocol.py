"""Bounded Content-Length framing for the LSP pilot (FEAT-580, M2).

Implements the byte-level transport LSP requires — ``Content-Length``
headers followed by a raw JSON-RPC body — independently of the line-
delimited JSON transport ``StdioMCPServer`` already uses for MCP
(:mod:`parrot.mcp.local_server`). The two protocols are not compatible:
LSP framing needs an exact byte count that never conflates JSON
*characters* with UTF-8 *bytes* (a single non-ASCII character can be one
Python ``str`` character and two or more UTF-8 bytes), so ``Content-Length``
is always computed and consumed in bytes, never in decoded-string length.

Everything here is a private, byte-oriented helper meant to be consumed by
``PyrightSession`` (``session.py``, a later task) — nothing in this module
is an agent-facing tool, spawns a process, or knows anything about Pyright
specifically. Reading/writing one frame never blocks longer than the
underlying stream allows; timeouts and cancellation are the caller's
responsibility (``asyncio.wait_for`` around :func:`read_message`, or
cancelling the awaiting task).

Two bounded caps enforce spec §2.10 ("Bounds"):

- :data:`MAX_HEADER_BYTES` (8 KiB) — the entire header block, including
  every ``\\r\\n``-terminated line up to (and including) the blank line
  that ends it.
- :data:`MAX_FRAME_BYTES` (8 MiB) — the declared ``Content-Length`` body
  size. A frame that declares more than this is rejected *before* the
  body is read, so an adversarial/oversized declaration never forces an
  unbounded read.

A malformed frame (bad header shape, non-integer/negative/oversized
``Content-Length``, non-UTF-8 body, non-JSON body, or a JSON-RPC shape
that is neither a request, a response, nor a notification) raises
:class:`~parrot_tools.lsp.models.LSPFailure` with code ``"protocol_error"``.
A connection that closes before a frame is complete (premature EOF) raises
:class:`~parrot_tools.lsp.models.LSPFailure` with code ``"server_crashed"``
instead, since — from the transport's point of view — an unexpected close
of the child's stdout is indistinguishable from the child having died.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from .models import LSPFailure

#: JSON-RPC version string every message on this transport must carry.
JSONRPC_VERSION = "2.0"

#: Header-block cap (spec §2.10 "Bounds": "headers 8 KiB").
MAX_HEADER_BYTES = 8 * 1024

#: Frame-body cap (spec §2.10 "Bounds": "frames 8 MiB").
MAX_FRAME_BYTES = 8 * 1024 * 1024

#: The discriminated JSON-RPC message shapes this transport recognizes.
FrameKind = Literal["request", "response", "notification"]

__all__ = [
    "JSONRPC_VERSION",
    "MAX_HEADER_BYTES",
    "MAX_FRAME_BYTES",
    "FrameKind",
    "ParsedMessage",
    "read_message",
    "write_message",
    "build_request",
    "build_notification",
    "build_response",
]


@dataclass(frozen=True)
class ParsedMessage:
    """One decoded, discriminated JSON-RPC message read off the wire.

    Attributes:
        kind: ``"request"`` (has ``id`` and ``method``), ``"response"``
            (has ``id`` and exactly one of ``result``/``error``), or
            ``"notification"`` (has ``method``, no ``id``).
        id: The exact, type-preserving JSON-RPC id (``int``, ``str``, or
            ``None`` for a notification) — never coerced to another type.
        method: The method name for a request/notification; ``None`` for
            a response.
        params: The raw ``params`` value for a request/notification, or
            ``None`` if absent.
        result: The raw ``result`` value for a response, or ``None``
            otherwise (including a response whose actual result is
            ``null``, which is indistinguishable at this layer).
        error: The raw ``error`` object for an error response, or ``None``
            otherwise.
        raw: The complete decoded JSON object, for callers that need a
            field this dataclass does not surface individually.
    """

    kind: FrameKind
    id: int | str | None
    method: str | None
    params: Any
    result: Any
    error: dict[str, Any] | None
    raw: dict[str, Any]


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


async def read_message(
    reader: asyncio.StreamReader,
    *,
    max_header_bytes: int = MAX_HEADER_BYTES,
    max_frame_bytes: int = MAX_FRAME_BYTES,
) -> ParsedMessage:
    """Read and strictly parse one ``Content-Length``-framed JSON-RPC message.

    Correctly handles a header/body arriving fragmented across many reads,
    and multiple complete frames already buffered from a single underlying
    read — both cases are transparent because :class:`asyncio.StreamReader`
    buffers internally; this function only ever consumes exactly one frame
    per call.

    Args:
        reader: The stream to read one frame from (typically a child
            process's ``stdout``).
        max_header_bytes: Cap on the header block, before the body is even
            located. Defaults to :data:`MAX_HEADER_BYTES`.
        max_frame_bytes: Cap on the declared ``Content-Length`` body size,
            checked before the body is read. Defaults to
            :data:`MAX_FRAME_BYTES`.

    Returns:
        The parsed, discriminated message.

    Raises:
        LSPFailure: ``"protocol_error"`` for a malformed/oversized frame or
            an invalid JSON-RPC shape; ``"server_crashed"`` for a
            connection that closed before a complete frame was received.
    """
    headers = await _read_header_block(reader, max_header_bytes)
    content_length = _extract_content_length(headers, max_frame_bytes)
    body = await _read_body(reader, content_length)
    return _parse_body(body)


async def _read_header_block(reader: asyncio.StreamReader, max_header_bytes: int) -> dict[str, str]:
    """Read ``name: value`` header lines up to the blank line that ends them.

    Raises:
        LSPFailure: ``"protocol_error"`` for a header block exceeding
            ``max_header_bytes``, a non-ASCII line, or a line without a
            ``:`` separator; ``"server_crashed"`` for EOF before the blank
            line that terminates the block.
    """
    headers: dict[str, str] = {}
    total = 0
    while True:
        line = await reader.readline()
        if not line:
            raise LSPFailure("server_crashed", "connection closed before a header block completed")
        total += len(line)
        if total > max_header_bytes:
            raise LSPFailure("protocol_error", f"header block exceeded the {max_header_bytes}-byte cap")
        if line in (b"\r\n", b"\n"):
            return headers
        try:
            decoded = line.decode("ascii")
        except UnicodeDecodeError as exc:
            raise LSPFailure("protocol_error", "header line is not ASCII") from exc
        decoded = decoded.rstrip("\r\n")
        name, separator, value = decoded.partition(":")
        if not separator:
            raise LSPFailure("protocol_error", f"malformed header line: {decoded!r}")
        headers[name.strip().lower()] = value.strip()


def _extract_content_length(headers: Mapping[str, str], max_frame_bytes: int) -> int:
    """Return the validated, in-bounds ``Content-Length`` header value.

    Raises:
        LSPFailure: ``"protocol_error"`` if the header is missing, not an
            integer, negative, or exceeds ``max_frame_bytes``.
    """
    raw_value = headers.get("content-length")
    if raw_value is None:
        raise LSPFailure("protocol_error", "frame is missing a Content-Length header")
    try:
        content_length = int(raw_value)
    except ValueError as exc:
        raise LSPFailure("protocol_error", f"Content-Length is not an integer: {raw_value!r}") from exc
    if content_length < 0:
        raise LSPFailure("protocol_error", f"Content-Length must not be negative: {content_length}")
    if content_length > max_frame_bytes:
        raise LSPFailure("protocol_error", f"frame of {content_length} bytes exceeds the {max_frame_bytes}-byte cap")
    return content_length


async def _read_body(reader: asyncio.StreamReader, content_length: int) -> bytes:
    """Read exactly ``content_length`` raw bytes — never fewer, never more.

    ``content_length`` is a byte count, so this always reads exactly that
    many bytes regardless of how many Unicode characters they decode to.

    Raises:
        LSPFailure: ``"server_crashed"`` if the connection closes before
            ``content_length`` bytes have arrived.
    """
    try:
        return await reader.readexactly(content_length)
    except asyncio.IncompleteReadError as exc:
        raise LSPFailure("server_crashed", "connection closed before a full frame body was received") from exc


def _parse_body(body: bytes) -> ParsedMessage:
    """Strictly decode+validate one frame body into a :class:`ParsedMessage`.

    Raises:
        LSPFailure: ``"protocol_error"`` for non-UTF-8 bytes, non-JSON
            text, a non-object JSON value, a missing/mismatched
            ``jsonrpc`` version, a boolean/malformed ``id``, or a shape
            that is neither a valid request, response, nor notification.
    """
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LSPFailure("protocol_error", "frame body is not valid UTF-8") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LSPFailure("protocol_error", f"frame body is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise LSPFailure("protocol_error", "frame body must be a JSON object")
    if raw.get("jsonrpc") != JSONRPC_VERSION:
        raise LSPFailure("protocol_error", f"unsupported or missing jsonrpc version: {raw.get('jsonrpc')!r}")

    message_id = raw.get("id")
    if "id" in raw and message_id is not None:
        if isinstance(message_id, bool) or not isinstance(message_id, (int, str)):
            raise LSPFailure("protocol_error", f"id must be a string or number, got {type(message_id).__name__}")

    method = raw.get("method")
    has_result = "result" in raw
    has_error = "error" in raw

    if method is not None:
        if not isinstance(method, str):
            raise LSPFailure("protocol_error", "method must be a string")
        if has_result or has_error:
            raise LSPFailure("protocol_error", "a request/notification must not carry 'result' or 'error'")
        kind: FrameKind = "request" if "id" in raw and message_id is not None else "notification"
        return ParsedMessage(
            kind=kind, id=message_id, method=method, params=raw.get("params"), result=None, error=None, raw=raw
        )

    if "id" in raw:
        if has_result and has_error:
            raise LSPFailure("protocol_error", "a response must not carry both 'result' and 'error'")
        if not has_result and not has_error:
            raise LSPFailure("protocol_error", "a response must carry either 'result' or 'error'")
        error_obj = raw.get("error")
        if has_error and not isinstance(error_obj, dict):
            raise LSPFailure("protocol_error", "'error' must be a JSON object")
        return ParsedMessage(
            kind="response", id=message_id, method=None, params=None, result=raw.get("result"), error=error_obj, raw=raw
        )

    raise LSPFailure("protocol_error", "message is neither a valid request, response, nor notification")


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


async def write_message(
    writer: asyncio.StreamWriter,
    message: Mapping[str, Any],
    *,
    max_frame_bytes: int = MAX_FRAME_BYTES,
) -> None:
    """Encode ``message`` as one ``Content-Length``-framed JSON-RPC frame.

    ``Content-Length`` is computed from the UTF-8-encoded body, in bytes —
    never from the decoded string's character count — so a message
    containing multi-byte Unicode content is always framed correctly.

    Args:
        writer: The stream to write the frame to (typically a child
            process's ``stdin``). Only ``write()``/``drain()`` are used, so
            any object exposing that shape (e.g. a test double) works.
        message: The JSON-RPC message body. ``jsonrpc`` is defaulted to
            :data:`JSONRPC_VERSION` if not already present.
        max_frame_bytes: Cap on the encoded body size. Defaults to
            :data:`MAX_FRAME_BYTES`.

    Raises:
        LSPFailure: ``"protocol_error"`` if ``message`` is not
            JSON-serializable or its encoded body exceeds
            ``max_frame_bytes``.
    """
    payload = dict(message)
    payload.setdefault("jsonrpc", JSONRPC_VERSION)
    try:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LSPFailure("protocol_error", f"outgoing message is not JSON-serializable: {exc}") from exc
    if len(body) > max_frame_bytes:
        raise LSPFailure(
            "protocol_error", f"outgoing frame of {len(body)} bytes exceeds the {max_frame_bytes}-byte cap"
        )
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    writer.write(header)
    writer.write(body)
    await writer.drain()


def build_request(request_id: int | str, method: str, params: Any = None) -> dict[str, Any]:
    """Build a JSON-RPC request body, preserving ``request_id``'s exact type.

    Args:
        request_id: The id the eventual response must echo back unchanged.
        method: The request method name.
        params: The request parameters, omitted from the body if ``None``.

    Returns:
        A plain ``dict`` ready for :func:`write_message`.
    """
    payload: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def build_notification(method: str, params: Any = None) -> dict[str, Any]:
    """Build a JSON-RPC notification body (no ``id``, never replied to).

    Args:
        method: The notification method name.
        params: The notification parameters, omitted from the body if
            ``None``.

    Returns:
        A plain ``dict`` ready for :func:`write_message`.
    """
    payload: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def build_response(request_id: int | str, *, result: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a JSON-RPC response body, echoing ``request_id`` unchanged.

    Args:
        request_id: The exact id from the request being answered.
        result: The success result. Ignored if ``error`` is given.
        error: The JSON-RPC error object, if this is an error response.

    Returns:
        A plain ``dict`` ready for :func:`write_message`.

    Raises:
        ValueError: If both ``result`` and ``error`` are given — a
            response must carry exactly one of them.
    """
    if error is not None and result is not None:
        raise ValueError("a JSON-RPC response carries either 'result' or 'error', never both")
    payload: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": request_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    return payload
