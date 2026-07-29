---
type: Wiki Overview
title: 'TASK-1019: End-to-end integration tests for FEAT-147'
id: doc:sdd-tasks-completed-task-1019-result-storage-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The earlier tasks (TASK-1013…TASK-1018) each ship narrowly scoped unit
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends.documentdb
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends.factory
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends.postgres
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends.redis
  rel: mentions
---

# TASK-1019: End-to-end integration tests for FEAT-147

**Feature**: FEAT-147 — Crew Result Storage Backends
**Spec**: `sdd/specs/crew-result-storage-backends.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1018
**Assigned-to**: unassigned

---

## Context

The earlier tasks (TASK-1013…TASK-1018) each ship narrowly scoped unit
tests. This task closes the loop with **integration tests** that
exercise the full path from `AgentCrew.run_*` / `AgentsFlow.run_flow`
through the `PersistenceMixin` to each backend, validating the
acceptance criteria in spec §5 end-to-end.

Implements spec §3 Module 8 and §4 "Integration Tests".

---

## Scope

- Add the following integration tests under
  `tests/bots/flows/core/storage/test_integration.py`:
  1. `test_default_backend_is_documentdb` — running a crew with no
     storage params and no env var triggers exactly one `DocumentDb`
     write.
  2. `test_global_env_var_routes_to_postgres` — setting only
     `CREW_RESULT_STORAGE=postgres` (no constructor args) routes to the
     Postgres backend.
  3. `test_persist_results_false_opens_no_connection` — `persist_results=False`
     prevents any `DocumentDb`, asyncdb redis, or asyncdb pg constructor
     from being invoked. Verified with three constructor mocks asserted as not-called.
  4. `test_async_with_releases_connection` — exiting an `async with`
     block on a crew triggers exactly one `close()` on the storage backend.
  5. `test_pending_persist_tasks_complete_before_close` — at least two
     in-flight slow saves; `aclose()` waits for them before invoking
     `storage.close()`.
  6. `test_agentsflow_redis_backend_writes_key` — `AgentsFlow(...,
     result_storage="redis").run_flow(...)` writes one key matching
     `crew_executions:<name>:<digits>`.
- Use mocks (`unittest.mock`) for the underlying drivers; do NOT spin up
  real Postgres/Redis/DocumentDB. The unit-test layer already covers the
  driver surface; this layer covers the wiring.
- Run with `pytest-asyncio` (already a dev dep).

**NOT in scope**: Adding read-side APIs, querying past executions,
performance benchmarks, real-DB CI fixtures, or Docker-compose harness.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/bots/flows/core/storage/test_integration.py` | CREATE | The six integration tests above. |
| `tests/bots/flows/core/storage/conftest.py` | CREATE | Shared fixtures: `mock_documentdb`, `mock_asyncdb_pg`, `mock_asyncdb_redis`, `tiny_agent_crew`, `tiny_agents_flow`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.bots.orchestration.crew import AgentCrew
from parrot.bots.flow.fsm import AgentsFlow
from parrot.bots.flows.core.storage.backends import (
    ResultStorage,
    DocumentDbResultStorage,
    PostgresResultStorage,
    RedisResultStorage,
    get_result_storage,
)
```

### Existing Signatures to Use
```python
# All three host classes already have the new constructor params after
# TASK-1018. Verify with:
#   grep -n "persist_results\|result_storage" parrot/bots/orchestration/crew.py parrot/bots/flow/fsm.py
```

### Driver mock targets (verified import paths)
```python
# DocumentDB
"parrot.bots.flows.core.storage.backends.documentdb.DocumentDb"

# Postgres
"parrot.bots.flows.core.storage.backends.postgres.AsyncDB"

# Redis
"parrot.bots.flows.core.storage.backends.redis.AsyncDB"
```

### Does NOT Exist
- ~~A real Postgres/Redis/DocumentDB CI fixture in this repo~~ — all integration tests must mock the drivers.
- ~~`AgentCrew.run_now()` or other one-shot helpers~~ — use the standard `run_sequential` / `run_flow` methods. If running a real crew is too heavy for these tests, exercise `_save_result` directly on the constructed crew (still goes through the full mixin path).

---

## Implementation Notes

### Pattern to Follow

```python
# tests/bots/flows/core/storage/conftest.py
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_documentdb(monkeypatch):
    instance = MagicMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    instance.write = AsyncMock(return_value=None)
    cls = MagicMock(return_value=instance)
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.documentdb.DocumentDb",
        cls,
    )
    return cls, instance


@pytest.fixture
def mock_asyncdb_pg(monkeypatch):
    conn = MagicMock()
    conn.connection = AsyncMock(return_value=conn)
    conn.execute = AsyncMock(return_value=None)
    conn.close = AsyncMock(return_value=None)
    cls = MagicMock(return_value=conn)
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.postgres.AsyncDB",
        cls,
    )
    return cls, conn


