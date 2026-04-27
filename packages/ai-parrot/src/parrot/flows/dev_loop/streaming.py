"""FlowStreamMultiplexer — aiohttp WebSocket fan-in for two Redis streams.

Implements **Module 3** of the dev-loop spec. The UI (nav-admin Svelte
plugin) consumes a single WebSocket per flow run; the multiplexer fans
in:

* ``flow:{run_id}:flow`` — flow-level events emitted by ``AgentsFlow``.
* ``flow:{run_id}:dispatch:{node_id}`` — per-dispatch events emitted by
  :class:`ClaudeCodeDispatcher`.

Goal (spec G4): the UI never speaks Redis directly. The multiplexer
emits flat JSON envelopes:

.. code-block:: json

    {"source": "flow"|"dispatch", "node_id": str|null,
     "event_kind": str, "ts": float, "payload": {...}}

Query parameters on the WebSocket URL:

* ``view`` — ``"flow" | "dispatch" | "both"`` (default ``"both"``).
* ``replay`` — ``true|false`` (default ``true``).

The handler is intentionally a thin wrapper over
:class:`FlowStreamMultiplexer` so the merge / dispatch-discovery logic is
unit-testable without an aiohttp test server.
"""

from __future__ import annotations

import asyncio
import heapq
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Tuple

from aiohttp import web

logger = logging.getLogger(__name__)


SourceLiteral = Literal["flow", "dispatch"]
ViewLiteral = Literal["flow", "dispatch", "both"]


# ---------------------------------------------------------------------------
# FlowStreamMultiplexer
# ---------------------------------------------------------------------------


