---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Crew Result Storage Backends

**Feature ID**: FEAT-147
**Date**: 2026-05-05
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

> Replace the hard-wired DocumentDB result persistence in `AgentCrew` and
> `AgentsFlow` with a pluggable `ResultStorage` abstraction, an opt-out flag,
> and three first-class backends (Redis, Postgres, DocumentDB).

### Problem Statement

Today every `AgentCrew.run_*` method and the `AgentsFlow.run_flow` method
unconditionally fire-and-forget a write to DocumentDB via
`PersistenceMixin._save_result()`:

```python
async def _save_result(self, result, method, *, collection="crew_executions", **kwargs):
    from .....interfaces.documentdb import DocumentDb   # always DocumentDB
    ...
    async with DocumentDb() as db:
        await db.write(collection, data)
```

This produces three concrete pains in production:

1. **Hard dependency on DocumentDB.** When DocumentDB is not configured (dev
   laptops, on-prem deployments, or any tenant without MongoDB-compatible
   storage), every crew run emits
   `WARNING parrot.bots.flows.core.storage.persistence:_save_result Failed to save result to 'crew_executions': ...`
   even though the crew itself succeeded. There is no way to silence it short
   of raising the logger level.
2. **No opt-out.** A user who genuinely does not want execution logs has no
   constructor flag to disable persistence — the `create_task` is wired
   inside the framework code and runs no matter what.
3. **Code duplication.** Two byte-identical copies of `PersistenceMixin`
   exist (`parrot/bots/flow/storage/persistence.py` consumed by `AgentsFlow`
   and `parrot/bots/flows/core/storage/persistence.py` consumed by
   `AgentCrew`). Any future fix has to be applied twice and stay in sync.

The DocumentDB cluster is also expensive (~$400/mo per FEAT-103
context). For deployments that already run Postgres or Redis, paying for a
DocumentDB cluster solely to persist crew execution logs is wasteful.

### Goals
- Introduce a `ResultStorage` abstract base class with a single backend
  contract: `async save(collection, document) -> None`, `async close() -> None`.
- Ship three first-class implementations: `RedisResultStorage`,
  `PostgresResultStorage`, `DocumentDbResultStorage` (current behaviour).
- Allow per-instance backend selection via constructor:
  `AgentCrew(result_storage="postgres")` or `AgentCrew(result_storage=my_instance)`.
- When the constructor argument is omitted, fall back to a global env var
  `CREW_RESULT_STORAGE` (`"redis" | "postgres" | "documentdb"`); when that
  is also unset, default to `"documentdb"` so existing consumers do not
  observe a behaviour change.
- Add a constructor flag `persist_results: bool = True`. When `False`, the
  framework MUST NOT open any storage connection, schedule any background
  task, or emit any persistence-related warning.
- Reconcile the two duplicated `PersistenceMixin` files into a single
  canonical location at `parrot/bots/flows/core/storage/persistence.py`;
  point `parrot/bots/flow/fsm.py` at the canonical module and delete the
  legacy duplicate.
- Provide explicit lifecycle cleanup: each backend owns an `async close()`
  contract, and the host crew/flow exposes an `async aclose()` method
  that releases the cached `ResultStorage` instance. Connections must
  not be left dangling until process exit.

### Non-Goals (explicitly out of scope)
- Migrating historical crew execution data already living in DocumentDB.
- Adding additional backends (S3, DynamoDB, file, SQLite) — the abstraction
  must permit them as a future iteration.
- Touching credential persistence (`parrot/handlers/credentials.py`) or
  `ChatStorage` — those belong to FEAT-103 and will keep their own backends.
- A schema-migration framework for the Postgres backend. The backend will
  emit a single `CREATE TABLE IF NOT EXISTS` on first write.
- Read APIs (querying past executions). This spec only covers the write
  path; reads stay outside the framework.
- Failure-recovery queues equivalent to `DocumentDb._failed_writes`. The
  Redis and Postgres backends do best-effort fire-and-forget; transient
  errors are logged and dropped, matching the current semantics.
- Removing `parrot/bots/flow/storage/__init__.py`. The legacy package is
  kept in place pending a user review of out-of-tree consumers. Only
  `persistence.py` inside that package is deleted by this feature; the
  remaining modules (`memory.py`, `mixin.py`, `synthesis.py`,
  `__init__.py`) stay untouched until that review concludes.

---

## 2. Architectural Design

### Overview

A new package `parrot/bots/flows/core/storage/backends/` introduces an
abstract `ResultStorage` base class plus three concrete backends. A small
factory turns a string name (`"redis"`, `"postgres"`, `"documentdb"`) into a
configured backend instance, reading credentials from `parrot.conf` /
`navconfig`. The shared `PersistenceMixin` is rewritten to delegate to
`self._result_storage` and is consumed by both `AgentCrew` and `AgentsFlow`
after consolidating the two duplicated modules into one.

