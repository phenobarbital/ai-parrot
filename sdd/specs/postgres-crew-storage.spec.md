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
**Status**: approved
**Target version**: next minor release

---

## 1. Motivation & Business Requirements

Persist `CrewDefinition` documents durably in `navigator.crew_definitions`, rehydrate them through
`BotManager`, and optionally migrate existing tenant-scoped and legacy-global Redis definitions.
Execution-result storage is unchanged. Redis-only mode remains the default and retains its existing API.

In Postgres mode, Postgres is authoritative. Redis is a read-only source for definitions that have
neither an active Postgres row nor a deletion tombstone. A successful write must never mean that a
newer Redis edit will silently be discarded after recovery. A successful delete must suppress fallback
even when Redis cleanup fails. Migration must never delete an uncopied or concurrently changed payload.

### Review decisions superseding draft 0.1

The four confirmed review findings require changes to the original degraded-mode promise (proposal U7)
and the spec-time conflict/write-error decisions. These are explicit design changes, not claims that
the original proposal already required them:

- Postgres mode never falls back to Redis writes, including after failed startup initialization.
- On a Postgres read error, fail closed rather than consult Redis: the missing answer might be a
  tombstone. Startup continues with a warning but cannot load authoritative crews while Postgres is down.
- Postgres wins conflicts for serving, but differing Redis payloads are retained and reported for
  operator reconciliation; they are not automatically destroyed.
- Deletes use durable Postgres tombstones. Redis cleanup is best effort after the tombstone commits.

### Non-goals

- Execution results (`PostgresResultStorage`, `crew_executions`), `CrewDefinition` model fields,
  configurable table names, and a standalone migration CLI.
- Changes to `creation.sql` or `BotManager._load_database_bots` (FEAT-621 byte-frozen gate).
- Full cache coherence for already-running executions; existing cross-worker synchronization remains
  eventually consistent. New storage reads must honor tombstones immediately.
- Closing stores on manager shutdown; introducing new dependencies.

## 2. Architectural Design

`definition_codec.py` shares legacy deserialization. `postgres_persistence.py` owns `CrewPostgres`.
`definition_storage.py` owns `CrewDefinitionStorage`, migration reporting, and storage exceptions.
`BotManager` retains `crew_redis`, adds `crew_postgres` and `crew_storage`, and routes persistence through
the composition. Redis is initialized first, then Postgres. Use per-call `AsyncDB("pg", dsn=...)`
connections following `PgUISurfaceStore`; ensure schema before each operation until initialization
succeeds. Do not permanently select Redis after a failed Postgres ping: later calls retry Postgres.

### Routing and error contract

| Operation | Redis mode | Postgres mode |
|---|---|---|
| Initialize | Existing Redis behavior | Ping Redis then Postgres; missing DSN/unreachable DB logs warning, skips migration; no Redis-only downgrade |
| Read by name | Delegate | Query Postgres including tombstone; active row wins, tombstone means absent, only genuine absence permits Redis fallback |
| Read by ID | Delegate | Query Postgres by tenant/ID including tombstones; if absent, resolve Redis candidate then check its tenant/name in Postgres before returning it; a tombstone or active row with another ID suppresses that candidate |
| List/get all | Delegate | Read active rows and tombstone identities, union Redis-only names, exclude tombstones; any Postgres failure raises and skips cache synchronization |
| Save | Delegate | Upsert Postgres only; DB failure raises `CrewStorageUnavailable`; never write Redis |
| Delete | Delegate | Commit tombstone, then attempt Redis cleanup; DB failure raises and leaves Redis untouched; cleanup failure warns but cannot make the deleted crew readable |
| Ping | Delegate | Postgres reachability only; a healthy Redis does not make Postgres mode healthy |

Database errors must be distinguished from not-found. Deserialization errors are logged; malformed
Postgres rows still reserve their identities and must not expose a stale Redis replacement. Lists
must not silently treat a failed Postgres query as empty. Redis read failures also invalidate a union
listing: introduce strict read helpers rather than relying on legacy methods that swallow errors.
The composition must never evict caches based on an incomplete listing.
Every Redis fallback candidate must be checked against authoritative rows by **both** `(tenant, name)`
and `(tenant, crew_id)`, for name loads, ID loads, and union listings alike. A tombstone on either
identity suppresses it; an active row claiming either identity wins and a different Redis candidate
is not returned. Thus a stale Redis alias with another name cannot expose a deleted crew ID.
Capture strict Redis inventory and its payload snapshots **before** reading Postgres rows for a union.
This ordering prevents migration from moving a crew between two queries so that it appears in neither
result. If a snapshotted inventory entry disappears before its payload is read, retain its identity
and resolve it against the subsequent Postgres result; on unexplained absence, skip the synchronization
round and retry rather than infer a deletion from that incomplete snapshot.