class FlowStreamMultiplexer:
    """Merge events from a flow stream and many dispatch streams."""

    def __init__(
        self,
        redis: Any,
        *,
        run_id: str,
        view: ViewLiteral = "both",
        dispatch_refresh_seconds: float = 2.0,
        block_ms: int = 1000,
    ) -> None:
        """Construct a multiplexer.

        Args:
            redis: An ``redis.asyncio.Redis`` instance with
                ``decode_responses=True``.
            run_id: The flow run id; appears in stream keys.
            view: Which sources to emit (``flow``/``dispatch``/``both``).
            dispatch_refresh_seconds: Polling interval for the
                ``KEYS flow:{run_id}:dispatch:*`` discovery loop.
            block_ms: ``XREAD BLOCK <ms>`` timeout — controls how often
                the live loop wakes up to re-check dispatch discovery.
        """
        self._redis = redis
        self._run_id = run_id
        self._view: ViewLiteral = view
        self._dispatch_refresh_seconds = dispatch_refresh_seconds
        self._block_ms = block_ms
        self._flow_key = f"flow:{run_id}:flow"
        self._dispatch_prefix = f"flow:{run_id}:dispatch:"
        # Per-stream cursor for XREAD BLOCK $, populated lazily.
        self._cursors: Dict[str, str] = {}
        self._closed = asyncio.Event()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def _discover_dispatch_streams(self) -> List[str]:
        """Return all dispatch stream keys for this run.

        Uses ``SCAN`` (cursor-based iteration) rather than ``KEYS`` so a
        flow run with many dispatch streams does not block the Redis
        server. ``KEYS`` is O(N) and discouraged for production use.
        """
        result: List[str] = []
        cursor = 0
        scan = getattr(self._redis, "scan", None)
        if scan is None:
            # Fallback for stubs that only implement ``keys`` (test env).
            keys = await self._redis.keys(f"{self._dispatch_prefix}*")
            for k in keys:
                result.append(k.decode("utf-8") if isinstance(k, bytes) else k)
            return sorted(result)
        while True:
            cursor, keys = await scan(
                cursor=cursor,
                match=f"{self._dispatch_prefix}*",
                count=100,
            )
            for k in keys:
                result.append(
                    k.decode("utf-8") if isinstance(k, bytes) else k
                )
            if cursor == 0:
                break
        return sorted(set(result))

    async def _subscribed_streams(self) -> List[str]:
        """Compute the active list of stream keys based on ``view``."""
        streams: List[str] = []
        if self._view in ("flow", "both"):
            streams.append(self._flow_key)
        if self._view in ("dispatch", "both"):
            streams.extend(await self._discover_dispatch_streams())
        return streams

    # ------------------------------------------------------------------
    # Replay
    # ------------------------------------------------------------------

    async def replay(self) -> AsyncIterator[Dict[str, Any]]:
        """Replay historical events from every subscribed stream.

        Reads ``XRANGE 0 +`` from each stream, decodes the
        :class:`DispatchEvent` payload, merges by ``ts`` ascending, and
        yields one envelope per event. The cursor for each stream is
        updated to the last seen entry id so the subsequent ``tail()``
        call only forwards genuinely new events.
        """
        streams = await self._subscribed_streams()
        # heap entries: (ts, stream_key, entry_id, fields_dict)
        heap: List[Tuple[float, str, str, Dict[str, str]]] = []
        for stream_key in streams:
            entries = await self._redis.xrange(stream_key, min="-", max="+")
            for entry_id, fields in entries:
                ts = self._extract_ts(fields, entry_id)
                heap.append((ts, stream_key, entry_id, fields))
                self._cursors[stream_key] = entry_id
        heapq.heapify(heap)
        while heap:
            ts, stream_key, entry_id, fields = heapq.heappop(heap)
            envelope = self._fields_to_envelope(stream_key, fields, ts=ts)
            if envelope is None:
                continue
            yield envelope

    # ------------------------------------------------------------------
    # Tail / live
    # ------------------------------------------------------------------

    async def tail(self) -> AsyncIterator[Dict[str, Any]]:
        """Forward live events as they arrive.

        Uses ``XREAD BLOCK <ms>`` with the per-stream cursor populated by
        :meth:`replay` (or initialised to ``"$"`` for streams discovered
        only after replay). Periodically re-discovers dispatch streams
        so events from late-arriving nodes are picked up.
        """
        last_discovery = 0.0
        while not self._closed.is_set():
            now = asyncio.get_running_loop().time()
            if now - last_discovery >= self._dispatch_refresh_seconds:
                # Refresh subscribed-streams set; new streams start at "$".
                for key in await self._subscribed_streams():
                    self._cursors.setdefault(key, "$")
                last_discovery = now
            if not self._cursors:
                # Nothing to read yet — wait for discovery to find streams.
                await asyncio.sleep(self._dispatch_refresh_seconds)
                continue
            streams_arg = dict(self._cursors)
            try:
                response = await self._redis.xread(
                    streams=streams_arg, block=self._block_ms, count=100
                )
            except Exception as exc:  # pragma: no cover - transport errors
                logger.warning("xread failed: %s", exc)
                await asyncio.sleep(0.5)
                continue
            if not response:
                continue
            for stream_key, entries in response:
                if isinstance(stream_key, bytes):
                    stream_key = stream_key.decode("utf-8")
                for entry_id, fields in entries:
                    if isinstance(entry_id, bytes):
                        entry_id = entry_id.decode("utf-8")
                    self._cursors[stream_key] = entry_id
                    ts = self._extract_ts(fields, entry_id)
                    envelope = self._fields_to_envelope(
                        stream_key, fields, ts=ts
                    )
                    if envelope is None:
                        continue
                    yield envelope

    async def close(self) -> None:
        """Stop the tail loop. Idempotent."""
        self._closed.set()

    # ------------------------------------------------------------------
    # Envelope helpers
    # ------------------------------------------------------------------

    def _classify_source(
        self, stream_key: str
    ) -> Tuple[SourceLiteral, Optional[str]]:
        if stream_key == self._flow_key:
            return "flow", None
        if stream_key.startswith(self._dispatch_prefix):
            return "dispatch", stream_key[len(self._dispatch_prefix):]
        # Should never happen; default to flow for safety.
        return "flow", None

    def _passes_view(self, source: SourceLiteral) -> bool:
        if self._view == "both":
            return True
        return self._view == source

    def _fields_to_envelope(
        self,
        stream_key: str,
        fields: Dict[str, str],
        *,
        ts: float,
    ) -> Optional[Dict[str, Any]]:
        """Translate a Redis stream entry into a UI envelope."""
        source, node_id = self._classify_source(stream_key)
        if not self._passes_view(source):
            return None
        # The dispatcher writes one field "event" containing the
        # JSON-encoded DispatchEvent. Be defensive against future
        # schema evolution.
        raw_event = fields.get("event") if isinstance(fields, dict) else None
        if raw_event is None:
            # Some flow-level events may write multiple plain fields
            # rather than a JSON blob; pass them through verbatim.
            return {
                "source": source,
                "node_id": node_id,
                "event_kind": fields.get("event_kind", "flow.unknown"),
                "ts": ts,
                "payload": dict(fields),
            }
        try:
            decoded = json.loads(raw_event)
        except (TypeError, ValueError):
            return {
                "source": source,
                "node_id": node_id,
                "event_kind": "stream.malformed",
                "ts": ts,
                "payload": {"raw": raw_event},
            }
        return {
            "source": source,
            "node_id": decoded.get("node_id", node_id),
            "event_kind": decoded.get("kind", "stream.unknown"),
            "ts": float(decoded.get("ts", ts)),
            "payload": decoded.get("payload", {}),
        }

    @staticmethod
    def _extract_ts(fields: Dict[str, str], entry_id: str) -> float:
        """Pull ``ts`` from the JSON event blob, fall back to entry id."""
        raw = fields.get("event") if isinstance(fields, dict) else None
        if isinstance(raw, str):
            try:
                decoded = json.loads(raw)
                return float(decoded.get("ts", 0.0))
            except (TypeError, ValueError):
                pass
        # entry_id format: "<ms>-<seq>"
        try:
            ms_part = entry_id.split("-", 1)[0]
            return int(ms_part) / 1000.0
        except (ValueError, AttributeError):
            return 0.0


