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

* ``view`` — ``"flow" | "dispatch" | "both" | "state"`` (default ``"both"``).
* ``replay`` — ``true|false`` (default ``true``).
* ``last_seen`` — ``int``, ``view="state"`` only (AHP reconnect semantics,
  FEAT-322 TASK-1854): replays ``flow:{run_id}:actions`` envelopes with
  ``server_seq > last_seen`` instead of the initial snapshot.

The handler is intentionally a thin wrapper over
:class:`FlowStreamMultiplexer` so the merge / dispatch-discovery logic is
unit-testable without an aiohttp test server.

``view="state"`` (FEAT-322) is a separate code path from the legacy
``flow``/``dispatch``/``both`` views: it reads ONLY the operational
``flow:{run_id}:actions`` stream (never the flow/dispatch streams) and
folds it through the transport-free ``session_state.reduce()`` — this
works identically for a live run or a finished one (crash-rebuild
invariant, spec §7), and deliberately never looks up a live
``SessionHost``/``DevLoopRunner`` (the multiplexer may run in another
worker process). Legacy views are untouched — zero changes to their code
paths.
"""

from __future__ import annotations

import asyncio
import heapq
import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Tuple

from aiohttp import web

from parrot.flows.dev_loop.session_state import (
    ActionEnvelope,
    DevLoopSessionState,
    Snapshot,
    reduce,
    session_channel,
)

logger = logging.getLogger(__name__)


SourceLiteral = Literal["flow", "dispatch"]
ViewLiteral = Literal["flow", "dispatch", "both", "state"]


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
        # FEAT-322 TASK-1854 — the operational actions stream, ``view="state"``
        # only. Never mixed into the flow/dispatch discovery/merge above.
        self._actions_key = f"flow:{run_id}:actions"
        self._state_cursor = "$"
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
    # State view (FEAT-322 TASK-1854) — reads ONLY flow:{run_id}:actions
    # ------------------------------------------------------------------

    async def _read_action_envelopes(self) -> List[Tuple[str, ActionEnvelope]]:
        """Read + parse every entry on the actions stream, in stream order.

        Returns ``(entry_id, envelope)`` pairs. Malformed entries (parse
        failure) are logged and skipped — forward-compat: an unknown/newer
        action type inside an envelope must never crash the view. Order is
        NOT re-sorted: ``server_seq`` ordering comes free from the Redis
        stream (single writer per run, TASK-1851's sink).
        """
        entries = await self._redis.xrange(self._actions_key, min="-", max="+")
        out: List[Tuple[str, ActionEnvelope]] = []
        for entry_id, fields in entries:
            raw = fields.get("envelope") if isinstance(fields, dict) else None
            if raw is None:
                continue
            try:
                envelope = ActionEnvelope.model_validate_json(raw)
            except Exception:  # noqa: BLE001 - forward-compat, never crash the view
                logger.debug(
                    "state view: skipping malformed actions-stream entry %s "
                    "for run=%s", entry_id, self._run_id, exc_info=True,
                )
                continue
            out.append((entry_id, envelope))
        return out

    async def state_replay(
        self, *, last_seen: Optional[int] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """``view="state"`` connect sequence — snapshot or gap replay.

        Folds every envelope on ``flow:{run_id}:actions`` from seq 0
        through :func:`reduce` (works identically for a live run or a
        finished one — no live host lookup, spec §7 crash-rebuild
        invariant).

        * ``last_seen is None`` (fresh connect): yields the folded
          :class:`Snapshot` as the FIRST frame, then nothing else from this
          historical batch (the snapshot already reflects it).
        * ``last_seen is not None`` (AHP reconnect): skips the snapshot and
          yields only envelopes with ``server_seq > last_seen`` — no gaps,
          no duplicates.

        Sets ``self._state_cursor`` to the last raw stream entry id seen,
        so a subsequent :meth:`state_tail` call continues from exactly
        where this method left off.
        """
        entries = await self._read_action_envelopes()
        state = DevLoopSessionState(
            run_id=self._run_id, channel=session_channel(self._run_id)
        )
        from_seq = 0
        for _entry_id, envelope in entries:
            state = reduce(state, envelope.action)
            from_seq = envelope.server_seq

        if entries:
            self._state_cursor = entries[-1][0]

        if last_seen is None:
            snapshot = Snapshot(
                channel=session_channel(self._run_id),
                state=state,
                from_seq=from_seq,
            )
            yield {
                "source": "state",
                "node_id": None,
                "event_kind": "snapshot",
                "ts": time.time(),
                "payload": snapshot.model_dump(),
            }
            return

        for _entry_id, envelope in entries:
            if envelope.server_seq <= last_seen:
                continue
            yield {
                "source": "state",
                "node_id": None,
                "event_kind": "action",
                "ts": envelope.action.ts,
                "payload": envelope.model_dump(),
            }

    async def state_tail(self) -> AsyncIterator[Dict[str, Any]]:
        """``view="state"`` live continuation after :meth:`state_replay`.

        Uses ``XREAD BLOCK`` from ``self._state_cursor`` (populated by
        ``state_replay``, or ``"$"`` — new entries only — if that method
        was never called). Malformed entries are logged and skipped, same
        forward-compat contract as :meth:`_read_action_envelopes`.
        """
        while not self._closed.is_set():
            try:
                response = await self._redis.xread(
                    streams={self._actions_key: self._state_cursor},
                    block=self._block_ms,
                    count=100,
                )
            except Exception as exc:  # pragma: no cover - transport errors
                logger.warning("state-view xread failed: %s", exc)
                await asyncio.sleep(0.5)
                continue
            if not response:
                continue
            for stream_key, stream_entries in response:
                if isinstance(stream_key, bytes):
                    stream_key = stream_key.decode("utf-8")
                for entry_id, fields in stream_entries:
                    if isinstance(entry_id, bytes):
                        entry_id = entry_id.decode("utf-8")
                    self._state_cursor = entry_id
                    raw = fields.get("envelope") if isinstance(fields, dict) else None
                    if raw is None:
                        continue
                    try:
                        envelope = ActionEnvelope.model_validate_json(raw)
                    except Exception:  # noqa: BLE001 - forward-compat
                        logger.debug(
                            "state view: skipping malformed live entry %s "
                            "for run=%s", entry_id, self._run_id, exc_info=True,
                        )
                        continue
                    yield {
                        "source": "state",
                        "node_id": None,
                        "event_kind": "action",
                        "ts": envelope.action.ts,
                        "payload": envelope.model_dump(),
                    }

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

    * ``view`` — ``"flow" | "dispatch" | "both" | "state"`` (default ``"both"``).
    * ``replay`` — ``true|false`` (default ``true``, legacy views only).
    * ``last_seen`` — ``int``, ``view="state"`` only (FEAT-322): reconnect
      replay — envelopes with ``server_seq > last_seen`` instead of the
      initial snapshot.

    Emits a JSON envelope per event:

    .. code-block:: json

        {"source": "flow"|"dispatch", "node_id": str|null,
         "event_kind": str, "ts": float, "payload": {...}}

    ``view="state"`` emits the AHP-style snapshot/action shape instead
    (``source="state"``, ``event_kind="snapshot"|"action"``,
    ``payload`` = ``Snapshot``/``ActionEnvelope`` — see
    :meth:`FlowStreamMultiplexer.state_replay`); legacy views are
    byte-identical to before this parameter existed.

    The owning aiohttp app must populate ``request.app["redis_url"]``
    (or ``request.app["redis"]`` with a pre-built client). The handler
    closes both the Redis connection it created and the WebSocket on
    client disconnect.
    """
    run_id = request.match_info["run_id"]
    view: ViewLiteral = request.query.get("view", "both")  # type: ignore[assignment]
    if view not in ("flow", "dispatch", "both", "state"):
        view = "both"
    replay = request.query.get("replay", "true").lower() == "true"
    last_seen_raw = request.query.get("last_seen")
    last_seen: Optional[int] = None
    if last_seen_raw is not None:
        try:
            last_seen = int(last_seen_raw)
        except ValueError:
            last_seen = None

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
        if view == "state":
            # FEAT-322 TASK-1854 — separate code path; legacy branch below
            # is completely untouched.
            async for envelope in mux.state_replay(last_seen=last_seen):
                if ws.closed:
                    break
                await ws.send_json(envelope)
            async for envelope in mux.state_tail():
                if ws.closed:
                    break
                await ws.send_json(envelope)
        else:
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
        # Ctrl-C / aiohttp GracefulExit / client disconnect all surface
        # as CancelledError here. We deliberately do NOT re-raise:
        # aiohttp 3.x's RequestHandler races on _handler_waiter.set_result
        # during shutdown and produces an `InvalidStateError` wall of
        # red if we propagate. The cancel is honored implicitly by
        # returning normally — the surrounding cleanup (finally block)
        # still runs.
        logger.debug("flow_stream_ws cancelled for run=%s", run_id)
    except Exception as exc:  # pragma: no cover - log and swallow
        logger.exception("flow_stream_ws error for run=%s: %s", run_id, exc)
    finally:
        # Each await here is wrapped because the loop may already be
        # tearing down on Ctrl-C — losing one cleanup step shouldn't
        # mask the others.
        try:
            await mux.close()
        except Exception:  # pragma: no cover
            logger.debug("mux.close() raised during shutdown", exc_info=True)
        if owns_redis:
            try:
                await redis_client.aclose()
            except AttributeError:  # pragma: no cover - older redis-py
                try:
                    await redis_client.close()
                except Exception:  # pragma: no cover
                    logger.debug(
                        "redis close raised during shutdown", exc_info=True
                    )
            except Exception:  # pragma: no cover
                logger.debug("redis aclose raised during shutdown",
                             exc_info=True)
        if not ws.closed:
            try:
                await ws.close()
            except Exception:  # pragma: no cover
                logger.debug("ws.close raised during shutdown", exc_info=True)
    return ws


__all__ = ["FlowStreamMultiplexer", "flow_stream_ws"]