### Database schema and identity

```sql
CREATE SCHEMA IF NOT EXISTS navigator;
CREATE TABLE IF NOT EXISTS navigator.crew_definitions (
    tenant TEXT NOT NULL DEFAULT 'global',
    name TEXT NOT NULL,
    crew_id TEXT NOT NULL,
    description TEXT,
    execution_mode VARCHAR(32),
    definition JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    PRIMARY KEY (tenant, name),
    CONSTRAINT uq_crew_definitions_tenant_crew_id UNIQUE (tenant, crew_id)
);
```

Normalize `tenant` with `tenant or "global"`. Store `crew_id` as text, not UUID. Store
`model_dump(mode="json")` as a dict for the asyncdb JSONB codec. Preserve timestamps during migration
(naive timestamps mean UTC); normal saves set UTC-aware `updated_at` consistently in document and columns.

`save_crew` uses `ON CONFLICT (tenant, name) DO UPDATE`, clearing `deleted_at` only on an explicit save
(intentional recreation). `insert_if_absent` uses **`ON CONFLICT (tenant, name) DO NOTHING`**, never an
untargeted conflict clause. A same-ID/different-name uniqueness violation raises and leaves Redis intact.
Tombstones reserve name and ID until an explicit save; migration never revives them. Automatic tombstone
purging is out of scope because legacy Redis copies can otherwise become visible again.

Deletion accepts the resolved `CrewDefinition`, so even a Redis-only crew can be tombstoned with its
name, ID, and document. Update/insert the tombstone atomically in Postgres; do not issue a physical DELETE.
A conflicting identity is an error, not permission to delete another crew. Retrying a committed
tombstone with the same ID is safe; deleting from a stale cached definition whose ID differs from the
current same-name row raises `CrewStorageConflict` without overwriting the new identity. Perform that
identity check and mutation in the same statement or transaction. Retrying a committed
tombstone is idempotent. Redis cleanup failure is logged with tenant/name and retried on repeated delete
or later migration; retaining a tombstone indefinitely is safe. Live-test cleanup may physically delete
only rows belonging to its unique fixture tenant.
Provide an internal tombstone-aware resolver by name or ID for deletion retries; it returns a typed
active/deleted/absent state plus the stored definition. Never turn database errors into the absent state.

### Migration and concurrent cleanup

1. When migration is enabled and both stores are reachable, acquire a dedicated-session
   `pg_try_advisory_lock(hashtextextended('parrot:crew_definitions:migration', 0))`. Release it in `finally`
   on the same connection. Non-holders skip and continue serving. This lock serializes migration sweeps
   only; it is **not** a lock on application writers.
2. Read strict Redis inventory and capture a snapshot for each tenant/name: exact raw payloads for both
   the namespaced key and, for global, the legacy key, including missing-key state and associated IDs.
   Deserialize without modifying the captured bytes. Unreadable entries are failures and remain intact.
3. For each snapshot, insert with the targeted conflict clause. Re-read the Postgres row including
   tombstone state. A same-ID/different-name collision is `failed`, never a cleanup candidate.
4. Compare complete normalized model documents, excluding only `created_at` and `updated_at`.
   An active row equal to the source is eligible for cleanup, whether newly inserted or already present.
   A differing active row is a conflict: retain Redis and record `failed[key] = "definition conflict"`
   as well as `conflicts`. A tombstone remains authoritative; its stale source may be conditionally
   cleaned without being counted as a copied definition. If namespaced and legacy payloads differ,
   retain both and report a conflict instead of deleting the hidden legacy version.
5. Cleanup must be one atomic Redis Lua operation that first compares **all** captured raw payloads
   (including expected absence). If any differs, mutate nothing and report `source_changed` in `failed`.
   Otherwise delete matching payloads and remove their name memberships atomically. Remove ID mappings
   only if they still point to this name; remove tenant membership only when the namespaced list is empty.
   Never call the unconditional `CrewRedis.delete_crew` for migration. A Redis error is recorded in
   `redis_cleanup_failed`; the snapshot is retained whenever no cleanup committed.
