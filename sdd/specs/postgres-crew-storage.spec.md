---
type: feature
base_branch: dev
projects: [ai-parrot-server, ai-parrot]
tags: [crew, persistence, postgres, redis, migration]
docs:
  policy: required
  pages: [wiki/bots/orchestration/crew-definition-storage.md, wiki/bots/crew_handler.md]
  api_modules: [parrot.handlers.crew.definition_codec, parrot.handlers.crew.postgres_persistence, parrot.handlers.crew.definition_storage]
---

# Feature Specification: Postgres CrewDefinition Storage

**Feature ID**: FEAT-860
**Date**: 2026-11-09
**Author**: Jesus Lara
**Status**: draft
**Target version**: next minor release

---

## 1. Motivation & Business Requirements

### Problem Statement

Crew definitions (`CrewDefinition`) are persisted only in Redis, by `CrewRedis`
(`handlers/crew/redis_persistence.py`). `BotManager` is its only production consumer: it rehydrates every
tenant's crews at startup (`load_crews`) and writes through on `add_crew` / `remove_crew`. There is no
durable, queryable store for definitions — Postgres only holds execution results (`crew_executions`,
FEAT-147/FEAT-307). The request (proposal `sdd/proposals/postgres-crew-storage.proposal.md`):

> vamos a definir un Postgres Crew Definition Storage para el CrewDefinition de Redis a Postgres, con este
> nuevo storage se inicializan los dos (redis y luego postgres) y un flag "migration=True" permite "mover"
> desde redis a postgres los Crew existentes, una tabla `navigator.crew_definitions` en postgres de donde
> se pueden re-hidratar los crew tal como se realiza desde Redis.

### Goals
- A Postgres store over a new table `navigator.crew_definitions` that offers the seven methods
  `BotManager` uses on `CrewRedis` (`save_crew`, `load_crew`, `load_crew_by_id`, `delete_crew`, `ping`,
  `get_all_crews`, `list_all_crews`) and rehydrates crews exactly as Redis does.
- A storage composition that initializes Redis first, then Postgres; with Postgres enabled, Postgres is
  the source of truth and Redis is a read-only fallback for crews Postgres does not have.
- A `migration=True` flag that, at startup, moves every Redis crew into Postgres: copy, verify, then
  delete the Redis keys — serialized across gunicorn workers.
- Opt-in, backward compatible: with nothing configured, behaviour is exactly today's Redis-only storage.
- Degrade, never fail: when Postgres is unavailable, crews keep being served and saved through Redis with
  a clear warning.

### Non-Goals (explicitly out of scope)
- The `CrewHandler` HTTP surface (`/api/v1/crew` GET/PUT/DELETE); no PATCH endpoint here.
- Execution results: `PostgresResultStorage` / `crew_executions`.
- `packages/ai-parrot-server/src/parrot/handlers/creation.sql` and `BotManager._load_database_bots`
  (byte-frozen by the FEAT-621 AC17 gate).
- `CrewDefinition` model fields; a configurable schema/table name; a standalone migration CLI.
- Closing the crew stores on `BotManager.on_shutdown` (not done today either).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:4f0464521ac6d1e1b5e78a83973b790ad7c21d269b04cc79ad2d4d85985eac9c evaluation_digest=sha256:e7e3885e7f45eea36feca2d2e992e3ce165859d8d9659f8be09e9db19dd36874 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Three new modules under `packages/ai-parrot-server/src/parrot/handlers/crew/`:

1. **`definition_codec.py`** — the read-side compatibility step (unknown-key stripping + ISO timestamp
   parsing) moved out of `CrewRedis` so both stores build `CrewDefinition` the same way. `CrewRedis`
   keeps its `_strip_unknown_keys` / `_deserialize_crew` methods as thin delegates (the legacy-payload
   tests call them).
2. **`postgres_persistence.py`** — `CrewPostgres`, the `navigator.crew_definitions` store. It follows the
   `PgUISurfaceStore` idiom: `AsyncDB("pg", dsn=...)` per call, `_DDL_STATEMENTS` auto-applied by an
   idempotent `ensure_schema()` (`CREATE SCHEMA IF NOT EXISTS navigator` + `CREATE TABLE IF NOT EXISTS`),
   writes through `fetchval` on a `RETURNING` clause. The whole `CrewDefinition` is stored as one `jsonb`
   document next to identity/listing columns. Unlike `CrewRedis` it **raises** on database errors and
   returns `None` / `False` only for "not found"; error policy lives in the composition.
3. **`definition_storage.py`** — `CrewDefinitionStorage`, the composition `BotManager` talks to, plus
   `CrewMigrationReport`. It exposes the same seven methods and applies the routing rules below.

`BotManager` keeps `self.crew_redis` and gains `self.crew_postgres` and `self.crew_storage`; every crew
persistence call site moves from `self.crew_redis` to `self.crew_storage`. Three `parrot.conf` keys select
the backend, DSN and migration; `BotManager.__init__` kwargs override them.

**Routing rules (`CrewDefinitionStorage`)**

| Situation | Behaviour |
|---|---|
| `CREW_DEFINITION_STORAGE=redis` (default) | Postgres is never constructed; every call goes to `CrewRedis` — identical to today. |
| `postgres`, no DSN resolved | Warning at startup; Redis-only (degraded). |
| `postgres`, `ping()` fails at startup | Warning at startup; Redis-only (degraded); migration skipped. |
| `postgres`, active — read (`load_crew`, `load_crew_by_id`) | Postgres first; on "not found" **or** error (warning) → Redis. Postgres always wins. |
| `postgres`, active — `get_all_crews` / `list_all_crews` | Postgres rows plus Redis-only `(tenant, name)` entries; a key in both resolves to Postgres. `list_all_crews` **raises** if the Postgres query fails (so `sync_crews` skips the round instead of evicting every cached crew); `get_all_crews` degrades to Redis-only with a warning. |
| `postgres`, active — `save_crew` | Postgres upsert. On a database error: warning and fall back to `CrewRedis.save_crew` (the next migration brings it over). |
| `postgres`, active — `delete_crew` | Delete from Postgres **and** Redis (a Redis copy left behind would resurrect the crew through the fallback). Returns `True` if either deleted. A Postgres error is logged as a warning and the Redis delete still runs. |

**Migration (`migration=True`)** — runs inside `CrewDefinitionStorage.initialize()`, which
`BotManager.load_crews` calls before reading, only when Postgres is active and Redis answers `ping`:

1. Take the session advisory lock `pg_try_advisory_lock(hashtextextended('parrot:crew_definitions:migration', 0))`
   on a dedicated connection (`CrewPostgres.migration_lock()`); a worker that does not get it skips the
   migration (`lock_acquired=False`) and continues — the Redis fallback serves crews not moved yet.
