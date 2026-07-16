# TASK-1784: BusCore — queued dispatch, worker pool, severity filters, retry, backpressure

**Feature**: FEAT-310 — Unified EventBus v2 — queue-based dispatch, severity, ingress channels, and notifications
**Spec**: `sdd/specs/eventbus-v2.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1783
**Assigned-to**: unassigned

---

## Context

Module 2 of FEAT-310 (spec §3) — the heart of the feature. Today
`EventBus.publish()` awaits handlers sequentially (evb.py:188): head-of-line
blocking, no queue, no backpressure. `BusCore` makes publish an O(1) enqueue
drained by a bounded worker pool, with severity-filtered subscriptions,
retry-with-backoff, per-topic-class backpressure policies, and meta-events —
implementing goals G2, G3 (filtering half), and G7 of spec §1.

---

## Scope

- Implement `packages/ai-parrot/src/parrot/core/events/bus/core.py`:
  - `BusCore` with per-priority `asyncio.Queue`s (one per `EventPriority`),
    drained by a bounded worker pool (`asyncio.TaskGroup`); higher-priority
    queues drain first (CRITICAL before LOW under load).
  - `async def publish(self, envelope: EventEnvelope) -> None` — O(1) enqueue,
    returns before any handler runs.
  - `def subscribe(self, pattern, handler, *, priority=0, filter_fn=None,
    min_severity: Severity | None = None) -> str` and
    `def unsubscribe(self, subscriber_id: str) -> bool`.
  - Glob/exact topic matching — REUSE the current algorithm from
    `EventBus._pattern_matches` (evb.py; `fnmatch`-based).
  - Per-handler `asyncio.timeout`; timeout counts as failure toward retry.
  - Retry-with-backoff (configurable attempts/base delay); exhausted retries
    hand the envelope to a DLQ callback hook (`on_dlq: Callable | None`) —
    actual persistence is TASK-1788.
  - Backpressure policy per topic class: `block` (default; emits
    `bus.backpressure` meta-event), `drop_oldest`, `reject` (raises to emitter).
  - Error isolation model B: handler exceptions never propagate to emitter;
    re-emitted as `bus.subscriber_error` meta-events with a **contextvar
    recursion guard** (same pattern as `EventRegistry`).
  - `async def start()` / `async def close()` — graceful drain with deadline;
    publishes rejected after `close()` begins.
- Unit tests per spec §4 (see Test Specification).

**NOT in scope**: transport backends (TASK-1785), `evb.py` facade
(TASK-1786), DLQ persistence (TASK-1788), notification rules (TASK-1787).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/bus/core.py` | CREATE | `BusCore` dispatcher |
| `packages/ai-parrot/src/parrot/core/events/bus/__init__.py` | MODIFY | export `BusCore` |
| `packages/ai-parrot/tests/core/events/bus/test_core.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` 2026-07-16 (commit b7226186d).

### Verified Imports
```python
from parrot.core.events.bus.envelope import EventEnvelope, Severity  # TASK-1783 output
from parrot.core.events.evb import EventPriority                      # evb.py:15
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/core/events/evb.py:188 — the defect being replaced
class EventBus:
    async def publish(self, event: Event) -> int:   # awaits handlers sequentially — DO NOT copy
    def subscribe(self, pattern, handler, *, priority=0, filter_fn=None) -> str  # line 129 — keep kwarg names
    def unsubscribe(self, subscriber_id: str) -> bool                            # line 171

# packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py — patterns to copy
class EventRegistry:                                  # line 90
    async def emit(self, event: LifecycleEvent) -> None   # line 235 — never raises (model B)
    # fire-and-forget dual-emit: asyncio.create_task(self._event_bus.emit(...))  # line 283
    # contextvar recursion guard for meta/error re-emission — mirror this mechanism
```

### Does NOT Exist
- ~~Any `asyncio.Queue`/worker pool in `EventBus`~~ — current `publish()` awaits inline; BusCore is new.
- ~~DLQ, retry policy, dedup, ACK in evb.py~~ — none exist; retry/DLQ-hook created here.
- ~~`bus.subscriber_error` / `bus.backpressure` topics~~ — defined by THIS task.
- ~~`TransportBackend`~~ — TASK-1785; BusCore must not import backends (accept an optional callable/protocol placeholder only if needed for publish-out, else keep dispatch fully in-process for now).