6. Mark `migrated` only after a newly inserted, verified snapshot was conditionally cleaned. Report
   already-equal cleanup separately as `already_present`; report tombstone cleanup as `deleted_sources`.
   On rerun, differing or changed sources remain failures until explicitly reconciled by an operator.

Concurrent legacy/degraded writers may leave a newer Redis payload after a successful cleanup. It is
never automatically authoritative over Postgres and must remain available for reconciliation on the
next sweep. No migration pass promises that Redis stays empty while external writers continue.
The new Postgres-mode composition never writes Redis, even during an outage. Rollout must upgrade
workers before relying on the new acknowledged-write contract; old Redis-only workers retain their
old semantics. Lua cleanup requires the existing single-instance Redis deployment; Redis Cluster
cross-slot support is out of scope and must be rejected before destructive migration.

`dry_run=True` captures and compares snapshots but performs no INSERT, UPDATE, Redis mutation, or
schema creation; it classifies would-migrate/equal/conflict/tombstone cleanup. Missing schema is a
reported precondition failure. The advisory lock may still be acquired and released.

### Migration report

```python
class CrewMigrationReport(BaseModel):
    dry_run: bool = False
    lock_acquired: bool = True
    skipped_reason: Optional[str] = None
    migrated: List[str] = Field(default_factory=list)
    already_present: List[str] = Field(default_factory=list)
    deleted_sources: List[str] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)
    failed: Dict[str, str] = Field(default_factory=dict)
    redis_cleanup_failed: List[str] = Field(default_factory=list)
```

Report keys are `tenant:name`. Dry runs use the same categories for predicted outcomes with `dry_run=True`.
Inventory/lock failures set `skipped_reason` and must not be reported as successful empty migrations.

## 3. Module Breakdown

### M1 — Shared codec and safe Redis source operations

Files: new `packages/ai-parrot-server/src/parrot/handlers/crew/definition_codec.py`; modify sibling
`redis_persistence.py`. Move unknown-key stripping and timestamp parsing into
`strip_unknown_keys`, `crew_definition_from_dict`, `crew_definition_to_document`. Keep existing Redis
private helpers as delegates with unchanged logging and legacy-payload behavior.

Add typed `CrewRedisSnapshot` (tenant/name, both raw key states, parsed definition, mapping IDs) and
`CrewRedisCleanupResult` (`deleted`, `source_changed`, `already_absent`) plus:

- `snapshot_crew(name, tenant=None) -> Optional[CrewRedisSnapshot]`: async, strict failures.
- `delete_snapshot(snapshot) -> CrewRedisCleanupResult`: async, atomic Lua contract from §2, raises on errors.
- `list_all_crews_strict() -> List[Dict[str, str]]`: async inventory with errors propagated, including
  failures within individual tenant lists. Existing Redis public methods retain their behavior.

These helpers are new contracts, not existing symbols. Composition union reads use strict inventory
and snapshot reads to distinguish unavailable Redis from absent records.

### M2 — Postgres store

New `packages/ai-parrot-server/src/parrot/handlers/crew/postgres_persistence.py`. Dependencies: M1, M4.
Use `_DDL_STATEMENTS`, `ensure_schema`, `_get_db`, `configured`, `ping`, and `migration_lock` following
the verified AsyncDB pattern. Use `fetchval` plus RETURNING for mutations, `fetch_one` for one row,
`fetch_all` with None normalized to empty. Database failures raise.

Public async methods: `save_crew(crew) -> bool`, `insert_if_absent(crew) -> bool`,
`delete_crew(crew: CrewDefinition) -> bool` (durable tombstone), `load_crew(name, tenant=None)`,
`load_crew_by_id(crew_id, tenant=None)`, `list_all_crews()`, `get_all_crews(tenant=None)`, and `close()`.
Add internal typed row lookup/list methods retaining `deleted_at` and identity even when a document
does not deserialize; composition uses these to enforce fallback suppression. Public loads/lists
return active definitions only. `insert_if_absent=False` means a same-name row exists, including a
tombstone; all other integrity errors raise. Close is a no-op for per-call connections.

### M3 — Composition and migration

New `packages/ai-parrot-server/src/parrot/handlers/crew/definition_storage.py`. Dependencies: M1, M2.
Expose `CrewDefinitionStorage(redis, postgres=None, *, migration=False)` and the seven manager operations.
Change composition deletion to `delete_crew(crew: CrewDefinition) -> bool`; Redis mode translates this
to the existing Redis name/tenant signature. Define `CrewStorageUnavailable` and `CrewStorageConflict`.
Do not classify integrity/identity conflicts as transient outages. Translate driver exceptions with
their cause retained, without logging DSNs or secrets.

