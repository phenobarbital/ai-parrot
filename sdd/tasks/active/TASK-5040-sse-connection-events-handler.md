# TASK-5040: SSE endpoint GET /api/v1/connections/events + push wiring

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5033
**Assigned-to**: unassigned

---

## Context

Spec §2 "Push (M1, D1)" and §3 Module 1: an authenticated Server-Sent-Events stream relays only the session
principal's `connection.*` events, fed by `RedisConnectionPush` (TASK-5033). This task adds the handler, registers the
route, and wires the sink onto the shared publisher at server setup. AC-2, AC-3, AC-4.

Two facts found while verifying (not in the spec text):
- **Route order.** `/api/v1/connections/{provider}` (ConnectionsHandler, `manager.py:2489`) would capture `events`;
  the SSE route MUST be registered **before** it.
- **Publisher ownership.** On `dev` the only `ConnectionEventPublisher` is built lazily by the integrations package
  (`parrot/integrations/manager.py:146-158`, `_connection_publisher(app)`, reusing `app["connection_event_publisher"]`
  when present). A server without integration bots has no publisher at all, and descriptor providers read
  `app.get("connection_event_publisher")` at setup (`manager.py:2824`). So the server creates the shared publisher
  itself (same shape as integrations: singleton `ChannelNotifierRegistry()` + `AuditLedger()` + fan-out bus) when the key
  is absent, before descriptor providers are registered; the integrations path then reuses it.

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/handlers/connection_events.py` with `ConnectionEventsHandler(BaseView)`:
  - `get()`: principal = session Navigator id only (same `_get_user_id` logic as `ConnectionsHandler`, never a query/body
    value) → 401 JSON when absent; `app["connection_push"]` missing → 503 JSON.
  - `web.StreamResponse` headers `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `Connection: keep-alive`,
    `X-Accel-Buffering: no` (no `Access-Control-Allow-Origin: *`).
  - Frames: `event: connection\ndata: <ConnectionEvent.model_dump_json()>\n\n`; `: keep-alive\n\n` every 25 s of silence.
  - Producer task iterates `push.subscribe(user_id)` into an `asyncio.Queue`; the writer loop waits on the queue with a
    25 s timeout (never `wait_for` the async generator's `__anext__` — cancelling it closes the generator).
  - Ends on client disconnect (`ConnectionResetError` / `asyncio.CancelledError`) and always cancels+awaits the producer.
- In `manager.py`:
  - add `_setup_connection_push(self, app)` (sync) and call it in `setup()` right before
    `self._register_descriptor_oauth2_providers(self.app)`; it ensures `app["connection_event_publisher"]`, builds
    `RedisConnectionPush(REDIS_URL)`, `publisher.add_sink(push)`, stores `app["connection_push"]`, appends `push.start` to
    `on_startup` and `push.close` to `on_cleanup`. Idempotent (guard on `app.get("connection_push")`).
  - register `router.add_view("/api/v1/connections/events", ConnectionEventsHandler)` immediately after the
    `/api/v1/connections` route and before `/api/v1/connections/{provider}`.
- Tests: session required / query user ignored, frames + keep-alive, unsubscribe on disconnect, cross-worker delivery,
  route precedence.

**NOT in scope**: no WebSocket route, no change to `UserSocketManager` / `wsService` (AC-4); UI store (TASK-5053);
channel-link routes (TASK-5041).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/connection_events.py` | CREATE | `ConnectionEventsHandler` (SSE) |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `_setup_connection_push`, route registration |
| `packages/ai-parrot-server/tests/unit/test_connection_events_handler.py` | CREATE | Handler + wiring tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web
from navigator.views import BaseView  # type: ignore[import]                      # pattern: handlers/connections.py:8
from navigator_auth.decorators import is_authenticated, user_session  # type: ignore[import]   # handlers/connections.py:9
from navigator_session import get_session  # type: ignore[import]                 # handlers/connections.py:10
from parrot.auth.oauth2.events import ConnectionEventPublisher, ChannelNotifierRegistry, setup_connection_fanout  # events.py:70, :41, :139
from parrot.security.audit_ledger import AuditLedger                              # packages/ai-parrot/src/parrot/security/audit_ledger.py:296 (no-arg ctor used at integrations/manager.py:153)
from parrot.observability.fanout import get_event_fanout_bus                      # packages/ai-parrot/src/parrot/observability/fanout.py:123
from parrot.services.connection_push import RedisConnectionPush                   # created by TASK-5033
# manager.py already imports REDIS_URL from ..conf (manager.py:100-110) and ConnectionsHandler (:41)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/connections.py
@is_authenticated()
@user_session()
class ConnectionsHandler(BaseView):                                   # :17-19
    async def _get_user_id(self) -> str | None                        # :22-39 — request.get("user_id") → session user_id/id; str or None
# packages/ai-parrot-server/src/parrot/manager/manager.py
    def setup(...)                                                    # :2331
        self._register_descriptor_oauth2_providers(self.app)          # :2400 (anchor, 1 occurrence)
        router.add_view("/api/v1/connections", ConnectionsHandler)    # :2488 (anchor, 1 occurrence)
        router.add_view("/api/v1/connections/{provider}", ConnectionsHandler)   # :2489
    def _register_descriptor_oauth2_providers(self, app) -> None      # :2806 (reads app.get("connection_event_publisher") :2824)
# packages/ai-parrot-integrations/src/parrot/integrations/manager.py:146-170 — _connection_publisher / _attach_fanout_bus (pattern to mirror; do NOT import it: server must not require integrations)
# packages/ai-parrot-server/src/parrot/handlers/stream.py:122-131 — SSE StreamResponse header pattern
# RedisConnectionPush (TASK-5033): start(), close(), deliver(event), subscribe(user_id) -> AsyncIterator[ConnectionEvent]
```

### Does NOT Exist
- ~~`parrot.handlers.connection_events`~~, ~~`app["connection_push"]`~~ — created here.
- ~~A server-side publisher factory~~ — only `parrot.integrations.manager._connection_publisher` (private, integrations package).
- ~~`EventSource` auth via query token~~ — the principal never comes from the query (spec, AC-2).
- ~~A WebSocket connections route~~ — must not be added (AC-4).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/connection_events.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/src/parrot/manager/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/test_connection_events_handler.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/connections.py#ConnectionsHandler",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#ConnectionEventPublisher",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#setup_connection_fanout"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `manager.py` is shared with TASK-5041, TASK-5047, TASK-5048 (they depend on this task); keep edits to the two anchors + one new method.
- Never log event payloads; log principal-agnostic counts only.
- AC-2 keep-alive ≤ 30 s → 25 s constant `KEEPALIVE_SECONDS = 25`.

---

## Implementation Blueprint

### Steps (in order)
1. Create the handler module — *why*: `manager.py` imports it.
2. Add `_setup_connection_push` and its call before descriptor-provider registration — *why*: descriptor managers must get the shared publisher.
3. Register the SSE route before the `{provider}` route — *why*: aiohttp matches in registration order.
4. Write tests; run them.

### `packages/ai-parrot-server/src/parrot/handlers/connection_events.py` (CREATE)
```python
"""SSE stream of the session principal's connection events (FEAT-777 M1)."""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web
from navigator.views import BaseView  # type: ignore[import]
from navigator_auth.decorators import is_authenticated, user_session  # type: ignore[import]
from navigator_session import get_session  # type: ignore[import]

logger = logging.getLogger(__name__)

KEEPALIVE_SECONDS = 25
_SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@is_authenticated()
@user_session()
class ConnectionEventsHandler(BaseView):
    """``GET /api/v1/connections/events`` — relays only the caller's ``connection.*`` events."""

    async def _get_user_id(self) -> str | None:
        """Session Navigator id only (same rules as ``ConnectionsHandler._get_user_id``)."""
        # FILL IN: copy handlers/connections.py:22-39 logic verbatim (request.get("user_id") → session user_id/id) — never query/body
        ...

    async def get(self) -> web.StreamResponse:
        """401 without session; 503 without push; SSE frames + keep-alive until the client disconnects."""
        user_id = await self._get_user_id()
        if not user_id:
            return web.json_response({"error": "Authenticated user not identified."}, status=401)
        push = self.request.app.get("connection_push")
        if push is None:
            return web.json_response({"error": "connection events unavailable"}, status=503)

        response = web.StreamResponse(status=200, headers=_SSE_HEADERS)
        await response.prepare(self.request)
        queue: "asyncio.Queue[str]" = asyncio.Queue()

        async def _produce() -> None:
            async for event in push.subscribe(user_id):
                await queue.put(event.model_dump_json())

        producer = asyncio.create_task(_produce(), name="connection-events-sse")
        try:
            # FILL IN: loop — wait_for(queue.get(), KEEPALIVE_SECONDS); on data write
            #   f"event: connection\ndata: {data}\n\n".encode(); on TimeoutError write b": keep-alive\n\n";
            #   stop when producer finished with an error (log it); break on ConnectionResetError — bounded by AC-2/AC-3
            ...
        finally:
            producer.cancel()
            # FILL IN: await producer suppressing CancelledError/Exception (log at debug) so the pubsub unsubscribes
            ...
        return response
```
**Why this shape**: the queue decouples Redis reads from the keep-alive timer, so a timeout never cancels the subscriber
generator; the `finally` guarantees the per-request pubsub is released (spec §7 Redis connection count).

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY — call site)
```python
# occurrences: 1 (verified: grep -c '        self._register_descriptor_oauth2_providers(self.app)' packages/ai-parrot-server/src/parrot/manager/manager.py)
# BEFORE — insert above `        self._register_descriptor_oauth2_providers(self.app)` (verified: manager.py:2400)
        # FEAT-777 M1: shared connection-event publisher + per-principal Redis push sink (SSE).
        self._setup_connection_push(self.app)
```

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY — method)
```python
# occurrences: 1 (verified: grep -c '    def _register_descriptor_oauth2_providers(self, app: web.Application) -> None:' packages/ai-parrot-server/src/parrot/manager/manager.py)
# BEFORE — insert above that def (verified: manager.py:2806)
    def _setup_connection_push(self, app: web.Application) -> None:
        """Ensure ``app["connection_event_publisher"]`` and attach the Redis SSE sink (FEAT-777 M1). Idempotent."""
        if app.get("connection_push") is not None:
            return
        try:
            from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEventPublisher, setup_connection_fanout
            from parrot.services.connection_push import RedisConnectionPush

            publisher = app.get("connection_event_publisher")
            if publisher is None:
                # FILL IN: mirror integrations/manager.py:146-170 — AuditLedger() into app["connection_audit_ledger"]
                #   (reuse if set), ConnectionEventPublisher(notifiers=ChannelNotifierRegistry(), audit_ledger=...),
                #   attach get_event_fanout_bus() via setup_connection_fanout when not None (log on failure), store app key
                ...
            push = RedisConnectionPush(REDIS_URL)
            publisher.add_sink(push)
            app["connection_push"] = push

            async def _start_push(_app: web.Application) -> None:
                await push.start()

            async def _close_push(_app: web.Application) -> None:
                await push.close()

            app.on_startup.append(_start_push)
            app.on_cleanup.append(_close_push)
        except Exception:  # noqa: BLE001 — SSE is additive; never block server setup
            self.logger.exception("Connection event push not configured; /api/v1/connections/events will return 503")
```

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY — route)
```python
# occurrences: 1 (verified: grep -c '        router.add_view("/api/v1/connections", ConnectionsHandler)' packages/ai-parrot-server/src/parrot/manager/manager.py)
# AFTER — insert below that line (verified: manager.py:2488); MUST stay above the "/api/v1/connections/{provider}" route
        # FEAT-777 M1: SSE stream — registered before /{provider} so "events" is not captured as a provider id.
        router.add_view("/api/v1/connections/events", ConnectionEventsHandler)
```
and add `from ..handlers.connection_events import ConnectionEventsHandler` next to
`from ..handlers.connections import ConnectionsHandler` (anchor occurrences: 1, verified manager.py:41).

