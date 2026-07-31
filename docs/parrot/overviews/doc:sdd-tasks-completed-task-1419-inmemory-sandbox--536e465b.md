---
type: Wiki Overview
title: 'TASK-1419: `InMemoryStateSandbox` + `DatabaseToolkitBinder`'
id: doc:sdd-tasks-completed-task-1419-inmemory-sandbox-db-binder-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The state-based sandbox plus the FIRST `ToolkitBinder`. This is the proof
  of the binding pattern: a'
relates_to:
- concept: mod:parrot.bots.database.toolkits.base
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.postgres
  rel: mentions
- concept: mod:parrot.eval
  rel: mentions
- concept: mod:parrot.eval.sandbox.base
  rel: mentions
- concept: mod:parrot.eval.sandbox.state
  rel: mentions
---

# TASK-1419: `InMemoryStateSandbox` + `DatabaseToolkitBinder`

**Feature**: FEAT-217 — Generic Agent Evaluation Harness
**Spec**: `sdd/specs/generic-evaluation-harness.spec.md`
**Spec section**: §2/§3 Module 4 (brainstorm §13.2–§13.4, §13.7 step 3)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1418
**Assigned-to**: unassigned

---

## Context

The state-based sandbox plus the FIRST `ToolkitBinder`. This is the proof of the binding pattern: a
real `DatabaseToolkit`/`PostgresToolkit` runs its CRUD tools against an in-memory `DictStateBackend`
with **no real database connection**. Implements brainstorm §13.7 step 3 — the smallest real toolkit
surface, fully unit-testable.

---

## Scope

- In `parrot/eval/sandbox/state.py` (or a sibling module) add:
  - `ToolkitBinder(ABC)` — `bind(toolkit, backend) -> None`.
  - `InMemoryStateSandbox(Sandbox)` — owns `(backend, binder)`; `reset`→`backend.reset`,
    `snapshot`→`backend.snapshot`, `health_check`→`True`, `exec`→`NotImplementedError`,
    plus `bind(toolkit)` delegating to the binder.
  - `InMemoryStateSandboxProvider(SandboxProvider)` — fresh `DictStateBackend` + binder per
    `acquire()`; `release()` is GC (no pool).
  - `DatabaseToolkitBinder(ToolkitBinder)` + `FakeAsyncDBConnection`: set
    `toolkit._connection = FakeAsyncDBConnection(backend)` and `toolkit._connected = True` so
    `DatabaseToolkit.start()` is bypassed. `FakeAsyncDBConnection` implements exactly the asyncdb
    surface the CRUD tools call — **read `PostgresToolkit._execute_crud` and the query helpers first**
    to enumerate the required methods (resolves Open Question in spec §8).

**NOT in scope**: `JiraToolkitBinder` (TASK-1420), evaluator (TASK-1422), runner (TASK-1425).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/sandbox/state.py` | MODIFY | Add binder ABC, sandbox, provider, DB binder |
| `packages/ai-parrot/src/parrot/eval/sandbox/fakes.py` | CREATE | `FakeAsyncDBConnection` |
| `packages/ai-parrot/src/parrot/eval/__init__.py` | MODIFY | Export new names |
| `packages/ai-parrot/tests/eval/test_inmemory_sandbox.py` | CREATE | Sandbox tests |
| `packages/ai-parrot/tests/eval/test_db_binder.py` | CREATE | DB binder tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.eval.sandbox.base import Sandbox, SandboxProvider, SandboxSpec   # TASK-1417
from parrot.eval.sandbox.state import StateBackend, DictStateBackend          # TASK-1418
from parrot.bots.database.toolkits.base import DatabaseToolkit                 # bots/database/toolkits/base.py:78
# Concrete toolkit used in tests:
from parrot.bots.database.toolkits.postgres import PostgresToolkit            # bots/database/toolkits/postgres.py
```

### Existing Signatures to Use
```python
# bots/database/toolkits/base.py
class DatabaseToolkit(AbstractToolkit, ABC):     # line 78
    self.dsn = dsn                                # line 129
    self._connection: Any = None                 # line 145  ← set to FakeAsyncDBConnection
    self._connected: bool = False                # line 146  ← set True to skip start()
    async def start(self) -> None: ...           # line 210  (opens real asyncdb conn — must NOT run)
# Read PostgresToolkit._execute_crud + query helpers to learn the exact methods the fake must expose.
```

### Does NOT Exist
- ~~A toolkit `.store` / `.backend` attribute~~ — backends differ per toolkit; bind via `_connection`.
- ~~`moto` fixtures~~ — none in repo; the fake is hand-written.

---

## Implementation Notes

### Key Constraints
- The bound `PostgresToolkit` must **never** call asyncdb `start()` against a real DSN. Assert this
  in tests (e.g. patch `DatabaseToolkit.start` to raise, confirm it is not called after binding).
- `FakeAsyncDBConnection` translates SQL-ish CRUD calls into `DictStateBackend` ops. Keep it scoped to
  exactly the methods the benchmark exercises — do not implement a full SQL engine.
- `InMemoryStateSandboxProvider` provisions fresh per attempt (no pool, no health eviction).

### References in Codebase
- `parrot/bots/database/toolkits/postgres.py` — `_execute_crud`, `$N` param binding, JSONB casts.
- `parrot/tools/toolkit.py:306` — `_pre_execute` (generic injection hook, used by the Jira binder).

---

## Acceptance Criteria

- [ ] `from parrot.eval import InMemoryStateSandbox, InMemoryStateSandboxProvider, DatabaseToolkitBinder` resolves.
- [ ] `InMemoryStateSandbox`: `reset`/`snapshot` delegate to the backend; `health_check()` True;
      `exec()` raises `NotImplementedError`.
- [ ] Provider yields a fresh backend per `acquire()` (two acquires are independent).
- [ ] After `binder.bind(toolkit, backend)`, a `PostgresToolkit` CRUD tool call mutates the backend
      and `start()` is NOT invoked (no real connection).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/eval/test_inmemory_sandbox.py packages/ai-parrot/tests/eval/test_db_binder.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/eval/sandbox/`

---

## Test Specification

```python
import pytest
from parrot.eval import InMemoryStateSandbox, DictStateBackend, DatabaseToolkitBinder

async def test_sandbox_delegates_to_backend():
    sb = InMemoryStateSandbox(DictStateBackend(), DatabaseToolkitBinder())
    await sb.reset({"t": {"1": {"v": 1}}})
    assert (await sb.snapshot())["t"]["1"]["v"] == 1
    assert await sb.health_check() is True

async def test_db_binder_no_real_start(monkeypatch):
    # Build a PostgresToolkit, bind it, exercise a CRUD tool, assert start() never ran
    ...
```

---

## Agent Instructions

Standard SDD flow: verify the contract (especially the asyncdb method set), set index `in-progress`,
implement, run tests + ruff, move to `completed/`, set index `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*