---

## Implementation Notes

### Pattern to Follow
```python
# Recursion guard (mirror lifecycle/registry.py contextvar approach):
_in_meta_dispatch: ContextVar[bool] = ContextVar("_in_meta_dispatch", default=False)
# When emitting bus.subscriber_error: if _in_meta_dispatch.get(): log and drop.

# Worker pool: N workers per priority tier or a single pool draining
# queues in strict priority order; use asyncio.TaskGroup for lifecycle.
```

### Key Constraints
- `publish()` must NEVER await a handler (spec AC: verified by slow-handler test).
- Severity is orthogonal to priority: `min_severity` filters delivery, never scheduling.
- Meta-events (`bus.*`) default to `Severity.DEBUG`/`INFO` so they can't trigger alert loops (spec §7).
- `self.logger` via `navconfig.logging`; Google-style docstrings; strict typing.
- Config knobs (workers, queue size, retry, backpressure) as constructor kwargs with sane defaults; TOML `[bus]` parsing arrives with the facade task.

### References in Codebase
- `packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py` — model B isolation + recursion guard
- `packages/ai-parrot/src/parrot/core/events/evb.py` — glob matching algorithm to reuse

---

## Acceptance Criteria

- [ ] `publish()` returns before any handler runs (slow-handler test proves it).
- [ ] CRITICAL-priority envelopes drain before LOW under load.
- [ ] `min_severity=WARNING` subscription never receives INFO.
- [ ] Handler exception → `bus.subscriber_error` meta-event; siblings and emitter unaffected; recursion guard prevents loops.
- [ ] `block`/`drop_oldest`/`reject` backpressure policies behave per config; `bus.backpressure` meta-event emitted on activation.
- [ ] Exhausted retries invoke the DLQ callback with the envelope.
- [ ] `close()` drains with deadline and rejects new publishes.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/core/events/bus/test_core.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/bus/` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/core/events/bus/test_core.py
import asyncio
import pytest
from parrot.core.events.bus import BusCore, EventEnvelope, Severity


@pytest.fixture
async def bus_core():
    core = BusCore(workers=2, queue_size=8)   # small queue for backpressure tests
    await core.start()
    yield core
    await core.close()


async def test_publish_is_o1_enqueue(bus_core): ...
async def test_priority_queues_scheduling(bus_core): ...
async def test_severity_filter_subscription(bus_core): ...
async def test_handler_error_isolation_model_b(bus_core): ...
async def test_meta_event_recursion_guard(bus_core): ...
async def test_backpressure_block_drop_reject(): ...
async def test_retry_backoff_then_dlq_callback(): ...
async def test_graceful_shutdown_drain(): ...
```

---

## Agent Instructions

1. Read spec §2 (Core dispatcher), §7 (Known Risks) and this contract first.
2. Verify TASK-1783 is in `sdd/tasks/completed/` before starting.
3. Verify contract references; update contract first if code moved.
4. Update `sdd/tasks/index/eventbus-v2.json` status transitions.
5. Move this file to `sdd/tasks/completed/` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-16
**Notes**: `BusCore` implemented with per-priority asyncio.Queues + counting semaphore, drained by an asyncio.TaskGroup worker pool in strict priority order. publish() is O(1) enqueue (slow-handler test proves emitter never waits). min_severity filters delivery only. Per-handler asyncio.timeout; retry-with-backoff (retry_attempts/retry_base_delay); exhausted retries emit `bus.subscriber_error` (contextvar recursion guard, mirroring EventRegistry) and invoke `on_dlq(envelope, attempts=, error=, subscriber_id=)` — signature aligned with TASK-1788's DLQHandler. Backpressure per topic (exact → topic-class → default): block (emits `bus.backpressure` meta then awaits), drop_oldest, reject (BackpressureError). Meta `bus.*` envelopes are Severity.INFO (alert-loop cap) and never DLQ'd (spec §7 loop prevention). close() drains with deadline and rejects publishes (BusClosedError). 10 unit tests pass; ruff clean.

**Deviations from spec**: none
