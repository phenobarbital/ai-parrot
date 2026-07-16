# TASK-1792: AuditSubscriber (asyncdb) + MetricsSubscriber

**Feature**: FEAT-310 — Unified EventBus v2 — queue-based dispatch, severity, ingress channels, and notifications
**Spec**: `sdd/specs/eventbus-v2.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1784
**Assigned-to**: unassigned

---

## Context

Module 10 of FEAT-310 (spec §3, Phase 3). Egress observability: an
append-only audit trail of bus traffic (asyncdb) and a metrics subscriber
(counters + latency histograms), complementing the existing OTel lifecycle
subscriber (which stays untouched on the typed-registry side).

---

## Scope

- `subscribers/audit.py`: `AuditSubscriber` — subscribes to configurable
  patterns (default `*` minus `bus.*` internals), persists envelopes
  append-only via asyncdb `pg` driver, table `navigator.evb_audit`
  (naming aligned with `navigator.evb_dlq` from TASK-1788; same DDL/
  `ensure_table()` pattern). Batched writes (size/interval flush) so audit
  can keep up under load; fire-and-forget, model B isolation.
- `subscribers/metrics.py`: `MetricsSubscriber` — in-process counters
  (published/delivered/failed per topic-class + severity) and dispatch
  latency histogram (enqueue→handler-start). Expose a `snapshot() -> dict`
  API; integrate with existing metrics/OTel infra ONLY if a bus-agnostic
  helper already exists (verify with grep — do not invent an OTel setup).
- Unit tests: asyncdb mocked; metrics asserted via `snapshot()`.

**NOT in scope**: DLQ (TASK-1788), notifications (TASK-1787), OTel lifecycle
subscriber changes, dashboards.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/bus/subscribers/audit.py` | CREATE | append-only audit |
| `packages/ai-parrot/src/parrot/core/events/bus/subscribers/metrics.py` | CREATE | counters + latency |
| `packages/ai-parrot/src/parrot/core/events/bus/subscribers/__init__.py` | MODIFY | exports |
| `packages/ai-parrot/tests/core/events/bus/test_audit_metrics.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` 2026-07-16 (commit b7226186d).

### Verified Imports
```python
from asyncdb import AsyncDB                                 # asyncdb>=2.11.6, pyproject.toml:71
from parrot.core.events.bus.core import BusCore             # TASK-1784
from parrot.core.events.bus.envelope import EventEnvelope, Severity  # TASK-1783
```

### Existing Signatures to Use
```python
# asyncdb usage pattern (same as TASK-1788):
db = AsyncDB("pg", dsn=..., params=...)
async with await db.connection() as conn:
    await conn.execute(sql)

# BusCore subscription API (TASK-1784):
def subscribe(self, pattern, handler, *, priority=0, filter_fn=None,
              min_severity: Severity | None = None) -> str
```

### Does NOT Exist
- ~~`navigator.evb_audit` table~~ — created by THIS task's DDL; align column style with TASK-1788's `navigator.evb_dlq`.
- ~~A bus metrics registry / Prometheus exporter in core/events~~ — `snapshot()` dict is the contract; exporting is future work.
- ~~`AuditSubscriber` anywhere~~ — nothing subscribes bus→storage today.
- ~~TTL/`expires_at` on audit rows~~ — append-only, no TTL (consistent with resolved DLQ decision).

---

## Implementation Notes

### Pattern to Follow
Batching: internal `asyncio.Queue` + flush task (size N or T seconds,
whichever first) — mirrors the fire-and-forget discipline used everywhere in
this feature; on `close()`, flush remaining rows within the drain deadline.

### Key Constraints
- Audit must NEVER apply backpressure to the bus: if its internal queue
  fills, drop-oldest and count drops (exposed in metrics + warning log).
- Metrics use monotonic clock; histogram buckets fixed + documented.
- Missing DSN → audit disabled with loud warning (same degrade rule as DLQ).
- `bus.*` meta-topics excluded from audit by default to avoid self-amplification.

### References in Codebase
- TASK-1788 `dlq.py` — asyncdb DDL/insert pattern to mirror
- `packages/ai-parrot/src/parrot/core/events/lifecycle/` — existing OTel/logging subscriber style

---

## Acceptance Criteria

- [ ] Envelopes matching the pattern are persisted append-only to `navigator.evb_audit` (mock asserts batched INSERT).
- [ ] Batch flush triggers on both size and interval; `close()` flushes remainder.
- [ ] Audit overload → drop-oldest + drop counter, bus dispatch unaffected.
- [ ] `MetricsSubscriber.snapshot()` reports per-topic-class counters and latency percentiles/buckets.
- [ ] `bus.*` topics excluded from audit by default.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/core/events/bus/test_audit_metrics.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/bus/subscribers/` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/core/events/bus/test_audit_metrics.py
import pytest

async def test_audit_batched_append_only(mock_asyncdb): ...
async def test_audit_flush_on_close(mock_asyncdb): ...
async def test_audit_overload_drop_oldest(mock_asyncdb): ...
async def test_metrics_counters_and_latency(): ...
async def test_bus_meta_topics_excluded(): ...
```

---

## Agent Instructions

1. Read spec §2 (Egress) and TASK-1788's completed implementation for the asyncdb pattern.
2. Verify TASK-1784 is in `sdd/tasks/completed/` (TASK-1788 completion also recommended for pattern reuse).
3. Grep for existing metrics helpers before adding any OTel code.
4. Update `sdd/tasks/index/eventbus-v2.json` status transitions.
5. Move this file to `sdd/tasks/completed/` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-16
**Notes**: `AuditSubscriber`: append-only rows into `navigator.evb_audit` (DDL/ensure_table/lazy-AsyncDB pattern mirrored 1:1 from TASK-1788's dlq.py; BIGSERIAL PK, event_id NOT unique — duplicates allowed by design, no ON CONFLICT, no TTL). Internal bounded deque + flusher task: flush on batch_size (wakeup event) OR flush_interval, whichever first; one connection round per flush; close() drains the remainder. Overload -> drop-oldest + dropped counter in .stats + rate-limited warning — NEVER backpressures the bus. bus.* topics excluded by default (include_bus_internal knob). Missing DSN disables with loud warning (same degrade rule as DLQ). `MetricsSubscriber`: in-process counters (delivered per topic-class, per severity; failed per topic-class via bus.subscriber_error observation) + dispatch-latency histogram (wall-clock envelope.timestamp -> handler start) in fixed documented buckets [0.001..5.0]s + inf; snapshot() dict is the contract (grep confirmed the observability MetricsSubscriber is lifecycle-registry/OTel-specific, no bus-agnostic helper exists — no OTel code added, per task). attach()/detach() on BusCore; reset() supported. 10 unit tests pass (asyncdb fully mocked); ruff clean.

**Deviations from spec**: none
