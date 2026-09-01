"""Redis-backed shared session + event store (FEAT-477, Module 6, G5/OQ4).

The project's own deploy template runs `aiohttp.GunicornWebWorker` with
`(2xCPUs)+1` workers, recycles them every 2000 requests, and states
*"Do NOT rely on in-process dicts for cross-request state"*
(`autonomous/deploy/templates.py:3`). Today
`StreamableHttpMCPServer._sessions` is a plain dict and its `StreamBuffer`
event log is an in-process ring, so a session created on one worker is
invisible to the next, and its buffered events cannot be replayed there —
**this also affects the existing tool-level Streamable HTTP endpoint**, not
just the new agent mounts.

This module defines the storage abstraction and two implementations:

- :class:`InMemorySessionStore` — the current in-process behavior, kept
  available as an **explicit** choice (never an automatic fallback) for
  tests and single-worker development.
- :class:`RedisSessionStore` — the shared, cross-worker-visible
  implementation. **Fails closed**: any Redis error raises
  :class:`SessionStoreUnavailable` rather than silently degrading to
  per-process state, which is exactly the failure mode this module exists
  to eliminate.

Both honor `MCPServerConfig.session_ttl` / `.event_buffer_size` — no new
configuration knobs are introduced.
"""

import json
import logging
import secrets
import time
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger("Parrot.MCP.SessionStore")


class SessionStoreUnavailable(Exception):
    """Raised when the backing store cannot service a request.

    Callers MUST surface this as a clean error to the client — never catch
    it and silently fall back to per-process state, which would
    reintroduce exactly the multi-worker bug this module fixes.
    """


class SessionRecord(BaseModel):
    """Durable, cross-worker-visible session metadata.

    Deliberately excludes anything that cannot survive a process
    boundary — no `asyncio.Event`/`asyncio.Task` references, and no
    `time.monotonic()` values (meaningless outside the process that took
    them). `created_at`/`last_seen` are wall-clock epoch seconds instead.

    Attributes:
        session_id: The session identifier issued to the client.
        protocol_version: Negotiated MCP protocol version.
        created_at: Wall-clock epoch seconds the session was created.
        last_seen: Wall-clock epoch seconds of the last access.
        principal: Stable identifier of the authenticated principal that
            opened the session, or `None` when the auth method
            establishes no identity.
    """

    session_id: str
    protocol_version: str
    created_at: float
    last_seen: float
    principal: Any = None


class StreamEventRecord(BaseModel):
    """One durable, replayable event within one session's stream.

    Attributes:
        stream_id: The stream this event belongs to (scoped within its
            session — the same `stream_id` in two different sessions are
            unrelated streams).
        sequence: Monotonically increasing, per-`(session_id, stream_id)`
            sequence number — combines with `stream_id` to form the SSE
            `Last-Event-ID` the same way `StreamEvent.event_id` does.
        message: The buffered JSON-RPC message.
    """

    stream_id: str
    sequence: int
    message: dict[str, Any]


