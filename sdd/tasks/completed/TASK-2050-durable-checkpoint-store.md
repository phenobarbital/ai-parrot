# TASK-2050: DurableCheckpointStore — sqlite | postgres | mongodb (asyncdb)

**Feature**: FEAT-399 — AgentsFlow State Checkpointing (Two-Tier Persistence)
**Spec**: `sdd/specs/agentsflow-state-checkpointing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2046, TASK-2047, TASK-2048
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 — the durable tier (resolved: all three backends in v1).
Suspended flows are dumped here for indefinite recovery; `durable=True` flows
write-through on every checkpoint. One asyncdb-parametrized implementation
covering `sqlite`, `pg`, `mongodb` drivers (FEAT-147 backend pattern).

---

## Scope

- Implement `store/durable.py`: `DurableCheckpointStore(CheckpointStore)`
  parametrized by asyncdb driver name (`"sqlite" | "pg" | "mongodb"`), plus
  three thin aliases the factory maps names to (or a `driver=` constructor
  arg — follow whichever shape `get_checkpoint_store` from TASK-2048 expects).
- Storage model: one row/document per checkpoint keyed
  `(flow_id, checkpoint_id)` with columns/fields: `flow_id`, `checkpoint_id`,
  `parent_checkpoint_id`, `status`, `flow_name`, `created_at`, `lossy`,
  `payload` (ormsgpack bytes / BLOB / binary). SQL DDL auto-created on first
  use (`CREATE TABLE IF NOT EXISTS flow_checkpoints ...`); Mongo uses a
  `flow_checkpoints` collection with a compound index.
- **No TTL/expiry in durable backends** — durability is the point; deletion
  is explicit via `delete_flow` or the HTTP handlers.
- `list_flows(status="suspended")` — one entry per flow using its latest
  checkpoint's status.
- Lease methods: durable stores are NOT the lease authority — implement
  `acquire_lease/renew_lease/release_lease` as a simple table/collection-based
  fallback ONLY if trivial with the driver; otherwise raise
  `NotImplementedError("lease requires the redis store")` and document it
  (the checkpointer always takes leases on the ephemeral store).
- Unit tests: sqlite driver always runs (file/`:memory:`); pg/mongo suites
  skip when the service is unavailable.

**NOT in scope**: dump orchestration (TASK-2051), Redis store, HTTP.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/durable.py` | CREATE | DurableCheckpointStore |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/__init__.py` | MODIFY | Re-export |
| `packages/ai-parrot/tests/flows/checkpoint/test_durable_store.py` | CREATE | Contract tests (sqlite always; pg/mongo skippable) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from asyncdb import AsyncDB                                     # verified: core/storage/backends/redis.py header; drivers sqlite/pg/mongodb ship with asyncdb>=2.11.6 (pyproject:75,143)
from parrot.bots.flows.core.checkpoint.store.base import CheckpointStore     # from TASK-2048
from parrot.bots.flows.core.checkpoint.serializer import FlowStateSerializer # from TASK-2047
from parrot.bots.flows.core.checkpoint.model import FlowCheckpoint           # from TASK-2046
from parrot.conf import FLOW_CHECKPOINT_DURABLE_STORE          # from TASK-2048
```

### Existing Signatures to Use (pattern reference)
```python
# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py
class PostgresResultStorage(ResultStorage): ...  # DDL-on-first-use + AsyncDB pg pattern — READ IT FIRST

# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/documentdb.py
class DocumentDbResultStorage(ResultStorage): ... # Mongo-compatible collection pattern — READ IT FIRST
```

### Does NOT Exist
- ~~`DurableCheckpointStore`~~ — introduced HERE.
- ~~A sqlite backend anywhere under `core/storage/backends/`~~ — FEAT-147 never shipped one; there is NO sqlite pattern file to copy, derive it from the postgres backend + asyncdb `sqlite` driver docs.
- ~~TTL/`expires_at` columns~~ — durable stores have NO expiry by design (spec §1 two-tier rationale).
- ~~`asyncpg` direct usage~~ — go through AsyncDB.

---

## Implementation Notes

### Key Constraints
- Payload is opaque bytes from `FlowStateSerializer` — durable stores never
  introspect it except for the indexed header fields listed above.
- Upsert semantics on `(flow_id, checkpoint_id)` (dump may retry).
- DSNs: constructor arg > env (follow FEAT-147 conf conventions per driver).
- `close()` idempotent; lazy connection `_ensure()`.
- Keep SQL portable between sqlite and pg (or branch minimally per driver).

---

## Acceptance Criteria

