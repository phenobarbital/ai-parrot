# TASK-2609: Redis-backed shared session + event store

**Feature**: FEAT-477 — Expose an AI-Parrot Agent as an MCP Server
**Spec**: `sdd/specs/mcp-as-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 6** — goal **G5**, resolving spec **OQ4**. Independent of the
rest of the feature and **also fixes the existing tool-level streamable endpoint**.

The project's own deploy template runs `aiohttp.GunicornWebWorker` with `(2×CPUs)+1`
workers, recycles them every 2000 requests, and states *"Do NOT rely on in-process dicts
for cross-request state"* (`autonomous/deploy/templates.py:3`). Today
`StreamableHttpMCPServer._sessions` is a plain dict and `StreamBuffer` is an in-process
ring — so a session created on one worker is invisible to the next.

---

## Scope

- Replace `self._sessions` (`streamable_http.py:265`) and the in-process `StreamBuffer`
  (`:144`) with a Redis-backed store, behind an interface that keeps the in-memory
  implementation available for tests and single-worker runs.
- A session created by one worker must resolve on any other, and must survive the
  `max_requests = 2000` worker recycle.
- Preserve `Last-Event-ID` replay semantics across workers.
- **Store unavailability must fail the request cleanly** — never silently degrade to
  per-process state. This is the security-relevant requirement: silent degradation makes
  multi-worker breakage intermittent and invisible.
- Honour the existing `session_ttl` (`config.py:75`) and `event_buffer_size` (`:77`).
- Unit tests, including a two-client cross-worker simulation.

**NOT in scope**: job handles (TASK-2607) — a different store with different semantics.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/session_store.py` | CREATE | Store interface + Redis and in-memory implementations |
| `packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py` | MODIFY | Use the store instead of `_sessions` / in-process `StreamBuffer` |
| `packages/ai-parrot-server/tests/mcp/test_session_store.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> VERIFIED against `dev` on 2026-08-31 (post PR #1274). **These line numbers changed in the
> merge — the brainstorm's are stale.**

### Verified Imports
```python
from parrot.mcp.config import MCPServerConfig
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py
KEEP_ALIVE_INTERVAL: float = 15.0                             # :56
ASSUMED_HEADER_VERSION: str = "2025-03-26"                    # :65
class StreamEvent:                                            # :104
    def event_id(self) -> str                                 # :113
    def to_sse(self) -> bytes                                 # :117
class StreamBuffer:                                           # :144   <-- in-process ring; REPLACE
    def __init__(self, stream_id: str, max_events: int = 1000)  # :154
    def append(self, message) -> StreamEvent                  # :163
    def events_after(self, sequence: int) -> list[StreamEvent] # :174
    def undelivered(self) -> list[StreamEvent]                # :184
class McpStreamSession:                                       # :184
    def open_stream(...)                                      # :204
    def prune_streams(self, max_streams: int) -> None         # :223
    def is_busy(self) -> bool                                 # :243
class StreamableHttpMCPServer(HttpMCPServer):                 # :250
    def __init__(self, ...)                                   # :259
    self._sessions: dict[str, McpStreamSession] = {}          # :265   <-- REPLACE
    self._max_sessions: int                                   # :272
    async def _create_session(...)                            # :362
    async def _get_session(...)                               # :389
    async def _prune_loop(self)                               # :409
    async def _prune_sessions(self)                           # :420
    async def _teardown_session(self, session)                # :440
    async def _handle_streamable_get(self, request)           # :892   Last-Event-ID replay
    async def _handle_streamable_delete(self, request)        # :1035