2. For every `CrewRedis.list_all_crews()` entry (legacy `global` keys included): `load_crew` from Redis;
   unreadable → `failed`, Redis kept.
3. `CrewPostgres.insert_if_absent(crew)` (`ON CONFLICT DO NOTHING`, timestamps preserved):
   - **inserted** → re-read from Postgres; if `model_dump(mode="json", exclude={"created_at", "updated_at"})`
     matches the Redis copy → `CrewRedis.delete_crew` → `migrated`; otherwise `failed` ("verification
     mismatch"), Redis kept.
   - **already in Postgres** → Postgres wins; the Redis copy is deleted → `conflicts` (logged at warning
     with the crew key, since a newer Redis-only edit is discarded).
   - **error** → `failed` with the error text, Redis kept.
4. A Redis delete that returns `False` is recorded in `redis_cleanup_failed` (harmless: Postgres wins).
5. Release the lock; log the report summary. Re-running is idempotent.

`dry_run=True` (method argument, used by tests and operators from a shell) classifies every crew as
would-migrate / would-conflict without writing or deleting anything.

### Component Diagram
```
BotManager.load_crews ──→ CrewDefinitionStorage.initialize()
                              │  1. CrewRedis.ping()
                              │  2. CrewPostgres.ping() (+ ensure_schema)  → postgres_active
                              │  3. migration? → migrate_from_redis() ── CrewPostgres.migration_lock()
                              │                     CrewRedis.list_all_crews/load_crew/delete_crew
                              │                     CrewPostgres.insert_if_absent/load_crew
BotManager.add_crew/get_crew/remove_crew/sync_crews ──→ CrewDefinitionStorage
                              ├──→ CrewPostgres  ──→ navigator.crew_definitions (AsyncDB "pg")
                              └──→ CrewRedis     ──→ Redis db 2 (fallback / degraded / migration source)
CrewRedis._deserialize_crew ─┐
CrewPostgres (row → model) ──┴──→ definition_codec.crew_definition_from_dict
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `CrewRedis` | composed (unchanged API) | fallback, degraded store and migration source; its two (de)serialization helpers delegate to the codec |
| `BotManager.__init__` | modified | builds `crew_postgres` / `crew_storage`; two new kwargs |
| `BotManager.load_crews` / `add_crew` / `get_crew` / `remove_crew` / `sync_crews` | modified | call `self.crew_storage` instead of `self.crew_redis` |
| `parrot.conf` | extended | `CREW_DEFINITION_STORAGE`, `CREW_DEFINITION_PG_DSN`, `CREW_DEFINITION_MIGRATION` |
| `PgUISurfaceStore` | pattern only | DDL list + `ensure_schema` + asyncdb adapter rules (`fetchval` + `RETURNING`, dict for jsonb, `fetch_one`, `fetch_all` → `None`) |
| `CrewHandler` and other `get_crew` consumers | untouched | they only see `BotManager` |

### Data Models
```python
# navigator.crew_definitions (DDL owned by postgres_persistence._DDL_STATEMENTS)
# CREATE SCHEMA IF NOT EXISTS navigator
# CREATE TABLE IF NOT EXISTS navigator.crew_definitions (
#     tenant          TEXT NOT NULL DEFAULT 'global',
#     name            TEXT NOT NULL,
#     crew_id         TEXT NOT NULL,              -- TEXT, not UUID: crew_id is a free str in the model
#     description     TEXT,
#     execution_mode  VARCHAR(32),
#     definition      JSONB NOT NULL,             -- CrewDefinition.model_dump(mode="json")
#     created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
#     updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
#     PRIMARY KEY (tenant, name),
#     CONSTRAINT uq_crew_definitions_tenant_crew_id UNIQUE (tenant, crew_id)
# )

class CrewMigrationReport(BaseModel):
    """Outcome of one Redis → Postgres crew migration sweep (keys are "tenant:name")."""
    dry_run: bool = False
    lock_acquired: bool = True
    skipped_reason: Optional[str] = None
    migrated: List[str] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)
    failed: Dict[str, str] = Field(default_factory=dict)
    redis_cleanup_failed: List[str] = Field(default_factory=list)
```

### New Public Interfaces
See the Interface Skeletons in §3 (M1–M3, M5). Configuration surface:

```python
# parrot.conf (FEAT-860)
CREW_DEFINITION_STORAGE = config.get("CREW_DEFINITION_STORAGE", fallback="redis")      # "redis" | "postgres"
CREW_DEFINITION_PG_DSN = config.get("CREW_DEFINITION_PG_DSN", fallback=default_dsn)
CREW_DEFINITION_MIGRATION = config.getboolean("CREW_DEFINITION_MIGRATION", fallback=False)
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: definition codec | yes | function names/signatures below; bodies moved verbatim from `CrewRedis` | — |
| M2: `CrewPostgres` | yes | DDL in §2 Data Models; `PgUISurfaceStore` asyncdb rules; raise-on-error contract | — |
| M3: `CrewDefinitionStorage` + migration | no | — | error routing and migration ordering are the core design; keep with the thinking model |
| M4: config keys | yes | three exact lines in §2 New Public Interfaces | — |
| M5: `BotManager` wiring | yes | call-site table in §6 Edit Sites; kwargs + attributes below | — |
| M6: documentation | yes | pages in §10; README sections in §6 | — |

### Module 1: Crew definition codec
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/crew/definition_codec.py` (new); modifies
  `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
- **Responsibility**: one implementation of "stored document → `CrewDefinition`" (and back) shared by both
  stores. Behaviour of `CrewRedis` reads stays byte-identical (same log message, same dropped keys).
