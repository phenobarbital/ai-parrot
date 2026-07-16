# TASK-1785: TransportBackend protocol, MemoryBackend, RedisPubSubBackend port

**Feature**: FEAT-310 — Unified EventBus v2 — queue-based dispatch, severity, ingress channels, and notifications
**Spec**: `sdd/specs/eventbus-v2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1784
**Assigned-to**: unassigned

---

## Context

Module 3 of FEAT-310 (spec §3). Defines the pluggable transport layer so
Memory (default), legacy Redis pub/sub, and later Redis Streams (TASK-1789)
are drop-in backends. Porting the legacy pub/sub kills the duplicated
dispatch path in `EventBus.start_redis_listener()` (evb.py:257), which
re-implements `publish()`'s matching inline.

---

## Scope

- Implement `backends/base.py`: `TransportBackend` Protocol —
  `async def publish(self, envelope: EventEnvelope) -> None`,
  `async def start_consumer(self, on_envelope: Callable[[EventEnvelope], Awaitable[None]]) -> None`,
  `async def close(self) -> None`.
- Implement `backends/memory.py`: `MemoryBackend` — in-process; `publish`
  feeds `on_envelope` directly (BusCore's queues provide the buffering);
  at-most-once semantics.
- Implement `backends/redis_pubsub.py`: `RedisPubSubBackend` — port of the
  legacy listener: `PUBLISH`/`psubscribe` on `parrot:events:*` channels,
  envelope `to_dict()`/`from_dict()` as the wire format; consumer loop as a
  background task feeding `on_envelope` (fan-out only, at-most-once,
  unpersisted — documented).
- Wire `BusCore` to an optional backend (constructor kwarg `backend:
  TransportBackend | None`); local dispatch always runs, backend fan-out is
  additive (matches current dual local+Redis behavior of `publish()`).
- Unit tests with a fake/mocked redis client (no live Redis in unit tier).

**NOT in scope**: Redis Streams / consumer groups / ACK (TASK-1789),
`evb.py` facade rewiring (TASK-1786).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/bus/backends/__init__.py` | CREATE | exports |
| `packages/ai-parrot/src/parrot/core/events/bus/backends/base.py` | CREATE | `TransportBackend` protocol |
| `packages/ai-parrot/src/parrot/core/events/bus/backends/memory.py` | CREATE | `MemoryBackend` |
| `packages/ai-parrot/src/parrot/core/events/bus/backends/redis_pubsub.py` | CREATE | legacy pub/sub port |
| `packages/ai-parrot/src/parrot/core/events/bus/core.py` | MODIFY | optional `backend` kwarg + fan-out |
| `packages/ai-parrot/tests/core/events/bus/test_backends.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` 2026-07-16 (commit b7226186d).

### Verified Imports
```python
import redis.asyncio as aioredis                      # already used in evb.py
from parrot.core.events.bus.envelope import EventEnvelope   # TASK-1783
from parrot.core.events.bus.core import BusCore              # TASK-1784
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/core/events/evb.py — the code being ported
class EventBus:
    CHANNEL_PREFIX = "parrot:events:"                 # line 83 — keep for wire compat
    async def start_redis_listener(self)              # line 257 — duplicated dispatch; absorb into RedisPubSubBackend
    async def close(self)                             # line 117 — punsubscribe() fix at line 124 already on dev

# packages/ai-parrot/src/parrot/core/hooks/brokers/base.py — consumer lifecycle pattern
class BaseBrokerHook:
    async def start(self) -> None:                    # line 29
        self._consume_task = asyncio.create_task(self._run_consumer())   # line 31
    async def _run_consumer(self) -> None:            # line 56
```

### Does NOT Exist
- ~~Redis Streams usage (`XADD`/`XREADGROUP`)~~ — TASK-1789, not here.
- ~~Persistence/replay in pub/sub~~ — pub/sub stays at-most-once by design.
- ~~`parrot.core.events.bus.backends`~~ — created by THIS task.
- ~~A shared "connection manager" for Redis in core/events~~ — each backend owns its `aioredis.Redis` client (same as evb.py today).

---

## Implementation Notes

### Pattern to Follow
Consumer-task lifecycle mirrors `BaseBrokerHook.start() → connect() +
create_task(self._run_consumer())` (hooks/brokers/base.py:29-56): store the
task, cancel + await on `close()`, reconnect loop with backoff on
`ConnectionError` (degraded-mode: log + emit meta-event via callback, keep
local dispatch alive — spec §7 "Redis down").

### Key Constraints
- Wire format: `EventEnvelope.to_dict()` JSON — one format for pub/sub AND
  future Streams backend.
- Keep `CHANNEL_PREFIX = "parrot:events:"` so old and new processes can
  interoperate during rollout.
- No new required dependencies; `redis` is already present.
- Backend fan-out must be fire-and-forget from BusCore's perspective (never
  blocks local dispatch).

### References in Codebase
- `packages/ai-parrot/src/parrot/core/events/evb.py:257` — logic being absorbed
- `packages/ai-parrot/src/parrot/core/hooks/brokers/base.py` — consumer loop pattern

---

## Acceptance Criteria

- [ ] `TransportBackend` protocol importable; `MemoryBackend` and `RedisPubSubBackend` satisfy it (isinstance/runtime-checkable or mypy-level check).
- [ ] `BusCore(backend=...)` fans out published envelopes to the backend without delaying local dispatch.
- [ ] `RedisPubSubBackend` round-trips an envelope through a mocked pubsub (publish → wire dict → consumer → identical envelope).
- [ ] Redis connection failure triggers reconnect-with-backoff; local dispatch unaffected.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/core/events/bus/test_backends.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/bus/` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/core/events/bus/test_backends.py
import pytest
from parrot.core.events.bus.backends.base import TransportBackend
from parrot.core.events.bus.backends.memory import MemoryBackend
from parrot.core.events.bus.backends.redis_pubsub import RedisPubSubBackend


async def test_memory_backend_delivers_to_consumer(): ...
async def test_pubsub_wire_roundtrip(mock_redis): ...
async def test_pubsub_reconnect_backoff(mock_redis_failing): ...
async def test_buscore_fanout_nonblocking(): ...
```

---

## Agent Instructions

1. Read spec §2 layer 3 and §7 ("Redis down") first; verify contract references.
2. Verify TASK-1784 is in `sdd/tasks/completed/`.
3. Do NOT modify `evb.py` — the facade rewire is TASK-1786.
4. Update `sdd/tasks/index/eventbus-v2.json` status transitions.
5. Move this file to `sdd/tasks/completed/` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
