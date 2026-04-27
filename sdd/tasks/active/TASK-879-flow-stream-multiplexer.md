# TASK-879: `FlowStreamMultiplexer` aiohttp WebSocket handler

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-874, TASK-876
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** (`parrot.flows.dev_loop.streaming`). The UI
(nav-admin Svelte plugin, separate repo) consumes a single WebSocket per
flow run. The multiplexer fans-in two Redis streams:

- `flow:{run_id}:flow` — flow-level events emitted by `AgentsFlow`.
- `flow:{run_id}:dispatch:{node_id}` — per-dispatch events emitted by
  `ClaudeCodeDispatcher` (TASK-878).

Goal: the UI never imports a Redis client (spec G4).

Spec sections: §2 "Component Diagram", §3 Module 3, §4
`test_stream_multiplexer_replay_then_subscribe`,
`test_stream_multiplexer_view_filter`.

---

## Scope

- Implement `parrot/flows/dev_loop/streaming.py`:
  - `async def flow_stream_ws(request: web.Request) ->
    web.WebSocketResponse` — aiohttp handler bound to
    `GET /api/flow/{run_id}/ws`.
  - Internal class `FlowStreamMultiplexer` that owns the merge loop,
    so the handler is a thin wrapper over it.
- Query parameter handling:
  - `view`: `"flow" | "dispatch" | "both"` (default `"both"`).
  - `replay`: bool (`"true"|"false"`, default `"true"`).
- Replay phase (when `replay=true`): `XRANGE 0 +` on each subscribed
  stream, merge by `ts`, send each as a JSON envelope.
- Live phase: `XREAD BLOCK <ms> STREAMS ... $` loop, send each new
  event as it arrives. The multiplexer dynamically subscribes to new
  per-dispatch streams (`flow:{run_id}:dispatch:*`) discovered via
  `XLEN`/`KEYS` polling — keep a refresh interval (e.g., 2s) bounded.
- Envelope:
  ```json
  {"source": "flow"|"dispatch", "node_id": str|null,
   "event_kind": str, "ts": float, "payload": {...}}
  ```
- Graceful WebSocket close on client disconnect.

**NOT in scope**:
- Authentication / authorization on the WebSocket (deferred to the
  embedding aiohttp app).
- The orchestrator's flow-event production (separate concern; the
  orchestrator emits to `flow:{run_id}:flow` directly via `XADD`).
- The Svelte UI consumer (Module 14, separate repo).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py` | CREATE | Multiplexer + handler. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | MODIFY | Re-export `flow_stream_ws`, `FlowStreamMultiplexer`. |
| `packages/ai-parrot/tests/flows/dev_loop/test_streaming.py` | CREATE | Unit tests with a mocked Redis. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
import json
import time
from typing import AsyncIterator, Dict, List, Literal, Optional

import redis.asyncio as aioredis
from aiohttp import web                       # already in core deps

from parrot.flows.dev_loop.models import DispatchEvent
from parrot.conf import FLOW_STREAM_TTL_SECONDS
```

### Existing Signatures to Use

```python
# aiohttp WebSocket pattern (already used elsewhere in parrot.handlers):
async def handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    try:
        ...
    finally:
        await ws.close()
    return ws

# redis.asyncio.Redis API (verified against redis-py >=4.2):
#   xrange(name, min="-", max="+") -> list[(id, dict)]
#   xread(streams: dict, block: int|None, count: int|None) -> list[(stream, [(id, dict), ...])]
#   xlen(name) -> int
#   keys(pattern) -> list[bytes]
```

### Does NOT Exist

- ~~`aiohttp.web.WebSocketResponse.send_event(...)`~~ — use
  `await ws.send_json(...)`.
- ~~`redis.asyncio.Redis.subscribe(...)`~~ — that's the pub/sub API.
  This task uses **Redis Streams** (`XADD`/`XRANGE`/`XREAD`), not
  pub/sub. Mixing them is a common bug.