- **Depends on**: existing `parrot.handlers.crew.models` re-exports
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/handlers/crew/definition_codec.py  (new)
  """Shared (de)serialization of stored CrewDefinition documents (FEAT-860)."""
  import logging
  from typing import Any, Dict
  from .models import AgentDefinition, CrewDefinition, FlowRelation, ToolNodeDefinition  # verified: redis_persistence.py:13, :141-145

  def strip_unknown_keys(crew_dict: Dict[str, Any], crew_id: str, logger: logging.Logger) -> Dict[str, Any]:
      """Drop keys no crew model declares, root and nested (agents, tool_nodes, flow_relations).

      Moved verbatim from CrewRedis._strip_unknown_keys (redis_persistence.py:125-178), including the
      warning text. Returns a copy carrying only declared fields.
      """

  def crew_definition_from_dict(crew_dict: Dict[str, Any], logger: logging.Logger) -> CrewDefinition:
      """Parse ISO ``created_at``/``updated_at`` strings, strip unknown keys, build the model.

      Raises pydantic.ValidationError when the stored document no longer validates.
      """

  def crew_definition_to_document(crew: CrewDefinition) -> Dict[str, Any]:
      """Return ``crew.model_dump(mode="json")`` — the jsonb document stored in Postgres."""

  # packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py  (modifies :125, :180)
  class CrewRedis:
      def _strip_unknown_keys(self, crew_dict: dict, crew_id: str) -> dict:  # verified: redis_persistence.py:125
          """Delegate to definition_codec.strip_unknown_keys(crew_dict, crew_id, self.logger)."""
      def _deserialize_crew(self, data: str) -> CrewDefinition:  # verified: redis_persistence.py:180
          """json.loads(data) → definition_codec.crew_definition_from_dict; keep the error logging and re-raise."""
  ```

### Module 2: `CrewPostgres`
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/crew/postgres_persistence.py` (new)
- **Responsibility**: CRUD over `navigator.crew_definitions`, schema auto-creation, and the migration
  advisory lock. Raises on database errors; `None`/`False` mean "not found".
- **Depends on**: M1, M4 (`CREW_DEFINITION_PG_DSN`)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/handlers/crew/postgres_persistence.py  (new)
  from contextlib import asynccontextmanager
  from typing import AsyncIterator, Dict, List, Optional
  from asyncdb import AsyncDB  # verified: handlers/models/ui_surfaces.py:29
  from parrot.conf import CREW_DEFINITION_PG_DSN  # added by M4
  from .models import CrewDefinition  # verified: redis_persistence.py:13

  TABLE = "navigator.crew_definitions"
  MIGRATION_LOCK_KEY = "parrot:crew_definitions:migration"
  _DDL_STATEMENTS: tuple[str, ...]  # CREATE SCHEMA IF NOT EXISTS navigator; CREATE TABLE IF NOT EXISTS (§2 Data Models)

  class CrewPostgres:
      """Postgres persistence for CrewDefinition documents (navigator.crew_definitions)."""

      def __init__(self, dsn: Optional[str] = None) -> None:
          """dsn or CREW_DEFINITION_PG_DSN; never connects in __init__."""

      @property
      def configured(self) -> bool:
          """True when a DSN resolved (default_dsn may be None)."""

      def _get_db(self) -> AsyncDB:
          """Fresh AsyncDB("pg", dsn=self.dsn) per call (PgUISurfaceStore idiom)."""

      async def ensure_schema(self) -> None:
          """Apply _DDL_STATEMENTS once per instance; tolerate 'already exists' races; raise otherwise."""

      async def ping(self) -> bool:
          """False when not configured or on any error; otherwise runs ensure_schema + SELECT 1 and returns True."""

      async def save_crew(self, crew: CrewDefinition) -> bool:
          """Upsert ON CONFLICT (tenant, name) DO UPDATE; sets crew.updated_at to now (UTC-aware). Raises on DB error."""

      async def insert_if_absent(self, crew: CrewDefinition) -> bool:
          """INSERT ... ON CONFLICT DO NOTHING RETURNING name, keeping the crew's timestamps (naive → UTC).

          True when inserted, False when (tenant, name) already exists. Raises on DB error.
          """

      async def load_crew(self, name: str, tenant: Optional[str] = None) -> Optional[CrewDefinition]:
          """Row → definition_codec.crew_definition_from_dict (jsonb may arrive as dict or str). None if absent."""

      async def load_crew_by_id(self, crew_id: str, tenant: Optional[str] = None) -> Optional[CrewDefinition]:
          """Lookup by (tenant, crew_id). None if absent."""

      async def delete_crew(self, name: str, tenant: Optional[str] = None) -> bool:
          """DELETE ... RETURNING name; True when a row was removed."""

      async def list_all_crews(self) -> List[Dict[str, str]]:
          """[{"tenant": ..., "name": ...}] across tenants (same shape as CrewRedis.list_all_crews)."""

      async def get_all_crews(self, tenant: Optional[str] = None) -> List[CrewDefinition]:
          """All definitions, or one tenant's. A row that fails to deserialize is logged and skipped."""

      @asynccontextmanager
      async def migration_lock(self) -> AsyncIterator[bool]:
          """Hold pg_try_advisory_lock(hashtextextended(MIGRATION_LOCK_KEY, 0)) on a dedicated connection.

          Yields True when acquired (released with pg_advisory_unlock on exit), False when another
          worker holds it.
          """

      async def close(self) -> None:
          """No-op (per-call connections); kept for interface parity with CrewRedis."""
  ```
  Tenant normalization: `None → "global"`, as `CrewRedis._normalize_tenant` (redis_persistence.py:54).

### Module 3: `CrewDefinitionStorage` and the migration
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/crew/definition_storage.py` (new)
- **Responsibility**: the routing rules and the migration in §2; the only crew store `BotManager` calls.
- **Depends on**: M2 (`CrewPostgres`), existing `CrewRedis`
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/handlers/crew/definition_storage.py  (new)
  from typing import Dict, List, Optional
  from pydantic import BaseModel, Field
  from .models import CrewDefinition  # verified: redis_persistence.py:13
  from .postgres_persistence import CrewPostgres  # M2
  from .redis_persistence import CrewRedis  # verified: manager.py:98

  class CrewMigrationReport(BaseModel):
      """See §2 Data Models."""

  class CrewDefinitionStorage:
      """Postgres-primary crew definition storage with a read-only Redis fallback (FEAT-860)."""

      def __init__(self, redis: CrewRedis, postgres: Optional[CrewPostgres] = None, *, migration: bool = False) -> None:
          """postgres=None means Redis-only (CREW_DEFINITION_STORAGE=redis)."""

      @property
      def postgres_active(self) -> bool:
          """True after initialize() found Postgres configured and reachable."""

      async def initialize(self) -> Optional[CrewMigrationReport]:
          """Ping Redis, then Postgres; set postgres_active; warn on degradation; run the migration when enabled.

          Returns the migration report, or None when no migration ran. Never raises.
          """

      async def ping(self) -> bool:
          """True when the active primary (Postgres) or Redis answers."""

      async def save_crew(self, crew: CrewDefinition) -> bool: ...
      async def load_crew(self, name: str, tenant: Optional[str] = None) -> Optional[CrewDefinition]: ...
      async def load_crew_by_id(self, crew_id: str, tenant: Optional[str] = None) -> Optional[CrewDefinition]: ...
      async def delete_crew(self, name: str, tenant: Optional[str] = None) -> bool: ...
      async def list_all_crews(self) -> List[Dict[str, str]]:
          """Union, Postgres wins; raises when Postgres is active and its query fails."""
      async def get_all_crews(self, tenant: Optional[str] = None) -> List[CrewDefinition]: ...

      async def migrate_from_redis(self, *, dry_run: bool = False) -> CrewMigrationReport:
          """Steps 1-5 of the §2 Migration. Never raises; per-crew errors land in report.failed."""

      async def close(self) -> None:
          """Close CrewRedis and CrewPostgres."""
  ```

### Module 4: Configuration keys
- **Path**: `packages/ai-parrot/src/parrot/conf.py` (modifies, after line 316)
- **Responsibility**: the three keys in §2 New Public Interfaces, under a `# Crew definition storage
  (FEAT-860)` comment, right after the `CREW_RESULT_STORAGE*` block.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/conf.py  (modifies :316)
  CREW_RESULT_STORAGE_REDIS_TTL = int(config.get("CREW_RESULT_STORAGE_REDIS_TTL", fallback=604800))  # verified: conf.py:316
  # Crew definition storage (FEAT-860)
  CREW_DEFINITION_STORAGE: str   # "redis" (default) | "postgres"
  CREW_DEFINITION_PG_DSN: Optional[str]   # fallback default_dsn (conf.py:72/76)
  CREW_DEFINITION_MIGRATION: bool   # fallback False
  ```