The design preserves the existing public API (`_save_result(result, method,
collection=..., **kwargs)`) so callers in `crew.py` and `fsm.py` need no
changes beyond the constructor wiring of `persist_results` /
`result_storage`.

### Component Diagram
```
┌──────────────────────────────────────────────────────────────────────┐
│ AgentCrew (orchestration/crew.py)        AgentsFlow (flow/fsm.py)   │
│   self._persist_results: bool                                        │
│   self._result_storage: ResultStorage | None                         │
│   self._persist_tasks: set[asyncio.Task]                             │
│   async aclose() / __aenter__ / __aexit__                            │
└────────────┬─────────────────────────────────────────────────────────┘
             │  inherits
             ▼
┌──────────────────────────────────────────────────────────────────────┐
│ PersistenceMixin (flows/core/storage/persistence.py)                 │
│   async _save_result(result, method, *, collection, **kwargs)        │
│     - if not self._persist_results: return                           │
│     - storage = self._result_storage  (lazy via factory)             │
│     - await storage.save(collection, document)                       │
└────────────┬─────────────────────────────────────────────────────────┘
             │  delegates to
             ▼
┌──────────────────────────────────────────────────────────────────────┐
│ ResultStorage (flows/core/storage/backends/base.py)  [ABC]           │
│   async save(collection: str, document: dict) -> None                │
│   async close() -> None                                              │
└────────────┬─────────────────────────────────────────────────────────┘
             │
   ┌─────────┼──────────────────────────────────┐
   ▼         ▼                                  ▼
┌────────┐ ┌──────────┐                      ┌─────────────┐
│ Redis  │ │ Postgres │                      │ DocumentDB  │
│ JSON   │ │ jsonb    │                      │ (current)   │
│ + TTL  │ │ + DDL    │                      │             │
└────────┘ └──────────┘                      └─────────────┘

   get_result_storage("redis" | "postgres" | "documentdb" | instance | None)
```

### Backend Resolution

Resolution at construction time follows this precedence (first match wins):

1. **Explicit instance**: `result_storage=MyResultStorage(...)` → use as-is.
2. **Explicit name**: `result_storage="postgres"` → call factory, no fallback.
3. **Global env var**: `CREW_RESULT_STORAGE` (set in `parrot.conf` via
   `navconfig.config.get`) → call factory.
4. **Default**: `"documentdb"` → preserves today's behaviour.

If `persist_results=False`, steps 1–4 are skipped entirely; no backend is
ever instantiated. The mixin attribute `self._result_storage` stays `None`.

The backend is instantiated **lazily on first write**, not in
`__init__`. Reasons:
- Keeps `AgentCrew`/`AgentsFlow` construction cheap (no I/O on init).
- Allows `persist_results=False` to truly cost nothing.
- Mirrors the existing fire-and-forget pattern.

### Lifecycle & Cleanup

Each `ResultStorage` implementation MUST expose an `async close()` that
releases its underlying connection. The mixin stores the resolved backend
on `self._result_storage` and adds a public `async aclose()` to the host
crew/flow:

```python
async def aclose(self) -> None:
    """Release storage connections held by this crew/flow."""
    storage = getattr(self, "_result_storage", None)
    if storage is not None:
        try:
            await storage.close()
        except Exception as exc:
            self.logger.warning("Failed to close result storage: %s", exc)
        finally:
            self._result_storage = None
```

`AgentCrew` and `AgentsFlow` also implement `__aenter__` / `__aexit__`
that delegate to `aclose()` so callers can use:

```python
async with AgentCrew(name="x", result_storage="postgres") as crew:
    await crew.run_flow(...)
# connections released here
```

`aclose()` is idempotent (safe to call twice). Calling it before any
`_save_result` has run is a no-op (no backend was instantiated).

The fire-and-forget tasks scheduled by `_save_result` MUST be tracked on
`self._persist_tasks: set[asyncio.Task]` (with a discard-on-done callback)
so `aclose()` can `await asyncio.gather(*pending, return_exceptions=True)`
before closing the backend. This guarantees in-flight writes complete
before the connection is dropped.

### Backend: Redis

- Driver: `asyncdb.AsyncDB('redis', dsn=...)` (matches the rest of the
  codebase; see `parrot/handlers/agents/abstract.py:48`). The DSN comes
  from `parrot.conf.REDIS_URL` unless `CREW_RESULT_STORAGE_REDIS_URL` is
  set.
- Key shape: `{collection}:{crew_name}:{timestamp_ms}` — one key per
  execution (Q2 option (a)). The value is the JSON-serialized document.
- TTL: configurable via env var `CREW_RESULT_STORAGE_REDIS_TTL` (default
  `604800` seconds = 7 days). Setting `0` disables TTL.
- Failure mode: connection or `SET` errors are logged at `WARNING` and
  dropped (matches current DocumentDB best-effort semantics).

### Backend: Postgres

