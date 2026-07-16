---
type: Wiki Overview
title: 'Feature Specification: AgentCrew Saved Crews (Execution Persistence & Replay)'
id: doc:sdd-specs-agentcrew-saved-crews-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AgentCrew already persists execution results via the `ResultStorage` backends
relates_to:
- concept: mod:parrot.bots.flows.core.storage.backends
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends.base
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends.documentdb
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends.postgres
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends.redis
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.persistence
  rel: mentions
- concept: mod:parrot.bots.flows.crew
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.interfaces.documentdb
  rel: mentions
- concept: mod:parrot.models.crew_definition
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: AgentCrew Saved Crews (Execution Persistence & Replay)

**Feature ID**: FEAT-307
**Date**: 2026-07-14
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

AgentCrew already persists execution results via the `ResultStorage` backends
(FEAT-147), but the persistence is **write-only** — the `ResultStorage` ABC only
exposes `save()` and `close()`. There is no way to list, retrieve, replay, or
schedule past executions through the API.

This means:
- Users who ran a complex crew query cannot find it again or re-run it later.
- There is no audit trail accessible via the API (only raw DB queries).
- The scheduler (`AgentSchedulerManager`) supports crew execution but requires
  manual configuration — there is no path from "I ran this crew successfully"
  to "run it again every Monday."

### Goals
- Extend `ResultStorage` ABC with read operations (`list`, `get`, `delete`, `count`)
  and implement them across all three backends (Postgres, Redis, DocumentDB).
- Enhance the save path to capture the original prompt/query and tenant as
  first-class columns.
- Provide REST endpoints to list, retrieve, replay, and schedule saved executions.
- Enable one-click scheduling of any saved execution via the existing
  `AgentSchedulerManager.add_schedule()` with `is_crew=True`.

### Non-Goals (explicitly out of scope)
- **Crew configuration snapshots**: Replay uses the crew's current configuration,
  not a frozen copy from the original execution. Configuration versioning is a
  separate concern.
- **Full-text search on prompts**: Can be added later via Postgres `tsvector`;
  not in scope for this spec.
- **Execution diffing**: Comparing results across replays is out of scope.
- **Cursor-based pagination**: OFFSET/LIMIT is sufficient for expected volumes.
- A dedicated SavedExecution table separate from the existing `crew_executions`
  storage was rejected in brainstorm — see `sdd/proposals/agentcrew-saved-crews.brainstorm.md` Option B.

---

## 2. Architectural Design

### Overview

Extend the existing `ResultStorage` ABC (FEAT-147) with read methods, implement
them in all three backends (`PostgresResultStorage`, `RedisResultStorage`,
`DocumentDbResultStorage`), enhance the save path to capture prompt and tenant,
add a thin `SavedExecutionService` orchestration layer in `ai-parrot-server`,
and expose it via a new `CrewExecutionHistoryHandler` at `/api/v1/crew/executions`.

For scheduling, the service delegates directly to
`AgentSchedulerManager.add_schedule()` with `is_crew=True`, accepting all
schedule types (ONCE, DAILY, WEEKLY, MONTHLY, INTERVAL, CRON, CRONTAB).

### Component Diagram
```
                         ┌─────────────────────────────────┐
                         │  CrewExecutionHistoryHandler     │
                         │  /api/v1/crew/executions         │
                         └──────────────┬──────────────────┘
                                        │
                         ┌──────────────▼──────────────────┐
                         │  SavedExecutionService           │
                         │  (list, get, replay, schedule,   │
                         │   delete)                        │
                         └───┬──────────┬──────────┬───────┘
                             │          │          │
                ┌────────────▼──┐  ┌────▼─────┐  ┌▼─────────────────┐
                │ ResultStorage  │  │BotManager│  │AgentScheduler    │
                │ (read + write) │  │(get_crew)│  │Manager           │
                └───┬────┬───┬──┘  └──────────┘  │(add_schedule)    │
                    │    │   │                    └──────────────────┘
              ┌─────▼┐ ┌─▼──┐ ┌▼──────────┐
              │Postgres│Redis│ │DocumentDB │
              └───────┘└────┘ └───────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ResultStorage` ABC | extends | Add `list`, `get`, `delete`, `count` abstract methods |