### Module 5: `BotManager` wiring
- **Path**: `packages/ai-parrot-server/src/parrot/manager/manager.py` (modifies);
  `packages/ai-parrot/tests/test_botmanager_flags.py` (modifies)
- **Responsibility**: construct the stores from config/kwargs and route every crew persistence call
  through `self.crew_storage`; run `initialize()` from `load_crews`.
- **Depends on**: M3, M4
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/manager/manager.py  (modifies :98, :102-112, :227-271, :3255-3555)
  from ..handlers.crew.redis_persistence import CrewRedis  # verified: manager.py:98 (unchanged)
  from ..handlers.crew.postgres_persistence import CrewPostgres  # new
  from ..handlers.crew.definition_storage import CrewDefinitionStorage  # new
  from ..conf import (..., CREW_DEFINITION_MIGRATION, CREW_DEFINITION_STORAGE, ...)  # verified block: manager.py:102-112

  class BotManager:  # verified: manager.py:217
      def __init__(
          self,
          enable_database_bots: bool = ENABLE_DATABASE_BOTS,
          enable_crews: bool = ENABLE_CREWS,
          enable_registry_bots: bool = ENABLE_REGISTRY_BOTS,
          enable_experts: bool = True,
          enable_swagger_api: bool = ENABLE_SWAGGER,
          crew_storage_backend: Optional[str] = None,   # new — overrides CREW_DEFINITION_STORAGE
          crew_migration: Optional[bool] = None,        # new — overrides CREW_DEFINITION_MIGRATION
      ) -> None:  # verified: manager.py:227-234
          """... Unknown backend value → warning, "redis"."""
          # self.crew_storage_backend: str ; self.crew_migration: bool
          # self.crew_redis = CrewRedis() if self.enable_crews else None          # verified: manager.py:271 (unchanged)
          # self.crew_postgres: Optional[CrewPostgres] = CrewPostgres() if enable_crews and backend == "postgres" else None
          # self.crew_storage: Optional[CrewDefinitionStorage] = CrewDefinitionStorage(
          #     self.crew_redis, self.crew_postgres, migration=self.crew_migration) if self.enable_crews else None

      async def load_crews(self) -> None:  # verified: manager.py:3457
          """initialize() (logs the migration report summary), then get_all_crews(); same in-memory caching."""
  ```
  Call-site replacements (all in `manager.py`): `self.crew_redis.save_crew` (3284), `.load_crew`
  (3342, 3534), `.load_crew_by_id` (3345), `.delete_crew` (3422), `.ping` (3469 → `initialize()` then
  `ping()`), `.get_all_crews` (3474), `.list_all_crews` (3517) → `self.crew_storage.<same method>`; the five
  `if self.crew_redis is None:` guards (3276, 3337, 3415, 3464, 3512) → `if self.crew_storage is None:`.
  Log/docstring text that says "Redis" in these methods says "crew storage".

### Module 6: Documentation
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/crew/README_BOTMANAGER_PERSISTENCE.md`,
  `packages/ai-parrot-server/src/parrot/handlers/crew/README_REDIS_PERSISTENCE.md` (modify);
  `wiki/bots/orchestration/crew-definition-storage.md` (create); `wiki/bots/crew_handler.md` (modify)
- **Responsibility**: fix the stale pre-tenant key layout in both READMEs (`crew:{tenant}:{name}`,
  `crew:{tenant}:list`, `crew:tenants`, `crew:{tenant}:id:{crew_id}`; legacy keys read for `global` only);
  document the three config keys, the routing table, the migration and its report, and degraded mode.