### `packages/ai-parrot-server/tests/unit/test_connection_events_handler.py` (CREATE)
```python
"""Tests for the connection-events SSE handler and its wiring (FEAT-777 M1)."""

from __future__ import annotations

import asyncio
import time

import pytest
from aiohttp import web

from parrot.auth.oauth2.events import ConnectionEvent
from parrot.handlers.connection_events import KEEPALIVE_SECONDS, ConnectionEventsHandler


def _unwrap(method):
    """Remove authentication decorators for isolated handler tests (pattern: test_connections_handler.py)."""
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


@pytest.mark.asyncio
async def test_sse_handler_requires_session_and_ignores_query_user(aiohttp_client) -> None:
    """401 without session; ?user_id= is ignored (the session principal is used)."""
    # FILL IN: tiny web.Application whose route calls _unwrap(ConnectionEventsHandler.get) on a handler whose request
    #   has request["user_id"] set (or not); fake push capturing the subscribe(user_id) argument
    ...


@pytest.mark.asyncio
async def test_sse_frames_and_keepalive(aiohttp_client, monkeypatch) -> None:
    """event: connection frames; keep-alive comment (patch KEEPALIVE_SECONDS small); unsubscribes on client disconnect."""
    # FILL IN
    ...


@pytest.mark.asyncio
async def test_sse_cross_worker_delivery(aiohttp_client) -> None:
    """Two app instances on one Redis (db 15): deliver on A's push, B's stream receives it; skip if Redis unreachable."""
    # FILL IN
    ...


def test_events_route_precedes_provider_route() -> None:
    """GET /api/v1/connections/events resolves to ConnectionEventsHandler, not ConnectionsHandler."""
    # FILL IN: build a router with the manager's registration order (or inspect the manager's setup) and resolve the path
    ...
```