| `PostgresResultStorage` | extends | Implement all four read methods + DDL migration |
| `RedisResultStorage` | extends | Implement all four read methods using SCAN + GET |
| `DocumentDbResultStorage` | extends | Implement using `DocumentDb.read()`, `find_documents()`, `delete_many()` |
| `PersistenceMixin._save_result()` | modifies | Accept and persist `prompt` and `tenant` kwargs |
| `AgentCrew.run_*` methods | modifies | Pass `prompt` kwarg to `_save_result()` |
| `AgentSchedulerManager.add_schedule()` | uses (no changes) | Called with `is_crew=True` for scheduling |
| `BotManager.get_crew()` | uses (no changes) | Used to resolve crew for replay |
| `CrewExecutionHandler` | sibling (no changes) | Existing run/status endpoints unchanged |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum


class ExecutionFilter(BaseModel):
    """Filters for listing saved executions."""
    crew_name: Optional[str] = None
    method: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class ExecutionSummary(BaseModel):
    """Summary of a saved execution for list responses."""
    id: str
    crew_name: str
    method: str
    prompt: Optional[str] = None
    user_id: Optional[str] = None
    tenant: str = "global"
    timestamp: datetime
    status: str = "success"


class ExecutionDetail(ExecutionSummary):
    """Full execution record with payload."""
    session_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class ReplayRequest(BaseModel):
    """Request body for replaying an execution (currently empty — future extension)."""
    pass


class ScheduleRequest(BaseModel):
    """Request body for scheduling a saved execution."""
    schedule_type: str  # ONCE, DAILY, WEEKLY, MONTHLY, INTERVAL, CRON, CRONTAB
    schedule_config: Dict[str, Any]
    created_by: Optional[int] = None
    created_email: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    callbacks: Optional[List[Dict[str, Any]]] = None


class PaginatedResponse(BaseModel):
    """Paginated list response."""
    items: List[ExecutionSummary]
    total: int
    limit: int
    offset: int
```

### New Public Interfaces

```python
class SavedExecutionService:
    """Orchestration layer for execution history, replay, and scheduling."""

    def __init__(self, storage: ResultStorage, bot_manager, scheduler_manager=None):
        ...

    async def list_executions(
        self, tenant: str, user_id: str,
        filters: Optional[ExecutionFilter] = None,
        limit: int = 20, offset: int = 0,
    ) -> tuple[list[dict], int]:
        ...

    async def get_execution(
        self, tenant: str, user_id: str, execution_id: str,
    ) -> Optional[dict]:
        ...

    async def replay_execution(
        self, tenant: str, user_id: str, execution_id: str,
    ) -> dict:
        """Returns a new job dict with job_id for the replayed execution."""
        ...

    async def schedule_execution(
        self, tenant: str, user_id: str, execution_id: str,
        schedule_config: ScheduleRequest,
    ) -> dict:
        """Returns the created AgentSchedule as dict."""
        ...

    async def delete_execution(
        self, tenant: str, user_id: str, execution_id: str,
    ) -> bool:
        ...
```

---

## 3. Module Breakdown

### Module 1: ResultStorage ABC Extension
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/base.py`
- **Responsibility**: Add `list`, `get`, `delete`, `count` abstract methods with
  default `NotImplementedError` implementations to preserve backwards compatibility.
- **Depends on**: nothing