- **Depends on**: none (names fixed by this spec)

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_strip_unknown_keys_root_and_nested` | M1 | root + agents/tool_nodes/flow_relations keys dropped, warning logged |
| `test_from_dict_parses_iso_timestamps` | M1 | ISO strings become datetimes; model validated |
| `test_to_document_round_trip` | M1 | `crew_definition_from_dict(crew_definition_to_document(c))` equals `c` |
| existing `test_crew_redis_legacy_payloads.py` | M1 | unchanged, still passes through the delegates |
| `test_ensure_schema_idempotent` | M2 | DDL applied once; "already exists" tolerated |
| `test_save_upserts_and_bumps_updated_at` | M2 | second save updates the row; `updated_at` UTC-aware |
| `test_insert_if_absent_true_then_false` | M2 | first insert True, second False; timestamps preserved (naive → UTC) |
| `test_load_by_name_and_by_id` | M2 | tenant-scoped lookups; `None` tenant → `global`; absent → `None` |
| `test_jsonb_str_or_dict` | M2 | a `definition` returned as `str` or `dict` both deserialize |
| `test_delete_returns_false_when_absent` | M2 | `DELETE ... RETURNING` semantics |
| `test_ping_false_without_dsn` | M2 | `configured` False → `ping()` False, no connection attempted |
| `test_migration_lock_yields_false_when_held` | M2 | try-lock False → no unlock call |
| `test_redis_only_mode_delegates` | M3 | `postgres=None` → every call hits `CrewRedis` only |
| `test_degraded_when_postgres_unreachable` | M3 | ping False → warning, Redis-only, migration skipped |
| `test_read_prefers_postgres_then_redis` | M3 | Postgres hit wins; miss or error → Redis |
| `test_save_falls_back_to_redis_on_error` | M3 | Postgres raises → warning + `CrewRedis.save_crew` |
| `test_delete_hits_both_stores` | M3 | both deletes run; Postgres error still deletes Redis |
| `test_list_union_postgres_wins` / `test_list_raises_on_postgres_error` | M3 | union dedupe; raise propagates |
| `test_get_all_degrades_on_postgres_error` | M3 | Redis-only result + warning |
| `test_migration_copy_verify_delete` | M3 | inserted + verified → Redis deleted, `migrated` |
| `test_migration_conflict_postgres_wins` | M3 | existing row kept, Redis copy deleted, `conflicts` |
| `test_migration_verification_mismatch_keeps_redis` | M3 | mismatch → `failed`, no Redis delete |
| `test_migration_per_crew_failure_isolated` | M3 | one insert raises; others migrate |
| `test_migration_dry_run_writes_nothing` | M3 | no insert/delete calls |
| `test_migration_lock_not_acquired_skips` | M3 | `lock_acquired=False`, nothing touched |
| `test_migration_idempotent_rerun` | M3 | second run: nothing left in Redis, empty report |
| `test_enable_crews_true_creates_crew_redis` (updated) | M5 | also asserts `crew_storage` built, `crew_postgres is None` by default |
| `test_postgres_backend_builds_crew_postgres` | M5 | `crew_storage_backend="postgres"` constructs `CrewPostgres` |
| `test_unknown_backend_warns_and_uses_redis` | M5 | invalid value → warning, Redis-only |
| `test_load_crews_initializes_then_loads` | M5 | `initialize()` before `get_all_crews()`; crews cached by `tenant:name` |
| `test_crud_routes_through_crew_storage` | M5 | `add_crew`/`get_crew`/`remove_crew`/`sync_crews` call `crew_storage` |

### Integration Tests
| Test | Description |
|---|---|
| `test_crew_postgres_round_trip_live` | real Postgres (skips unless `NAVIGATOR_PG_DSN` is set): ensure_schema, save, load, list, delete, advisory lock |

### Validation Contract

tests:
- packages/ai-parrot-server/tests/unit/test_crew_redis_legacy_payloads.py
- packages/ai-parrot-server/tests/unit/test_crew_definition_codec.py
- packages/ai-parrot-server/tests/unit/test_crew_postgres_store.py
- packages/ai-parrot-server/tests/unit/test_crew_definition_storage.py
- packages/ai-parrot-server/tests/manager/test_crew_storage_wiring.py
- packages/ai-parrot-server/tests/handlers/test_crew_postgres_store_live.py
- packages/ai-parrot/tests/test_botmanager_flags.py
markers: none

### Test Data / Fixtures

> Unit tests never touch a real database or Redis: `CrewPostgres` tests monkeypatch `_get_db` with an
> in-memory fake AsyncDB (the `_FakeAsyncDB` pattern of `tests/handlers/test_ui_surfaces_store.py`);
> `CrewDefinitionStorage` tests use `AsyncMock(spec=CrewRedis)` / `AsyncMock(spec=CrewPostgres)`.
> The live test follows `tests/handlers/test_ui_surfaces_store_live.py` (module-level skipif on
> `NAVIGATOR_PG_DSN`) and uses a unique tenant per run, deleting its rows afterwards.

```python
@pytest.fixture
def crew_def() -> CrewDefinition:
    return CrewDefinition(
        name="research-crew",
        tenant="acme",
        agents=[AgentDefinition(agent_id="writer", config={"llm": "google:gemini-3.5-flash"})],
    )
```

---

## 5. Acceptance Criteria

- [ ] With `CREW_DEFINITION_STORAGE` unset, `BotManager` builds no `CrewPostgres` and every crew persistence
      call reaches `CrewRedis` exactly as before (existing crew tests pass unchanged).
- [ ] With `CREW_DEFINITION_STORAGE=postgres`, startup creates `navigator.crew_definitions` if missing
      (idempotent across workers) and rehydrates crews from it through `BotManager.load_crews`.
- [ ] The table has `PRIMARY KEY (tenant, name)`, `UNIQUE (tenant, crew_id)` and a `jsonb` `definition`
      column holding `CrewDefinition.model_dump(mode="json")`.
- [ ] Postgres always wins: a `(tenant, name)` present in Postgres is never read from Redis, never
      overwritten by the migration, and its Redis copy is deleted by the migration.
- [ ] Redis is consulted for reads only when Postgres lacks the crew or the Postgres read fails.
- [ ] `delete_crew` removes the crew from Postgres and Redis, so the fallback cannot resurrect it.
- [ ] With `migration=True`, each Redis crew is copied, re-read and compared before its Redis keys are
      deleted; a failed or mismatched crew stays in Redis and appears in `CrewMigrationReport.failed`.
- [ ] Only one worker runs the migration (`pg_try_advisory_lock`); others skip with `lock_acquired=False`.
- [ ] Re-running the migration is idempotent; `dry_run=True` writes and deletes nothing.
- [ ] No DSN or unreachable Postgres at startup: startup continues on Redis with a warning that names the
      cause; the migration is skipped and no Redis key is deleted.
- [ ] A Postgres write error at runtime falls back to `CrewRedis.save_crew` with a warning.
- [ ] `CrewRedis` legacy-payload behaviour is unchanged (`test_crew_redis_legacy_payloads.py` passes).
- [ ] `creation.sql` and `BotManager._load_database_bots` are byte-identical
      (`packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py::test_load_database_bots_untouched`).
- [ ] All tests in the §4 Validation Contract pass; `ruff check` is clean on the changed files.
- [ ] Documentation pages declared in §10 exist under `wiki/` (`parrot sdd techwiki check`), and both
      READMEs show the tenant-scoped key layout.

---

## 6. Codebase Contract

> Verified against origin/dev `00108348b4` (code identical to `291baf5686` for every file below).

### Verified Imports
```python
from parrot.handlers.crew.redis_persistence import CrewRedis  # verified: manager.py:98 (as ..handlers.crew.redis_persistence)
from parrot.handlers.crew.models import CrewDefinition  # verified: redis_persistence.py:13 (from .models); re-export handlers/crew/models.py:7-22
from parrot.handlers.crew.models import AgentDefinition, FlowRelation, ToolNodeDefinition  # verified: redis_persistence.py:141-145
from asyncdb import AsyncDB  # verified: handlers/models/ui_surfaces.py:29
from parrot.conf import default_dsn  # verified: ui_surfaces.py:30; defined conf.py:72 / :76 (None without DBUSER)
from parrot.conf import ENABLE_CREWS  # verified: conf.py:96; imported by manager.py:104
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py
class CrewRedis:  # line 17
    def __init__(self, redis_url: str = None, key_prefix: str = "crew", db: int = 2):  # line 20; db 2, URL from REDIS_HOST/REDIS_PORT
    self.logger = logging.getLogger('CrewRedis')  # line 34
    @staticmethod
    def _normalize_tenant(tenant: Optional[str]) -> str:  # line 54 — tenant or "global"
    def _serialize_crew(self, crew: CrewDefinition) -> str:  # line 100 — model_dump(mode='json') + json.dumps
    def _strip_unknown_keys(self, crew_dict: dict, crew_id: str) -> dict:  # line 125
    def _deserialize_crew(self, data: str) -> CrewDefinition:  # line 180
    async def save_crew(self, crew: CrewDefinition) -> bool:  # line 220 — sets crew.updated_at = datetime.utcnow() (235); returns False on error, never raises
    async def load_crew(self, name: str, tenant: Optional[str] = None) -> Optional[CrewDefinition]:  # line 262 — legacy key for "global"
    async def load_crew_by_id(self, crew_id: str, tenant: Optional[str] = None) -> Optional[CrewDefinition]:  # line 292
    async def delete_crew(self, name: str, tenant: Optional[str] = None) -> bool:  # line 328 — also legacy keys + id mapping for "global"
    async def list_all_crews(self) -> List[Dict[str, str]]:  # line 397 — legacy names folded into "global"
    async def get_all_crews(self, tenant: Optional[str] = None) -> List[CrewDefinition]:  # line 444 — tenant=None → all tenants
    async def ping(self) -> bool:  # line 546
    async def close(self):  # line 560

