---
type: Wiki Overview
title: 'TASK-1400: EventLedger ABC + PostgresLedgerBackend'
id: doc:sdd-tasks-completed-task-1400-event-ledger-postgres-backend-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: activity timestamp and open/closed execution counts.
relates_to:
- concept: mod:parrot.autonomous.ledger
  rel: mentions
---

# TASK-1400: EventLedger ABC + PostgresLedgerBackend

**Feature**: FEAT-212 — Typed Event Ledger & Crash Resume
**Spec**: `sdd/specs/FEAT-212-event-ledger-resume.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1399
**Assigned-to**: unassigned

---

## Context

> Implements Module 2 of FEAT-212. Defines the `EventLedger` abstract interface
> and its concrete `PostgresLedgerBackend` implementation. This is the core
> persistence layer: append-only writes with monotonic `seq`, filtered reads,
> agent state projection (`last_state`), and incomplete execution detection
> (`find_incomplete`). All subsequent modules depend on this.

---

## Scope

- Add `EventLedger(ABC)` to `ledger.py` with abstract methods:
  `append`, `read`, `last_state`, `find_incomplete`.
- Implement `PostgresLedgerBackend(EventLedger)` using asyncdb's
  `app["database"]` / `db.acquire()` pattern.
- Implement `ensure_schema()` — idempotent DDL execution using the
  `LEDGER_DDL` constant from TASK-1399.
- Implement `append(event)` — INSERT returning assigned `seq`.
- Implement `read(*, agent_id, since_seq, event_class, limit)` — filtered SELECT.
- Implement `last_state(agent_id)` — returns `AgentLedgerState` with last
  activity timestamp and open/closed execution counts.
- Implement `find_incomplete()` — detects executions with a `Before*`/`Invoke`
  event but no matching `After*`/`*Failed` closure, based on `trace_id` correlation.
- Implement `InMemoryLedgerBackend(EventLedger)` for testing (no DB needed).
- Write unit tests using the in-memory backend.

**NOT in scope**: LedgerRecorder (TASK-1401), resume logic (TASK-1402),
wiring/exports (TASK-1403).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/autonomous/ledger.py` | MODIFY | Add EventLedger ABC + PostgresLedgerBackend + InMemoryLedgerBackend |
| `packages/ai-parrot-server/tests/test_ledger_backend.py` | CREATE | Unit tests for backend operations |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From TASK-1399 (same file — ledger.py)
from parrot.autonomous.ledger import LedgerEvent, LedgerConfig, AgentLedgerState, IncompleteExecution, LEDGER_DDL

# DB access pattern (verified in handlers + manager/manager.py)
# db = app["database"]                          # asyncdb instance
# async with await db.acquire() as conn: ...    # connection from pool
# conn is an asyncdb connection with execute/fetch/fetchrow/fetchval methods

# ABC
from abc import ABC, abstractmethod

# Standard library
from datetime import datetime
from typing import Optional
import logging
```

### Existing Signatures to Use
```python
# DB access pattern (verified in handlers/chat.py, manager/manager.py):
db = app["database"]                            # asyncdb instance
async with await db.acquire() as conn:          # acquire connection
    result = await conn.execute(sql, *args)      # execute statement
    rows = await conn.fetch(sql, *args)           # fetch multiple rows
    row = await conn.fetchrow(sql, *args)         # fetch single row
    val = await conn.fetchval(sql, *args)          # fetch single value

# SuspendedExecutionStore pattern (suspended_store.py:64) — mirror this style:
class SuspendedExecutionStore:                    # line 64
    def __init__(self, redis: Any) -> None:       # line 87
    async def save(self, record, ttl) -> None:    # line 103
    async def load(self, interaction_id) -> ...:  # line 128
    async def delete(self, interaction_id) -> ...:# line 149

# LedgerEvent fields (from TASK-1399):
class LedgerEvent(BaseModel):
    seq: Optional[int] = None
    event_id: str
    event_class: str
    trace_id: Optional[str] = None
    source_type: str = ""
    source_name: str = ""
    agent_id: Optional[str] = None
    timestamp: datetime
    event_data: dict