class SessionStore:
    """Abstract interface for a shared session + event store.

    Subclasses implement the storage; callers depend only on this
    interface so the in-memory and Redis-backed implementations are
    interchangeable — but the choice between them must always be
    **explicit** (constructor injection), never an automatic fallback.

    Args:
        ttl: Session retention in seconds
            (`MCPServerConfig.session_ttl`).
        max_events: Max buffered events retained per `(session_id,
            stream_id)` (`MCPServerConfig.event_buffer_size`) — once
            exceeded, the oldest events are dropped (no longer
            replayable), matching `StreamBuffer`'s existing ring
            semantics.
    """

    def __init__(self, ttl: int, max_events: int) -> None:
        self.ttl = ttl
        self.max_events = max_events

    async def create_session(
        self,
        *,
        user: Any,
        protocol_version: str = "2025-03-26",
        session_id: "str | None" = None,
    ) -> str:
        """Create and persist a new session.

        Args:
            user: The authenticated principal (or `None`), stored as-is
                on the resulting `SessionRecord.principal`.
            protocol_version: Negotiated MCP protocol version.
            session_id: A pre-generated session id to persist under
                (used when a caller — e.g. `StreamableHttpMCPServer`,
                which mints its own cryptographically secure id — already
                has one). A fresh `secrets.token_urlsafe(32)` id is
                generated when omitted.

        Returns:
            The session id.

        Raises:
            SessionStoreUnavailable: If the store cannot persist the
                session.
        """
        raise NotImplementedError

    async def get_session(self, session_id: str) -> "SessionRecord | None":
        """Look up a session's metadata.

        Args:
            session_id: The session identifier.

        Returns:
            The `SessionRecord`, or `None` if it does not exist or has
            expired.

        Raises:
            SessionStoreUnavailable: If the store cannot service the
                lookup.
        """
        raise NotImplementedError

    async def touch_session(self, session_id: str) -> None:
        """Refresh a session's `last_seen` and extend its TTL.

        Args:
            session_id: The session identifier.

        Raises:
            SessionStoreUnavailable: If the store cannot service the
                update.
        """
        raise NotImplementedError

    async def delete_session(self, session_id: str) -> None:
        """Delete a session and its buffered events.

        Args:
            session_id: The session identifier.

        Raises:
            SessionStoreUnavailable: If the store cannot service the
                deletion.
        """
        raise NotImplementedError

    async def append_event(self, session_id: str, stream_id: str, message: dict[str, Any]) -> StreamEventRecord:
        """Buffer one outbound message for `(session_id, stream_id)`.

        Args:
            session_id: The session identifier.
            stream_id: The stream identifier within that session.
            message: The JSON-RPC message to buffer.

        Returns:
            The persisted `StreamEventRecord` (with its assigned
            `sequence`).

        Raises:
            SessionStoreUnavailable: If the store cannot persist the
                event.
        """
        raise NotImplementedError

    async def events_after(self, session_id: str, stream_id: str, sequence: int) -> list[StreamEventRecord]:
        """Return buffered events with `sequence > sequence`.

        Args:
            session_id: The session identifier.
            stream_id: The stream identifier within that session.
            sequence: The last sequence number the caller already has.

        Returns:
            Buffered events after `sequence`, oldest first.

        Raises:
            SessionStoreUnavailable: If the store cannot service the
                read.
        """
        raise NotImplementedError


class InMemorySessionStore(SessionStore):
    """In-process implementation — today's behavior, kept as an explicit choice.

    Suitable for tests and single-worker development. Never silently
    substituted for `RedisSessionStore` — a caller opts into this by name.
    """

    def __init__(self, ttl: int = 3600, max_events: int = 1000) -> None:
        super().__init__(ttl, max_events)
        self._sessions: dict[str, SessionRecord] = {}
        self._events: dict[tuple[str, str], list[StreamEventRecord]] = {}
        self._sequences: dict[tuple[str, str], int] = {}

    async def create_session(
        self,
        *,
        user: Any,
        protocol_version: str = "2025-03-26",
        session_id: "str | None" = None,
    ) -> str:
        sid = session_id or secrets.token_urlsafe(32)
        now = time.time()
        self._sessions[sid] = SessionRecord(
            session_id=sid,
            protocol_version=protocol_version,
            created_at=now,
            last_seen=now,
            principal=user,
        )
        return sid

    async def get_session(self, session_id: str) -> "SessionRecord | None":
        record = self._sessions.get(session_id)
        if record is None:
            return None
        if time.time() - record.last_seen > self.ttl:
            self._sessions.pop(session_id, None)
            return None
        return record

    async def touch_session(self, session_id: str) -> None:
        record = self._sessions.get(session_id)
        if record is not None:
            self._sessions[session_id] = record.model_copy(update={"last_seen": time.time()})

    async def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        for key in [k for k in self._events if k[0] == session_id]:
            self._events.pop(key, None)
            self._sequences.pop(key, None)

    async def append_event(self, session_id: str, stream_id: str, message: dict[str, Any]) -> StreamEventRecord:
        key = (session_id, stream_id)
        self._sequences[key] = self._sequences.get(key, 0) + 1
        record = StreamEventRecord(stream_id=stream_id, sequence=self._sequences[key], message=message)
        events = self._events.setdefault(key, [])
        events.append(record)
        del events[: max(0, len(events) - self.max_events)]
        return record

    async def events_after(self, session_id: str, stream_id: str, sequence: int) -> list[StreamEventRecord]:
        events = self._events.get((session_id, stream_id), [])
        return [e for e in events if e.sequence > sequence]


