"""Unix-domain-socket JSON-RPC server for the Agent CLI Daemon (agentd).

Implements Module 4 of ``sdd/specs/agent-cli-daemon.spec.md``: the
transport server sitting between the wire protocol (``protocol.py``,
TASK-2208) and the daemon service (``service.py``, TASK-2212). Owns the
socket lifecycle (including stale-socket detection), per-connection
``Session`` state, method dispatch, streaming notification delivery, and
event fan-out via ``EventBroker``.

No RPC method implementations live here — those are supplied by the caller
as a ``dispatch`` mapping (built by ``AgentDaemon`` in TASK-2212).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import pwd
import socket
import struct
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from parrot.auth.permission import PermissionContext, build_principal_context
from pydantic import ValidationError

from .config import ServiceIdentityConfig
from .protocol import (
    DEFAULT_MAX_LINE_BYTES,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    MalformedMessageError,
    OversizedLineError,
    RpcError,
    RpcNotification,
    RpcRequest,
    RpcResponse,
    read_message,
    write_message,
)

__all__ = [
    "DaemonAlreadyRunning",
    "EventBroker",
    "Handler",
    "JsonRpcUnixServer",
    "RpcHandlerError",
    "Session",
]

#: `struct` format for `SO_PEERCRED`'s `(pid, uid, gid)` triple on Linux.
_PEERCRED_FORMAT = "3i"


def _read_peercred(sock: socket.socket) -> tuple[int, int, int]:
    """Blocking `SO_PEERCRED` read — always run via `asyncio.to_thread()`.

    Args:
        sock: The connection's underlying socket.

    Returns:
        The peer's `(pid, uid, gid)`.
    """
    raw = sock.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize(_PEERCRED_FORMAT)
    )
    return struct.unpack(_PEERCRED_FORMAT, raw)


def _uid_to_username(uid: int) -> str:
    """Blocking NSS uid -> username lookup — always run via `asyncio.to_thread()`.

    Args:
        uid: The OS user id to resolve.

    Returns:
        The resolved username.

    Raises:
        KeyError: If `uid` has no `pwd` entry.
    """
    return pwd.getpwuid(uid).pw_name


class DaemonAlreadyRunning(Exception):
    """Raised when a live daemon is already listening on the socket path."""


class RpcHandlerError(Exception):
    """Raised by a dispatch handler to return a specific JSON-RPC error.

    Use this instead of a bare exception when a handler needs to surface
    one of the application-range error codes (spec §2 "Wire Protocol":
    `AGENT_BUSY`, `UNKNOWN_AGENT_METHOD`, `SCHEDULER_UNAVAILABLE`,
    `SCHEDULE_NOT_FOUND`) rather than the generic `INTERNAL_ERROR`
    fallback every other exception gets.

    Attributes:
        code: The JSON-RPC (or agentd application-range) error code.
        message: The error message.
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Session:
    """Per-connection state for one UDS client.

    Attributes:
        session_id: Unique identifier for this connection (its own
            "conversation session", per spec §2).
        writer: The connection's ``asyncio.StreamWriter``.
        subscribed: Whether this session is subscribed to broadcast events
            via ``EventBroker``.
        stream_ids: Active `chat.send(stream=true)` stream identifiers for
            this session.
        tasks: In-flight handler tasks for this session (tracked so they
            can be cancelled on disconnect).
        permission_context: The caller's resolved `PermissionContext`
            (FEAT-434) — the OS user of the UDS peer, or the configured
            service identity when peer credentials are unavailable. `None`
            until `JsonRpcUnixServer._handle_connection` resolves it.
        identity_source: How `permission_context` was resolved — one of
            `"peercred"` or `"service_identity"` — for logging/audit.
    """

    def __init__(self, session_id: str, writer: asyncio.StreamWriter) -> None:
        self.session_id = session_id
        self.writer = writer
        self.subscribed = False
        self.stream_ids: set[str] = set()
        self.tasks: set[asyncio.Task] = set()
        self._lock = asyncio.Lock()
        self.permission_context: PermissionContext | None = None
        self.identity_source: str | None = None

    async def send(self, message: RpcResponse | RpcNotification) -> None:
        """Serialize and write one message, serialized under this session's lock.

        Args:
            message: The response or notification to send.
        """
        async with self._lock:
            write_message(self.writer, message)
            await self.writer.drain()

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a server-initiated notification (e.g. `chat.delta`).

        Args:
            method: Notification method name.
            params: Notification payload.
        """
        await self.send(RpcNotification(method=method, params=params))


#: Signature every dispatch table entry must implement.
Handler = Callable[[Session, dict[str, Any]], Awaitable[Any]]


class EventBroker:
    """Subscribe/fan-out broadcaster for scheduler/daemon events.

    Sessions opt in via `subscribe()` (typically from an `events.subscribe`
    RPC handler) and receive every `publish()`ed notification until they
    `unsubscribe()` or disconnect.
    """

    def __init__(self) -> None:
        self._subscribers: set[Session] = set()
        self.logger = logging.getLogger(__name__)

    def subscribe(self, session: Session) -> None:
        """Add `session` to the broadcast set."""
        session.subscribed = True
        self._subscribers.add(session)

    def unsubscribe(self, session: Session) -> None:
        """Remove `session` from the broadcast set (idempotent)."""
        session.subscribed = False
        self._subscribers.discard(session)

    async def publish(self, method: str, params: dict[str, Any]) -> None:
        """Fan out a notification to every subscribed session.

        Dead/broken connections are dropped silently (best-effort
        broadcast) rather than raising — one bad subscriber must not break
        delivery to the rest.

        Args:
            method: Notification method name (e.g. `event.job_executed`).
            params: Notification payload.
        """
        for session in list(self._subscribers):
            try:
                await session.notify(method, params)
            except Exception:  # noqa: BLE001 - isolate broadcast failures
                self.logger.debug(
                    "Dropping dead subscriber %s", session.session_id
                )
                self._subscribers.discard(session)


class JsonRpcUnixServer:
    """JSON-RPC 2.0 / NDJSON server over a Unix domain socket.

    Attributes:
        socket_path: Path to the UDS socket file.
        dispatch: Mapping of RPC method name to `Handler`. Mutable after
            construction — callers may add/replace entries at any time
            (the same `dict` object is retained, not copied).
        max_line_bytes: NDJSON line-size limit passed to `read_message()`.
        event_broker: Shared `EventBroker` for this server instance.
        service_identity: Fallback caller identity (FEAT-434) used when a
            UDS peer's credentials cannot be resolved via `SO_PEERCRED`.
    """

    def __init__(
        self,
        socket_path: Path,
        dispatch: dict[str, Handler],
        *,
        max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
        service_identity: ServiceIdentityConfig | None = None,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.dispatch = dispatch
        self.max_line_bytes = max_line_bytes
        self.event_broker = EventBroker()
        self.service_identity = service_identity or ServiceIdentityConfig.from_env()
        self.logger = logging.getLogger(__name__)
        self._server: asyncio.Server | None = None
        self._sessions: dict[str, Session] = {}

    @property
    def active_connections(self) -> int:
        """Number of currently connected sessions."""
        return len(self._sessions)

    async def start(self) -> None:
        """Bind and start accepting connections.

        Raises:
            DaemonAlreadyRunning: If a live daemon already owns
                `socket_path`.
        """
        await self._prepare_socket_path()
        # Defense in depth: even though the parent dir is already 0700
        # (unreachable to other local users), narrow the process umask
        # for the bind itself so the socket is never briefly created with
        # looser permissions before the chmod() below lands.
        previous_umask = os.umask(0o177)
        try:
            self._server = await asyncio.start_unix_server(
                self._handle_connection,
                path=str(self.socket_path),
                limit=self.max_line_bytes,
            )
        finally:
            os.umask(previous_umask)
        os.chmod(self.socket_path, 0o600)
        self.logger.info("agentd UDS server listening on %s", self.socket_path)

    async def close(self) -> None:
        """Stop accepting connections, close all sessions, unlink the socket."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        for session in list(self._sessions.values()):
            await self._disconnect(session)

        if self.socket_path.exists():
            with contextlib.suppress(OSError):
                self.socket_path.unlink()

    async def _prepare_socket_path(self) -> None:
        """Create the parent dir (0700) and resolve any stale socket file.

        Raises:
            DaemonAlreadyRunning: If an existing socket at `socket_path` is
                still accepting connections (a daemon is already running).
        """
        parent = self.socket_path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(parent, 0o700)

        if self.socket_path.exists():
            if await self._socket_is_alive():
                raise DaemonAlreadyRunning(
                    f"A daemon is already listening on {self.socket_path}"
                )
            self.socket_path.unlink()

    async def _socket_is_alive(self) -> bool:
        """Try-connect to `socket_path` to tell a live socket from a dead one."""
        try:
            _, writer = await asyncio.open_unix_connection(
                path=str(self.socket_path)
            )
        except OSError:
            return False
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
        return True

    async def _resolve_identity(
        self, writer: asyncio.StreamWriter
    ) -> tuple[PermissionContext, str]:
        """Resolve the connecting peer's identity (FEAT-434).

        Reads `SO_PEERCRED` off the connection's underlying socket to get
        the peer's `(pid, uid, gid)`, then resolves the uid to an OS
        username via `pwd`. Falls back to the configured service identity
        when peer credentials are unavailable — non-UDS transport
        (`AttributeError`/`OSError`), non-Linux (`AttributeError` on
        `socket.SO_PEERCRED`), or an unresolvable uid (`KeyError`). The
        literal `"anonymous"` never appears on this path.

        Both syscalls are dispatched via `asyncio.to_thread()` — `pwd`
        lookups are typically instant against local NSS, but a deployment
        resolving `passwd` through a remote backend (LDAP/SSSD) must not
        stall the accept loop for every other connecting session while
        one lookup is in flight.

        Args:
            writer: The connection's `asyncio.StreamWriter`.

        Returns:
            A `(permission_context, identity_source)` tuple, where
            `identity_source` is `"peercred"` or `"service_identity"`.
        """
        try:
            sock = writer.get_extra_info("socket")
            if sock is None:
                raise OSError("no underlying socket available on this transport")
            _pid, uid, _gid = await asyncio.to_thread(_read_peercred, sock)
            username = await asyncio.to_thread(_uid_to_username, uid)
            return build_principal_context(username, channel="agentd"), "peercred"
        except (AttributeError, OSError, KeyError) as exc:
            self.logger.debug(
                "Peer credentials unavailable (%s); falling back to service identity.",
                exc,
            )
            return self.service_identity.to_permission_context(), "service_identity"

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Per-connection accept-loop callback for `start_unix_server`."""
        session = Session(session_id=str(uuid.uuid4()), writer=writer)
        session.permission_context, session.identity_source = (
            await self._resolve_identity(writer)
        )
        self._sessions[session.session_id] = session
        self.logger.info(
            "Session %s connected: identity resolved via %s (user_id=%s)",
            session.session_id,
            session.identity_source,
            session.permission_context.user_id,
        )

        try:
            while True:
                try:
                    message = await read_message(
                        reader, max_line_bytes=self.max_line_bytes
                    )
                except OversizedLineError as exc:
                    with contextlib.suppress(Exception):
                        await session.send(
                            RpcResponse(
                                id=None,
                                error=RpcError(
                                    code=INVALID_REQUEST, message=str(exc)
                                ),
                            )
                        )
                    break
                except MalformedMessageError as exc:
                    with contextlib.suppress(Exception):
                        await session.send(
                            RpcResponse(
                                id=exc.rpc_id,
                                error=RpcError(code=PARSE_ERROR, message=str(exc)),
                            )
                        )
                    continue

                if message is None:
                    break  # Clean EOF.

                if isinstance(message, RpcRequest):
                    task = asyncio.create_task(self._run_handler(session, message))
                    session.tasks.add(task)
                    task.add_done_callback(session.tasks.discard)
                else:
                    self.logger.debug(
                        "Ignoring unsupported inbound message type: %s",
                        type(message).__name__,
                    )
        finally:
            await self._disconnect(session)

    async def _run_handler(self, session: Session, request: RpcRequest) -> None:
        """Dispatch one request to its handler and send back the response.

        Every failure mode is converted into a JSON-RPC error response —
        the connection (and the server) stay alive regardless of handler
        exceptions.
        """
        handler = self.dispatch.get(request.method)
        if handler is None:
            response = RpcResponse(
                id=request.id,
                error=RpcError(
                    code=METHOD_NOT_FOUND,
                    message=f"Unknown method: {request.method}",
                ),
            )
        else:
            try:
                result = await handler(session, request.params)
                response = RpcResponse(id=request.id, result=result)
            except RpcHandlerError as exc:
                response = RpcResponse(
                    id=request.id,
                    error=RpcError(code=exc.code, message=exc.message),
                )
            except ValidationError as exc:
                response = RpcResponse(
                    id=request.id,
                    error=RpcError(code=INVALID_PARAMS, message=str(exc)),
                )
            except Exception as exc:
                self.logger.exception(
                    "Handler for %r raised an exception", request.method
                )
                response = RpcResponse(
                    id=request.id,
                    error=RpcError(code=INTERNAL_ERROR, message=str(exc)),
                )

        with contextlib.suppress(Exception):
            await session.send(response)

    async def _disconnect(self, session: Session) -> None:
        """Tear down a session: cancel tasks, unsubscribe, close the writer."""
        for task in list(session.tasks):
            task.cancel()
        if session.tasks:
            await asyncio.gather(*session.tasks, return_exceptions=True)

        self.event_broker.unsubscribe(session)
        self._sessions.pop(session.session_id, None)

        with contextlib.suppress(Exception):
            session.writer.close()
        with contextlib.suppress(Exception):
            await session.writer.wait_closed()

        self.logger.debug("Session %s disconnected", session.session_id)
