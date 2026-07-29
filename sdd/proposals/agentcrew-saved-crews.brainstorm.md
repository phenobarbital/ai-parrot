---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: AgentCrew Saved Crews (Execution Persistence & Replay)

**Date**: 2026-07-14
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

AgentCrew already persists execution results via the `ResultStorage` backends
(FEAT-147), but the persistence is **write-only** — there is no way to list,
retrieve, replay, or schedule past executions. The `ResultStorage` ABC only
exposes `save()` and `close()`.

This means:
- Users who ran a complex crew query cannot find it again or re-run it later.
- There is no audit trail accessible via the API (only raw DB queries).
- The scheduler (`AgentSchedulerManager`) supports crew execution but requires
  manual configuration — there is no path from "I ran this crew successfully"
  to "run it again every Monday."

**Who is affected:**
- **API consumers** who want execution history and replay.
- **Ops/analysts** who need recurring crew executions on a schedule.
- **Developers** building dashboards or monitoring crew usage.

## Constraints & Requirements

- Must extend the existing `ResultStorage` ABC — no parallel persistence layer.
- PostgreSQL is the target backend (the existing `PostgresResultStorage` table
  schema is the starting point).
- Replay stores prompt + crew ID only (uses the crew's current configuration,
  not a snapshot).
- Scoping: tenant + user (the `user_id` and `crew_name` columns already exist).
- The scheduler integration uses the existing `AgentSchedulerManager.add_schedule()`
  with `is_crew=True`.
- Must not break existing fire-and-forget `_save_result()` callers.
- New endpoints under `/api/v1/crew/executions` — separate from the existing
  run/status endpoints at `/api/v1/crews`.

---

## Options Explored

### Option A: Extend ResultStorage ABC + New Handler

Extend the `ResultStorage` ABC with read methods (`list`, `get`, `delete`),
implement them in `PostgresResultStorage`, add a `SavedExecutionService` that
wraps storage + replay + schedule-creation, and expose it via a new
`CrewExecutionHistoryHandler` at `/api/v1/crew/executions`.

The service layer coordinates: reads from storage, replays by fetching the
crew from `BotManager` and calling the appropriate `run_*` method with the
saved prompt, and schedules by calling `AgentSchedulerManager.add_schedule()`.

✅ **Pros:**
- Builds on existing infrastructure (no new tables, no new storage pattern).
- Single ABC contract for all backends — Redis and DocumentDB get read methods
  too (even if initially unimplemented / raise NotImplementedError).
- The service layer is thin: most logic already exists in `BotManager` and
  `AgentSchedulerManager`.
- Backwards-compatible: `save()` and `close()` unchanged.

