# TASK-1788: DLQ — bus.dlq terminal topic persisted via asyncdb (pg)

**Feature**: FEAT-310 — Unified EventBus v2 — queue-based dispatch, severity, ingress channels, and notifications
**Spec**: `sdd/specs/eventbus-v2.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1784
**Assigned-to**: unassigned

---

## Context

Module 6 of FEAT-310 (spec §3) — goal G7's terminal leg. Envelopes that
exhaust retries land on `bus.dlq` and MUST be persisted in BOTH memory and
Streams modes (*resolved in brainstorm*). Storage decision (*resolved in
spec §8*): **asyncdb `pg` driver, table `navigator.evb_dlq`**.

---

## Scope

- Implement `packages/ai-parrot/src/parrot/core/events/bus/dlq.py`:
  - `DLQHandler` — plugs into BusCore's DLQ callback (TASK-1784's `on_dlq`),
    republishes the failed envelope on terminal topic `bus.dlq` (with
    failure metadata: attempts, last error, failed handler id) and persists
    it via asyncdb.
  - Persistence: asyncdb **`pg`** driver, append-only table
    **`navigator.evb_dlq`** — columns: `event_id` (unique), `topic`,
    `payload` (jsonb), `severity`, `priority`, `source`, `correlation_id`,
    `trace_context` (jsonb), `metadata` (jsonb), `failure_reason`,
    `attempts`, `failed_at` (timestamptz), `created_at` (timestamptz).
    Include DDL as a module-level constant + `ensure_table()` helper.
  - Replay helper: `async def replay(event_id | since) -> int` — re-publishes
    stored envelopes to their original topic (marks replayed).
  - Persistence failures degrade gracefully: log + meta-event, never raise
    into the dispatch path (model B).
- Unit tests with asyncdb mocked (no live Postgres in unit tier).

**NOT in scope**: retry logic itself (TASK-1784), audit subscriber
(TASK-1792), Streams backend (TASK-1789 — it reuses this handler as-is).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/bus/dlq.py` | CREATE | `DLQHandler`, DDL, replay |
| `packages/ai-parrot/src/parrot/core/events/bus/__init__.py` | MODIFY | export `DLQHandler` |
| `packages/ai-parrot/tests/core/events/bus/test_dlq.py` | CREATE | unit tests (asyncdb mocked) |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` 2026-07-16 (commit b7226186d).

### Verified Imports
```python
from asyncdb import AsyncDB                                # asyncdb>=2.11.6, pyproject.toml:71
from parrot.core.events.bus.core import BusCore            # TASK-1784
from parrot.core.events.bus.envelope import EventEnvelope, Severity  # TASK-1783
```

### Existing Signatures to Use
```python
# asyncdb usage pattern found across the repo (e.g. memory/audit stores):
db = AsyncDB("pg", dsn=..., params=...)
async with await db.connection() as conn:
    await conn.execute(sql)         # DDL / INSERT
    result, error = await conn.query(sql)   # SELECT — asyncdb returns (result, error) tuples on query
```

### Does NOT Exist
- ~~DLQ, retry policy, dedup, ACK in evb.py~~ — DLQ handling created HERE (retry lives in BusCore).
- ~~`navigator.evb_dlq` table~~ — created by THIS task's DDL (`ensure_table()`); do not assume it pre-exists.
- ~~A generic "bus persistence layer"~~ — DLQ persistence is self-contained in `dlq.py`; the audit subscriber (TASK-1792) is separate by design.
- ~~`EventBus` persistence of `_event_history`~~ — in-memory list only; unrelated to DLQ.

---

## Implementation Notes

### Pattern to Follow
Check existing asyncdb consumers before coding (grep `AsyncDB(` under
`packages/ai-parrot/src/parrot/memory/` and `stores/`) and mirror their
connection-lifecycle handling (acquire per write vs pooled) — align with
whatever `parrot/memory/` does for Redis/Postgres-backed stores.

### Key Constraints
- Table name is FIXED by the resolved spec question: **`navigator.evb_dlq`**,
  driver **`pg`** (spec §8, resolved 2026-07-16). Schema-qualify all SQL.
- No TTL/`expires_at` column — SQL DLQ rows are permanent until replayed/
  cleaned manually (consistent with append-only audit semantics).
- `event_id` unique constraint → `ON CONFLICT (event_id) DO NOTHING`
  (at-least-once delivery may hand the same envelope twice).
- DSN comes from navconfig (same env-driven config other asyncdb users use);
  a missing DSN disables persistence with a loud warning meta-event, it does
  not crash the bus.
- Writes must be fire-and-forget from the dispatch path (queue or task).

### References in Codebase
- `packages/ai-parrot/src/parrot/memory/` — existing asyncdb connection patterns
- `pyproject.toml:71` — `asyncdb>=2.11.6` already a dependency

---

## Acceptance Criteria

- [ ] Envelope exhausting retries → `bus.dlq` publication + one persisted row (mock asserts SQL + params).
- [ ] Works identically when BusCore uses MemoryBackend or (later) Streams — no backend-conditional logic in `dlq.py`.
- [ ] Duplicate `event_id` insert is a no-op (ON CONFLICT path tested).
- [ ] Persistence failure logs + emits meta-event; dispatch unaffected.
- [ ] `replay()` re-publishes stored envelope to its original topic.
- [ ] DDL targets `navigator.evb_dlq` with `pg` driver.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/core/events/bus/test_dlq.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/bus/` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/core/events/bus/test_dlq.py
import pytest


@pytest.fixture
def mock_asyncdb(monkeypatch):
    """Fake AsyncDB('pg') capturing executed SQL + params."""
    ...

async def test_retry_exhaustion_persists_to_dlq(mock_asyncdb): ...
async def test_dlq_duplicate_event_id_noop(mock_asyncdb): ...
async def test_dlq_persistence_failure_is_isolated(mock_asyncdb): ...
async def test_dlq_replay_republishes(mock_asyncdb): ...
```

---

## Agent Instructions

1. Read spec §2 layer 2 (DLQ), §7 gotchas, and §8 resolved question on table naming.
2. Verify TASK-1784 is in `sdd/tasks/completed/`.
3. Grep real asyncdb usage in the repo BEFORE writing connection code.
4. Update `sdd/tasks/index/eventbus-v2.json` status transitions.
5. Move this file to `sdd/tasks/completed/` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-16
**Notes**: `DLQHandler.on_dlq` plugs into BusCore's on_dlq hook: republishes on `bus.dlq` (Severity.WARNING - capped below alert threshold per spec s7 loop guard) with failure metadata (attempts, error type/message, failed subscriber id), then persists fire-and-forget via asyncdb `pg` into `navigator.evb_dlq` (module-level DDL constant + idempotent lock-guarded ensure_table(), pattern mirrored from storage/security_reports store). INSERT uses ON CONFLICT (event_id) DO NOTHING. DSN from parrot.conf.default_dsn when not injected; missing DSN disables persistence with loud warning, never crashes. Persistence failures log + emit `bus.dlq_error` meta-event (model B). `replay(event_id|since)` re-publishes to ORIGINAL topics and marks rows replayed. No backend-conditional logic. 7 unit tests (asyncdb fully mocked) + 63-test events regression pass; ruff clean.

**Deviations from spec**: added a `replayed_at TIMESTAMPTZ` column beyond the listed schema - required to honor this task's own 'marks replayed' replay requirement.