class RedisSessionStore(SessionStore):
    """Redis-backed implementation — a session created by one worker is
    visible to every other, and survives a worker recycle.

    Key layout:
        `mcp:session:{session_id}` -> JSON `SessionRecord`, `SETEX` with `ttl`.
        `mcp:session:{session_id}:stream:{stream_id}:seq` -> `INCR` counter.
        `mcp:session:{session_id}:stream:{stream_id}:events` -> Redis list
            of JSON `StreamEventRecord`s, `RPUSH` + `LTRIM` to `max_events`.

    Every operation wraps the underlying client call and raises
    `SessionStoreUnavailable` on any error — **fail closed**. A fallback to
    a local dict here would reintroduce exactly the bug this task fixes,
    and hide it.

    Args:
        redis: An async Redis-like client (`redis.asyncio`-shaped:
            `get`/`setex`/`expire`/`delete`/`incr`/`rpush`/`lrange`/`ltrim`).
        ttl: Session retention in seconds
            (`MCPServerConfig.session_ttl`).
        max_events: Max buffered events per `(session_id, stream_id)`
            (`MCPServerConfig.event_buffer_size`).
    """

    def __init__(self, redis: Any, ttl: int = 3600, max_events: int = 1000) -> None:
        super().__init__(ttl, max_events)
        self.redis = redis
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _session_key(session_id: str) -> str:
        return f"mcp:session:{session_id}"

    @staticmethod
    def _events_key(session_id: str, stream_id: str) -> str:
        return f"mcp:session:{session_id}:stream:{stream_id}:events"

    @staticmethod
    def _seq_key(session_id: str, stream_id: str) -> str:
        return f"mcp:session:{session_id}:stream:{stream_id}:seq"

    async def _call(self, op: str, coro: Any) -> Any:
        """Await `coro`, translating any failure into `SessionStoreUnavailable`.

        Args:
            op: Short operation name, for the log/error message.
            coro: The awaitable Redis call.

        Returns:
            The awaited result.

        Raises:
            SessionStoreUnavailable: On any underlying error.
        """
        try:
            return await coro
        except SessionStoreUnavailable:
            raise
        except Exception as exc:
            self.logger.error("RedisSessionStore.%s failed: %s", op, exc)
            raise SessionStoreUnavailable(f"session store unavailable ({op}): {exc}") from exc

    async def create_session(
        self,
        *,
        user: Any,
        protocol_version: str = "2025-03-26",
        session_id: "str | None" = None,
    ) -> str:
        sid = session_id or secrets.token_urlsafe(32)
        now = time.time()
        record = SessionRecord(
            session_id=sid,
            protocol_version=protocol_version,
            created_at=now,
            last_seen=now,
            principal=user,
        )
        await self._call(
            "create_session",
            self.redis.setex(self._session_key(sid), self.ttl, record.model_dump_json()),
        )
        return sid

    async def get_session(self, session_id: str) -> "SessionRecord | None":
        raw = await self._call("get_session", self.redis.get(self._session_key(session_id)))
        if raw is None:
            return None
        return SessionRecord.model_validate_json(raw)

    async def touch_session(self, session_id: str) -> None:
        record = await self.get_session(session_id)
        if record is None:
            return
        updated = record.model_copy(update={"last_seen": time.time()})
        await self._call(
            "touch_session",
            self.redis.setex(self._session_key(session_id), self.ttl, updated.model_dump_json()),
        )

    async def delete_session(self, session_id: str) -> None:
        await self._call("delete_session", self.redis.delete(self._session_key(session_id)))

    async def append_event(self, session_id: str, stream_id: str, message: dict[str, Any]) -> StreamEventRecord:
        seq_key = self._seq_key(session_id, stream_id)
        events_key = self._events_key(session_id, stream_id)
        sequence = await self._call("append_event", self.redis.incr(seq_key))
        record = StreamEventRecord(stream_id=stream_id, sequence=sequence, message=message)
        await self._call("append_event", self.redis.rpush(events_key, json.dumps(record.model_dump())))
        await self._call("append_event", self.redis.ltrim(events_key, -self.max_events, -1))
        # Keep the counters and event log alive for at least `ttl` seconds
        # after the last write, mirroring session retention.
        await self._call("append_event", self.redis.expire(events_key, self.ttl))
        await self._call("append_event", self.redis.expire(seq_key, self.ttl))
        return record

    async def events_after(self, session_id: str, stream_id: str, sequence: int) -> list[StreamEventRecord]:
        raw_events = await self._call("events_after", self.redis.lrange(self._events_key(session_id, stream_id), 0, -1))
        records = [StreamEventRecord.model_validate_json(raw) for raw in raw_events]
        return [r for r in records if r.sequence > sequence]


__all__ = [
    "InMemorySessionStore",
    "RedisSessionStore",
    "SessionRecord",
    "SessionStore",
    "SessionStoreUnavailable",
    "StreamEventRecord",
]
