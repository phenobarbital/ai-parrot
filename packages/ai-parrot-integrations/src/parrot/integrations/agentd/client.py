"""Async Unix-domain-socket JSON-RPC client for the Agent CLI Daemon.

Implements Module 6 of ``sdd/specs/agent-cli-daemon.spec.md``: the single
shared client consumed by the Rich console (``proxy.py``, TASK-2214), the
one-shot ``parrot ask`` command, and the MCP stdio proxy
(``mcp_server.py``, TASK-2215). A background reader task demultiplexes
incoming NDJSON lines: RPC responses are matched to pending futures by
``id``; streaming ``chat.*`` notifications are routed by ``stream_id`` to
per-stream queues; ``event.*`` notifications are delivered to an optional
callback.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from .config import default_socket_path
from .protocol import (
    DEFAULT_MAX_LINE_BYTES,
    METHOD_CHAT_COMPLETE,
    METHOD_CHAT_DELTA,
    METHOD_CHAT_ERROR,
    METHOD_CHAT_SEND,
    METHOD_EVENTS_SUBSCRIBE,
    MalformedMessageError,
    OversizedLineError,
    ProtocolError,
    RpcNotification,
    RpcRequest,
    RpcResponse,
    read_message,
    write_message,
)

__all__ = [
    "AgentDaemonClient",
    "ConnectionClosed",
    "DaemonNotRunning",
    "RpcRemoteError",
    "StreamEvent",
    "resolve_socket",
]

#: Bounded queue size for per-stream notification delivery -- backpressure:
#: a slow stream consumer blocks further daemon writes on this connection
#: rather than growing client memory without bound.
_STREAM_QUEUE_MAXSIZE = 1024


def resolve_socket(name_or_path: str) -> Path:
    """Resolve a daemon identifier into a concrete socket path.

    Args:
        name_or_path: Either an existing filesystem path to a socket, or a
            bare service name (resolved via `default_socket_path()`).

    Returns:
        The concrete socket path (existence/liveness is NOT re-checked
        here — `AgentDaemonClient.connect()` handles that).
    """
    candidate = Path(name_or_path)
    if candidate.exists():
        return candidate
    return default_socket_path(name_or_path)


class DaemonNotRunning(Exception):
    """Raised when `connect()` exhausts its retries with no live daemon."""


class ConnectionClosed(Exception):
    """Raised against pending calls/streams when the connection is closed."""


class RpcRemoteError(Exception):
    """Raised when a `call()` receives a JSON-RPC error response.

    Attributes:
        code: The JSON-RPC (or agentd application-range) error code.
        message: The error message.
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class StreamEvent(BaseModel):
    """One event yielded by `AgentDaemonClient.stream()`.

    Attributes:
        kind: `"delta"`, `"complete"`, or `"error"`.
        text: Incremental text (only set when `kind == "delta"`).
        response: Final response (only set when `kind == "complete"`).
        usage: Usage metadata (only set when `kind == "complete"`).
        error: Error message (only set when `kind == "error"`).
    """

    kind: Literal["delta", "complete", "error"]
    text: str | None = None
    response: Any | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None