❌ **Cons:**
- Extending an ABC requires touching all three backends (Postgres, Redis, DocumentDB).
- The Postgres table schema may need migration (add `tenant` column, add
  `query`/`prompt` column that's currently buried in `payload` jsonb).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | Postgres queries (already in use) | Used by `PostgresResultStorage` |
| `apscheduler` | Schedule creation (already in use) | Used by `AgentSchedulerManager` |
| `pydantic` | Request/response models | Standard in codebase |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/core/storage/backends/base.py` — `ResultStorage` ABC to extend
- `parrot/bots/flows/core/storage/backends/postgres.py` — `PostgresResultStorage` to add read methods
- `parrot/bots/flows/core/storage/persistence.py` — `PersistenceMixin._save_result()` (add prompt to saved document)
- `packages/ai-parrot-server/src/parrot/scheduler/manager.py` — `AgentSchedulerManager.add_schedule()` for one-click scheduling
- `packages/ai-parrot-server/src/parrot/handlers/crew/execution_handler.py` — reference for handler patterns

---

### Option B: Separate SavedExecution Table + Dedicated Service

Create a new `saved_executions` table with a richer relational schema
(explicit `prompt`, `crew_id`, `tenant`, `execution_mode`, `tags` columns
instead of relying on jsonb). Build a dedicated `SavedExecutionStore` that
does not inherit from `ResultStorage`. Wire it into the save path by having
`PersistenceMixin` write to both the existing `ResultStorage` and the new
store.

✅ **Pros:**
- Clean relational schema optimized for queries (no jsonb digging).
- Does not pollute the existing `ResultStorage` contract with read concerns.
- Easier to add features like tagging, favoriting, and full-text search on prompts.

❌ **Cons:**
- Dual-write adds complexity and failure modes.
- New table, new DDL, new migration — more surface area.
- Duplicates data that already exists in `crew_executions`.
- Higher effort: need to keep two stores in sync.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | Postgres queries | Same as Option A |
| `asyncpg` | Direct Postgres driver (alternative) | If richer query support needed |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/scheduler/manager.py` — `AgentSchedule` model pattern (Navigator ORM)
- `parrot/bots/flows/core/storage/persistence.py` — hook point for dual-write

---

### Option C: Redis-Only with Replay Queue

Keep execution history in Redis (extending `RedisResultStorage` with list/scan
operations). Replay works by pushing a message onto a Redis queue that a
worker process picks up and re-executes. Scheduling uses Redis-based delayed
queues (e.g., `arq` or a simple sorted-set pattern) instead of APScheduler.

✅ **Pros:**
- No Postgres dependency for this feature.
- Redis is already the crew definition store — keeps everything in one backend.
- Pub/sub replay is naturally async and decoupled.

❌ **Cons:**
- Redis is ephemeral by default — execution history lost on restart unless
  persistence is configured.
- Redis SCAN for listing is O(N) and unreliable for pagination.
- Bypasses the existing `AgentSchedulerManager` (APScheduler) — creates a
  parallel scheduling system.
- No ACID guarantees, no joins, no rich querying.
- The user explicitly chose PostgreSQL.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `redis`/`aioredis` | Storage + queuing | Already in use |
| `arq` | Task queue on Redis | Alternative to APScheduler |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py` — `CrewRedis` patterns
- `parrot/bots/flows/core/storage/backends/redis.py` — `RedisResultStorage`

---

## Recommendation

**Option A** is recommended because it extends existing infrastructure with
minimal new surface area. The `ResultStorage` ABC is the natural home for read
operations — it's where writes already go, and adding `list`/`get`/`delete`
makes the contract complete. The Postgres table already has the right shape;
we only need to: (1) ensure `prompt`/`query` is stored as a top-level column
(or reliably extracted from `payload`), (2) add a `tenant` column, and
(3) implement the read methods.

The tradeoff vs Option B is that we rely on `payload` jsonb for some fields
instead of having fully normalized columns. This is acceptable because:
- The primary query patterns are by `crew_name`, `user_id`, and time range —
  all already indexed columns.
- Prompt text is stored once per execution; we can add it as a top-level
  column in the same migration that adds `tenant`.
- Full-text search on prompts (if needed later) can use Postgres `tsvector`
  on the column.

Option C is rejected because the user chose PostgreSQL, and building a
parallel scheduling system alongside APScheduler adds unnecessary complexity.

---

## Feature Description

### User-Facing Behavior

**List executions (GET /api/v1/crew/executions)**
Returns a paginated list of past crew executions for the authenticated user
and tenant. Supports filters: `crew_name`, `method`, `date_from`, `date_to`.
Each entry shows: `id`, `crew_name`, `method`, `prompt` (extracted), `timestamp`,
`status` (success/error derived from payload).

**Get execution detail (GET /api/v1/crew/executions/{execution_id})**
Returns the full execution record including the result payload.

**Replay execution (POST /api/v1/crew/executions/{execution_id}/replay)**
Re-submits the saved prompt to the same crew using its **current**
configuration. Returns a new job ID (same as the existing crew execution
flow). The new execution is itself saved, creating an audit chain.

**Schedule execution (POST /api/v1/crew/executions/{execution_id}/schedule)**
Creates an APScheduler job for the saved prompt + crew combination. Accepts
schedule configuration (cron, interval, daily, etc.) in the request body.
Returns the `AgentSchedule` record. Uses `AgentSchedulerManager.add_schedule()`
with `is_crew=True`.

**Delete execution (DELETE /api/v1/crew/executions/{execution_id})**
Soft-deletes (or hard-deletes) a saved execution record.

### Internal Behavior

1. **Save path enhancement**: `PersistenceMixin._save_result()` is updated to
   include the original `prompt`/`query` in the persisted document. The caller
   (each `run_*` method in `AgentCrew`) passes the prompt as a kwarg.

2. **Schema migration**: The `crew_executions` table gets:
   - `tenant TEXT NOT NULL DEFAULT 'global'` — for multi-tenant filtering.
   - `prompt TEXT` — the original query/prompt (extracted from kwargs or payload).
   - Index on `(tenant, user_id)` for scoped listing.

3. **ResultStorage ABC extension**: New abstract methods with default
   `NotImplementedError` implementations so existing backends don't break:
   - `async def list(collection, filters, limit, offset) -> list[dict]`
   - `async def get(collection, record_id) -> Optional[dict]`
   - `async def delete(collection, record_id) -> bool`
   - `async def count(collection, filters) -> int`

4. **PostgresResultStorage**: Implements all four new methods with parameterized
   queries against the `crew_executions` table.

5. **SavedExecutionService**: Thin orchestration layer in `ai-parrot-server`:
   - `list_executions(tenant, user_id, filters)` — delegates to storage.list()
   - `get_execution(tenant, user_id, execution_id)` — delegates to storage.get()
   - `replay_execution(execution_id, bot_manager)` — fetches record, resolves
     crew via `BotManager.get_crew()`, calls the appropriate `run_*` method.
   - `schedule_execution(execution_id, schedule_config, scheduler_manager)` —
     fetches record, calls `AgentSchedulerManager.add_schedule()`.
   - `delete_execution(tenant, user_id, execution_id)` — delegates to storage.delete()

6. **CrewExecutionHistoryHandler**: New aiohttp handler at `/api/v1/crew/executions`
   wiring HTTP methods to `SavedExecutionService`.

### Edge Cases & Error Handling

- **Crew deleted after execution saved**: Replay returns 404 with message
  "Crew '{name}' no longer exists." Schedule creation is also blocked.
- **Prompt missing from legacy records**: Old records saved before this feature
  won't have a `prompt` column. `list` shows them with `prompt: null`;
  replay returns 400 "Cannot replay: original prompt not available."
- **Concurrent replay**: Two replays of the same execution are independent —
  each creates its own job. No dedup.
- **Pagination**: Default page size 20, max 100. Uses `OFFSET`/`LIMIT` (good
  enough for expected volumes; cursor-based pagination is a future optimization).
- **Tenant isolation**: Every query includes `WHERE tenant = $1 AND user_id = $2`.
  Missing tenant defaults to `'global'`.

---

## Capabilities

### New Capabilities
- `crew-execution-history`: List and retrieve past AgentCrew execution records
- `crew-execution-replay`: Re-run a saved execution with the crew's current config
- `crew-execution-schedule`: Create a recurring schedule from a saved execution
- `result-storage-read`: Read/list/delete methods on the ResultStorage ABC

### Modified Capabilities
- `result-storage-write` (FEAT-147): `PersistenceMixin._save_result()` updated to
  include prompt and tenant in persisted documents.
- `crew-execution` (existing): Each `run_*` method passes the prompt to `_save_result()`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `ResultStorage` ABC | extends | New abstract methods: list, get, delete, count |
| `PostgresResultStorage` | extends | Implements new read methods + schema migration |
| `RedisResultStorage` | extends | Raise NotImplementedError (or basic implementation) |
| `DocumentDbResultStorage` | extends | Raise NotImplementedError (or basic implementation) |
| `PersistenceMixin._save_result()` | modifies | Accepts and persists prompt/tenant |
| `AgentCrew.run_*` methods | modifies | Pass prompt kwarg to `_save_result()` |
| `crew_executions` Postgres table | modifies | Add tenant, prompt columns + index |
| `AgentSchedulerManager` | depends on | Used by schedule_execution (no changes needed) |
| `BotManager` | depends on | Used by replay_execution (no changes needed) |
| Handler routing (`parrot/handlers/crew/`) | extends | New handler + __init__ export |

---

## Code Context

### User-Provided Code
None — feature described verbally during brainstorming.

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/base.py:8
class ResultStorage(ABC):
    async def save(self, collection: str, document: dict[str, Any]) -> None: ...  # line 18
    async def close(self) -> None: ...  # line 27

# From packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py:23
class PostgresResultStorage(ResultStorage):
    def __init__(self, dsn: Optional[str] = None) -> None: ...  # line 35
    async def _ensure(self) -> AsyncDB: ...  # line 46
    async def _ensure_table(self, conn: AsyncDB, table: str) -> None: ...  # line 53
    async def save(self, collection: str, document: dict[str, Any]) -> None: ...  # line 85
    async def close(self) -> None: ...  # line 131

# From packages/ai-parrot/src/parrot/bots/flows/core/storage/persistence.py:29
class PersistenceMixin:
    async def _save_result(self, result: Any, method: str, *, collection: str = "crew_executions", **kwargs: Any) -> None: ...  # line 65
    async def aclose(self) -> None: ...  # line 110

# From packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:93
class AgentCrew(PersistenceMixin, SynthesisMixin):
    def __init__(self, name, agents, shared_tool_manager, ..., persist_results=True, result_storage=None, **kwargs): ...  # line 132
    async def run_sequential(self, query, ...) -> FlowResult: ...  # line 1172
    async def run_parallel(self, tasks, ...) -> FlowResult: ...  # line 1966
    async def run_flow(self, initial_task, ...) -> FlowResult: ...  # line 2289
    async def run_loop(self, query, ...) -> FlowResult: ...  # line 1500
    async def run(self, prompt, ...) -> AIMessage: ...  # line 2618
    async def ask(self, question, ...) -> AIMessage: ...  # line 3108
    @classmethod
    def from_definition(cls, crew_def, class_resolver, tool_resolver): ...  # line 346

# From packages/ai-parrot/src/parrot/models/crew_definition.py:90
class CrewDefinition(BaseModel):
    crew_id: str  # default uuid4()
    tenant: str  # default "global"
    name: str
    description: Optional[str]
    execution_mode: ExecutionMode
    agents: List[AgentDefinition]
    # ... (flow_relations, shared_tools, max_parallel_tasks, metadata, created_at, updated_at)

# From packages/ai-parrot-server/src/parrot/scheduler/manager.py:284
class AgentSchedulerManager:
    async def add_schedule(self, agent_name, schedule_type, schedule_config, prompt=None,
                           method_name=None, created_by=None, created_email=None,
                           metadata=None, agent_id=None, *, is_crew=False,
                           send_result=None, success_callback=None,
                           scheduler_type='default', callbacks=None) -> AgentSchedule: ...  # line 932

# From packages/ai-parrot-server/src/parrot/handlers/crew/execution_handler.py:15
class CrewExecutionHandler(BaseView):
    path: str = '/api/v1/crews'  # line 27

# From packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py:17
class CrewRedis:
    async def save_crew(self, crew) -> None: ...  # line 150
    async def load_crew(self, name, tenant) -> Optional[CrewDefinition]: ...  # line 192
    async def list_crews(self, tenant) -> list: ...  # line 307
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.bots.flows.core.storage.backends.base import ResultStorage  # backends/__init__.py
from parrot.bots.flows.core.storage.backends.postgres import PostgresResultStorage  # backends/__init__.py
from parrot.bots.flows.core.storage.backends import get_result_storage  # backends/__init__.py
from parrot.bots.flows.core.storage.persistence import PersistenceMixin  # persistence.py
from parrot.bots.flows.crew import AgentCrew  # crew/__init__.py (inferred)
from parrot.models.crew_definition import CrewDefinition  # models/crew_definition.py
from parrot.conf import CREW_RESULT_STORAGE_PG_DSN  # used by PostgresResultStorage
```

#### Key Attributes & Constants
- `PostgresResultStorage._dsn` → `str` (postgres.py:41)
- `PostgresResultStorage._conn` → `Optional[AsyncDB]` (postgres.py:42)
- `PostgresResultStorage._initialised` → `set[str]` (postgres.py:43)
- `PersistenceMixin._persist_results` → `bool` (persistence.py:86)
- `PersistenceMixin._result_storage` → `Optional[ResultStorage]` (persistence.py:55)
- `AgentCrew._persist_tasks` → `set[asyncio.Task]` (crew.py, constructor)
- `_NAMED_COLUMNS` → `frozenset(("crew_name", "method", "user_id", "session_id", "timestamp"))` (postgres.py:20)
- `_TABLE_RE` → `re.compile(r"^[a-z_][a-z0-9_]*$")` (postgres.py:19)

### Does NOT Exist (Anti-Hallucination)
- ~~`ResultStorage.list()`~~ — does not exist; ABC only has `save()` and `close()`
- ~~`ResultStorage.get()`~~ — does not exist
- ~~`ResultStorage.delete()`~~ — does not exist
- ~~`PostgresResultStorage.query()`~~ — no read methods exist
- ~~`SavedExecutionService`~~ — does not exist; must be created
- ~~`CrewExecutionHistoryHandler`~~ — does not exist; must be created
- ~~`crew_executions.tenant` column~~ — table has no tenant column currently
- ~~`crew_executions.prompt` column~~ — prompt is buried in `payload` jsonb, not a top-level column
- ~~`PersistenceMixin._save_result(prompt=...)`~~ — prompt is not currently passed or stored explicitly

---

## Parallelism Assessment

- **Internal parallelism**: Yes — the feature decomposes into independent layers:
  (1) ABC + Postgres backend read methods, (2) schema migration, (3) service layer,
  (4) HTTP handler, (5) `_save_result` prompt passthrough. Layers 1 and 5 can
  proceed in parallel; 3 depends on 1; 4 depends on 3.
- **Cross-feature independence**: Low conflict risk. The `ResultStorage` ABC is
  stable (FEAT-147 shipped). No in-flight specs touch the storage backends or
  `PersistenceMixin`. The crew handler package has a new `tool_catalog.py` in
  progress (unrelated).
- **Recommended isolation**: per-spec
- **Rationale**: Tasks share the same ABC and Postgres backend — changes to the
  ABC signature affect multiple tasks. Sequential execution in one worktree
  avoids merge conflicts on `base.py` and `postgres.py`.

---

## Open Questions

- [x] Should the `crew_executions` table migration be idempotent DDL (like the
  existing `_ensure_table`) or a formal migration script? — *Owner: Jesus*: Use idempotent DDL (same pattern as existing `_ensure_table` in `PostgresResultStorage`).
- [x] Should `RedisResultStorage` and `DocumentDbResultStorage` get real read
  implementations or just `NotImplementedError`? — *Owner: Jesus*: Get real read implementations for all backends.
- [x] What is the retention policy for saved executions? Unlimited? Configurable
  TTL per tenant? — *Owner: Jesus*: Unlimited retention for now.
- [x] Should the schedule endpoint accept all `ScheduleType` values (ONCE, DAILY,
  WEEKLY, MONTHLY, INTERVAL, CRON, CRONTAB) or a subset? — *Owner: Jesus*: Accept all schedule types.