`initialize() -> Optional[CrewMigrationReport]` logs connectivity failures without raising and runs
migration only when safe. `postgres_active` is last observed health, not routing authority: configured
backend selection remains immutable. Every later Postgres operation retries initialization as needed.
`migrate_from_redis(*, dry_run=False)` returns a report, isolating per-crew failures; cancellation must
propagate after releasing resources. `close()` closes both stores.

### M4 — Configuration

Modify `packages/ai-parrot/src/parrot/conf.py` after the `CREW_RESULT_STORAGE*` block:

```python
CREW_DEFINITION_STORAGE = config.get("CREW_DEFINITION_STORAGE", fallback="redis")
CREW_DEFINITION_PG_DSN = config.get("CREW_DEFINITION_PG_DSN", fallback=default_dsn)
CREW_DEFINITION_MIGRATION = config.getboolean("CREW_DEFINITION_MIGRATION", fallback=False)
```

Unknown backend warns and selects Redis for backward compatibility. Explicit `postgres` with no DSN
stays unavailable Postgres mode and never silently enables Redis writes.

### M5 — Manager and HTTP integration

Modify `packages/ai-parrot-server/src/parrot/manager/manager.py`,
`packages/ai-parrot-server/src/parrot/handlers/crew/handler.py`, and
`packages/ai-parrot/tests/test_botmanager_flags.py`.
Add constructor kwargs `crew_storage_backend: Optional[str] = None`, `crew_migration: Optional[bool] = None`;
DSN remains configured through `parrot.conf`. Build stores only when crews are enabled. Route existing
call sites listed in §6 through `crew_storage`; `load_crews` initializes before reading.

In Postgres mode, `add_crew` persists before publishing to `_crews`; failure leaves the prior cache
unchanged and propagates. `remove_crew` resolves the definition and commits a tombstone before cache
eviction; failure preserves the cached crew and propagates. A retry must also recognize an existing
tombstone and succeed without requiring an active cached definition. Redis-only mode keeps existing
best-effort manager behavior. `sync_crews` skips a failed/incomplete listing without cache eviction.

The HTTP handler must map unavailable storage to 503 and identity conflicts to 409, rather than catch
and report success. In Postgres mode replace the existing update path's remove-then-add sequence with
a single persistence upsert followed by cache replacement: preserve crew ID and creation timestamp.
Same-name updates are supported. Reject rename updates with 409 in Postgres mode in this release;
otherwise a failed second step could strand a tombstone or collide with the old unique ID. Redis mode
retains existing behavior. Storage error mapping must precede generic exception handlers. No new route.
In Postgres mode `BotManager.get_crew` must propagate typed storage errors instead of swallowing them
into `(None, None)`; handlers must map them to 503/409 before their not-found checks. HTTP DELETE must
call tombstone-aware `remove_crew` directly, without an active-crew existence precheck. Removal uses the
internal resolver when cache/active lookup misses: a matching tombstone is successful idempotent
deletion (including after restart), true absence is 404, and unavailable storage is 503. Preserve the
existing Redis-only behavior. Add handler tests with an empty cache for these three outcomes.

### M6 — Documentation

Modify `README_BOTMANAGER_PERSISTENCE.md` and `README_REDIS_PERSISTENCE.md` under the crew handlers;
create `wiki/bots/orchestration/crew-definition-storage.md`; update `wiki/bots/crew_handler.md`.
Document tenant keys, config, fail-closed behavior, 503/409 responses, tombstones, rename restriction,
operator reconciliation, migration categories, rollout limits and single-instance Redis requirement.

## 4. Test Specification

Retain codec round-trip, unknown-key/ISO parsing, legacy Redis payload, Postgres CRUD/tenant isolation,
JSONB dict/string, schema idempotence, UTC timestamp, flags, default Redis delegation, manager wiring,
advisory-lock acquisition/release, and migration rerun/dry-run tests. Add the following mandatory cases:

| Scenario | Required assertion |
|---|---|
| Postgres v1; failed v2 write; recovery/migration | Failure reaches caller; no Redis write/cache publication; v1 remains; no acknowledged v2 is lost |
| Startup missing DSN/down, then recovery | No backend downgrade; writes fail; migration skipped; recovery permits Postgres operations |
| Two Redis names sharing one ID | First migrates; second uniqueness error is failed; second Redis payload and mappings remain |
| Same-name differing Postgres/Redis documents | Postgres serves; Redis retained and conflict reported on every rerun |
| Delete fails before tombstone commit | Redis and cache unchanged; 503, never success |
| Tombstone commits, Redis cleanup fails | Delete succeeds; name/ID/list/get-all never resurrect; retry safe |
| Postgres unavailable after tombstone | Read fails closed; no Redis fallback; sync preserves cache rather than using incomplete inventory |
| Redis-only crew deletion | Tombstone created before cleanup; prevents subsequent migration and fallback |
| Migration read v1; concurrent Redis write v2 before cleanup | Atomic compare fails; no key/index mutation; v2 retained and source_changed reported |
| Global legacy key changes or appears during migration | Compare includes both keys/absence; no destructive cleanup |
| ID mapping reassigned to another name | Cleanup leaves reassigned mapping intact |
| Redis writes v2 after cleanup | Rerun retains differing v2 for reconciliation |
| Migration moves a crew during a union read | Redis-first snapshot plus subsequent Postgres read retains the crew; incomplete snapshots skip sync |
| Stale cached delete after same-name recreation with a new ID | Conflict; new active row and cache are not evicted |
| Postgres/Redis inventory failure | No successful empty report or cache eviction |
| By-ID Redis fallback has same name as Postgres row with another ID | Stale Redis identity suppressed |
| Tombstoned ID survives in Redis under another name | Name/ID reads and both listing methods all suppress that alias |
| HTTP lookup with failed Postgres and empty cache | Typed error propagates through manager; 503 rather than 404 |
| HTTP DELETE retry with empty cache and committed tombstone | Success without active existence precheck; genuinely absent identifier remains 404 |
| Postgres-mode HTTP update failure | Prior active row/cache preserved; no intermediate tombstone; 503/409 propagated |
| Rename update in Postgres mode | 409 before mutation |
| Dry run with missing schema | Reports precondition; no DDL or data writes |

Unit tests use fakes/AsyncMock but must assert error propagation and retained state, not just call counts.
Live integration tests must exercise targeted uniqueness conflicts against real Postgres and the Lua
cleanup against real Redis with a barrier-controlled intervening write. Mock-only tests cannot validate
SQL conflict targets or atomic cleanup. Use unique tenants and clean only fixture-owned rows/keys.
Skip services when their environment configuration is absent; explicitly report skips. Live validation
is required before production migration; never claim mock results prove destructive migration safety.

### Validation Contract

tests:
- packages/ai-parrot-server/tests/unit/test_crew_redis_legacy_payloads.py
- packages/ai-parrot-server/tests/unit/test_crew_definition_codec.py
- packages/ai-parrot-server/tests/unit/test_crew_redis_snapshot.py
- packages/ai-parrot-server/tests/unit/test_crew_postgres_store.py
- packages/ai-parrot-server/tests/unit/test_crew_definition_storage.py
- packages/ai-parrot-server/tests/manager/test_crew_storage_wiring.py
- packages/ai-parrot-server/tests/handlers/test_crew_storage_errors.py
- packages/ai-parrot-server/tests/handlers/test_crew_postgres_store_live.py
- packages/ai-parrot-server/tests/handlers/test_crew_migration_live.py
- packages/ai-parrot/tests/test_botmanager_flags.py
markers: none

Live tests require `NAVIGATOR_PG_DSN`; Redis integration additionally requires an explicit
`CREW_MIGRATION_TEST_REDIS_URL` to an isolated disposable Redis database. No service provisioning is
implicit. Run black/ruff for changed Python files and retain test logs under `artifacts/logs/`.

## 5. Acceptance Criteria

- [ ] Default Redis mode preserves existing behavior, constructs no Postgres store, and passes legacy tests.
- [ ] Postgres mode creates the schema idempotently and rehydrates active definitions with tenant isolation.
- [ ] No Postgres-mode write failure is acknowledged as a Redis save; cache publication follows persistence.
- [ ] Missing DSN or unavailable Postgres never switches the configured backend; recovery is retried.
- [ ] Only verified Postgres absence permits fallback; tombstones, malformed authoritative rows, and
      Postgres query errors never expose Redis substitutes, including by-ID lookup and union listings.
- [ ] A committed delete stays absent despite Redis cleanup failure; failed tombstone writes preserve
      Redis/cache and propagate to the caller. Repeat deletion is idempotent.
