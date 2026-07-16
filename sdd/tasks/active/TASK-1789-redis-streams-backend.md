# TASK-1789: RedisStreamsBackend — durable at-least-once distributed mode

**Feature**: FEAT-310 — Unified EventBus v2 — queue-based dispatch, severity, ingress channels, and notifications
**Spec**: `sdd/specs/eventbus-v2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1785
**Assigned-to**: unassigned

---

## Context

Module 7 of FEAT-310 (spec §3, Phase 2) — goal G4. Redis pub/sub is
at-most-once and unpersisted; crashed consumers lose events. This backend
brings consumer groups, ACKs, pending-claim recovery, and `event_id` dedup:
at-least-once delivery across Cloud Run instances with zero app-code change
(it's just another `TransportBackend`).

---

## Scope

- Implement `backends/redis_streams.py`: `RedisStreamsBackend` satisfying the
  `TransportBackend` protocol (TASK-1785):
  - `publish`: `XADD parrot:stream:<topic-class>` with the envelope
    `to_dict()` wire format (topic-class = first topic segment, documented).
  - Consumer loop: `XREADGROUP` with per-instance consumer name
    (hostname+pid based), explicit `XACK` after successful `on_envelope`.
  - `XAUTOCLAIM` sweeper task reclaiming messages pending past
    `min_idle_time` (crashed consumer recovery).
  - `event_id` dedup: TTL'd Redis SET (`SET key NX EX <ttl>`) checked before
    dispatching to `on_envelope` — mitigates duplicate delivery.
  - Group auto-create (`XGROUP CREATE ... MKSTREAM`), reconnect-with-backoff
    (reuse TASK-1785 degraded-mode pattern).
  - Retention: choose `MAXLEN ~` vs `MINID` during implementation
    (*resolved in brainstorm: evaluate during implementation*) — RECORD the
    decision + rationale in the Completion Note below.
- Tests: unit tier with `fakeredis` if it supports streams in our pinned
  version, otherwise mark `@pytest.mark.integration` against real Redis.
  Must cover ACK, autoclaim reclaim, and dedup.

**NOT in scope**: BusCore changes (protocol already accommodates backends),
DLQ persistence (TASK-1788 handles it backend-agnostically), pub/sub backend.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/bus/backends/redis_streams.py` | CREATE | Streams backend |
| `packages/ai-parrot/src/parrot/core/events/bus/backends/__init__.py` | MODIFY | export |
| `packages/ai-parrot/tests/core/events/bus/test_redis_streams.py` | CREATE | ACK/autoclaim/dedup tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` 2026-07-16 (commit b7226186d).

### Verified Imports
```python
import redis.asyncio as aioredis                               # already used in evb.py
from parrot.core.events.bus.backends.base import TransportBackend   # TASK-1785
from parrot.core.events.bus.envelope import EventEnvelope            # TASK-1783
```

### Existing Signatures to Use
```python
# TASK-1785 protocol (backends/base.py):
class TransportBackend(Protocol):
    async def publish(self, envelope: EventEnvelope) -> None
    async def start_consumer(self, on_envelope) -> None
    async def close(self) -> None

# packages/ai-parrot/src/parrot/core/hooks/brokers/base.py — consumer-task lifecycle
class BaseBrokerHook:
    async def start(self) -> None:                             # line 29
        self._consume_task = asyncio.create_task(self._run_consumer())   # line 31
    async def _run_consumer(self) -> None:                     # line 56

# redis.asyncio client methods used (redis-py, already a dependency):
# xadd, xreadgroup, xack, xautoclaim, xgroup_create, set(name, v, nx=True, ex=ttl)
```

### Does NOT Exist
- ~~Redis Streams usage anywhere in the repo~~ — only pub/sub today; every `X*` call is new code from THIS task.
- ~~Exactly-once delivery~~ — dedup SET mitigates but does NOT eliminate duplicates; consumers must be idempotent — document loudly (spec §7).
- ~~A stream-per-topic design~~ — spec fixes stream-per-**topic-class** (`parrot:stream:<topic-class>`); do not shard per full topic.
- ~~`fakeredis` in dependencies~~ — check `pyproject.toml` dev extras first; if absent, add as dev dependency via `uv` OR mark tests integration-only.

---

## Implementation Notes

### Pattern to Follow
Consumer lifecycle: `start_consumer()` spawns `_run_consumer()` +
`_run_autoclaim_sweeper()` tasks (mirror `BaseBrokerHook`); `close()` cancels
both, ACKs in-flight handled messages, closes the client.

### Key Constraints
- Consumer name must be stable per instance for XAUTOCLAIM bookkeeping:
  `f"{socket.gethostname()}-{os.getpid()}"`.
- Dedup TTL default 24h, configurable; dedup key `parrot:events:dedup:<event_id>`.
- Blocking `XREADGROUP` with `block=` ms timeout inside the loop so `close()`
  can cancel promptly.
- Deployment note (spec §2 integration table): requires reachable
  Memorystore/Upstash on Cloud Run — config only, no code assumptions.
- Retention decision (`MAXLEN ~` vs `MINID`) MUST be written to the
  Completion Note (spec §7 requires recording it).

### References in Codebase
- `packages/ai-parrot/src/parrot/core/hooks/brokers/base.py` — consumer loop pattern
- `packages/ai-parrot/src/parrot/core/events/bus/backends/redis_pubsub.py` (TASK-1785) — reconnect/degraded-mode pattern

---

## Acceptance Criteria

- [ ] Envelope published via `XADD` is consumed by a group member and `XACK`ed exactly once in the happy path.
- [ ] Un-ACKed message (simulated crashed consumer) is reclaimed by `XAUTOCLAIM` and reprocessed.
- [ ] Second delivery of an already-seen `event_id` is skipped (dedup SET honored).
- [ ] Two consumers in one group: each message processed by only one (with dedup, no double-processing) — integration test per spec §4.
- [ ] Reconnect-with-backoff on Redis outage; no unhandled task exceptions.
- [ ] Retention policy decision recorded in Completion Note.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/core/events/bus/test_redis_streams.py -v` (integration-marked tests may require Redis).
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/bus/backends/` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/core/events/bus/test_redis_streams.py
import pytest


async def test_streams_publish_consume_ack(streams_backend): ...
async def test_streams_autoclaim_reclaims_pending(streams_backend): ...
async def test_streams_event_id_dedup(streams_backend): ...

@pytest.mark.integration
async def test_end_to_end_streams_two_consumers(): ...
```

---

## Agent Instructions

1. Read spec §2 layer 3, §7 ("Duplicate delivery", "Streams retention") first.
2. Verify TASK-1785 is in `sdd/tasks/completed/`.
3. Check whether `fakeredis` (with streams support) is available before choosing the test strategy; use `uv` for any dev-dependency addition.
4. Update `sdd/tasks/index/eventbus-v2.json` status transitions.
5. Move this file to `sdd/tasks/completed/`; fill in Completion Note INCLUDING the retention decision.

---

## Completion Note

*(Agent fills this in when done — MUST include the MAXLEN vs MINID retention decision and rationale)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
