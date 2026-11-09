---
title: Crew Definition Storage
summary: Postgres authority, Redis fallback, tombstones and safe crew migration.
---

# Crew Definition Storage

## Purpose

Crew definition storage persists the configuration used to reconstruct an `AgentCrew`. It is separate from crew
execution-result storage and its `CREW_RESULT_STORAGE*` settings. Definition storage remains opt-in: the default
backend is Redis, while `postgres` mode makes PostgreSQL authoritative for acknowledged writes and durable deletes.

## Public API

- [`CrewPostgres`](ref:parrot.handlers.crew.postgres_persistence.CrewPostgres) — stores active definitions and
  deletion tombstones in PostgreSQL.
- [`CrewDefinitionStorage`](ref:parrot.handlers.crew.definition_storage.CrewDefinitionStorage) — routes definition
  operations to the configured authority and performs safe Redis migration.
- [`crew_definition_from_dict`](ref:parrot.handlers.crew.definition_codec.crew_definition_from_dict) — validates a
  stored document as a `CrewDefinition`, including legacy timestamp and unknown-key compatibility.

## Configuration & Parameters

The application configuration accepts these environment-backed keys:

| Key | Default | Meaning |
|---|---|---|
| `CREW_DEFINITION_STORAGE` | `redis` | Definition authority: `redis` or `postgres`. An unknown value warns and selects Redis. |
| `CREW_DEFINITION_PG_DSN` | the main database DSN, when configured | PostgreSQL DSN used by `CrewPostgres`. |
| `CREW_DEFINITION_MIGRATION` | `false` | Run a Redis-to-Postgres migration sweep during initialization when both services are healthy. |

`BotManager(crew_storage_backend=..., crew_migration=...)` can override the backend and migration flag for one
manager. The DSN remains application configuration. Crew storage is constructed only when `enable_crews=True`.
Selecting `postgres` without a usable DSN remains PostgreSQL mode but unavailable; it never silently routes writes
to Redis.

## Usage Examples

Configure PostgreSQL as the authority before starting the server:

```bash
export CREW_DEFINITION_STORAGE=postgres
export CREW_DEFINITION_PG_DSN='postgres://app:secret@postgres.example/parrot'
export CREW_DEFINITION_MIGRATION=false
```

PostgreSQL must be reachable for authoritative reads and writes. Redis must also be reachable for migration and for
legacy fallback candidates that PostgreSQL has confirmed do not conflict with a stored name or ID.

Inspect migration without changing PostgreSQL or Redis:

```python
from parrot.manager.manager import BotManager

manager = BotManager(enable_crews=True, crew_storage_backend="postgres", crew_migration=False)
storage = manager.crew_storage
assert storage is not None
report = await storage.migrate_from_redis(dry_run=True)

if report.skipped_reason:
    raise RuntimeError(report.skipped_reason)
migration_summary = report.model_dump()
```

`migrated` predicts or records newly inserted and cleaned definitions; `already_present` records equal definitions;
`deleted_sources` records stale sources suppressed by tombstones; `conflicts` and `failed` require operator
reconciliation; `redis_cleanup_failed` means PostgreSQL is authoritative but the verified source could not be
removed. A dry run can acquire the advisory lock but performs no schema creation, row write, or Redis mutation.

After reviewing the dry run, enable startup migration with `CREW_DEFINITION_MIGRATION=true`, or call
`migrate_from_redis()` without `dry_run`. Live migration safety depends on real PostgreSQL and Redis behavior;
mock-only or skipped live tests do not prove destructive cleanup safety.

## Gotchas

- PostgreSQL mode fails closed. An outage or malformed authoritative row is not absence; the crew definition
  endpoints (create, read, update, delete) return `503` for storage failures and `409` for identity conflicts. Other
  callers of `BotManager.get_crew` (execution, saved executions, the orchestrator and the scheduler) do not map these
  typed errors yet, so they surface as their own generic failures.
- PostgreSQL reserves both `(tenant, name)` and `(tenant, crew_id)`. Redis fallback is allowed only when both
  identities are confirmed absent from PostgreSQL.
- Deletes commit a tombstone before cache eviction or best-effort Redis cleanup. Tombstones are not auto-purged,
  because a legacy Redis copy could otherwise become visible again.
- Migration retains unreadable, conflicting, concurrently changed, or cleanup-failed Redis sources for operator
  reconciliation. Never unconditionally purge them.
- PostgreSQL updates are same-name only. Rename requests are rejected with `409` before mutation.
- Upgrade all workers before relying on PostgreSQL acknowledged-write behavior; older Redis-only workers retain the
  legacy best-effort semantics.
- Conditional Redis cleanup requires a single-instance Redis deployment. Redis Cluster cross-slot cleanup is
  rejected.
- The live migration safety gate requires explicitly configured PostgreSQL and an isolated Redis database; a skipped
  live test is only a skip, not evidence that cleanup is safe.

## Related

- [Crew handler](../crew_handler.md) — HTTP behavior and error responses.
