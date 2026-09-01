"""MCP Streamable HTTP transport (spec revision 2025-03-26).

Implements the single-endpoint Streamable HTTP transport required by
Claude.ai custom connectors and the official MCP SDK client:

- ``POST {base_path}``: JSON-RPC messages (single or batch). Bodies with
  only notifications/responses are acknowledged with ``202``. Bodies with
  requests are answered as ``application/json``, or as an SSE stream when
  the client's ``Accept`` header includes ``text/event-stream``.
- ``GET {base_path}``: opens the session's server-to-client SSE stream.
  Supports resumability via ``Last-Event-ID``: buffered events after that
  id are replayed in order, so a client that disconnected during a
  long-running ``tools/call`` (e.g. launching an agent flow) can reconnect
  and still collect the result.
- ``DELETE {base_path}``: terminates the session.

Sessions are identified by the ``Mcp-Session-Id`` header minted on
``initialize``. Request dispatch in SSE mode runs as asyncio tasks that
record their responses in a per-*stream* event buffer regardless of
connection state, which is what makes disconnect-and-resume possible.

Streams, not sessions, own their events. Each request-bearing POST opens
its own stream and only that stream's SSE response writes its events, so
a concurrently open ``GET`` stream can never consume a response the POST
still owes its client (the spec requires the response to travel on the
stream that carried the request). Event ids are
``{stream_id}:{sequence}``, so a client that reconnects with
``Last-Event-ID`` names the stream it was cut off from and receives that
stream and nothing else. A plain ``GET`` is the session's
server-to-client stream; it additionally *adopts* streams orphaned by a
disconnected client, which is what lets a client collect a long tool
call's result after a drop without having kept the event id.

The event store is in-memory and per-process, matching how the rest of
the MCP server stack keeps state; a shared (e.g. Redis-backed) store for
multi-worker deployments is a documented follow-up.
"""

import asyncio
import contextlib
import hashlib
import json
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from aiohttp import web
from parrot.mcp.server_base import SUPPORTED_PROTOCOL_VERSIONS

from parrot.mcp.config import AuthMethod, MCPServerConfig
from parrot.mcp.session_store import (
    InMemorySessionStore,
    SessionStore,
    SessionStoreUnavailable,
)
from parrot.mcp.transports.http import HttpMCPServer

#: Seconds between SSE keep-alive comments on an idle stream.
KEEP_ALIVE_INTERVAL: float = 15.0

#: Seconds between background sweeps for idle sessions. Pruning also runs
#: lazily on session lookup; the sweep is what reclaims sessions on a
#: server that stops receiving requests entirely.
PRUNE_INTERVAL: float = 60.0

#: Version assumed when a request carries no ``MCP-Protocol-Version``
#: header, per the 2025-06-18 spec's backwards-compatibility rule.
ASSUMED_HEADER_VERSION: str = "2025-03-26"

#: Origins always accepted regardless of configuration — a loopback origin
#: cannot be produced by the DNS-rebinding attack Origin checking exists
#: to stop.
LOCALHOST_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})

#: Seconds to wait for cancelled dispatch tasks before abandoning them,
#: so a tool that swallows cancellation cannot hang DELETE or shutdown.
TEARDOWN_TIMEOUT: float = 5.0

#: Stream id of the session's dedicated server-to-client stream.
SERVER_STREAM: str = "server"


def _cancelled_by_caller() -> bool:
    """True when the *current* task is the one being cancelled.

    ``await``ing a child task that gets cancelled also raises
    ``CancelledError`` here, and that case must not be confused with aiohttp
    tearing the request handler down — swallowing the latter would keep a
    dead handler alive.
    """
    task = asyncio.current_task()
    return bool(task is not None and task.cancelling())