### Module 2: PostgresResultStorage Read Methods + DDL Migration
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py`
- **Responsibility**: Implement all four new read methods. Extend `_ensure_table()`
  with idempotent DDL to add `tenant` and `prompt` columns + composite index.
- **Depends on**: Module 1

### Module 3: RedisResultStorage Read Methods
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/redis.py`
- **Responsibility**: Implement `list` (via SCAN + pattern matching + GET),
  `get` (key lookup), `delete` (DEL), `count` (SCAN count). Key format uses
  `{collection}:{crew_name}:{ts_ms}` — scanning filters by prefix.
- **Depends on**: Module 1

### Module 4: DocumentDbResultStorage Read Methods
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/documentdb.py`
- **Responsibility**: Implement using `DocumentDb.find_documents()` for list,
  `DocumentDb.read_one()` for get, `DocumentDb.delete_many()` for delete,
  and `DocumentDb.find_documents()` with count for count.
- **Depends on**: Module 1

### Module 5: PersistenceMixin Save Path Enhancement
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/storage/persistence.py`
- **Responsibility**: Update `_save_result()` to include `prompt` and `tenant`
  in the persisted document. These are passed via `**kwargs` from callers.
- **Depends on**: nothing (parallel with Module 1)

### Module 6: AgentCrew run_* Prompt Passthrough
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
- **Responsibility**: Each `run_*` method (`run_sequential`, `run_parallel`,
  `run_flow`, `run_loop`, `run`) passes the original prompt/query/initial_task
  as a `prompt` kwarg to `_save_result()`. Also pass `tenant` from the crew's
  `CrewDefinition` if available.
- **Depends on**: Module 5

### Module 7: Pydantic Request/Response Models
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/crew/models.py`
- **Responsibility**: Add `ExecutionFilter`, `ExecutionSummary`, `ExecutionDetail`,
  `ReplayRequest`, `ScheduleRequest`, `PaginatedResponse` models.
- **Depends on**: nothing (parallel)

### Module 8: SavedExecutionService
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/crew/saved_execution_service.py`
- **Responsibility**: Thin orchestration layer. `list`/`get`/`delete` delegate to
  `ResultStorage`. `replay` resolves the crew via `BotManager.get_crew()` and calls
  the appropriate `run_*` method. `schedule` calls
  `AgentSchedulerManager.add_schedule(is_crew=True)`.
- **Depends on**: Module 1, Module 2 (or any backend), Module 7

### Module 9: CrewExecutionHistoryHandler
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/crew/execution_history_handler.py`
- **Responsibility**: aiohttp `BaseView` handler at `/api/v1/crew/executions`.
  HTTP method routing: GET (list + detail), POST (replay + schedule), DELETE.
  Update `__init__.py` to export the new handler.
- **Depends on**: Module 8, Module 7

### Module 10: Tests
- **Path**: `tests/` (multiple files)
- **Responsibility**: Unit tests for each storage backend's read methods,
  integration tests for the service layer, and handler endpoint tests.
- **Depends on**: all previous modules

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_result_storage_abc_has_read_methods` | Module 1 | Verify ABC defines list/get/delete/count |
| `test_postgres_list_executions` | Module 2 | List with filters, pagination, tenant+user scoping |
| `test_postgres_get_execution_by_id` | Module 2 | Retrieve single record by UUID |
| `test_postgres_delete_execution` | Module 2 | Delete record, verify gone |
| `test_postgres_count_executions` | Module 2 | Count with filters |
| `test_postgres_ddl_adds_columns` | Module 2 | Idempotent DDL adds tenant + prompt columns |
| `test_redis_list_executions` | Module 3 | SCAN-based listing with filters |
| `test_redis_get_execution` | Module 3 | Get by key |
| `test_redis_delete_execution` | Module 3 | Delete by key |
| `test_documentdb_list_executions` | Module 4 | find_documents-based listing |
| `test_documentdb_get_execution` | Module 4 | read_one-based retrieval |
| `test_documentdb_delete_execution` | Module 4 | delete_many-based deletion |
| `test_save_result_includes_prompt` | Module 5 | Verify prompt kwarg persisted |
| `test_save_result_includes_tenant` | Module 5 | Verify tenant kwarg persisted |
| `test_run_sequential_passes_prompt` | Module 6 | Verify prompt forwarded to _save_result |
| `test_run_parallel_passes_prompt` | Module 6 | Verify prompt forwarded |
| `test_run_flow_passes_prompt` | Module 6 | Verify prompt forwarded |
| `test_replay_execution_success` | Module 8 | Replay calls correct run_* method |
| `test_replay_crew_not_found` | Module 8 | Returns 404 when crew deleted |
| `test_replay_no_prompt` | Module 8 | Returns 400 when prompt missing |
| `test_schedule_execution_success` | Module 8 | Creates APScheduler job |