# ---------------------------------------------------------------------------
# aiohttp handler
# ---------------------------------------------------------------------------


async def flow_stream_ws(request: web.Request) -> web.WebSocketResponse:
    """aiohttp WebSocket handler bound to ``GET /api/flow/{run_id}/ws``.

    Query parameters:

    * ``view`` — ``"flow" | "dispatch" | "both"`` (default ``"both"``).
    * ``replay`` — ``true|false`` (default ``true``).

    Emits a JSON envelope per event:

    .. code-block:: json

        {"source": "flow"|"dispatch", "node_id": str|null,
         "event_kind": str, "ts": float, "payload": {...}}

    The owning aiohttp app must populate ``request.app["redis_url"]``
    (or ``request.app["redis"]`` with a pre-built client). The handler
    closes both the Redis connection it created and the WebSocket on
    client disconnect.
    """
    run_id = request.match_info["run_id"]
    view: ViewLiteral = request.query.get("view", "both")  # type: ignore[assignment]
    if view not in ("flow", "dispatch", "both"):
        view = "both"
    replay = request.query.get("replay", "true").lower() == "true"

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    # Resolve redis client: prefer a pre-built one on the app, fall back
    # to constructing one from the URL.
    redis_client = request.app.get("redis")
    owns_redis = False
    if redis_client is None:
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(
            request.app["redis_url"], decode_responses=True
        )
        owns_redis = True

    mux = FlowStreamMultiplexer(redis_client, run_id=run_id, view=view)
    try:
        if replay:
            async for envelope in mux.replay():
                if ws.closed:
                    break
                await ws.send_json(envelope)
        async for envelope in mux.tail():
            if ws.closed:
                break
            await ws.send_json(envelope)
    except asyncio.CancelledError:  # pragma: no cover - shutdown path
        raise
    except Exception as exc:  # pragma: no cover - log and swallow
        logger.exception("flow_stream_ws error for run=%s: %s", run_id, exc)
    finally:
        await mux.close()
        if owns_redis:
            try:
                await redis_client.aclose()
            except AttributeError:  # pragma: no cover - older redis-py
                await redis_client.close()
        if not ws.closed:
            await ws.close()
    return ws


__all__ = ["FlowStreamMultiplexer", "flow_stream_ws"]