class AgentDaemonClient:
    """Async JSON-RPC 2.0 / NDJSON client over a Unix domain socket.

    Attributes:
        on_event: Optional callback invoked with `(method, params)` for
            every `event.*` notification received (scheduler/daemon
            fan-out events — distinct from `chat.*` stream notifications).
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
        on_event: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._max_line_bytes = max_line_bytes
        self.on_event = on_event
        self.logger = logging.getLogger(__name__)

        self._id_counter = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._streams: dict[str, asyncio.Queue] = {}
        self._closed = False
        self._reader_task = asyncio.ensure_future(self._read_loop())

    @classmethod
    async def connect(
        cls,
        socket_path: Path,
        *,
        retries: int = 3,
        backoff: float = 0.5,
        on_event: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> AgentDaemonClient:
        """Connect to a daemon's UDS socket, retrying with a fixed backoff.

        Args:
            socket_path: Path to the daemon's Unix domain socket.
            retries: Number of connection attempts before giving up.
            backoff: Seconds to sleep between attempts (survives a
                `systemctl restart` window).
            on_event: Optional `event.*` notification callback.

        Returns:
            A connected `AgentDaemonClient`.

        Raises:
            DaemonNotRunning: If all `retries` attempts fail, with an
                actionable message.
        """
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                # `limit` MUST match the server's `max_line_bytes`. Without
                # it asyncio caps the StreamReader at its 64 KiB default, so
                # any reply larger than that makes `readuntil(b"\n")` raise
                # LimitOverrunError, kills the reader task, and surfaces on
                # every pending call as the very misleading "Connection
                # closed by daemon" -- while the daemon had in fact answered
                # correctly. Agent replies carrying a structured artifact,
                # or a bridged tool result (FEAT-434), routinely exceed it.
                reader, writer = await asyncio.open_unix_connection(
                    path=str(socket_path), limit=DEFAULT_MAX_LINE_BYTES
                )
                return cls(reader, writer, on_event=on_event)
            except OSError as exc:
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(backoff)

        raise DaemonNotRunning(
            f"No daemon listening on {socket_path} after {retries} attempt(s). "
            "Start it with 'parrot serve <config.yaml|module:attr>', or check "
            f"'systemctl --user status parrot-<name>' ({last_exc})."
        )

    async def call(
        self,
        method: str,
        *,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Issue a request and await its response.

        Args:
            method: RPC method name.
            params: Explicit params mapping. Merged with `**kwargs` (kwargs
                win on key collision) -- use this when a param key would
                otherwise collide with this method's own `method`/`params`
                argument names (e.g. `agent.invoke`'s own `"method"` param:
                `call("agent.invoke", params={"method": "some_method"})`).
            **kwargs: Method parameters, for the common case where no
                param name collides with `call()`'s own signature.

        Returns:
            The response `result`.

        Raises:
            RpcRemoteError: If the daemon returns an error response.
            ConnectionClosed: If the connection closes before a response
                arrives.
        """
        merged_params = {**(params or {}), **kwargs}
        request_id = next(self._id_counter)
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future
        try:
            write_message(
                self._writer,
                RpcRequest(id=request_id, method=method, params=merged_params),
            )
            await self._writer.drain()
            response: RpcResponse = await future
        finally:
            self._pending.pop(request_id, None)

        if response.error is not None:
            raise RpcRemoteError(response.error.code, response.error.message)
        return response.result

    async def stream(self, prompt: str, **metadata: Any) -> AsyncIterator[StreamEvent]:
        """Issue a streaming `chat.send` and yield events as they arrive.

        Args:
            prompt: The prompt to send.
            **metadata: Extra `chat.send` metadata, passed through as-is.

        Yields:
            Zero or more `kind="delta"` events, followed by exactly one
            terminal `kind="complete"` or `kind="error"` event.
        """
        # The stream_id is generated CLIENT-side and the queue registered
        # BEFORE the request is even sent (rather than waiting for the
        # daemon's ack to hand one back). `_read_loop()` is a single task
        # processing the wire strictly in order, but it does not yield
        # back to this coroutine between processing the ack and the very
        # next buffered line -- for a fast/local daemon, `chat.delta`
        # notifications can already be queued up behind the ack by the
        # time it resumes. Registering the queue first closes that race:
        # any notification for this stream_id always finds its queue.
        stream_id = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue(maxsize=_STREAM_QUEUE_MAXSIZE)
        self._streams[stream_id] = queue

        try:
            ack = await self.call(
                METHOD_CHAT_SEND,
                prompt=prompt,
                stream=True,
                stream_id=stream_id,
                metadata=metadata,
            )
            assert ack.get("stream_id", stream_id) == stream_id
        except Exception:
            self._streams.pop(stream_id, None)
            raise

        try:
            while True:
                item = await queue.get()
                if isinstance(item, BaseException):
                    raise item
                yield item
                if item.kind in ("complete", "error"):
                    break
        finally:
            self._streams.pop(stream_id, None)

    async def subscribe_events(
        self, callback: Callable[[str, dict[str, Any]], Any]
    ) -> None:
        """Subscribe to daemon/scheduler events and register the callback.

        Args:
            callback: Invoked with `(method, params)` for every `event.*`
                notification received from this point on.
        """
        self.on_event = callback
        await self.call(METHOD_EVENTS_SUBSCRIBE)

    async def close(self) -> None:
        """Close the connection: cancel the reader, fail pending calls/streams."""
        if self._closed:
            return
        self._closed = True

        self._reader_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._reader_task

        self._fail_all(ConnectionClosed("Connection closed"))

        with contextlib.suppress(Exception):
            self._writer.close()
        with contextlib.suppress(Exception):
            await self._writer.wait_closed()

    def _fail_all(self, exc: Exception) -> None:
        """Fail every pending call and stream with `exc` (idempotent)."""
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()

        for queue in list(self._streams.values()):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(exc)
        self._streams.clear()

    async def _read_loop(self) -> None:
        """Background task: demux incoming lines to pending futures/streams.

        Must never die silently -- on EOF, protocol error, or unexpected
        exception, every pending call/stream is failed with
        `ConnectionClosed` so callers never hang.
        """
        try:
            while True:
                try:
                    message = await read_message(
                        self._reader, max_line_bytes=self._max_line_bytes
                    )
                except (MalformedMessageError, OversizedLineError, ProtocolError) as exc:
                    self.logger.warning("Protocol error from daemon: %s", exc)
                    break

                if message is None:
                    break  # Clean EOF.

                if isinstance(message, RpcResponse):
                    future = self._pending.get(message.id)
                    if future is not None and not future.done():
                        future.set_result(message)
                elif isinstance(message, RpcNotification):
                    self._dispatch_notification(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger.exception("agentd client reader loop crashed")

        self._fail_all(ConnectionClosed("Connection closed by daemon"))

    def _dispatch_notification(self, note: RpcNotification) -> None:
        """Route one notification to its stream queue or the event callback."""
        if note.method in (METHOD_CHAT_DELTA, METHOD_CHAT_COMPLETE, METHOD_CHAT_ERROR):
            stream_id = note.params.get("stream_id")
            queue = self._streams.get(stream_id)
            if queue is None:
                self.logger.debug(
                    "Notification for unknown stream_id=%r: %s",
                    stream_id,
                    note.method,
                )
                return
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(self._to_stream_event(note))
        elif note.method.startswith("event."):
            if self.on_event is not None:
                self.on_event(note.method, note.params)
        else:
            self.logger.debug("Unhandled notification method: %s", note.method)

    @staticmethod
    def _to_stream_event(note: RpcNotification) -> StreamEvent:
        """Convert a `chat.*` notification into a typed `StreamEvent`."""
        if note.method == METHOD_CHAT_DELTA:
            return StreamEvent(kind="delta", text=note.params.get("text"))
        if note.method == METHOD_CHAT_COMPLETE:
            return StreamEvent(
                kind="complete",
                response=note.params.get("response"),
                usage=note.params.get("usage"),
            )
        return StreamEvent(kind="error", error=note.params.get("error"))