```

### Does NOT Exist
- ~~`AbstractStore` for the ledger~~ — that's for vector stores in `parrot/stores/`. Use asyncdb directly.
- ~~`conn.insert()` or `conn.table()`~~ — asyncdb uses raw SQL via `conn.execute()` / `conn.fetch()`.
- ~~`LedgerEvent.save()` / `.load()`~~ — it's a plain Pydantic model; persistence is via the backend.
- ~~ORM layer~~ — no ORM; use raw SQL with parameterized queries.

---

## Implementation Notes

### Pattern to Follow
```python
class EventLedger(ABC):
    @abstractmethod
    async def append(self, event: LedgerEvent) -> int: ...

    @abstractmethod
    async def read(self, *, agent_id: Optional[str] = None,
                   since_seq: Optional[int] = None,
                   event_class: Optional[str] = None,
                   limit: int = 100) -> list[LedgerEvent]: ...

    @abstractmethod
    async def last_state(self, agent_id: str) -> AgentLedgerState: ...

    @abstractmethod
    async def find_incomplete(self) -> list[IncompleteExecution]: ...


class PostgresLedgerBackend(EventLedger):
    def __init__(self, db, *, config: LedgerConfig | None = None) -> None:
        self._db = db
        self._config = config or LedgerConfig()
        self.logger = logging.getLogger(__name__)

    async def ensure_schema(self) -> None:
        """Execute idempotent DDL."""
        async with await self._db.acquire() as conn:
            await conn.execute(LEDGER_DDL)
```

### Key Constraints
- `append` must be append-only; never UPDATE or DELETE rows.
- `seq` is assigned by Postgres (`BIGSERIAL`), not by Python.
- `find_incomplete()` logic: find `trace_id` values that have a `Before*` or
  `BeforeInvoke*` event but no corresponding `After*` or `*Failed*` event.
  The "opening" events are: `BeforeInvokeEvent`, `BeforeToolCallEvent`.
  The "closing" events are: `AfterInvokeEvent`, `InvokeFailedEvent`,
  `AfterToolCallEvent`, `ToolCallFailedEvent`.
- `InMemoryLedgerBackend` must replicate the same semantics (monotonic seq,
  filtering) for reliable tests without Postgres.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/human/suspended_store.py` — async store pattern
- `packages/ai-parrot-server/src/parrot/manager/manager.py` — DB access via `app["database"]`

---

## Acceptance Criteria

- [ ] `EventLedger` ABC defines `append`, `read`, `last_state`, `find_incomplete`.
- [ ] `PostgresLedgerBackend.ensure_schema()` is idempotent (runs DDL with IF NOT EXISTS).
- [ ] `append(event)` returns monotonically increasing `seq`.
- [ ] `read()` filters by `agent_id`, `since_seq`, `event_class`, and respects `limit`.
- [ ] `last_state(agent_id)` returns `AgentLedgerState` with last activity and execution counts.
- [ ] `find_incomplete()` correctly detects unclosed executions (Before* without After*/Failed*).
- [ ] `InMemoryLedgerBackend` passes the same logical tests as Postgres (used in CI).
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/test_ledger_backend.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/autonomous/ledger.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_ledger_backend.py
import pytest
from datetime import datetime, timezone
from parrot.autonomous.ledger import (
    LedgerEvent, InMemoryLedgerBackend, LedgerConfig,
)


@pytest.fixture
def memory_ledger():
    return InMemoryLedgerBackend()