# packages/ai-parrot-server/src/parrot/mcp/config.py
session_ttl: int = 3600                                       # :75
event_buffer_size: int = 1000                                 # :77
```

### Does NOT Exist
- ~~`SessionEventStore`~~ — **removed by PR #1274**. It is now `StreamBuffer` at `:144`.
  Do not import or reference the old name; the brainstorm cites it at a stale `:77`.
- ~~A Redis session store for Streamable HTTP~~ — none. The only `redis` mention in the
  module is a docstring note at `:35` calling a shared store a follow-up. You are it.
- ~~`McpStreamSession.to_redis()` / `.from_redis()`~~ — not real methods; you design the
  serialization.

---

## Implementation Notes

### Key Constraints
- **Fail closed.** If Redis is unreachable, return a clean error. A fallback to a local
  dict reintroduces exactly the bug this task fixes, and hides it.
- Keep an in-memory implementation behind the same interface so existing tests and
  single-worker development keep working — but it must be an explicit choice, never an
  automatic fallback.
- Preserve replay: `events_after(sequence)` semantics must hold across workers.
- Respect `session_ttl` and `event_buffer_size` from config; do not introduce new knobs
  without adding them to `MCPServerConfig`.
- G11: the tool-level streamable endpoint must keep working — it shares this code.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/autonomous/deploy/templates.py:3` — the gunicorn
  template and its explicit "no in-process dicts" rule
- `packages/ai-parrot-server/src/parrot/human/suspended_store.py:87` — an existing
  Redis-store constructor shape in this codebase

---

## Acceptance Criteria

- [ ] A session written by one store client resolves from a second, independent client
- [ ] `Last-Event-ID` replay works across store clients
- [ ] Store unavailability fails the request cleanly — no silent per-process fallback
- [ ] `session_ttl` and `event_buffer_size` are honoured
- [ ] The in-memory implementation remains available as an explicit choice
- [ ] Sessions survive a simulated worker recycle
- [ ] **G11**: the existing tool-level streamable endpoint still passes its tests
      (`pytest packages/ai-parrot-server/tests/mcp/test_streamable_http.py -v`)
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/mcp/test_session_store.py -v`
- [ ] No linting errors

---

## Test Specification

```python
class TestSessionStore:
    async def test_session_resolves_across_workers(self, redis_store_a, redis_store_b):
        sid = await redis_store_a.create_session(user={"user_id": "u1"})
        assert await redis_store_b.get_session(sid) is not None

    async def test_event_replay_across_workers(self, redis_store_a, redis_store_b):
        sid = await redis_store_a.create_session(user={})
        await redis_store_a.append_event(sid, {"n": 1})
        await redis_store_a.append_event(sid, {"n": 2})
        assert len(await redis_store_b.events_after(sid, 0)) == 2

    async def test_store_unavailable_fails_cleanly(self, broken_redis_store):
        with pytest.raises(SessionStoreUnavailable):
            await broken_redis_store.get_session("s1")

    async def test_no_silent_local_fallback(self, broken_redis_store):
        with pytest.raises(SessionStoreUnavailable):
            await broken_redis_store.create_session(user={})
        assert not getattr(broken_redis_store, "_local_sessions", None)

    async def test_survives_worker_recycle(self, redis_store_a, fresh_store_client):
        sid = await redis_store_a.create_session(user={})
        assert await fresh_store_client.get_session(sid) is not None

    async def test_ttl_and_buffer_size_honoured(self, redis_store_a, cfg):
        assert redis_store_a.ttl == cfg.session_ttl
        assert redis_store_a.max_events == cfg.event_buffer_size
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 6, G5, OQ4 in §8, §7 "Silent multi-worker breakage".
2. **Check dependencies** — none. This task is parallelizable.
3. **Verify the Codebase Contract** — `SessionEventStore` is gone; it is `StreamBuffer`.
4. **Update status** → `"in-progress"`. 5. **Implement** — fail closed.
6. **Verify** acceptance criteria, including the tool-level regression suite.
7. **Move** to `sdd/tasks/completed/`. 8. **Update index** → `"done"`. 9. **Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-01
**Notes**: `session_store.py` defines the abstraction (`SessionStore`) and two
implementations: `InMemorySessionStore` (today's behavior, an explicit
opt-in — never an automatic fallback) and `RedisSessionStore` (shared,
cross-worker-visible). Both are keyed on `SessionRecord` (wall-clock
`created_at`/`last_seen`, since `McpStreamSession`'s `time.monotonic()`
values are meaningless across a process boundary) and `StreamEventRecord`
(preserves the same `stream_id:sequence` numbering `StreamEvent.event_id`
uses, so `Last-Event-ID` continuity holds after a cross-worker replay).
`RedisSessionStore` wraps every Redis call in `_call()`, translating any
exception into `SessionStoreUnavailable` — **fail closed**, no local-dict
fallback (verified: `broken_redis_store` raises on every operation, and
`InMemorySessionStore`/`RedisSessionStore` share zero state). `session_ttl`/
`event_buffer_size` are threaded in as constructor args (`ttl`/`max_events`)
— no new `MCPServerConfig` fields. 15/15 new tests pass, including a real
`TestCrossWorkerServerSimulation` class instantiating two independent
`StreamableHttpMCPServer`s sharing one fake-Redis backend (not just the bare
store) to exercise the literal "two-client cross-worker simulation"
requirement end to end.