def _jsonrpc_error(code: int, message: str, request_id: Any = None) -> dict[str, Any]:
    """Build a JSON-RPC error object."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


@dataclass
class StreamEvent:
    """One buffered outbound JSON-RPC message with its SSE event id."""

    stream_id: str
    sequence: int
    message: dict[str, Any]
    delivered: bool = False

    @property
    def event_id(self) -> str:
        """SSE ``id:`` value — scoped to the stream that produced it."""
        return f"{self.stream_id}:{self.sequence}"

    def to_sse(self) -> bytes:
        """Serialize as an SSE ``message`` event carrying the event id."""
        data = json.dumps(self.message)
        return (f"id: {self.event_id}\nevent: message\ndata: {data}\n\n").encode()


def parse_event_id(raw: str) -> tuple[str, int] | None:
    """Split a ``Last-Event-ID`` into its ``(stream_id, sequence)`` parts.

    Args:
        raw: The header value sent by the client.

    Returns:
        The parsed pair, or ``None`` when the value is not a well-formed
        event id this server could have issued.
    """
    stream_id, sep, sequence = raw.rpartition(":")
    if not sep or not stream_id:
        return None
    try:
        return stream_id, int(sequence)
    except ValueError:
        return None


class StreamBuffer:
    """Ordered, bounded buffer of outbound messages for one SSE stream.

    Sequence numbers increase monotonically per stream and combine with the
    stream id to form the SSE ``id:`` field, so a client can resume with
    ``Last-Event-ID`` after a disconnect. The buffer is a ring: once
    ``max_events`` is exceeded the oldest events are dropped (no longer
    replayable).
    """

    def __init__(self, stream_id: str, max_events: int = 1000):
        self.stream_id = stream_id
        self._events: deque[StreamEvent] = deque(maxlen=max_events)
        self._counter = 0
        #: True while an SSE response is actively writing this stream. An
        #: unattached stream with undelivered events is orphaned, and the
        #: session's GET stream may adopt it.
        self.attached: bool = False

    def append(self, message: dict[str, Any]) -> StreamEvent:
        """Buffer an outbound message."""
        self._counter += 1
        event = StreamEvent(
            stream_id=self.stream_id,
            sequence=self._counter,
            message=message,
        )
        self._events.append(event)
        return event

    def events_after(self, sequence: int) -> list[StreamEvent]:
        """Return buffered events with a sequence greater than ``sequence``."""
        return [e for e in self._events if e.sequence > sequence]

    def undelivered(self) -> list[StreamEvent]:
        """Return buffered events not yet written to any stream."""
        return [e for e in self._events if not e.delivered]


@dataclass
class McpStreamSession:
    """State for one Streamable HTTP session."""

    session_id: str
    protocol_version: str
    created_at: float
    last_seen: float
    #: Stable identifier of the authenticated principal that opened the
    #: session, or ``None`` when the auth method establishes no identity.
    principal: Any = None
    streams: dict[str, StreamBuffer] = field(default_factory=dict)
    #: In-flight dispatch tasks keyed by their JSON-RPC request id, so
    #: ``notifications/cancelled`` and DELETE can reach them.
    tasks: dict[Any, asyncio.Task] = field(default_factory=dict)
    #: Set whenever a new event is appended anywhere in the session; the
    #: live GET stream waits on it and clears it after draining.
    wakeup: asyncio.Event = field(default_factory=asyncio.Event)
    #: True while a GET SSE stream is attached (one per session).
    live_stream: bool = False

    def open_stream(
        self,
        max_events: int,
        stream_id: str | None = None,
        max_streams: int = 64,
    ) -> StreamBuffer:
        """Create (or fetch) a buffer for one outbound stream.

        Opening a stream first reclaims spent ones, so a session that issues
        many SSE POSTs does not accumulate buffers for the whole of its TTL.
        """
        self.prune_streams(max_streams)
        stream_id = stream_id or secrets.token_urlsafe(6)
        buffer = self.streams.get(stream_id)
        if buffer is None:
            buffer = StreamBuffer(stream_id, max_events=max_events)
            self.streams[stream_id] = buffer
        return buffer

    def prune_streams(self, max_streams: int) -> None:
        """Keep at most ``max_streams`` streams, evicting the least useful.

        Streams are not dropped merely because their events were delivered —
        a client may still resume one from an earlier ``Last-Event-ID``. They
        are dropped only to stay under the cap, and then spent streams (no
        attached response, nothing undelivered) go first, oldest to newest,
        before any stream that still owes someone data. The server stream is
        permanent.
        """
        evictable = [
            stream_id
            for stream_id, buffer in self.streams.items()
            if stream_id != SERVER_STREAM and not buffer.attached
        ]
        # Spent streams first (insertion order preserved within each group).
        evictable.sort(key=lambda sid: bool(self.streams[sid].undelivered()))
        while len(self.streams) > max_streams and evictable:
            del self.streams[evictable.pop(0)]

    def is_busy(self) -> bool:
        """True when the session has a live stream or unfinished work."""
        return self.live_stream or any(not task.done() for task in self.tasks.values())


class StreamableHttpMCPServer(HttpMCPServer):
    """MCP server speaking the Streamable HTTP transport on aiohttp.

    Extends :class:`HttpMCPServer` (reusing auth, OAuth routes, and the
    parent-app/standalone mounting logic) with the 2025-03-26 transport
    semantics: session ids, ``Accept`` negotiation, SSE responses, a
    resumable GET stream, and DELETE session termination.
    """

    def __init__(
        self,
        config: MCPServerConfig,
        parent_app: web.Application | None = None,
        session_store: SessionStore | None = None,
    ):
        super().__init__(config, parent_app=parent_app)
        self._sessions: dict[str, McpStreamSession] = {}
        self._session_ttl: float = float(getattr(config, "session_ttl", 3600) or 3600)
        self._event_buffer_size: int = int(getattr(config, "event_buffer_size", 1000) or 1000)
        self._max_sessions: int = int(getattr(config, "max_sessions", 1000) or 1000)
        self._max_streams: int = int(getattr(config, "max_streams_per_session", 64) or 64)
        self._allowed_origins: list[str] | None = getattr(config, "allowed_origins", None)
        self._allow_any_origin: bool = bool(getattr(config, "allow_any_origin", False))
        # FEAT-477 TASK-2609: shared session + event store. Defaults to the
        # in-process implementation — an explicit choice preserving today's
        # single-worker behavior byte-for-byte (G11). Pass a
        # `RedisSessionStore` to make sessions/events visible across
        # gunicorn workers and survive a worker recycle; never an automatic
        # fallback (see `session_store.py`).
        self._session_store: SessionStore = session_store or InMemorySessionStore(
            ttl=int(self._session_ttl), max_events=self._event_buffer_size
        )
        self._prune_task: asyncio.Task | None = None

    def _register_routes(self, router, base_route: str) -> None:
        """Register POST/GET/DELETE on the single MCP endpoint."""
        router.add_post(base_route, self._handle_streamable_post)
        router.add_get(base_route, self._handle_streamable_get)
        router.add_delete(base_route, self._handle_streamable_delete)
        router.add_get(f"{base_route.rstrip('/')}/info", self._handle_info)

    async def start(self):
        """Start the server and its background session sweeper."""
        await super().start()
        if self._prune_task is None:
            self._prune_task = asyncio.create_task(self._prune_loop())

    async def stop(self):
        """Stop the server, cancelling pending dispatch tasks."""
        if self._prune_task is not None:
            self._prune_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._prune_task
            self._prune_task = None
        for session in list(self._sessions.values()):
            await self._teardown_session(session)
        self._sessions.clear()
        await super().stop()

    async def _handle_info(self, request: web.Request) -> web.Response:
        """Return server info."""
        return web.json_response(
            {
                "name": self.config.name,
                "version": self.config.version,
                "transport": "streamable-http",
                "protocol_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
                "tools_count": len(self.tools),
            }
        )

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _principal(self, request: web.Request) -> Any:
        """Return a stable identifier for the request's authenticated caller.

        Prefers the authenticated user id. Auth methods that validate a
        credential without attributing it to a user (internal OAuth) — or
        that hand back a principal with no recognisable id (navigator-auth
        session data) — fall back to a digest of the presented credential,
        so the session is at least bound to the token that opened it rather
        than shared across everyone the same method authenticates.

        ``None`` only when no authentication is configured at all, where
        there is no identity to bind to and ownership is not enforced.
        """
        user = request.get("mcp_user")
        if isinstance(user, dict):
            for key in ("user_id", "id", "sub", "username", "email"):
                value = user.get(key)
                if value:
                    return value
        elif user:
            return user

        if self.config.auth_method == AuthMethod.NONE:
            return None
        return self._credential_digest(request)

    def _credential_digest(self, request: web.Request) -> str | None:
        """Hash the presented credential, for binding without storing it."""
        credential = request.headers.get(self.config.api_key_header) or request.headers.get("Authorization")
        if not credential:
            return None
        return hashlib.sha256(credential.encode("utf-8")).hexdigest()

    async def _create_session(self, protocol_version: str, principal: Any = None) -> McpStreamSession | None:
        """Mint a new session with a cryptographically secure id.

        Returns ``None`` when the server is already holding its configured
        maximum number of sessions, so the caller can answer 503 instead of
        growing memory without bound.

        Mirrors the session's metadata into ``self._session_store``
        (FEAT-477 TASK-2609) so another worker sharing a
        ``RedisSessionStore`` can resolve it later (``_get_session``). This
        propagates ``SessionStoreUnavailable`` — an explicitly configured
        shared store that is unreachable must fail the request cleanly,
        never silently mint a session only this process knows about.
        """
        await self._prune_sessions()
        if len(self._sessions) >= self._max_sessions:
            self.logger.warning(
                "Refusing new MCP session: %s sessions already open (max_sessions)",
                len(self._sessions),
            )
            return None
        session_id = secrets.token_urlsafe(32)
        # Control-plane operation: fail closed (propagate
        # SessionStoreUnavailable) rather than mint a session this store
        # will never be able to resolve for another worker.
        await self._session_store.create_session(
            user=principal,
            protocol_version=protocol_version,
            session_id=session_id,
        )
        now = time.monotonic()
        session = McpStreamSession(
            session_id=session_id,
            protocol_version=protocol_version,
            created_at=now,
            last_seen=now,
            principal=principal,
        )
        self._sessions[session.session_id] = session
        return session

    async def _get_session(self, session_id: str, request: web.Request) -> McpStreamSession | None:
        """Look up a session, expiring it when past its TTL.

        A session is only returned to the principal that created it, so a
        leaked ``Mcp-Session-Id`` cannot be replayed under another identity.

        FEAT-477 TASK-2609: when the session is not held locally (this
        worker did not create it, or was recycled since), falls through to
        ``self._session_store``. A hit is adopted as a fresh local
        ``McpStreamSession`` shell — the durable identity/principal
        resolves correctly across workers, though in-flight dispatch tasks
        and a live GET stream are inherently per-process and cannot be
        recovered (buffered *events* still replay via the store; see
        ``_handle_streamable_get``). Propagates
        ``SessionStoreUnavailable`` so an explicitly configured shared
        store that is unreachable fails the request cleanly rather than
        silently reporting "session not found".
        """
        await self._prune_sessions()
        session = self._sessions.get(session_id)
        if session is None:
            record = await self._session_store.get_session(session_id)
            if record is None:
                return None
            if record.principal != self._principal(request):
                self.logger.warning("Rejecting MCP session %s: principal mismatch", session_id)
                return None
            now = time.monotonic()
            session = McpStreamSession(
                session_id=session_id,
                protocol_version=record.protocol_version,
                created_at=now,
                last_seen=now,
                principal=record.principal,
            )
            self._sessions[session_id] = session
            self.logger.info("Adopted MCP session %s from shared store (cross-worker)", session_id)
            return session
        if session.principal != self._principal(request):
            self.logger.warning("Rejecting MCP session %s: principal mismatch", session_id)
            return None
        session.last_seen = time.monotonic()
        return session

    async def _prune_loop(self) -> None:
        """Sweep idle sessions periodically, independent of traffic."""
        try:
            while True:
                await asyncio.sleep(PRUNE_INTERVAL)
                await self._prune_sessions()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the sweeper must never die
            self.logger.error("MCP session sweeper failed: %s", exc)

    async def _prune_sessions(self) -> None:
        """Drop sessions idle beyond the TTL.

        Sessions with an attached stream or unfinished dispatch work are
        never pruned — a long-running tool call must not have its session
        expire out from under it.
        """
        now = time.monotonic()
        expired = [
            sid
            for sid, session in self._sessions.items()
            if now - session.last_seen > self._session_ttl and not session.is_busy()
        ]
        for sid in expired:
            session = self._sessions.pop(sid, None)
            if session:
                await self._teardown_session(session)
                self.logger.info("Expired MCP session: %s", sid)

    async def _teardown_session(self, session: McpStreamSession) -> None:
        """Cancel a session's pending dispatch tasks and wake its stream.

        Waits for the cancellations to land so a 204 from DELETE means the
        work has actually stopped — but only up to ``TEARDOWN_TIMEOUT``, so a
        tool that swallows cancellation cannot hang session deletion or
        server shutdown.
        """
        tasks = [task for task in session.tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=TEARDOWN_TIMEOUT)
            if pending:
                self.logger.warning(
                    "%s task(s) on session %s ignored cancellation after %ss; " "abandoning them",
                    len(pending),
                    session.session_id,
                    TEARDOWN_TIMEOUT,
                )
        session.tasks.clear()
        session.wakeup.set()
        # FEAT-477 TASK-2609: keep the shared store in sync so a pruned/
        # deleted session cannot "resurrect" via _get_session's cross-worker
        # fallback. Best effort — local teardown must complete regardless of
        # the store's availability (unlike create/get, this is cleanup, not
        # a control-plane decision to serve or refuse traffic).
        try:
            await self._session_store.delete_session(session.session_id)
        except SessionStoreUnavailable as exc:
            self.logger.warning(
                "Could not mirror-delete session %s from the shared store: %s",
                session.session_id,
                exc,
            )

    @staticmethod
    def _session_store_unavailable_response() -> web.Response:
        """Clean 503 for a control-plane session-store failure (TASK-2609).

        Returned when an explicitly configured shared store
        (``RedisSessionStore``) cannot service a session create/lookup —
        fail closed, never silently degrade to per-process state.
        """
        return web.json_response(_jsonrpc_error(-32000, "Session store unavailable"), status=503)

    def _track(self, session: McpStreamSession | None, message: dict[str, Any], coro) -> asyncio.Task:
        """Run a dispatch coroutine as a task the session can cancel."""
        task = asyncio.create_task(coro)
        if session is not None:
            key = message.get("id")
            session.tasks[key] = task
            task.add_done_callback(
                lambda finished, s=session, k=key: (
                    # Only drop our own entry: a batch may repeat an id, and
                    # the later task then owns the slot.
                    s.tasks.pop(k, None)
                    if s.tasks.get(k) is finished
                    else None
                )
            )
        return task

    # ------------------------------------------------------------------
    # Request validation helpers
    # ------------------------------------------------------------------

    def _check_origin(self, request: web.Request) -> web.Response | None:
        """Validate the Origin header (DNS-rebinding protection).

        Requests without an ``Origin`` header (server-to-server clients such
        as Claude.ai) are always allowed — the header is browser-supplied and
        its absence means no browser is involved. Localhost origins are
        always allowed. Any other origin must appear in
        ``config.allowed_origins``; with no allowlist configured only
        localhost passes, unless ``config.allow_any_origin`` is set.
        """
        origin = request.headers.get("Origin")
        if not origin:
            return None
        if self._allow_any_origin:
            return None
        hostname = urlparse(origin).hostname or ""
        if hostname in LOCALHOST_HOSTS:
            return None
        if self._allowed_origins and origin.rstrip("/") in {o.rstrip("/") for o in self._allowed_origins}:
            return None
        return web.json_response(
            _jsonrpc_error(-32600, f"Origin not allowed: {origin}"),
            status=403,
        )

    def _check_protocol_header(self, request: web.Request) -> web.Response | None:
        """Reject requests carrying an unsupported protocol-version header."""
        header = request.headers.get("MCP-Protocol-Version")
        if header and header not in SUPPORTED_PROTOCOL_VERSIONS:
            return web.json_response(
                _jsonrpc_error(
                    -32600,
                    f"Unsupported MCP protocol version: {header}. "
                    f"Supported: {', '.join(SUPPORTED_PROTOCOL_VERSIONS)}",
                ),
                status=400,
            )
        return None

    async def _guard(self, request: web.Request) -> web.Response | None:
        """Run auth plus the transport checks every verb shares."""
        auth_response = await self._authenticate_request(request)
        if auth_response:
            return auth_response
        for check in (self._check_origin, self._check_protocol_header):
            error = check(request)
            if error:
                return error
        return None

    @staticmethod
    def _wants_sse(request: web.Request) -> bool:
        """True when the client accepts SSE responses to POST."""
        return "text/event-stream" in request.headers.get("Accept", "")

    @staticmethod
    def _wants_json(request: web.Request) -> bool:
        """True when the client accepts a plain JSON response body."""
        accept = request.headers.get("Accept", "")
        if not accept:
            return True  # unset Accept means "anything"
        return "application/json" in accept or "*/*" in accept

    @staticmethod
    def _is_request(message: Any) -> bool:
        """True for a JSON-RPC request (has method AND id).

        Notifications are excluded even when a client mistakenly gives them
        an ``id``: they produce no response, and treating them as requests
        leaves the caller waiting for an answer that never comes.
        """
        return (
            isinstance(message, dict)
            and "method" in message
            and "id" in message
            and not str(message.get("method", "")).startswith("notifications/")
        )

    def _session_headers(self, session: McpStreamSession | None, **extra: str) -> dict[str, str]:
        """Response headers echoing the session id when one is in play."""
        headers = dict(extra)
        if session is not None:
            headers["Mcp-Session-Id"] = session.session_id
        return headers

    # ------------------------------------------------------------------
    # POST — client-to-server messages
    # ------------------------------------------------------------------

    async def _handle_streamable_post(self, request: web.Request) -> web.StreamResponse:
        """Handle POST: JSON-RPC single messages or batches."""
        error = await self._guard(request)
        if error:
            return error

        if not self._wants_sse(request) and not self._wants_json(request):
            return web.json_response(
                _jsonrpc_error(
                    -32600,
                    "Accept must include application/json or text/event-stream",
                ),
                status=406,
            )

        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return web.json_response(_jsonrpc_error(-32700, "Parse error"), status=400)

        is_batch = isinstance(data, list)
        messages: list[Any] = data if is_batch else [data]
        if not messages or not all(isinstance(m, dict) for m in messages):
            return web.json_response(_jsonrpc_error(-32600, "Invalid Request"), status=400)

        is_initialize = any(m.get("method") == "initialize" for m in messages)
        if is_initialize and len(messages) > 1:
            # The MCP lifecycle forbids batching initialize; refusing keeps a
            # malformed body from being the one path that creates state.
            return web.json_response(
                _jsonrpc_error(-32600, "initialize must not be batched"),
                status=400,
            )

        session: McpStreamSession | None = None
        if not is_initialize:
            session_id = request.headers.get("Mcp-Session-Id")
            if session_id:
                try:
                    session = await self._get_session(session_id, request)
                except SessionStoreUnavailable:
                    return self._session_store_unavailable_response()
                if session is None:
                    return web.json_response(
                        _jsonrpc_error(-32001, "Session not found"),
                        status=404,
                    )
            # Missing session id is tolerated (lenient stateless mode) —
            # the spec says SHOULD 400; we accept for pragmatic interop
            # with hand-rolled clients.

        requests_ = [m for m in messages if self._is_request(m)]

        if not requests_:
            # Only notifications and/or responses: run them for their side
            # effects and acknowledge with 202 (spec requirement).
            for message in messages:
                await self._handle_notification(session, message)
            return web.Response(status=202, headers=self._session_headers(session))

        if is_initialize:
            return await self._respond_initialize(request, messages[0])

        if self._wants_sse(request):
            if session is not None:
                return await self._respond_sse(request, session, messages)
            if not self._wants_json(request):
                return web.json_response(
                    _jsonrpc_error(
                        -32600,
                        "Mcp-Session-Id is required for text/event-stream " "responses; call initialize first",
                    ),
                    status=400,
                )

        return await self._respond_json(request, session, messages, is_batch)

    async def _handle_notification(self, session: McpStreamSession | None, message: dict[str, Any]) -> None:
        """Run one notification for its side effects."""
        if message.get("method") == "notifications/cancelled":
            self._cancel_request(session, message)
            return
        await self._handle_request(message)

    def _cancel_request(self, session: McpStreamSession | None, message: dict[str, Any]) -> None:
        """Cancel the in-flight dispatch named by ``notifications/cancelled``."""
        if session is None:
            return
        request_id = (message.get("params") or {}).get("requestId")
        task = session.tasks.get(request_id)
        if task is not None and not task.done():
            task.cancel()
            self.logger.info(
                "Cancelled MCP request %s on session %s",
                request_id,
                session.session_id,
            )

    async def _respond_initialize(self, request: web.Request, message: dict[str, Any]) -> web.StreamResponse:
        """Dispatch an initialize request, minting a new session."""
        response = await self._handle_request(message)
        if response is None:  # pragma: no cover - initialize always answers
            return web.Response(status=202)

        negotiated = response.get("result", {}).get("protocolVersion")
        try:
            session = await self._create_session(
                protocol_version=negotiated or ASSUMED_HEADER_VERSION,
                principal=self._principal(request),
            )
        except SessionStoreUnavailable:
            return self._session_store_unavailable_response()
        if session is None:
            return web.json_response(
                _jsonrpc_error(-32000, "Server session capacity reached"),
                status=503,
            )

        if self._wants_sse(request) and not self._wants_json(request):
            # SSE-only client: answer on a stream rather than forcing JSON.
            buffer = session.open_stream(self._event_buffer_size, max_streams=self._max_streams)
            event = buffer.append(response)
            return await self._write_events(request, session, buffer, [event])

        return web.json_response(response, headers=self._session_headers(session))

    async def _respond_json(
        self,
        request: web.Request,
        session: McpStreamSession | None,
        messages: list[dict[str, Any]],
        is_batch: bool,
    ) -> web.Response:
        """Answer a request-bearing body with a plain JSON response."""
        responses = []
        for message in messages:
            if not self._is_request(message):
                await self._handle_notification(session, message)
                continue
            # Dispatch through a tracked task so DELETE and
            # notifications/cancelled can reach the work.
            task = self._track(session, message, self._handle_request(message))
            try:
                response = await task
            except asyncio.CancelledError:
                if not task.cancelled():
                    raise  # this handler is being cancelled, not the task
                response = _jsonrpc_error(-32800, "Request cancelled", message.get("id"))
            if response is None:
                continue
            if "tools" in response.get("result", {}) and "Anthropic" in request.headers.get("User-Agent", ""):
                response["result"] = self._convert_tools_to_anthropic(response["result"])
            responses.append(response)

        headers = self._session_headers(session)
        if not responses:
            # Every message turned out to be a notification (a client may
            # give one an id); there is nothing to answer with.
            return web.Response(status=202, headers=headers)
        payload: Any = responses if is_batch else responses[0]
        return web.json_response(payload, headers=headers)

    async def _respond_sse(
        self,
        request: web.Request,
        session: McpStreamSession,
        messages: list[dict[str, Any]],
    ) -> web.StreamResponse:
        """Answer a request-bearing body with an SSE stream.

        The POST opens its own stream. Each request is dispatched as an
        independent asyncio task that records its response in that stream's
        buffer even if the client disconnects — the client can then resume
        via ``GET`` (optionally with ``Last-Event-ID``) and still collect the
        results. Because the buffer belongs to this stream alone, a
        concurrently open GET stream cannot consume these responses while
        this response is still writing them.
        """
        buffer = session.open_stream(self._event_buffer_size, max_streams=self._max_streams)
        tasks: list[asyncio.Task] = []
        for message in messages:
            if self._is_request(message):
                tasks.append(
                    self._track(
                        session,
                        message,
                        self._dispatch_to_stream(session, buffer, message),
                    )
                )
            else:
                # Notifications inside a mixed body: side effects only.
                await self._handle_notification(session, message)

        return await self._write_events(request, session, buffer, tasks=tasks)

    async def _write_events(
        self,
        request: web.Request,
        session: McpStreamSession,
        buffer: StreamBuffer,
        events: list[StreamEvent] | None = None,
        tasks: list[asyncio.Task] | None = None,
    ) -> web.StreamResponse:
        """Stream a set of already-known or still-pending events to a client."""
        response = web.StreamResponse(
            status=200,
            headers=self._session_headers(
                session,
                **{
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            ),
        )
        buffer.attached = True
        try:
            await response.prepare(request)
            for event in events or []:
                await response.write(event.to_sse())
                event.delivered = True
            for finished in asyncio.as_completed(tasks or []):
                event = await finished
                if event is None or event.delivered:
                    continue
                await response.write(event.to_sse())
                event.delivered = True
            with contextlib.suppress(Exception):
                await response.write_eof()
        except asyncio.CancelledError:
            if _cancelled_by_caller():
                # aiohttp is tearing this handler down — do not swallow it.
                raise
            # A dispatch task was cancelled (session teardown): its response
            # stays buffered and the stream is orphaned below.
            self.logger.info(
                "SSE POST dispatch cancelled for session %s (stream %s)",
                session.session_id,
                buffer.stream_id,
            )
        except (
            ConnectionResetError,
            ConnectionError,
            OSError,
        ):
            # Client went away mid-call: dispatch tasks keep running and
            # their responses stay buffered (undelivered) for resumption.
            self.logger.info(
                "SSE POST client disconnected; %s call(s) continue for " "session %s (stream %s)",
                sum(1 for t in (tasks or []) if not t.done()),
                session.session_id,
                buffer.stream_id,
            )
        finally:
            # Orphan the stream so the session's GET stream may adopt any
            # events this response did not manage to deliver.
            buffer.attached = False
            session.wakeup.set()
        return response

    async def _mirror_event(self, session_id: str, stream_id: str, message: dict[str, Any]) -> None:
        """Best-effort mirror of one buffered event into the shared store.

        FEAT-477 TASK-2609: durability for the "launch a long tool call,
        disconnect, reconnect on a different worker, collect the result"
        scenario. Deliberately **not** fail-closed like session
        create/get — a data-plane durability hiccup must not fail an
        otherwise-successful in-process response delivery to the client
        that is actually connected right now.

        Args:
            session_id: The owning session's id.
            stream_id: The stream this event belongs to.
            message: The JSON-RPC message being buffered.
        """
        try:
            await self._session_store.append_event(session_id, stream_id, message)
        except SessionStoreUnavailable as exc:
            self.logger.warning(
                "Could not mirror event for session %s stream %s to the " "shared store: %s",
                session_id,
                stream_id,
                exc,
            )

    async def _dispatch_to_stream(
        self,
        session: McpStreamSession,
        buffer: StreamBuffer,
        message: dict[str, Any],
    ) -> StreamEvent | None:
        """Run one JSON-RPC request and buffer its response as an event."""
        try:
            response = await self._handle_request(message)
        except asyncio.CancelledError:
            # Record the cancellation for anyone resuming the stream, then
            # let the cancellation propagate.
            cancelled = _jsonrpc_error(-32800, "Request cancelled", message.get("id"))
            buffer.append(cancelled)
            await self._mirror_event(session.session_id, buffer.stream_id, cancelled)
            session.wakeup.set()
            raise
        if response is None:
            return None
        event = buffer.append(response)
        await self._mirror_event(session.session_id, buffer.stream_id, response)
        session.wakeup.set()
        return event

    # ------------------------------------------------------------------
    # GET — server-to-client stream (resumable)
    # ------------------------------------------------------------------

    async def _handle_streamable_get(self, request: web.Request) -> web.StreamResponse:
        """Open the session's SSE stream, replaying from Last-Event-ID."""
        error = await self._guard(request)
        if error:
            return error

        if not self._wants_sse(request):
            return web.Response(status=405, headers={"Allow": "POST, DELETE"})

        session_id = request.headers.get("Mcp-Session-Id")
        if not session_id:
            return web.json_response(
                _jsonrpc_error(-32600, "Missing Mcp-Session-Id header"),
                status=400,
            )
        try:
            session = await self._get_session(session_id, request)
        except SessionStoreUnavailable:
            return self._session_store_unavailable_response()
        if session is None:
            return web.json_response(_jsonrpc_error(-32001, "Session not found"), status=404)
        if session.live_stream:
            return web.json_response(
                _jsonrpc_error(-32600, "A stream is already open for this session"),
                status=409,
            )

        resumed: StreamBuffer | None = None
        replay: list[StreamEvent] = []
        raw_last_id = request.headers.get("Last-Event-ID")
        if raw_last_id:
            parsed = parse_event_id(raw_last_id)
            if parsed is None:
                return web.json_response(
                    _jsonrpc_error(-32600, f"Malformed Last-Event-ID: {raw_last_id}"),
                    status=400,
                )
            stream_id, sequence = parsed
            resumed = session.streams.get(stream_id)
            if resumed is None:
                # FEAT-477 TASK-2609: the stream may belong to a different
                # worker (e.g. this session was just adopted from the
                # shared store in ``_get_session``). Best-effort fallback:
                # replay from the shared event log before giving up. A
                # store hiccup here degrades to the existing "unknown
                # stream" 404 rather than a hard failure — the client can
                # still reconnect fresh without ``Last-Event-ID``.
                try:
                    store_events = await self._session_store.events_after(session.session_id, stream_id, sequence)
                except SessionStoreUnavailable as exc:
                    self.logger.warning(
                        "Could not query the shared store for session %s " "stream %s replay: %s",
                        session.session_id,
                        stream_id,
                        exc,
                    )
                    store_events = []
                if not store_events:
                    return web.json_response(
                        _jsonrpc_error(-32001, f"Unknown stream in Last-Event-ID: {stream_id}"),
                        status=404,
                    )
                resumed = session.open_stream(
                    self._event_buffer_size,
                    stream_id=stream_id,
                    max_streams=self._max_streams,
                )
                # Rehydrate the buffer preserving the store's original
                # sequence numbers, so Last-Event-ID continuity holds.
                for record in store_events:
                    resumed._events.append(
                        StreamEvent(
                            stream_id=stream_id,
                            sequence=record.sequence,
                            message=record.message,
                        )
                    )
                resumed._counter = max(record.sequence for record in store_events)
            # Replay from where the client says it stopped, delivered or not.
            replay = resumed.events_after(sequence)

        session.live_stream = True
        response = web.StreamResponse(
            status=200,
            headers=self._session_headers(
                session,
                **{
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            ),
        )
        try:
            await response.prepare(request)
            for event in replay:
                await response.write(event.to_sse())
                event.delivered = True

            # Live phase.
            #
            # Resuming (``Last-Event-ID``) delivers that stream and nothing
            # else: the spec forbids a resumed stream from replaying
            # messages that belong to a different one.
            #
            # A plain GET is the session's server-to-client stream. It
            # carries server-initiated messages, and — as a deliberate
            # extension — adopts streams orphaned by a disconnected client,
            # which is what lets "POST a long tool call, drop, reconnect,
            # collect the result" work without the client having kept the
            # event id. A stream still attached to its own SSE response is
            # never drained here: that response owes those events to its
            # own client.
            server_stream = session.open_stream(
                self._event_buffer_size,
                stream_id=SERVER_STREAM,
                max_streams=self._max_streams,
            )
            while session.session_id in self._sessions:
                session.wakeup.clear()
                if resumed is not None:
                    sources = [resumed]
                else:
                    sources = [
                        buffer for buffer in session.streams.values() if not buffer.attached or buffer is server_stream
                    ]
                for buffer in list(sources):
                    if buffer.attached and buffer is not server_stream:
                        continue
                    for event in buffer.undelivered():
                        await response.write(event.to_sse())
                        event.delivered = True
                try:
                    await asyncio.wait_for(session.wakeup.wait(), timeout=KEEP_ALIVE_INTERVAL)
                except TimeoutError:
                    await response.write(b": keep-alive\n\n")
                # An attached stream is proof of life: keep the session from
                # expiring under a client that is connected but idle.
                session.last_seen = time.monotonic()
        except asyncio.CancelledError:
            session.live_stream = False
            if _cancelled_by_caller():
                raise
            self.logger.info("SSE GET stream cancelled: %s", session.session_id)
        except (
            ConnectionResetError,
            ConnectionError,
            OSError,
        ):
            self.logger.info("SSE GET client disconnected: %s", session.session_id)
        finally:
            session.live_stream = False
            with contextlib.suppress(Exception):
                await response.write_eof()
        return response

    # ------------------------------------------------------------------
    # DELETE — session termination
    # ------------------------------------------------------------------

    async def _handle_streamable_delete(self, request: web.Request) -> web.Response:
        """Terminate a session, cancelling its pending dispatch tasks."""
        error = await self._guard(request)
        if error:
            return error

        session_id = request.headers.get("Mcp-Session-Id")
        if not session_id:
            return web.json_response(
                _jsonrpc_error(-32600, "Missing Mcp-Session-Id header"),
                status=400,
            )
        # Look up before removing so ownership is enforced on DELETE too.
        try:
            session = await self._get_session(session_id, request)
        except SessionStoreUnavailable:
            return self._session_store_unavailable_response()
        if session is None:
            return web.json_response(_jsonrpc_error(-32001, "Session not found"), status=404)
        self._sessions.pop(session_id, None)
        # Awaits cancellation, so 204 means the work has actually stopped.
        await self._teardown_session(session)
        self.logger.info("Terminated MCP session: %s", session_id)
        return web.Response(status=204)