- ~~A central registry of "active streams"~~ — discover dispatch
  streams via `KEYS flow:{run_id}:dispatch:*` (or `SCAN` if perf
  matters; v1 may use `KEYS` for simplicity since the cardinality is
  bounded by the number of nodes).

---

## Implementation Notes

### Pattern to Follow

```python
async def flow_stream_ws(request):
    run_id = request.match_info["run_id"]
    view = request.query.get("view", "both")
    replay = request.query.get("replay", "true").lower() == "true"

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    redis = aioredis.from_url(request.app["redis_url"], decode_responses=True)
    mux = FlowStreamMultiplexer(redis, run_id=run_id, view=view)
    try:
        if replay:
            async for envelope in mux.replay():
                await ws.send_json(envelope)
        async for envelope in mux.tail():
            await ws.send_json(envelope)
    except asyncio.CancelledError:
        pass
    finally:
        await mux.close()
        await redis.close()
        await ws.close()
    return ws
```

### Merging by timestamp

Each Redis Stream entry has an auto-generated ID `<ms>-<seq>`. The
multiplexer should NOT re-sort events globally; instead:

- During **replay**: read each stream's full history, merge with a
  small heap (key by `ts` from the entry payload, fall back to the
  entry ID's millis), emit in order.
- During **tail**: events are already roughly time-ordered per stream.
  Just forward as they arrive — the UI can re-order client-side if
  needed.

Document this in code comments.

### View filter

```python
def _passes_view(self, source: Literal["flow", "dispatch"]) -> bool:
    if self.view == "both": return True
    return self.view == source
```

### Key Constraints

- Async throughout. No blocking IO. No `time.sleep`.
- Heartbeats every 30s on the `WebSocketResponse` (`heartbeat=30`).
- `aioredis.from_url(..., decode_responses=True)` so values arrive as
  `str` not `bytes`.
- Dispatch-stream discovery refresh: every 2s, do `await
  redis.keys(f"flow:{run_id}:dispatch:*")` and add any new ones.
- Tests use `fakeredis.aioredis` if available, else mock `aioredis`.

### References in Codebase

- `packages/ai-parrot/src/parrot/handlers/` — example aiohttp handler
  patterns.

---

## Acceptance Criteria

- [ ] `flow_stream_ws` is registered as an aiohttp route handler with
  the path `GET /api/flow/{run_id}/ws` (route registration is the
  caller's responsibility — document the path in the docstring).
- [ ] With `replay=true`, all historical events from both subscribed
  streams arrive on the WebSocket in `ts` order BEFORE any live event
  (`test_stream_multiplexer_replay_then_subscribe`).
- [ ] `view=flow` only forwards `source=="flow"` envelopes
  (`test_stream_multiplexer_view_filter`).
- [ ] `view=dispatch` only forwards `source=="dispatch"`.
- [ ] Closing the client cleanly closes the Redis connection (no
  leaked tasks).
- [ ] Tests pass:
  `pytest packages/ai-parrot/tests/flows/dev_loop/test_streaming.py -v`.

---

## Test Specification

```python
import json
import pytest
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web

from parrot.flows.dev_loop.streaming import flow_stream_ws


@pytest.fixture
def app(fake_redis):
    app = web.Application()
    app["redis_url"] = "fakeredis://"
    app.router.add_get("/api/flow/{run_id}/ws", flow_stream_ws)
    return app


@pytest.mark.asyncio
async def test_replay_then_subscribe(app, fake_redis):
    # pre-seed two streams with events; connect with ?replay=true;
    # assert history arrives before live events; assert ts ordering.
    ...


@pytest.mark.asyncio
async def test_view_filter_flow(app, fake_redis):
    # ?view=flow → only "source":"flow" envelopes.
    ...
```

---

## Agent Instructions

1. Read `parrot/handlers/` for the existing aiohttp route style.
2. Use `fakeredis` (if installed) for tests; otherwise mock
   `redis.asyncio.from_url` with `unittest.mock.AsyncMock`.
3. Implement; run tests; lint.
4. Move task to completed; update index; fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
