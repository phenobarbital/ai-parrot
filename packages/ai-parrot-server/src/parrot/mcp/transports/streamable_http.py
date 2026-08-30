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
record their responses in a per-session event store regardless of
connection state, which is what makes disconnect-and-resume possible.

The event store is in-memory and per-process, matching how the rest of
the MCP server stack keeps state; a shared (e.g. Redis-backed) store for
multi-worker deployments is a documented follow-up.
"""
import asyncio
import contextlib
import json
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Set
from urllib.parse import urlparse

from aiohttp import web

from parrot.mcp.config import MCPServerConfig
from parrot.mcp.server_base import SUPPORTED_PROTOCOL_VERSIONS
from parrot.mcp.transports.http import HttpMCPServer

#: Seconds between SSE keep-alive comments on an idle stream.
KEEP_ALIVE_INTERVAL: float = 15.0

#: Version assumed when a request carries no ``MCP-Protocol-Version``
#: header, per the 2025-06-18 spec's backwards-compatibility rule.
ASSUMED_HEADER_VERSION: str = "2025-03-26"


def _jsonrpc_error(
    code: int, message: str, request_id: Any = None
) -> Dict[str, Any]:
    """Build a JSON-RPC error object."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


@dataclass
class StreamEvent:
    """One buffered outbound JSON-RPC message with its SSE event id."""

    event_id: int
    message: Dict[str, Any]
    delivered: bool = False

    def to_sse(self) -> bytes:
        """Serialize as an SSE ``message`` event carrying the event id."""
        data = json.dumps(self.message)
        return f"id: {self.event_id}\nevent: message\ndata: {data}\n\n".encode(
            "utf-8"
        )


class SessionEventStore:
    """Ordered, bounded buffer of outbound messages for one session.

    Event ids increase monotonically per session and become the SSE ``id:``
    field, so a client can resume with ``Last-Event-ID`` after a disconnect.
    The buffer is a ring: once ``max_events`` is exceeded the oldest events
    are dropped (no longer replayable).
    """

    def __init__(self, max_events: int = 1000):
        self._events: Deque[StreamEvent] = deque(maxlen=max_events)
        self._counter = 0
        #: Set whenever a new event is appended; the live GET stream waits
        #: on it and clears it after draining.
        self.new_event: asyncio.Event = asyncio.Event()

    def append(self, message: Dict[str, Any]) -> StreamEvent:
        """Buffer an outbound message and wake any live stream."""
        self._counter += 1
        event = StreamEvent(event_id=self._counter, message=message)
        self._events.append(event)
        self.new_event.set()
        return event

    def events_after(self, last_event_id: int) -> List[StreamEvent]:
        """Return buffered events with an id greater than ``last_event_id``."""
        return [e for e in self._events if e.event_id > last_event_id]

    def undelivered(self) -> List[StreamEvent]:
        """Return buffered events not yet written to any stream."""
        return [e for e in self._events if not e.delivered]