### Integration Tests
| Test | Description |
|---|---|
| `test_save_and_list_roundtrip` | Save via run_*, then list via API and verify prompt present |
| `test_replay_creates_new_execution` | Replay an execution, verify new record saved |
| `test_schedule_from_execution` | Schedule a saved execution, verify AgentSchedule created |
| `test_tenant_isolation` | Verify user A cannot see user B's executions |
| `test_pagination` | Verify offset/limit and total count |

### Test Data / Fixtures
```python
@pytest.fixture
def sample_execution_doc():
    return {
        "crew_name": "research-crew",
        "method": "run_sequential",
        "user_id": "user-001",
        "session_id": "sess-abc",
        "tenant": "acme",
        "prompt": "Analyze Q3 market trends",
        "timestamp": time.time(),
        "result": {"raw": "Analysis complete..."},
    }

@pytest.fixture
def sample_schedule_config():
    return {
        "schedule_type": "DAILY",
        "schedule_config": {"hour": 9, "minute": 0},
    }
```

---

## 5. Acceptance Criteria

- [ ] `ResultStorage` ABC defines `list`, `get`, `delete`, `count` methods
- [ ] `PostgresResultStorage` implements all four read methods with parameterized queries
- [ ] `RedisResultStorage` implements all four read methods using SCAN/GET/DEL
- [ ] `DocumentDbResultStorage` implements all four read methods using DocumentDb API
- [ ] `crew_executions` table has `tenant` and `prompt` columns (idempotent DDL)
- [ ] Composite index on `(tenant, user_id)` created idempotently
- [ ] `PersistenceMixin._save_result()` persists `prompt` and `tenant` from kwargs
- [ ] Each `AgentCrew.run_*` method passes `prompt` to `_save_result()`
- [ ] `GET /api/v1/crew/executions` returns paginated, tenant+user-scoped execution list
- [ ] `GET /api/v1/crew/executions/{id}` returns full execution detail with payload
- [ ] `POST /api/v1/crew/executions/{id}/replay` re-runs prompt against current crew config
- [ ] `POST /api/v1/crew/executions/{id}/schedule` creates APScheduler job via `add_schedule(is_crew=True)`
- [ ] Schedule endpoint accepts all schedule types: ONCE, DAILY, WEEKLY, MONTHLY, INTERVAL, CRON, CRONTAB
- [ ] `DELETE /api/v1/crew/executions/{id}` removes execution record
- [ ] Replay returns 404 if crew no longer exists
- [ ] Replay returns 400 if original prompt not available (legacy records)
- [ ] Every query enforces `WHERE tenant = ? AND user_id = ?` scoping
- [ ] Existing fire-and-forget `_save_result()` callers continue working unchanged
- [ ] No breaking changes to existing `ResultStorage` backends (default implementations)
- [ ] Unlimited retention — no TTL applied to saved executions
- [ ] All unit tests pass
- [ ] All integration tests pass

---

## 6. Codebase Contract