### FILL IN checklist
- [ ] `_get_user_id` copy — bounded by AC-2 (never query/body).
- [ ] Writer loop + producer cleanup — bounded by AC-2 (≤30 s keep-alive), AC-3, spec §7.
- [ ] Publisher creation mirroring the integrations shape — bounded by "core never imports integrations".
- [ ] Four tests — bounded by spec §4 M1 rows.

---

## Acceptance Criteria

- [ ] AC-2: only the session principal's events; principal never from query/body; keep-alive every 25 s.
- [ ] AC-3: an event published on another app instance reaches the stream within 2 s; another principal's stream gets nothing.
- [ ] AC-4: no WebSocket route; `UserSocketManager`/`wsService` untouched.
- [ ] `GET /api/v1/connections/events` is not captured by `ConnectionsHandler`.
- [ ] Existing `test_connections_handler.py` passes; `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_connection_events_handler.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_connections_handler.py -q`

---

## Test Specification

See the CREATE test block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** (§2 "Push (M1, D1)", §3 Module 1, AC-2–AC-4)
3. **Check dependencies** — TASK-5033 must be `"done"` in `sdd/tasks/index/connections-web-slack.json`
4. **Verify the Codebase Contract** before writing code
5. **Update status** → `"in-progress"` and commit only the index file
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the listed files
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5040 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