class TestLedgerBackend:
    @pytest.mark.asyncio
    async def test_append_returns_monotonic_seq(self, memory_ledger):
        e1 = LedgerEvent(event_id="e1", event_class="BeforeInvokeEvent",
                         timestamp=datetime.now(timezone.utc), event_data={})
        e2 = LedgerEvent(event_id="e2", event_class="AfterInvokeEvent",
                         timestamp=datetime.now(timezone.utc), event_data={})
        s1 = await memory_ledger.append(e1)
        s2 = await memory_ledger.append(e2)
        assert s2 > s1

    @pytest.mark.asyncio
    async def test_read_filters_by_agent_id(self, memory_ledger):
        for aid in ("a1", "a2", "a1"):
            await memory_ledger.append(LedgerEvent(
                event_id=f"e-{aid}", event_class="X", agent_id=aid,
                timestamp=datetime.now(timezone.utc), event_data={},
            ))
        results = await memory_ledger.read(agent_id="a1")
        assert len(results) == 2
        assert all(r.agent_id == "a1" for r in results)

    @pytest.mark.asyncio
    async def test_read_filters_by_event_class(self, memory_ledger):
        await memory_ledger.append(LedgerEvent(
            event_id="e1", event_class="BeforeInvokeEvent",
            timestamp=datetime.now(timezone.utc), event_data={},
        ))
        await memory_ledger.append(LedgerEvent(
            event_id="e2", event_class="AfterInvokeEvent",
            timestamp=datetime.now(timezone.utc), event_data={},
        ))
        results = await memory_ledger.read(event_class="BeforeInvokeEvent")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_last_state_projection(self, memory_ledger):
        now = datetime.now(timezone.utc)
        await memory_ledger.append(LedgerEvent(
            event_id="e1", event_class="BeforeInvokeEvent", agent_id="bot-1",
            trace_id="t1", timestamp=now, event_data={},
        ))
        await memory_ledger.append(LedgerEvent(
            event_id="e2", event_class="AfterInvokeEvent", agent_id="bot-1",
            trace_id="t1", timestamp=now, event_data={},
        ))
        state = await memory_ledger.last_state("bot-1")
        assert state.last_activity is not None
        assert state.open_executions == 0
        assert state.closed_executions == 1

    @pytest.mark.asyncio
    async def test_find_incomplete_detects_open(self, memory_ledger):
        now = datetime.now(timezone.utc)
        # Open execution (Before without After)
        await memory_ledger.append(LedgerEvent(
            event_id="e1", event_class="BeforeInvokeEvent", agent_id="bot-1",
            trace_id="open-trace", timestamp=now, event_data={},
        ))
        # Closed execution
        await memory_ledger.append(LedgerEvent(
            event_id="e2", event_class="BeforeInvokeEvent", agent_id="bot-1",
            trace_id="closed-trace", timestamp=now, event_data={},
        ))
        await memory_ledger.append(LedgerEvent(
            event_id="e3", event_class="AfterInvokeEvent", agent_id="bot-1",
            trace_id="closed-trace", timestamp=now, event_data={},
        ))
        incomplete = await memory_ledger.find_incomplete()
        assert len(incomplete) == 1
        assert incomplete[0].trace_id == "open-trace"

    @pytest.mark.asyncio
    async def test_find_incomplete_empty_when_all_closed(self, memory_ledger):
        now = datetime.now(timezone.utc)
        await memory_ledger.append(LedgerEvent(
            event_id="e1", event_class="BeforeInvokeEvent", trace_id="t1",
            timestamp=now, event_data={},
        ))
        await memory_ledger.append(LedgerEvent(
            event_id="e2", event_class="AfterInvokeEvent", trace_id="t1",
            timestamp=now, event_data={},
        ))
        assert await memory_ledger.find_incomplete() == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-212-event-ledger-resume.spec.md` for full context
2. **Check dependencies** — verify TASK-1399 is complete (models exist in `ledger.py`)
3. **Verify the Codebase Contract** — confirm DB access patterns, model fields
4. **Update status** in `sdd/tasks/index/event-ledger-resume.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1400-event-ledger-postgres-backend.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-01
**Notes**: EventLedger ABC, PostgresLedgerBackend, and InMemoryLedgerBackend were all
implemented in ledger.py (started in TASK-1399). Created test_ledger_backend.py with 21
tests covering append, read filters, last_state projection, and find_incomplete logic.
All tests pass.

**Deviations from spec**: None. All acceptance criteria met.