@dataclass
class McpStreamSession:
    """State for one Streamable HTTP session."""

    session_id: str
    protocol_version: str
    created_at: float
    last_seen: float
    user: Optional[Any] = None
    events: SessionEventStore = field(default_factory=SessionEventStore)
    tasks: Set[asyncio.Task] = field(default_factory=set)
    #: True while a GET SSE stream is attached (one per session).
    live_stream: bool = False


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
        parent_app: Optional[web.Application] = None,
    ):
        super().__init__(config, parent_app=parent_app)
        self._sessions: Dict[str, McpStreamSession] = {}
        self._session_ttl: float = float(
            getattr(config, "session_ttl", 3600) or 3600
        )
        self._event_buffer_size: int = int(
            getattr(config, "event_buffer_size", 1000) or 1000
        )
        self._allowed_origins: Optional[List[str]] = getattr(
            config, "allowed_origins", None
        )

    def _register_routes(self, router, base_route: str) -> None:
        """Register POST/GET/DELETE on the single MCP endpoint."""
        router.add_post(base_route, self._handle_streamable_post)
        router.add_get(base_route, self._handle_streamable_get)
        router.add_delete(base_route, self._handle_streamable_delete)
        router.add_get(f"{base_route.rstrip('/')}/info", self._handle_info)

    async def stop(self):
        """Stop the server, cancelling pending dispatch tasks."""
        for session in list(self._sessions.values()):
            self._teardown_session(session)
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

    def _create_session(
        self, protocol_version: str, user: Optional[Any] = None
    ) -> McpStreamSession:
        """Mint a new session with a cryptographically secure id."""
        now = time.monotonic()
        session = McpStreamSession(
            session_id=secrets.token_urlsafe(32),
            protocol_version=protocol_version,
            created_at=now,
            last_seen=now,
            user=user,
            events=SessionEventStore(max_events=self._event_buffer_size),
        )
        self._sessions[session.session_id] = session
        self._prune_sessions()
        return session

    def _get_session(self, session_id: str) -> Optional[McpStreamSession]:
        """Look up a session, expiring it when past its TTL."""
        self._prune_sessions()
        session = self._sessions.get(session_id)
        if session is None:
            return None
        session.last_seen = time.monotonic()
        return session

    def _prune_sessions(self) -> None:
        """Drop sessions idle beyond the TTL (lazy, no background task)."""
        now = time.monotonic()
        expired = [
            sid
            for sid, session in self._sessions.items()
            if now - session.last_seen > self._session_ttl
        ]
        for sid in expired:
            session = self._sessions.pop(sid, None)
            if session:
                self._teardown_session(session)
                self.logger.info("Expired MCP session: %s", sid)

    def _teardown_session(self, session: McpStreamSession) -> None:
        """Cancel a session's pending dispatch tasks and wake its stream."""
        for task in list(session.tasks):
            if not task.done():
                task.cancel()
        session.tasks.clear()
        session.events.new_event.set()

    # ------------------------------------------------------------------
    # Request validation helpers
    # ------------------------------------------------------------------

    def _check_origin(self, request: web.Request) -> Optional[web.Response]:
        """Validate the Origin header (DNS-rebinding protection).

        Requests without an ``Origin`` header (server-to-server clients such
        as Claude.ai) are always allowed. Localhost origins are always
        allowed. When ``config.allowed_origins`` is unset, any origin is
        allowed for backward compatibility.
        """
        origin = request.headers.get("Origin")
        if not origin:
            return None
        hostname = urlparse(origin).hostname or ""
        if hostname in {"localhost", "127.0.0.1", "::1"}:
            return None
        if self._allowed_origins is None:
            return None
        if origin.rstrip("/") in {o.rstrip("/") for o in self._allowed_origins}:
            return None
        return web.json_response(
            _jsonrpc_error(-32600, f"Origin not allowed: {origin}"),
            status=403,
        )

    def _check_protocol_header(
        self, request: web.Request
    ) -> Optional[web.Response]:
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

    @staticmethod
    def _wants_sse(request: web.Request) -> bool:
        """True when the client accepts SSE responses to POST."""
        return "text/event-stream" in request.headers.get("Accept", "")

    @staticmethod
    def _is_request(message: Any) -> bool:
        """True for a JSON-RPC request (has method AND id)."""
        return (
            isinstance(message, dict)
            and "method" in message
            and "id" in message
        )

    # ------------------------------------------------------------------
    # POST — client-to-server messages
    # ------------------------------------------------------------------

    async def _handle_streamable_post(
        self, request: web.Request
    ) -> web.StreamResponse:
        """Handle POST: JSON-RPC single messages or batches."""
        auth_response = await self._authenticate_request(request)
        if auth_response:
            return auth_response
        for check in (self._check_origin, self._check_protocol_header):
            error = check(request)
            if error:
                return error

        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return web.json_response(
                _jsonrpc_error(-32700, "Parse error"), status=400
            )

        is_batch = isinstance(data, list)
        messages: List[Any] = data if is_batch else [data]
        if not messages or not all(isinstance(m, dict) for m in messages):
            return web.json_response(
                _jsonrpc_error(-32600, "Invalid Request"), status=400
            )

        is_initialize = any(
            m.get("method") == "initialize" for m in messages
        )
        session: Optional[McpStreamSession] = None
        if not is_initialize:
            session_id = request.headers.get("Mcp-Session-Id")
            if session_id:
                session = self._get_session(session_id)
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
                await self._handle_request(message)
            return web.Response(status=202)

        if is_initialize:
            return await self._respond_initialize(
                request, messages, is_batch
            )

        if self._wants_sse(request) and session is not None:
            return await self._respond_sse(request, session, messages)

        return await self._respond_json(request, messages, is_batch)

    async def _respond_initialize(
        self,
        request: web.Request,
        messages: List[Dict[str, Any]],
        is_batch: bool,
    ) -> web.Response:
        """Dispatch an initialize body, minting a new session."""
        responses = []
        negotiated: Optional[str] = None
        for message in messages:
            response = await self._handle_request(message)
            if response is not None:
                responses.append(response)
                if message.get("method") == "initialize":
                    negotiated = response.get("result", {}).get(
                        "protocolVersion"
                    )

        session = self._create_session(
            protocol_version=negotiated or ASSUMED_HEADER_VERSION,
            user=request.get("mcp_user"),
        )
        payload: Any = responses if is_batch else responses[0]
        return web.json_response(
            payload, headers={"Mcp-Session-Id": session.session_id}
        )

    async def _respond_json(
        self,
        request: web.Request,
        messages: List[Dict[str, Any]],
        is_batch: bool,
    ) -> web.Response:
        """Answer a request-bearing body with a plain JSON response."""
        responses = []
        for message in messages:
            response = await self._handle_request(message)
            if response is None:
                continue
            if "result" in response and "tools" in response.get("result", {}):
                if "Anthropic" in request.headers.get("User-Agent", ""):
                    response["result"] = self._convert_tools_to_anthropic(
                        response["result"]
                    )
            responses.append(response)
        payload: Any = responses if is_batch else responses[0]
        return web.json_response(payload)

    async def _respond_sse(
        self,
        request: web.Request,
        session: McpStreamSession,
        messages: List[Dict[str, Any]],
    ) -> web.StreamResponse:
        """Answer a request-bearing body with an SSE stream.

        Each request is dispatched as an independent asyncio task that
        records its response in the session's event store even if the
        client disconnects — the client can then resume via
        ``GET + Last-Event-ID`` and still collect the results.
        """
        tasks: List[asyncio.Task] = []
        for message in messages:
            if self._is_request(message):
                task = asyncio.create_task(
                    self._dispatch_to_store(session, message)
                )
                session.tasks.add(task)
                task.add_done_callback(session.tasks.discard)
                tasks.append(task)
            else:
                # Notifications inside a mixed body: side effects only.
                await self._handle_request(message)

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)
        try:
            for finished in asyncio.as_completed(tasks):
                event = await finished
                if event is None or event.delivered:
                    continue
                await response.write(event.to_sse())
                event.delivered = True
            with contextlib.suppress(Exception):
                await response.write_eof()
        except (
            asyncio.CancelledError,
            ConnectionResetError,
            ConnectionError,
            OSError,
        ):
            # Client went away mid-call: dispatch tasks keep running and
            # their responses stay buffered (undelivered) for resumption.
            self.logger.info(
                "SSE POST client disconnected; %s call(s) continue for "
                "session %s",
                sum(1 for t in tasks if not t.done()),
                session.session_id,
            )
        return response

    async def _dispatch_to_store(
        self, session: McpStreamSession, message: Dict[str, Any]
    ) -> Optional[StreamEvent]:
        """Run one JSON-RPC request and buffer its response as an event."""
        response = await self._handle_request(message)
        if response is None:
            return None
        return session.events.append(response)

    # ------------------------------------------------------------------
    # GET — server-to-client stream (resumable)
    # ------------------------------------------------------------------

    async def _handle_streamable_get(
        self, request: web.Request
    ) -> web.StreamResponse:
        """Open the session's SSE stream, replaying from Last-Event-ID."""
        auth_response = await self._authenticate_request(request)
        if auth_response:
            return auth_response
        error = self._check_origin(request)
        if error:
            return error

        if not self._wants_sse(request):
            return web.Response(
                status=405, headers={"Allow": "POST, DELETE"}
            )

        session_id = request.headers.get("Mcp-Session-Id")
        if not session_id:
            return web.json_response(
                _jsonrpc_error(-32600, "Missing Mcp-Session-Id header"),
                status=400,
            )
        session = self._get_session(session_id)
        if session is None:
            return web.json_response(
                _jsonrpc_error(-32001, "Session not found"), status=404
            )
        if session.live_stream:
            return web.json_response(
                _jsonrpc_error(
                    -32600, "A stream is already open for this session"
                ),
                status=409,
            )

        last_event_id: Optional[int] = None
        raw_last_id = request.headers.get("Last-Event-ID")
        if raw_last_id:
            with contextlib.suppress(ValueError):
                last_event_id = int(raw_last_id)

        session.live_stream = True
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Mcp-Session-Id": session.session_id,
            },
        )
        try:
            await response.prepare(request)
            store = session.events

            # Resume: replay buffered events after the client's last id
            # (delivered or not — the client told us where it stopped).
            replay = (
                store.events_after(last_event_id)
                if last_event_id is not None
                else store.undelivered()
            )
            for event in replay:
                await response.write(event.to_sse())
                event.delivered = True

            # Live phase: deliver new events as dispatch tasks complete.
            while session.session_id in self._sessions:
                store.new_event.clear()
                for event in store.undelivered():
                    await response.write(event.to_sse())
                    event.delivered = True
                try:
                    await asyncio.wait_for(
                        store.new_event.wait(), timeout=KEEP_ALIVE_INTERVAL
                    )
                except asyncio.TimeoutError:
                    await response.write(b": keep-alive\n\n")
        except (
            asyncio.CancelledError,
            ConnectionResetError,
            ConnectionError,
            OSError,
        ):
            self.logger.info(
                "SSE GET client disconnected: %s", session.session_id
            )
        finally:
            session.live_stream = False
            with contextlib.suppress(Exception):
                await response.write_eof()
        return response

    # ------------------------------------------------------------------
    # DELETE — session termination
    # ------------------------------------------------------------------

    async def _handle_streamable_delete(
        self, request: web.Request
    ) -> web.Response:
        """Terminate a session, cancelling its pending dispatch tasks."""
        auth_response = await self._authenticate_request(request)
        if auth_response:
            return auth_response

        session_id = request.headers.get("Mcp-Session-Id")
        if not session_id:
            return web.json_response(
                _jsonrpc_error(-32600, "Missing Mcp-Session-Id header"),
                status=400,
            )
        session = self._sessions.pop(session_id, None)
        if session is None:
            return web.json_response(
                _jsonrpc_error(-32001, "Session not found"), status=404
            )
        self._teardown_session(session)
        self.logger.info("Terminated MCP session: %s", session_id)
        return web.Response(status=204)