# packages/ai-parrot/src/parrot/models/crew_definition.py
class AgentDefinition(BaseModel):  # line 31 — extra="forbid"; config: Dict[str, Any]
class CrewDefinition(BaseModel):  # line 178; crew_id: str uuid4 default (216); tenant: str = "global" (220); name: str (224)
    model_config = ConfigDict(extra="forbid", ...)  # lines 306-309
    # created_at / updated_at default datetime.now(timezone.utc)

# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:  # line 217
    def __init__(self, enable_database_bots: bool = ENABLE_DATABASE_BOTS, enable_crews: bool = ENABLE_CREWS,
                 enable_registry_bots: bool = ENABLE_REGISTRY_BOTS, enable_experts: bool = True,
                 enable_swagger_api: bool = ENABLE_SWAGGER) -> None:  # lines 227-234
    self._crews: Dict[str, Tuple[AgentCrew, CrewDefinition]]  # line 263, key "tenant:name"
    self.crew_redis = CrewRedis() if self.enable_crews else None  # line 271
    def _get_crew_key(self, tenant: str, name: str) -> str:  # line 284
    async def on_startup(self, app: web.Application) -> None:  # line 3160 — calls load_crews() at 3193-3194 when enable_crews
    async def add_crew(self, name: str, crew: AgentCrew, crew_def: CrewDefinition) -> None:  # line 3255
    async def get_crew(self, identifier: str, as_new: bool = False, tenant: Optional[str] = None) -> Optional[Tuple[AgentCrew, CrewDefinition]]:  # line 3294
    async def remove_crew(self, identifier: str, tenant: Optional[str] = None) -> bool:  # line 3383
    async def load_crews(self) -> None:  # line 3457
    async def sync_crews(self) -> None:  # line 3504
    async def _create_crew_from_definition(self, crew_def: CrewDefinition) -> AgentCrew:  # line 3557

# packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py (pattern only — do not import)
async def _exec(conn: Any, sql: str, *args: Any) -> None:  # line 438 — execute() returns [result, error] instead of raising
class PgUISurfaceStore:  # line 457
    def _get_db(self) -> AsyncDB:  # line 474
    async def ensure_schema(self) -> None:  # line 483 — tolerates "already exists"
    # asyncdb pg adapter rules: lines 396-415 (fetchval + RETURNING raises; pass dict for jsonb, never json.dumps;
    # fetch_one for one row; fetch_all returns None for empty; uuid params must be uuid.UUID)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `CrewRedis._deserialize_crew` | `definition_codec.crew_definition_from_dict` | delegation | `redis_persistence.py:180` |
| `CrewDefinitionStorage` | `CrewRedis.save_crew/load_crew/load_crew_by_id/delete_crew/list_all_crews/get_all_crews/ping` | method calls | `redis_persistence.py:220-560` |
| `BotManager.__init__` | `CrewDefinitionStorage(...)` | construction next to `crew_redis` | `manager.py:271` |
| `BotManager.load_crews` | `CrewDefinitionStorage.initialize()` + `get_all_crews()` | replaces `ping()` / `get_all_crews()` | `manager.py:3469`, `:3474` |
| `BotManager.add_crew` | `CrewDefinitionStorage.save_crew` | replaces `crew_redis.save_crew` | `manager.py:3284` |
| `BotManager.get_crew` | `CrewDefinitionStorage.load_crew` / `load_crew_by_id` | replaces | `manager.py:3342`, `:3345` |
| `BotManager.remove_crew` | `CrewDefinitionStorage.delete_crew` | replaces | `manager.py:3422` |
| `BotManager.sync_crews` | `CrewDefinitionStorage.list_all_crews` / `load_crew` | replaces | `manager.py:3517`, `:3534` |

### Does NOT Exist (Anti-Hallucination)
- ~~`navigator.crew_definitions`~~ — no table, DDL or reference anywhere in `packages/` (probe: `crew_definitions` absent).
- ~~`CREW_DEFINITION_STORAGE` / `CREW_DEFINITION_PG_DSN` / `CREW_DEFINITION_MIGRATION`~~ — not in `parrot.conf` (added by M4).
- ~~A crew-store base class / protocol~~ — `CrewRedis` has no base class; do not invent `AbstractCrewStorage`.
- ~~`migration=` flag or Redis → Postgres copy routine~~ — none exists anywhere (`recipes/migrate.py::migrate_store` is only a pattern).
- ~~`CrewRedis.crew_exists` / `list_crews` / `get_crew_metadata` / `update_crew_metadata` as BotManager calls~~ — they exist on `CrewRedis` but `BotManager` never calls them; `CrewPostgres` does not implement them.
- ~~Reusing `PostgresResultStorage._ensure_table`~~ — its `_TABLE_RE` (`backends/postgres.py:19`) rejects `navigator.crew_definitions`.
- ~~`app["database"]` inside `BotManager.__init__`~~ — the pool does not exist yet; `CrewPostgres` must use a DSN.
- ~~`conn.fetchrow(sql, ...)` for a one-row query~~ — on the asyncdb pg driver that is the cursor method; use `fetch_one`.