### Verified Imports
```python
# Core storage
from parrot.bots.flows.core.storage.backends.base import ResultStorage       # backends/base.py:8
from parrot.bots.flows.core.storage.backends.postgres import PostgresResultStorage  # backends/postgres.py:23
from parrot.bots.flows.core.storage.backends.redis import RedisResultStorage  # backends/redis.py:21
from parrot.bots.flows.core.storage.backends.documentdb import DocumentDbResultStorage  # backends/documentdb.py:17
from parrot.bots.flows.core.storage.backends import get_result_storage       # backends/factory.py
from parrot.bots.flows.core.storage.persistence import PersistenceMixin      # persistence.py:29

# Crew
from parrot.bots.flows.crew import AgentCrew  # crew/__init__.py (inferred)
from parrot.models.crew_definition import CrewDefinition  # models/crew_definition.py:90

# DocumentDb interface (for DocumentDbResultStorage read methods)
from parrot.interfaces.documentdb import DocumentDb  # interfaces/documentdb.py:63

# Scheduler
# AgentSchedulerManager is in ai-parrot-server, not core:
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:284

# Config
from parrot.conf import CREW_RESULT_STORAGE_PG_DSN     # used by PostgresResultStorage
from parrot.conf import CREW_RESULT_STORAGE_REDIS_URL   # used by RedisResultStorage
from parrot.conf import CREW_RESULT_STORAGE_REDIS_TTL   # used by RedisResultStorage
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/base.py:8
class ResultStorage(ABC):
    async def save(self, collection: str, document: dict[str, Any]) -> None: ...  # line 18
    async def close(self) -> None: ...  # line 27

# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py:23
class PostgresResultStorage(ResultStorage):
    def __init__(self, dsn: Optional[str] = None) -> None: ...  # line 35
    async def _ensure(self) -> AsyncDB: ...  # line 46
    async def _ensure_table(self, conn: AsyncDB, table: str) -> None: ...  # line 53
    async def save(self, collection: str, document: dict[str, Any]) -> None: ...  # line 85
    async def close(self) -> None: ...  # line 131
    # Internal state:
    #   _dsn: str                    (line 41)
    #   _conn: Optional[AsyncDB]     (line 42)
    #   _initialised: set[str]       (line 43)

# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/redis.py:21
class RedisResultStorage(ResultStorage):
    def __init__(self, dsn: Optional[str] = None, ttl: Optional[int] = None) -> None: ...  # line 29
    async def _ensure(self) -> AsyncDB: ...  # line 46
    async def save(self, collection: str, document: dict[str, Any]) -> None: ...  # line 53
    async def close(self) -> None: ...  # line 80
    # Key pattern: {collection}:{crew_name}:{ts_ms}

# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/documentdb.py:17
class DocumentDbResultStorage(ResultStorage):
    def __init__(self) -> None: ...  # line 25
    async def save(self, collection: str, document: dict[str, Any]) -> None: ...  # line 28
    async def close(self) -> None: ...  # line 45

# packages/ai-parrot/src/parrot/interfaces/documentdb.py:63
class DocumentDb:
    async def find_documents(self, collection_name, query, sort=None, limit=None, projection=None) -> List[dict]: ...  # line 317
    async def read(self, collection_name, query=None, limit=None, projection=None, sort=None) -> List[dict]: ...  # line 367
    async def read_one(self, collection_name, query) -> Optional[dict]: ...  # line 409
    async def delete_many(self, collection_name, query) -> Any: ...  # line 351
    async def write(self, collection_name, data) -> Any: ...  # line 447

# packages/ai-parrot/src/parrot/bots/flows/core/storage/persistence.py:29
class PersistenceMixin:
    def _ensure_result_storage(self) -> ResultStorage: ...  # line 45
    async def _save_result(self, result: Any, method: str, *, collection: str = "crew_executions", **kwargs: Any) -> None: ...  # line 65
    async def aclose(self) -> None: ...  # line 110
    # _save_result builds document: {"crew_name", "method", "timestamp", "result", **kwargs}
    # kwargs currently pass: user_id, session_id (from callers)

# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:93
class AgentCrew(PersistenceMixin, SynthesisMixin):
    async def run_sequential(self, query, ...) -> FlowResult: ...  # line 1172
    async def run_parallel(self, tasks, ...) -> FlowResult: ...  # line 1966
    async def run_flow(self, initial_task, ...) -> FlowResult: ...  # line 2289
    async def run_loop(self, query, ...) -> FlowResult: ...  # line 1500
    async def run(self, prompt, ...) -> AIMessage: ...  # line 2618
    async def ask(self, question, ...) -> AIMessage: ...  # line 3108

# packages/ai-parrot-server/src/parrot/scheduler/manager.py:284
class AgentSchedulerManager:
    async def add_schedule(
        self, agent_name, schedule_type, schedule_config,
        prompt=None, method_name=None, created_by=None, created_email=None,
        metadata=None, agent_id=None, *, is_crew=False,
        send_result=None, success_callback=None,
        scheduler_type='default', callbacks=None
    ) -> AgentSchedule: ...  # line 932

# packages/ai-parrot-server/src/parrot/handlers/crew/execution_handler.py:15
class CrewExecutionHandler(BaseView):
    path: str = '/api/v1/crews'  # line 27
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ResultStorage.list()` | `PostgresResultStorage._ensure()` | SELECT query | `postgres.py:46` |
| `ResultStorage.list()` | `RedisResultStorage._ensure()` | SCAN + GET | `redis.py:46` |
| `ResultStorage.list()` | `DocumentDb.find_documents()` | Motor cursor | `documentdb.py:317` |
| `SavedExecutionService.replay` | `BotManager.get_crew()` | method call | server handler pattern |
| `SavedExecutionService.schedule` | `AgentSchedulerManager.add_schedule()` | method call | `manager.py:932` |
| `CrewExecutionHistoryHandler` | `SavedExecutionService` | method call | new code |
| `PersistenceMixin._save_result()` | `ResultStorage.save()` | delegation | `persistence.py:102` |