- [ ] Same-name insert conflicts are distinct from ID uniqueness errors; ID collisions preserve source data.
- [ ] Differing source documents are retained and reported until explicit reconciliation.
- [ ] Migration cleanup atomically compares all captured raw key states and cannot delete a concurrent edit.
- [ ] Advisory locking serializes migrators, resources release on error/cancellation, and reports accurately
      distinguish copied/equal/conflicting/deleted/changed/cleanup-failed entries.
- [ ] Dry runs mutate neither schema nor data; reruns never discard a previously failed source.
- [ ] HTTP returns 503/409 for storage failures/conflicts; updates are single upserts, and renames are rejected
      before mutation in Postgres mode. Redis-only API behavior remains unchanged.
- [ ] Failed or incomplete inventories do not trigger cache eviction.
- [ ] All validation tests pass; live skips are disclosed and live safety checks run before production migration.
- [ ] `creation.sql` and `_load_database_bots` remain byte-identical; existing storage gate passes.
- [ ] Required documentation and API module documentation exist; `parrot sdd techwiki check` passes.

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

Use the verified imports and source anchors in §6 as baseline evidence, not as a mandate to retain the
old manager ordering. M5 explicitly changes mutation ordering, deletion signature, and handler update
behavior. M1 additionally owns all Redis snapshot/strict-read helpers; M2 owns tombstone-aware row APIs.
The handler and new test files in §3–4 extend the original edit-site table. No new library is required.
Use aiohttp, Pydantic v2, asyncdb, and the existing Redis client. No blocking I/O or provider SDK calls.

### Decision audit

The version 0.1 decision-audit pass and embedded digests apply only to that historical draft. They have
been removed because the reviewed decisions changed. Status: **pending revalidation** before task
generation; do not reuse the old pass as evidence for version 0.2.

## 8. Resolved Design Questions

- Postgres is authoritative; Redis fallback is permitted only after confirmed absence.
- Migration is copy/verify/conditional-cleanup, serialized among migrators; conflicts retain source data.
- Postgres write outages are caller-visible failures, not acknowledged Redis writes.
- Durable tombstones suppress stale Redis copies; tombstones are not automatically purged.
- Startup remains nonfatal on unavailable storage, but cannot promise crew availability without the primary.
- Config defaults to Redis; no automatic backend downgrade after explicit Postgres selection.
- HTTP integration is in scope to propagate failures and avoid remove-then-add updates.
- Migration rollout requires upgraded workers and single-instance Redis; live safety validation is mandatory.

## 9. Review Findings and Resolution

All four findings were independently cross-checked and confirmed against the version 0.1 spec and source.
These resolutions fix the specification; implementation and test execution remain future feature work.

| Ledger issue | Finding | Resolution | Required evidence at implementation |
|---|---|---|---|
| d60b6689f09a | Acknowledged fallback edits discarded | §2 rejects Redis writes in Postgres mode; §3 M5 publishes only persisted state | Outage/update/recovery test and HTTP 503 |
| 44c8fdcbe1f1 | ID conflict deletes uncopied crew | §2 targets name conflict; ID collision raises and retains source | Real Postgres two-name/same-ID test |
| fbef17fdb1a7 | Partial deletion resurrects crew | §2 tombstones and fail-closed reads; §3 M5 persistence before eviction | Both failure directions and all read surfaces |
| 457d8c6f2c4a | Cleanup destroys concurrent writes | §2 atomic raw-snapshot cleanup; differing conflicts retained | Real Redis interleaving, legacy key and mapping tests |

## 10. Documentation

Policy: required. Create `wiki/bots/orchestration/crew-definition-storage.md` and update
`wiki/bots/crew_handler.md` plus both persistence READMEs. API modules: `definition_codec`,
`postgres_persistence`, `definition_storage` under `parrot.handlers.crew`. Include operator steps for
reviewing retained conflicts and deliberately saving the chosen definition before rerunning migration;
never recommend unconditional source deletion as recovery.

## Worktree Strategy

One feature worktree `feat-FEAT-860-postgres-crew-storage`; task worktrees follow the SDD engine policy.
M1 and M4 are independent; M2 depends on both; M3 depends on M1/M2; M5 depends on M3/M4; M6 documents the
final contracts. Assign Redis helpers entirely to M1 to avoid shared-file edits. Live tests own isolated
tenant/key namespaces and must not interfere with production resources. No cross-feature dependency.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-09 | Jesus Lara | Initial draft from proposal FEAT-860 |
| 0.2 | 2026-11-09 | Codex | Resolve four review findings: reject unsafe fallback writes, targeted conflicts, durable deletion, conditional migration cleanup; expand manager/HTTP scope, tests and acceptance criteria |