### Edit Sites (Blueprint Anchors)

Verified against: `00108348b4`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/crew/definition_codec.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/crew/postgres_persistence.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/crew/definition_storage.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py` | MODIFY | `    def _strip_unknown_keys(self, crew_dict: dict, crew_id: str) -> dict:` | `redis_persistence.py:125` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py` | MODIFY | `    def _deserialize_crew(self, data: str) -> CrewDefinition:` | `redis_persistence.py:180` | 1 |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `CREW_RESULT_STORAGE_REDIS_TTL = int(config.get("CREW_RESULT_STORAGE_REDIS_TTL", fallback=604800))` | `conf.py:316` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `from ..handlers.crew.redis_persistence import CrewRedis` | `manager.py:98` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `    ENABLE_CREWS,` | `manager.py:104` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `        self.crew_redis = CrewRedis() if self.enable_crews else None` | `manager.py:271` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `    async def add_crew(self, name: str, crew: AgentCrew, crew_def: CrewDefinition) -> None:` | `manager.py:3255` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `    async def get_crew(` | `manager.py:3294` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `    async def remove_crew(self, identifier: str, tenant: Optional[str] = None) -> bool:` | `manager.py:3383` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `    async def load_crews(self) -> None:` | `manager.py:3457` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `    async def sync_crews(self) -> None:` | `manager.py:3504` | 1 |
| `packages/ai-parrot/tests/test_botmanager_flags.py` | MODIFY | `def test_enable_crews_true_creates_crew_redis():` | `test_botmanager_flags.py:186` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/crew/README_BOTMANAGER_PERSISTENCE.md` | MODIFY | `## Key Format` (also `## Migration`, :256) | `README_BOTMANAGER_PERSISTENCE.md:32` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/crew/README_REDIS_PERSISTENCE.md` | MODIFY | `## Key Format` | `README_REDIS_PERSISTENCE.md:161` | 1 |
| `wiki/bots/crew_handler.md` | MODIFY | `The key is never stored in a \`CrewDefinition\`, so it never reaches Redis and never appears in \`GET /api/v1/crew\`, and it is never logged.` | `crew_handler.md:602` | 1 |
| `wiki/bots/orchestration/crew-definition-storage.md` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/unit/test_crew_definition_codec.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/unit/test_crew_postgres_store.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/unit/test_crew_definition_storage.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/manager/test_crew_storage_wiring.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/handlers/test_crew_postgres_store_live.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- `PgUISurfaceStore` (`handlers/models/ui_surfaces.py`): `_DDL_STATEMENTS` list, `ensure_schema()` race
  tolerance, `AsyncDB("pg", dsn=...)` per call, and the asyncdb adapter rules at lines 396-415.
- `migrate_store` (`parrot/outputs/a2ui/recipes/migrate.py:101`): per-item `try/except` into a report,
  idempotent, `dry_run` never writes.
- Advisory locks with `hashtextextended(<key>, 0)` as in `knowledge/contracts/catalog_postgres.py:397`;
  here a **session** lock (`pg_try_advisory_lock` / `pg_advisory_unlock`) held on one connection for the
  whole sweep, so the sweep's own writes may use other connections.
- Conf flag + constructor override, as the FEAT-042 `BotManager` flags (`test_defaults_match_config`).
- Logging through `self.logger`, `%`-style arguments; never `print`.

### Known Risks / Gotchas
- **Edits lost to the conflict rule.** A crew saved to Redis by the runtime write fallback while its row
  already exists in Postgres is discarded by the next migration (Postgres wins, Redis copy deleted).
  Mitigation: the migration logs every conflict key at warning level and lists it in the report.
- **`CrewRedis.save_crew` never raises** (returns `False`), so `BotManager.add_crew`'s `except` branch never
  fires for it; `CrewDefinitionStorage.save_crew` must check the returned bool on the Redis path.
- **asyncdb `execute()` swallows errors** — every write in `CrewPostgres` goes through `fetchval` on a
  `RETURNING` clause; DDL goes through an `_exec`-style helper that raises.
- **Timestamps.** `CrewRedis` writes naive `datetime.utcnow()` (redis_persistence.py:235, :538); convert
  naive values to UTC-aware before writing `timestamptz`. The verification compare excludes timestamps.
- **`crew_id` is a free `str`** — keep the column `TEXT`; the driver's uuid codec rejects `str` values.
- **`sync_crews` and outages.** `list_all_crews` must raise (not return `[]`) when the Postgres query fails,
  or `sync_crews` would evict every cached crew.
- **Multi-worker startup.** Workers that lose the migration lock start immediately; crews not yet moved are
  served by the Redis fallback, so no request sees a missing crew.
- **Tests pin `bm.crew_redis`** and patch `parrot.manager.manager.CrewRedis`; keep both and add patch targets
  `parrot.manager.manager.CrewPostgres` / `CrewDefinitionStorage`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `asyncdb` | already a dependency | pg driver used by `PgUISurfaceStore` |

---

## Decisions

```yaml
schema_version: 1
document_id: postgres-crew-storage
entries:
  - id: crew-definitions-postgres-primary
    statement: With CREW_DEFINITION_STORAGE=postgres, navigator.crew_definitions is the source of truth for crew definitions; Redis is read only for a (tenant, name) Postgres does not have or cannot answer, and Postgres always wins a conflict.
    relation: constrains
    about: [bots, server]
    targets: [sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.load_crews, sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.get_crew]
    contradicts: []
    supersedes: []
    rationale: "One primary store avoids Redis/Postgres divergence through sync_crews; the read fallback covers crews not migrated yet."
    rejected_alternatives: ["dual-write to both stores", "Postgres-only with no Redis fallback"]
  - id: crew-migration-verify-before-delete
    statement: The Redis to Postgres crew migration deletes a crew's Redis keys only after re-reading it from Postgres and finding the same definition, or after finding a pre-existing Postgres row; a failed or mismatched crew stays in Redis.
    relation: requires
    about: [bots, server]
    targets: [sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.load_crews]
    contradicts: []
    supersedes: []
    rationale: "Persistence errors are swallowed in this code path, so a delete without a verified copy could lose crews."
    rejected_alternatives: ["copy and keep Redis", "copy and mark Redis keys as migrated"]
  - id: crew-storage-degrades-to-redis
    statement: An unavailable Postgres (no DSN, unreachable at startup, or a failed write) never stops crew persistence; crew definition storage degrades to Redis with a warning instead of failing closed.
    relation: constrains
    about: [bots, server]
    targets: [sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.add_crew]
    contradicts: []
    supersedes: []
    rationale: "Crews must keep working through a database outage; the next migration reconciles."
    rejected_alternatives: ["fail closed at startup (Agent Studio store switches)"]
```

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:4f0464521ac6d1e1b5e78a83973b790ad7c21d269b04cc79ad2d4d85985eac9c evaluation_digest=sha256:e7e3885e7f45eea36feca2d2e992e3ce165859d8d9659f8be09e9db19dd36874 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:postgres-crew-storage#crew-migration-verify-before-delete@1; scope: sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.load_crews; message: sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.load_crews impacts 3 dependent(s): sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.on_startup, sym:packages/ai-parrot/tests/test_botmanager_flags.py#test_enable_crews_false_skips_load_crews, sym:packages/ai-parrot/tests/test_botmanager_flags.py#test_enable_crews_true_calls_load_crews
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:postgres-crew-storage#crew-storage-degrades-to-redis@1; scope: sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.add_crew; message: sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.add_crew impacts 2 dependent(s): sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler.put, sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler.upload
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:postgres-crew-storage#crew-definitions-postgres-primary@1; scope: sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.load_crews; message: sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.load_crews impacts 3 dependent(s): sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.on_startup, sym:packages/ai-parrot/tests/test_botmanager_flags.py#test_enable_crews_false_skips_load_crews, sym:packages/ai-parrot/tests/test_botmanager_flags.py#test_enable_crews_true_calls_load_crews