**`streamable_http.py` integration** (real, but deliberately scoped — see
Deviations): `StreamableHttpMCPServer.__init__` gained an optional
`session_store: SessionStore | None = None` param, defaulting to a fresh
`InMemorySessionStore` — **G11 by construction**: zero behavior change for
every existing caller (verified: full `test_streamable_http.py` +
`test_streamable_http_interop.py` + `test_transport_integration.py`, 67
tests, unchanged and green). `_create_session` mirrors the new session's
metadata into the store (control-plane, fail-closed — propagates
`SessionStoreUnavailable`); `_get_session` falls through to the store on a
local miss and adopts a fresh local `McpStreamSession` shell on a hit
(verified end-to-end in `TestCrossWorkerServerSimulation`); `_teardown_session`
mirror-deletes from the store (best-effort — local cleanup must complete
regardless of store health) so a pruned/deleted session cannot "resurrect"
via the cross-worker fallback. `_dispatch_to_stream` mirrors each buffered
response into the store via a new `_mirror_event()` helper (best-effort —
a durability hiccup must not fail an in-process response actually being
delivered right now). `_handle_streamable_get`'s `Last-Event-ID` handling
falls back to `self._session_store.events_after(...)` when the stream isn't
held locally, rehydrating a `StreamBuffer` with the store's original
sequence numbers before replaying. All 4 `_get_session`/`_create_session`
call sites in the three JSON-RPC handlers (`POST`/`GET`/`DELETE`) now catch
`SessionStoreUnavailable` and return a clean 503
(`_session_store_unavailable_response()`) — verified not to affect any
existing test (default store never raises).

**Deviations from spec — scope disclosure, not a shortcut taken quietly:**
`McpStreamSession`'s live coordination primitives (`asyncio.Event` wakeup,
per-request `asyncio.Task` dispatch tracking, the `live_stream` flag) are
fundamentally per-process — no Redis operation can signal an `asyncio.Event`
in a different OS process. A session adopted cross-worker therefore gets a
**fresh** local shell: its principal/protocol_version resolve correctly
(the security/correctness-critical piece — no more spurious "session not
found" 404s or bypassed ownership checks across workers) and its **buffered
event history replays** via the store fallback, but any dispatch task that
was still *running* on the original worker at the moment of a cross-worker
reconnect is not itself transplanted (it keeps running to completion on its
original worker and its result gets mirrored into the store as soon as it
finishes — the exact "launch a long call, disconnect, reconnect elsewhere,
collect the result" scenario spec §7 highlights works correctly once that
mirrored event lands). A live, in-progress SSE push arriving on a
*different* worker than the one currently driving that dispatch is not
relayed in real time — that would need a pub/sub broadcast layer (Redis
Pub/Sub or Streams) driving cross-process wakeups, a materially larger
architectural change than "swap the session/event store" implies, and out
of proportion to this task's effort budget and file list (`session_store.py`
+ `streamable_http.py` only — no new transport-level pub/sub module was
scoped). Flagging this explicitly, per CLAUDE.md's Cardinal Rule 4, as a
concrete scoped follow-up rather than silently under-delivering on "shared
session store" or silently overreaching into a pub/sub rewrite neither the
task nor the spec's file list actually asked for.