- [ ] `test_durable_store_put_get_list_suspended` passes on sqlite (no external services).
- [ ] Same contract suite green on pg and mongodb when available (skip otherwise).
- [ ] Re-`put` of same `(flow_id, checkpoint_id)` upserts, no duplicate.
- [ ] No TTL/expiry mechanism present in any durable backend.
- [ ] `pytest packages/ai-parrot/tests/flows/checkpoint/test_durable_store.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/checkpoint/test_durable_store.py
@pytest.fixture
def sqlite_store(tmp_path):
    return DurableCheckpointStore(driver="sqlite", dsn=str(tmp_path / "ckpt.db"))

async def test_put_get_history_roundtrip(sqlite_store, sample_checkpoint):
    await sqlite_store.put(sample_checkpoint(checkpoint_id=1))
    await sqlite_store.put(sample_checkpoint(checkpoint_id=2, status="suspended"))
    assert (await sqlite_store.latest("f1")).checkpoint_id == 2
    assert len(await sqlite_store.history("f1")) == 2

async def test_list_flows_by_status(sqlite_store, sample_checkpoint):
    ...  # one suspended flow listed under status="suspended"

async def test_upsert_no_duplicates(sqlite_store, sample_checkpoint):
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context
2. **Check dependencies** — TASK-2046/2047/2048 in `tasks/completed/`
3. **Verify the Codebase Contract** — read `backends/postgres.py` and `backends/documentdb.py` in full first
4. **Update status** in `sdd/tasks/index/agentsflow-state-checkpointing.json` → `"in-progress"`
5. **Implement**, then **verify** all acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-01
**Notes**: Implemented `store/durable.py` (`DurableCheckpointStore`),
parametrized by `driver="sqlite"|"postgres"|"mongodb"`, one
`flow_checkpoints` table/collection keyed `(flow_id, checkpoint_id)` with
columns `flow_id, checkpoint_id, parent_checkpoint_id, status, flow_name,
created_at, lossy, payload` (payload = ormsgpack bytes from
`FlowStateSerializer`, the self-contained source of truth — the other
columns are indexed metadata for cheap `list_flows(status=...)`
filtering without decoding every payload). No TTL/expiry anywhere.
Upsert via `ON CONFLICT (flow_id, checkpoint_id) DO UPDATE` (sqlite/pg)
and `update_one(..., upsert=True)` (mongo) — verified no duplicates on
re-`put()`. Lease methods raise `NotImplementedError("lease requires the
redis store")` per the task's explicit instruction (durable stores are
not the lease authority).

**Investigation beyond the listed pattern files (worth flagging)**: the
task pointed at `PostgresResultStorage`/`DocumentDbResultStorage` as
pattern references, but empirical testing against throwaway
sqlite/postgres/mongo containers (`docker run ... :7-alpine` /
`postgres:16-alpine` / `mongo:7`) revealed the installed asyncdb
version's per-driver read-method signatures do NOT match what
`PostgresResultStorage` itself calls:
- sqlite: `execute()` binds named `:param` kwargs directly;
  `fetchrow()`/`fetch_one()` only accept a positional list via the
  literal `parameters=` kwarg (`?` placeholders) — passing named kwargs
  to them raises `TypeError` inside aiosqlite; `fetch_all()` wraps
  arbitrary kwargs into a dict passed as `parameters=` (named `:param`
  again, different wrapping than `fetch_one`).
- postgres: the `pg` driver's own `fetch(number=1)`/`fetchrow()` are
  cursor-only (NO `sentence` argument) in the installed version —
  calling them the way `PostgresResultStorage.list()`/`.get()` do
  (`conn.fetch(sql, *params)`) raises `TypeError: pg.fetch() takes from
  1 to 2 positional arguments but N were given`. Used `fetch_one`/
  `fetch_all` (aliased `fetchone`/`fetchall`) instead — confirmed
  correct via a real container.
- mongodb: `AsyncDB("mongodb", ...)` fails — the actual module is named
  `asyncdb.drivers.mongo`, so the correct call is `AsyncDB("mongo",
  ...)`. Also, passing only `dsn=` is silently discarded by the driver's
  internal `_construct_dsn()` unless a `params` dict (host/port/
  database/...) is also supplied — parsed the DSN into that dict in
  `_ensure()`. `execute(collection, operation, *args, **kwargs)`
  dispatches to the underlying Motor collection method and returns
  `(result, error)`; `query()` supports `sort=`/`limit=` and returns
  `[docs, error]` (list, not tuple, but unpacks the same).

All of the above is documented in the module docstring so the next
reader doesn't have to re-derive it. Confirmed correct end-to-end by
running the full contract suite against real throwaway containers for
all three drivers (not just sqlite): 10/10 pass (put/get/history/
list_flows-by-status/upsert-no-duplicates on each of sqlite, postgres,
mongodb). `store/__init__.py` and the top-level `checkpoint/__init__.py`
re-export `DurableCheckpointStore` directly (not lazy) — safe because
`durable.py` only imports the `AsyncDB` factory at module level; the
heavy driver modules (motor/pymongo/bson etc.) are imported lazily by
`AsyncDB()` itself only when a store instance actually connects.

Added `test_durable_store.py`: 6 sqlite tests always run (file-backed,
no external service — the mandated acceptance-criteria baseline), plus
4 postgres/mongo tests gated by a socket-based `_service_available()`
skip guard (verified: cleanly skip with no service reachable; all pass
against throwaway containers). `ruff check` clean.

**Deviations from spec**: none (the driver-signature workarounds are
implementation necessities to satisfy the store contract correctly
through the currently-installed asyncdb version, not changes to the
spec's storage model, key layout, or semantics).