Diagnostics:
- none

Coverage:
- Subsystems: auth, bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: crew, migration, persistence, postgres, redis
- Targets resolved: 3/3
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "auth",
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "server",
      "skills",
      "tools"
    ],
    "targets_resolved": 3,
    "targets_total": 3,
    "unmapped_tags": [
      "crew",
      "migration",
      "persistence",
      "postgres",
      "redis"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:e7e3885e7f45eea36feca2d2e992e3ce165859d8d9659f8be09e9db19dd36874",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:03b02a05dbbbefa7f735707d7efb20fddbe1695893966d27b7cd39aeeae67e1e",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.load_crews impacts 3 dependent(s): sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.on_startup, sym:packages/ai-parrot/tests/test_botmanager_flags.py#test_enable_crews_false_skips_load_crews, sym:packages/ai-parrot/tests/test_botmanager_flags.py#test_enable_crews_true_calls_load_crews",
      "participants": [
        {
          "decision_id": "adr:spec:postgres-crew-storage#crew-migration-verify-before-delete",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.load_crews"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:e93245c97e9dd84b3af0ed2ae566dc959771e5ec6c6059542d414f8d131f607a",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.add_crew impacts 2 dependent(s): sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler.put, sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler.upload",
      "participants": [
        {
          "decision_id": "adr:spec:postgres-crew-storage#crew-storage-degrades-to-redis",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.add_crew"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:f78fee10d441c875357511ee6a5a50782adf3226d73f47bb7ea37c7580c288e8",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.load_crews impacts 3 dependent(s): sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.on_startup, sym:packages/ai-parrot/tests/test_botmanager_flags.py#test_enable_crews_false_skips_load_crews, sym:packages/ai-parrot/tests/test_botmanager_flags.py#test_enable_crews_true_calls_load_crews",
      "participants": [
        {
          "decision_id": "adr:spec:postgres-crew-storage#crew-definitions-postgres-primary",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.load_crews"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:4f0464521ac6d1e1b5e78a83973b790ad7c21d269b04cc79ad2d4d85985eac9c",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:9dbc3d390bf45b1fb39b09ddec827da2b79cf35e6cadef75648652793cca7e60",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Source of truth once Postgres is enabled — *Resolved in proposal (U1)*: Postgres primary for reads and
      writes; Redis is a read-only fallback for crews not yet migrated.
- [x] What "mover" means — *Resolved in proposal (U2)*: copy, re-read each crew from Postgres to verify it,
      then delete its Redis keys.
- [x] Where the migration runs — *Resolved in proposal (U3)*: in `BotManager.load_crews` at startup when
      `migration=True`, serialized with a pg advisory lock, idempotent.
- [x] How the table is created — *Resolved in proposal (U4)*: the store auto-creates it
      (`CREATE SCHEMA/TABLE IF NOT EXISTS`, `PgUISurfaceStore` idiom).
- [x] Where the flags live and which DSN — *Resolved in proposal (U5)*: `parrot.conf` keys overridable by
      kwargs; DSN `CREW_DEFINITION_PG_DSN` falling back to `default_dsn`.
- [x] Migration conflict — *Resolved in proposal (U6)*: Postgres always wins; if the crew exists in Postgres,
      that row is used. *Resolved at spec time*: the Redis copy is deleted.
- [x] Postgres unreachable or no DSN — *Resolved in proposal (U7)*: keep serving from Redis with a clear
      warning; skip the migration.
- [x] Runtime write failure while Postgres is active — *Resolved at spec time*: fall back to
      `CrewRedis.save_crew` with a warning.
- [x] Default backend — *Resolved at spec time*: `CREW_DEFINITION_STORAGE` defaults to `redis` (opt-in).

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (exploration doc `sdd/proposals/postgres-crew-storage.proposal.md` has
> `status: review`, not `accepted`) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/bots/orchestration/crew-definition-storage.md` — create: backends, config keys, routing table,
    migration flow and report, degraded mode, table DDL.
  - `wiki/bots/crew_handler.md` — update: the persistence note (line 602) names the crew definition store
    instead of Redis only.
- **API modules**:
  - `parrot.handlers.crew.definition_codec`
  - `parrot.handlers.crew.postgres_persistence`
  - `parrot.handlers.crew.definition_storage`

---

## Worktree Strategy

- **Isolation**: one feature worktree (`feat-FEAT-860-postgres-crew-storage`); the `sdd-coder` engine gives
  each task its own sub-worktree.
- **Module dependency graph**:
  - M2 → M1 (`CrewPostgres.load_crew` uses `definition_codec.crew_definition_from_dict`)
  - M2 → M4 (`CREW_DEFINITION_PG_DSN` default)
  - M3 → M2 (`CrewDefinitionStorage` composes `CrewPostgres`)
  - M5 → M3, M4 (`BotManager` builds `CrewDefinitionStorage`, reads the new conf keys)
  - M1, M4 and M6 have no incoming edges and can run concurrently.
- **Shared files**: none — each file belongs to one module.
- **Exclusive resources**: none (the live test is skip-gated; no schema migration runs in CI).
- **Cross-feature dependencies**: none.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-09 | Jesus Lara | Initial draft from proposal FEAT-860 (U1–U7) + spec-time answers |