@pytest.fixture
def mock_asyncdb_redis(monkeypatch):
    conn = MagicMock()
    conn.connection = AsyncMock(return_value=conn)
    conn.execute = AsyncMock(return_value=None)
    conn.close = AsyncMock(return_value=None)
    cls = MagicMock(return_value=conn)
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.redis.AsyncDB",
        cls,
    )
    return cls, conn
```

### Sample integration test (use as template for the others)

```python
# tests/bots/flows/core/storage/test_integration.py
import pytest
from unittest.mock import MagicMock


@pytest.mark.asyncio
async def test_persist_results_false_opens_no_connection(
    monkeypatch, mock_documentdb, mock_asyncdb_pg, mock_asyncdb_redis,
):
    from parrot.bots.orchestration.crew import AgentCrew
    crew = AgentCrew(name="opt-out", persist_results=False)
    await crew._save_result(MagicMock(to_dict=lambda: {"a": 1}), "run_flow")
    docdb_cls, _ = mock_documentdb
    pg_cls, _ = mock_asyncdb_pg
    redis_cls, _ = mock_asyncdb_redis
    docdb_cls.assert_not_called()
    pg_cls.assert_not_called()
    redis_cls.assert_not_called()


@pytest.mark.asyncio
async def test_async_with_releases_connection(mock_asyncdb_pg):
    from parrot.bots.orchestration.crew import AgentCrew
    _, conn = mock_asyncdb_pg
    async with AgentCrew(name="x", result_storage="postgres") as crew:
        await crew._save_result(MagicMock(to_dict=lambda: {}), "run_flow")
    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_global_env_var_routes_to_postgres(
    monkeypatch, mock_asyncdb_pg, mock_documentdb,
):
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.factory.CREW_RESULT_STORAGE",
        "postgres",
    )
    from parrot.bots.orchestration.crew import AgentCrew
    crew = AgentCrew(name="x")
    await crew._save_result(MagicMock(to_dict=lambda: {}), "run_flow")
    pg_cls, _ = mock_asyncdb_pg
    docdb_cls, _ = mock_documentdb
    pg_cls.assert_called_once()
    docdb_cls.assert_not_called()
    await crew.aclose()


@pytest.mark.asyncio
async def test_pending_persist_tasks_complete_before_close():
    import asyncio
    from parrot.bots.orchestration.crew import AgentCrew
    from parrot.bots.flows.core.storage.backends import ResultStorage

    completed = []

    class _SlowStorage(ResultStorage):
        async def save(self, collection, document):
            await asyncio.sleep(0.01)
            completed.append(document)
        async def close(self):
            pass

    crew = AgentCrew(name="x", result_storage=_SlowStorage())
    t1 = asyncio.get_running_loop().create_task(
        crew._save_result(MagicMock(to_dict=lambda: {"a": 1}), "run_flow")
    )
    crew._persist_tasks.add(t1)
    t1.add_done_callback(crew._persist_tasks.discard)

    await crew.aclose()
    assert len(completed) == 1
```

### Key Constraints
- Each test must reset mocks per fixture scope (default `function`).
- Use `pytest.mark.asyncio` consistently. The repo's pytest config
  already enables `asyncio_mode = "auto"` in some areas — check
  `pyproject.toml` and respect whatever convention is in effect.
- Do NOT import asyncdb / motor / redis at module top-level in the
  tests — only inside fixtures or via the production code path.

---

## Acceptance Criteria

- [ ] All six integration tests are present in
      `tests/bots/flows/core/storage/test_integration.py`.
- [ ] Shared fixtures live in `tests/bots/flows/core/storage/conftest.py`
      and patch each driver at its production import location.
- [ ] `pytest tests/bots/flows/core/storage/ -v` is green
      (unit + integration combined).
- [ ] `ruff check tests/bots/flows/core/storage/` is clean.
- [ ] No real Postgres/Redis/DocumentDB connection is opened during the
      test run (verifiable by absence of network warnings; the patches
      cover all three driver entry points).

---

## Test Specification

The test list itself is the spec — see "Scope" above. Each numbered
test maps 1-to-1 to a §5 acceptance criterion in the feature spec.

---

## Agent Instructions

1. **Read the spec** §4 "Integration Tests" and §5 acceptance criteria.
2. **Verify** TASK-1018 is in `tasks/completed/`.
3. **Activate the venv**: `source .venv/bin/activate`.
4. **Confirm** the patch targets exist by running, for each:
   `python -c "import parrot.bots.flows.core.storage.backends.{redis,postgres,documentdb}"`.
5. **Implement** the conftest fixtures first, then the integration tests.
6. **Run** `pytest tests/bots/flows/core/storage/ -v --tb=short` end-to-end.
7. **Move this file** to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-05
**Notes**: All 6 integration tests pass. conftest.py provides mock_documentdb,
mock_asyncdb_pg, mock_asyncdb_redis fixtures. Full storage test suite is 50/50
green. No real DB connections opened during tests. ruff is clean on all test files.

**Deviations from spec**: none