- Driver: `asyncdb.AsyncDB('pg', dsn=...)` (asyncpg under the hood; see
  `parrot/interfaces/hierarchy.py:86` and `parrot/bots/product.py:118`).
- DSN: `parrot.conf.default_dsn` (Q3) unless overridden by the env var
  `CREW_RESULT_STORAGE_PG_DSN`.
- Schema (idempotent, executed on backend instance's first write):
  ```sql
  CREATE TABLE IF NOT EXISTS crew_executions (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    crew_name   text        NOT NULL,
    method      text        NOT NULL,
    user_id     text,
    session_id  text,
    timestamp   timestamptz NOT NULL DEFAULT now(),
    payload     jsonb       NOT NULL
  );
  CREATE INDEX IF NOT EXISTS crew_executions_crew_name_idx ON crew_executions (crew_name);
  CREATE INDEX IF NOT EXISTS crew_executions_session_id_idx ON crew_executions (session_id);
  ```
- The `collection` argument selects the table name. `crew_executions` and
  `flow_executions` are the only two used by the current call sites; the
  backend issues the same DDL with substitution and caches a `set` of
  tables it has already initialised in this process.
- Insert: a single parameterised `INSERT INTO {collection} (crew_name,
  method, user_id, session_id, timestamp, payload) VALUES ($1,...,$6)`.
  All fields outside the named columns are merged into `payload`.

### Backend: DocumentDB

- Thin adapter around `parrot.interfaces.documentdb.DocumentDb`. Preserves
  current behaviour exactly (`async with DocumentDb() as db: await
  db.write(collection, data)`).
- Carried as the default to avoid a behaviour change for existing
  deployments.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/bots/flows/core/storage/persistence.py::PersistenceMixin` | rewritten | Delegates to `self._result_storage`; honours `self._persist_results`. |
| `parrot/bots/flow/storage/persistence.py` | deleted | Legacy duplicate; FSM imports re-pointed. |
| `parrot/bots/flow/fsm.py:41` | updated | Import becomes `from ..flows.core.storage import PersistenceMixin, SynthesisMixin`. |
| `parrot/bots/flow/storage/__init__.py` | updated | Drop the `PersistenceMixin` re-export only. Other re-exports (`ExecutionMemory`, `VectorStoreMixin`, `SynthesisMixin`) stay until the user review concludes — see Open Questions. |
| `parrot/bots/orchestration/crew.py::AgentCrew.__init__` | extended | New params `persist_results`, `result_storage`. |
| `parrot/bots/flows/crew/crew.py::AgentCrew.__init__` | extended | Same new params. |
| `parrot/bots/flow/fsm.py::AgentsFlow.__init__` | extended | Same new params. |
| `parrot/interfaces/documentdb.DocumentDb` | reused | Wrapped by `DocumentDbResultStorage`; no changes. |
| `parrot/conf.py` | extended | New keys: `CREW_RESULT_STORAGE`, `CREW_RESULT_STORAGE_PG_DSN`, `CREW_RESULT_STORAGE_REDIS_URL`, `CREW_RESULT_STORAGE_REDIS_TTL`. |

### Data Models

```python
# parrot/bots/flows/core/storage/backends/base.py
from abc import ABC, abstractmethod
from typing import Any

class ResultStorage(ABC):
    """Abstract pluggable backend for crew/flow execution result persistence."""

    @abstractmethod
    async def save(self, collection: str, document: dict[str, Any]) -> None:
        """Persist a single execution document."""

    @abstractmethod
    async def close(self) -> None:
        """Release any underlying connection/pool."""
```

The document shape stored is unchanged from today:

```python
{
    "crew_name":  str,
    "method":     str,                       # "run_sequential" | "run_parallel" | "run_flow" | "run_loop"
    "timestamp":  float,                     # time.time()
    "result":     dict | str,                # CrewResult.to_dict() if available, else str(result)
    "user_id":    str,                       # "unknown" if not provided
    "session_id": str | None,
    # plus any **kwargs forwarded by the caller
}
```

### New Public Interfaces

```python
# parrot/bots/flows/core/storage/backends/__init__.py
from .base import ResultStorage
from .factory import get_result_storage
from .redis import RedisResultStorage
from .postgres import PostgresResultStorage
from .documentdb import DocumentDbResultStorage

__all__ = [
    "ResultStorage",
    "RedisResultStorage",
    "PostgresResultStorage",
    "DocumentDbResultStorage",
    "get_result_storage",
]


# parrot/bots/flows/core/storage/backends/factory.py
from typing import Optional, Union
from navconfig import config
from .base import ResultStorage

def get_result_storage(
    name_or_instance: Union[str, ResultStorage, None] = None,
) -> ResultStorage:
    """Resolve a ResultStorage instance.

    Resolution precedence:
        1. ResultStorage instance → returned as-is.
        2. Non-empty string → looked up in the backend registry.
        3. None → falls back to env var ``CREW_RESULT_STORAGE``,
           then defaults to ``"documentdb"``.
    """
```

```python
# AgentCrew constructor (orchestration/crew.py)
def __init__(
    self,
    name: str = "AgentCrew",
    ...
    persist_results: bool = True,
    result_storage: Union[str, "ResultStorage", None] = None,
    **kwargs,
):
    ...
    self._persist_results = persist_results
    self._result_storage_arg = result_storage   # resolved lazily on first write
    self._result_storage: Optional["ResultStorage"] = None
```

`AgentsFlow.__init__` mirrors this exactly.

---

## 3. Module Breakdown

### Module 1: `ResultStorage` abstract base + factory
- **Path**: `parrot/bots/flows/core/storage/backends/base.py`,
  `parrot/bots/flows/core/storage/backends/factory.py`,
  `parrot/bots/flows/core/storage/backends/__init__.py`
- **Responsibility**: Defines the `ResultStorage` ABC and the
  `get_result_storage(name_or_instance)` factory. Houses the backend
  registry mapping `"redis" | "postgres" | "documentdb"` to classes.
- **Depends on**: `navconfig` (for env var resolution).

### Module 2: `DocumentDbResultStorage` (default backend)
- **Path**: `parrot/bots/flows/core/storage/backends/documentdb.py`
- **Responsibility**: Wraps `parrot.interfaces.documentdb.DocumentDb` to
  satisfy the `ResultStorage` contract. Default backend.
- **Depends on**: Module 1, `parrot.interfaces.documentdb.DocumentDb`.

### Module 3: `RedisResultStorage`
- **Path**: `parrot/bots/flows/core/storage/backends/redis.py`
- **Responsibility**: Implements `ResultStorage` via `asyncdb.AsyncDB('redis')`.
  Builds keys, JSON-encodes documents, applies TTL.
- **Depends on**: Module 1, `asyncdb`, `parrot.conf.REDIS_URL`.

### Module 4: `PostgresResultStorage`
- **Path**: `parrot/bots/flows/core/storage/backends/postgres.py`
- **Responsibility**: Implements `ResultStorage` via `asyncdb.AsyncDB('pg')`.
  Issues idempotent DDL on first write per table, then parameterised inserts.
- **Depends on**: Module 1, `asyncdb`, `parrot.conf.default_dsn`.

### Module 5: `PersistenceMixin` consolidation + rewrite
- **Path**: `parrot/bots/flows/core/storage/persistence.py` (canonical),
  `parrot/bots/flow/storage/persistence.py` (deleted),
  `parrot/bots/flow/storage/__init__.py` (updated to drop the
  `PersistenceMixin` re-export only).
- **Responsibility**: Single mixin that respects `self._persist_results`,
  delegates to `self._result_storage` (lazily resolved via factory on
  first write), tracks in-flight persist tasks on `self._persist_tasks`,
  and exposes `async aclose()` plus `__aenter__` / `__aexit__` for the
  host class. Replace both legacy copies.
- **Depends on**: Modules 1–4.

### Module 6: AgentCrew & AgentsFlow constructor wiring
- **Path**: `parrot/bots/orchestration/crew.py`,
  `parrot/bots/flows/crew/crew.py`,
  `parrot/bots/flow/fsm.py`.
- **Responsibility**: Add `persist_results` and `result_storage` params;
  store them on `self`. Update FSM import to canonical mixin location.
  Wire `_save_result` call sites so the scheduled task is registered on
  `self._persist_tasks` (one-line change per call site — keeps the same
  fire-and-forget semantics). No public method signature changes.
- **Depends on**: Module 5.

### Module 7: Configuration plumbing
- **Path**: `parrot/conf.py`.
- **Responsibility**: Read `CREW_RESULT_STORAGE`,
  `CREW_RESULT_STORAGE_PG_DSN`, `CREW_RESULT_STORAGE_REDIS_URL`,
  `CREW_RESULT_STORAGE_REDIS_TTL` via `navconfig.config.get` with
  documented defaults. Backends import from `parrot.conf`, not from
  `navconfig` directly, to keep config in one place.
- **Depends on**: none.

### Module 8: Tests
- **Path**: `tests/bots/flows/core/storage/`
- **Responsibility**: Unit tests for each backend (mocked driver), the
  factory, the opt-out flag, and an integration test that exercises
  `AgentCrew.run_sequential` with each backend in record-and-assert mode.
- **Depends on**: All previous modules.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_factory_resolves_string_name` | M1 | `get_result_storage("redis")` returns a `RedisResultStorage`. |
| `test_factory_passes_instance_through` | M1 | `get_result_storage(my_instance)` returns the same object unchanged. |
| `test_factory_uses_env_var` | M1 | With `CREW_RESULT_STORAGE=postgres` and `name_or_instance=None`, returns Postgres backend. |
| `test_factory_defaults_to_documentdb` | M1 | No arg + no env var → `DocumentDbResultStorage`. |
| `test_factory_unknown_name_raises` | M1 | `get_result_storage("snowflake")` raises `ValueError`. |
| `test_redis_backend_writes_with_ttl` | M3 | Mock asyncdb redis driver; assert `SET key value EX <ttl>` issued, key shape correct. |
| `test_redis_backend_no_ttl_when_zero` | M3 | `CREW_RESULT_STORAGE_REDIS_TTL=0` → no `EX` argument. |
| `test_postgres_backend_creates_table_once` | M4 | Mock asyncdb pg driver; first `save()` issues DDL + INSERT, second issues only INSERT (DDL cache). |
| `test_postgres_backend_inserts_payload_jsonb` | M4 | Document fields outside named columns end up in `payload` jsonb. |
| `test_documentdb_backend_uses_async_with` | M2 | Mock `DocumentDb`; assert `__aenter__`, `write(collection, doc)`, `__aexit__` called. |
| `test_persistence_mixin_skips_when_disabled` | M5 | `persist_results=False` → no factory call, no log message. |
| `test_persistence_mixin_lazy_resolves_on_first_save` | M5 | First `_save_result` instantiates backend; second reuses. |
| `test_persistence_mixin_logs_warning_on_backend_failure` | M5 | Backend `save()` raises → mixin logs warning, does not propagate. |
| `test_aclose_awaits_pending_persist_tasks` | M5 | Two slow `_save_result` calls in flight; `await crew.aclose()` waits for both before calling `storage.close()`. |
| `test_aclose_calls_storage_close` | M5 | After at least one save, `aclose()` invokes the backend's `close()` and resets `self._result_storage` to `None`. |
| `test_aclose_is_idempotent` | M5 | Calling `aclose()` twice (or on a crew that never persisted) is a no-op and never raises. |
| `test_async_context_manager_releases_storage` | M5 | `async with AgentCrew(...) as crew:` calls `aclose()` on exit. |

### Integration Tests
| Test | Description |
|---|---|
| `test_agentcrew_with_persist_results_false_opens_no_connection` | Run `AgentCrew(persist_results=False).run_sequential(...)` with a fake agent; assert `DocumentDb`, asyncdb redis, and asyncdb pg constructors were never called. |
| `test_agentcrew_with_postgres_backend_inserts_row` | Run a crew with `result_storage="postgres"`; assert one row in `crew_executions` containing the serialized `CrewResult`. Uses a temporary Postgres or mocked asyncdb. |
| `test_agentsflow_with_redis_backend_writes_key` | Run an `AgentsFlow` with `result_storage="redis"`; assert one Redis key set with TTL. |
| `test_default_backend_is_documentdb` | Run with no kwargs; assert DocumentDB write happened (mocked). |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_crew_result():
    """Minimal CrewResult-like object with `.to_dict()` returning a small dict."""
    class _R:
        def to_dict(self): return {"agent": "x", "output": "ok"}
    return _R()

@pytest.fixture
def mock_asyncdb_redis(monkeypatch):
    """Patch asyncdb.AsyncDB to a fake recording redis driver."""

@pytest.fixture
def mock_asyncdb_pg(monkeypatch):
    """Patch asyncdb.AsyncDB to a fake recording pg driver."""

@pytest.fixture
def mock_documentdb(monkeypatch):
    """Patch parrot.interfaces.documentdb.DocumentDb to a recording context manager."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `ResultStorage` ABC and three backends (`redis`, `postgres`, `documentdb`)
      ship under `parrot/bots/flows/core/storage/backends/` and are importable
      from `parrot.bots.flows.core.storage.backends`.
- [ ] `get_result_storage(name_or_instance)` resolves: instance → as-is,
      string → registry, `None` → env var → `"documentdb"` default.
- [ ] `AgentCrew(name="x", persist_results=False).run_sequential(...)` opens
      NO storage connection (no DocumentDB, asyncdb pg, or asyncdb redis
      constructor invoked) and emits NO persistence-related log line.
- [ ] `AgentCrew(name="x", result_storage="postgres").run_flow(...)` inserts
      one row into `crew_executions` with the `CrewResult.to_dict()` payload
      under the `payload` jsonb column. The DDL is idempotent across runs.
- [ ] `AgentsFlow(..., result_storage="redis").run_flow(...)` writes one key
      `crew_executions:<crew_name>:<ts_ms>` with JSON value and the
      configured TTL (default 7 days).
- [ ] Setting only the global env var `CREW_RESULT_STORAGE=postgres` (with
      both constructor params unset) routes results to Postgres.
- [ ] Default behaviour with no params and no env var still writes to
      DocumentDB — no breaking change for existing consumers.
- [ ] `parrot/bots/flow/storage/persistence.py` is deleted; `fsm.py` imports
      `PersistenceMixin` from `parrot.bots.flows.core.storage`. A grep for
      `from .storage import PersistenceMixin` inside `parrot/bots/flow/`
      returns no results.
- [ ] The legacy package `parrot/bots/flow/storage/` (minus `persistence.py`)
      remains in place; only the `PersistenceMixin` re-export is dropped
      from its `__init__.py` while the user reviews out-of-tree consumers.
- [ ] `AgentCrew` and `AgentsFlow` expose `async aclose()`, `__aenter__`,
      and `__aexit__`. `aclose()` awaits all in-flight persist tasks
      registered in `self._persist_tasks` before calling `storage.close()`,
      and is idempotent.
- [ ] `async with AgentCrew(name="x", result_storage="postgres") as crew:`
      runs the crew and releases the asyncdb connection on exit (verifiable
      via mock recording exactly one `close()` call).
- [ ] `pytest tests/bots/flows/core/storage/ -v` is green.
- [ ] `ruff check parrot/bots/flows/core/storage/` and
      `ruff check parrot/bots/flow/fsm.py` are clean.
- [ ] No public method signature on `AgentCrew` / `AgentsFlow` changes
      beyond the additive `persist_results` and `result_storage` kwargs.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying via `grep` or `read`.

### Verified Imports
```python
# Persistence mixin canonical location (used by AgentCrew today)
from parrot.bots.flows.core.storage import PersistenceMixin, SynthesisMixin
# verified: parrot/bots/flows/core/storage/__init__.py:14

# Persistence mixin LEGACY location (used by AgentsFlow today — to be removed)
from parrot.bots.flow.storage import PersistenceMixin, SynthesisMixin
# verified: parrot/bots/flow/fsm.py:41

# DocumentDB interface (current default backend)
from parrot.interfaces.documentdb import DocumentDb
# verified: parrot/interfaces/documentdb.py:63

# AsyncDB driver (used by Postgres + Redis backends)
from asyncdb import AsyncDB
# verified across parrot/interfaces/database.py:12, parrot/handlers/agents/abstract.py:13

# Existing config keys
from parrot.conf import default_dsn, REDIS_URL
# verified: parrot/conf.py:63 (default_dsn), parrot/conf.py:271 (REDIS_URL)
```

### Existing Class Signatures
```python
# parrot/bots/flows/core/storage/persistence.py — current canonical mixin
class PersistenceMixin:                                                # line 14
    """Mixin that adds DocumentDB persistence to crew/flow orchestrators."""

    async def _save_result(                                            # line 20
        self,
        result: Any,
        method: str,
        *,
        collection: str = "crew_executions",
        **kwargs,
    ) -> None: ...
# Inside the body, the import is `from .....interfaces.documentdb import DocumentDb`
# (verified line 38). After the rewrite this import is removed.

# parrot/bots/flow/storage/persistence.py — duplicate to be deleted
class PersistenceMixin:                                                # line 9
    # Functionally identical to the canonical copy. Diff confirmed:
    # only header docstring, logger source (`logging` stdlib vs
    # `navconfig.logging`), and relative-import depth differ.

# parrot/bots/orchestration/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):                     # line 147
    def __init__(                                                      # line 186
        self,
        name: str = "AgentCrew",
        agents: List[Union[BasicAgent, AbstractBot]] = None,
        shared_tool_manager: ToolManager = None,
        max_parallel_tasks: int = 10,
        llm: Optional[Union[str, AbstractClient]] = None,
        auto_configure: bool = True,
        truncation_length: Optional[int] = None,
        truncate_context_summary: bool = True,
        embedding_model: Any = None,
        enable_analysis: bool = False,
        dimension: int = 384,
        index_type: str = "Flat",
        agent_execution_timeout: float = 600.0,
        **kwargs,
    ): ...
    self.name: str
    self.logger: logging.Logger
    # _save_result call sites (fire-and-forget):
    #   line 1355  run_sequential
    #   line 1810  run_loop
    #   line 2121  run_parallel
    #   line 2354  (run_flow inner)
    #   line 2610  (run_flow inner)
    #   line 3118  (run_flow outer)

# parrot/bots/flows/crew/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):                     # line 86
    def __init__(...)                                                   # line 125
    # _save_result call sites: lines 1292, 1753, 2071, 2303, 2559, 3067

# parrot/bots/flow/fsm.py
class AgentsFlow(PersistenceMixin, SynthesisMixin):                    # line 277
    def __init__(                                                      # line 316
        self,
        name: str = "AgentsFlow",
        agents: Optional[List[Union[BasicAgent, AbstractBot]]] = None,
        shared_tool_manager: Optional[ToolManager] = None,
        max_parallel_tasks: int = 10,
        default_max_retries: int = 3,
        execution_timeout: Optional[float] = None,
        truncation_length: Optional[int] = None,
        enable_execution_memory: bool = True,
        embedding_model: Optional[str] = None,
        vector_dimension: int = 384,
        vector_index_type: str = "Flat",
        llm: Optional[Union[str, AbstractClient]] = None,
        **kwargs,
    ): ...
    # _save_result call site: line 944 (collection='flow_executions')

# parrot/interfaces/documentdb.py — DocumentDb wrapper
class DocumentDb:                                                      # line 63
    async def documentdb_connect(self) -> None: ...                    # line 234
    async def close(self) -> None: ...                                 # line 261
    async def __aenter__(self) -> "DocumentDb": ...                    # line 299
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...  # line 304
    async def write(                                                   # line 447
        self,
        collection: str,
        data: Union[dict, List[dict]],
        ...
    ) -> ...: ...
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `RedisResultStorage` | `asyncdb.AsyncDB('redis', dsn=...)` | constructor | `parrot/handlers/agents/abstract.py:48` |
| `PostgresResultStorage` | `asyncdb.AsyncDB('pg', dsn=...)` | constructor | `parrot/interfaces/hierarchy.py:86`, `parrot/bots/product.py:118` |
| `DocumentDbResultStorage` | `parrot.interfaces.documentdb.DocumentDb` | `async with` + `write()` | `parrot/interfaces/documentdb.py:447` |
| `PersistenceMixin` (rewritten) | `self._result_storage`, `self._persist_results` | new instance attrs | added by Module 6 |
| `AgentsFlow` (fsm.py) | canonical `PersistenceMixin` | new import path | replaces line 41 |

### Configuration References
- `parrot/conf.py:63` → `default_dsn` (Postgres DSN reused by Postgres backend).
- `parrot/conf.py:271` → `REDIS_URL` (default Redis DSN).
- New keys to add (all optional, all read via `navconfig.config.get`):
  - `CREW_RESULT_STORAGE` (default `"documentdb"`).
  - `CREW_RESULT_STORAGE_PG_DSN` (default `default_dsn`).
  - `CREW_RESULT_STORAGE_REDIS_URL` (default `REDIS_URL`).
  - `CREW_RESULT_STORAGE_REDIS_TTL` (default `604800`, in seconds; `0` = no TTL).

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.bots.flows.core.storage.backends`~~ — package will be CREATED by this feature.
- ~~`ResultStorage`~~ — abstract class does not exist today.
- ~~`get_result_storage`~~ — factory does not exist today.
- ~~`PersistenceMixin._persist_results`~~ / ~~`PersistenceMixin._result_storage`~~ — attributes do not exist today; will be added on the host classes (`AgentCrew`/`AgentsFlow`), not the mixin itself.
- ~~`AgentCrew(persist_results=...)`~~ / ~~`AgentCrew(result_storage=...)`~~ — kwargs do not exist today.
- ~~`AgentsFlow(persist_results=...)`~~ / ~~`AgentsFlow(result_storage=...)`~~ — kwargs do not exist today.
- ~~`AgentCrew.aclose`~~ / ~~`AgentCrew.__aenter__`~~ / ~~`AgentCrew.__aexit__`~~ — async lifecycle methods do not exist today; same for `AgentsFlow`.
- ~~`PersistenceMixin._persist_tasks`~~ — task-tracking set does not exist today.
- ~~`parrot.conf.CREW_RESULT_STORAGE`~~ et al. — env-var-backed keys do not exist today.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first throughout. All `save()`/`close()` are `async def`.
- Use `asyncdb.AsyncDB('pg' | 'redis', dsn=...)` rather than importing
  `asyncpg` / `redis.asyncio` directly — keeps the codebase consistent
  with `parrot/handlers/agents/abstract.py:48` and
  `parrot/interfaces/hierarchy.py:86`.
- Read configuration from `parrot.conf`, not `navconfig` directly, in the
  backend modules. The `parrot.conf` module is the single integration
  point with `navconfig`.
- Logger pattern: each backend instance owns
  `self.logger = logging.getLogger(f"parrot.crew_storage.{backend_name}")`.
  Failures inside `save()` log at `WARNING` and are swallowed.
- Backend resolution is **lazy**. `_save_result` should call
  `_ensure_result_storage()` which materialises the backend on first use
  and caches it on `self._result_storage`.
- Preserve the fire-and-forget call shape in `crew.py` and `fsm.py`. Do
  NOT await `_save_result` synchronously — that would change runtime
  semantics for callers.

### Known Risks / Gotchas
- **Two `AgentCrew` classes.** There is a duplicate `AgentCrew` in
  `parrot/bots/flows/crew/crew.py` (line 86) in addition to the one in
  `parrot/bots/orchestration/crew.py` (line 147). Both must receive the
  new constructor params and call sites — easy to miss the second one.
  This duplication is pre-existing tech debt and out-of-scope for this
  feature beyond keeping both copies in lockstep.
- **DDL race.** Two processes inserting into Postgres for the first time
  may both run `CREATE TABLE IF NOT EXISTS`. This is safe (idempotent)
  but logs may show two DDL statements per process pool. Document this;
  do not mitigate.
- **Redis JSON encoding.** `CrewResult.to_dict()` may contain
  non-JSON-serializable objects (datetimes, custom dataclasses).
  `RedisResultStorage` MUST use `json.dumps(..., default=str)` to avoid
  raising on edge fields. Same precaution in `PostgresResultStorage`
  before passing the dict to asyncdb's jsonb encoder.
- **Backwards compatibility.** Default backend stays `documentdb`. Any
  user with `DOCUMENTDB_*` env vars set continues to work without code
  changes. Users with no DocumentDB will keep seeing the same warning
  unless they set `CREW_RESULT_STORAGE=` to something else OR opt out
  with `persist_results=False`. This is intentional — silently changing
  the default would surprise existing deployments.
- **Connection lifetime.** Backends are created on first write. The host
  crew/flow now owns explicit cleanup via `async aclose()` and the async
  context-manager protocol. Callers that do not use either still leak
  the underlying connection until process exit (same as today's
  DocumentDB code path) — this is the price of preserving the existing
  fire-and-forget API. Recommend `async with` in documentation.
- **In-flight persist tasks.** `aclose()` awaits all tasks in
  `self._persist_tasks` with `return_exceptions=True` before closing the
  backend. Slow Redis/Postgres writes therefore extend the close
  duration; `__aexit__` does not impose a timeout. Callers needing a
  bounded teardown can wrap the close in `asyncio.wait_for`.
- **CrewResult serialization quirks.** When `result.to_dict()` is
  unavailable, the mixin falls back to `str(result)`. Postgres jsonb does
  not accept a bare string at the column type level — the backend must
  wrap it as `{"raw": str(result)}` before insertion.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `asyncdb` | already in core deps | Postgres + Redis drivers (driver names `'pg'` and `'redis'`). |
| `navconfig` | already in core deps | Env-var resolution via `config.get`. |
| `motor` / `pymongo` | already in core deps via `asyncdb[documentdb]` | DocumentDB backend (transitively, no new dep). |

No new third-party packages are introduced.

---

## 8. Open Questions

> Resolved items from the clarifying-question round are kept here for the
> audit trail. Any unresolved questions block implementation.

- [x] **PersistenceMixin duplication: consolidate or replicate?** —
      *Resolved with user*: consolidate. The two files are byte-equivalent
      (verified diff). `parrot/bots/flow/storage/persistence.py` is deleted
      and `fsm.py` is re-pointed at `parrot/bots/flows/core/storage`.
- [x] **Redis storage shape** — *Resolved with user*: option (a), one key
      per execution `crew_executions:{crew_name}:{timestamp_ms}`, JSON
      value, configurable TTL (default 7 days).
- [x] **Postgres DSN source** — *Resolved with user*: reuse
      `parrot.conf.default_dsn` when no DSN is supplied; allow override
      via `CREW_RESULT_STORAGE_PG_DSN`.
- [x] **Per-instance vs global config** — *Resolved with user*: option (b),
      constructor param wins; if absent, fall back to global env var
      `CREW_RESULT_STORAGE`; if that is absent too, default to
      `"documentdb"`.
- [x] **Connection cleanup on crew teardown** — *Resolved with user*:
      explicit cleanup is in scope. `ResultStorage` defines `async close()`,
      the mixin tracks in-flight tasks on `self._persist_tasks`, and the
      host crew/flow exposes `async aclose()` plus `__aenter__` /
      `__aexit__` so callers can use `async with`. Connections are not
      left to leak when the caller opts in to the lifecycle protocol.
- [ ] **Removal of `parrot/bots/flow/storage/__init__.py` and its other
      modules** — *Owner: Jesus Lara*. User will manually review whether
      out-of-tree consumers import `ExecutionMemory`, `VectorStoreMixin`,
      or `SynthesisMixin` from the legacy package. **Until that review
      concludes, this feature only deletes `persistence.py` from the
      legacy package and drops its re-export from `__init__.py`** —
      everything else stays untouched. A follow-up will fully remove
      the package once the review confirms it is safe.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`. All tasks of FEAT-147 run
  sequentially in a single worktree at
  `.claude/worktrees/feat-147-crew-result-storage-backends/`.
- Tasks are tightly coupled (the mixin rewrite depends on the backends,
  and the constructor wiring depends on the mixin), so parallel
  worktrees would create more merge friction than they would save.
- **Cross-feature dependencies**: none. This spec is self-contained and
  does not block on or coordinate with FEAT-009 (AgentsFlow Persistency)
  or FEAT-103 (Agent Artifact Persistency). Both touch unrelated
  surfaces (flow JSON serialization, conversation storage respectively).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-05 | Jesus Lara | Initial draft (no prior brainstorm). Resolved Q1–Q4 with user during /sdd-spec. |
| 0.2 | 2026-05-05 | Jesus Lara | Resolved Q6 (explicit cleanup via `aclose()` + async-context-manager); narrowed Q5 scope to deleting only `persistence.py` from the legacy package pending user review. Status → approved. |