### Does NOT Exist (Anti-Hallucination)
- ~~`ResultStorage.list()`~~ — does not exist yet; ABC only has `save()` and `close()`
- ~~`ResultStorage.get()`~~ — does not exist yet
- ~~`ResultStorage.delete()`~~ — does not exist yet
- ~~`ResultStorage.count()`~~ — does not exist yet
- ~~`PostgresResultStorage.query()`~~ — no read methods exist
- ~~`RedisResultStorage.list()`~~ — no read methods exist
- ~~`DocumentDbResultStorage.list()`~~ — no read methods exist
- ~~`SavedExecutionService`~~ — does not exist; must be created
- ~~`CrewExecutionHistoryHandler`~~ — does not exist; must be created
- ~~`crew_executions.tenant` column~~ — table has no tenant column currently
- ~~`crew_executions.prompt` column~~ — prompt is buried in `payload` jsonb, not a top-level column
- ~~`PersistenceMixin._save_result(prompt=...)`~~ — prompt is not currently passed or stored; goes through `**kwargs` but no caller passes it yet
- ~~`_NAMED_COLUMNS` includes "tenant" or "prompt"~~ — currently only `frozenset(("crew_name", "method", "user_id", "session_id", "timestamp"))` at `postgres.py:20`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Idempotent DDL**: Schema migration uses `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
  inside `_ensure_table()`, same pattern as the existing table creation. No formal
  migration framework — DDL runs on first connection.
- **Async-first**: All new methods are `async def`.
- **Pydantic models** for all request/response structures.
- **`self.logger`** for all logging (no print statements).
- **`BaseView` pattern** for the HTTP handler (same as `CrewExecutionHandler`).
- **Parameterized queries**: All SQL uses `$N` placeholders — no string formatting
  of user input.
- **`_NAMED_COLUMNS` update**: Add `"tenant"` and `"prompt"` to the frozenset in
  `postgres.py` so `save()` extracts them as top-level columns instead of burying
  them in `payload`.

### Known Risks / Gotchas
- **Legacy records**: Executions saved before this feature will have `tenant = NULL`

…(truncated)…
