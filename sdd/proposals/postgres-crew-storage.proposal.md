---
id: FEAT-860
title: Postgres CrewDefinition storage (navigator.crew_definitions) beside CrewRedis, with a migration=True flag that moves existing Redis crews into Postgres
slug: postgres-crew-storage
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-11-09
  summary_oneline: Postgres CrewDefinition storage (navigator.crew_definitions) alongside Redis, with migration=True to move existing crews from Redis to Postgres
overall_confidence: medium
base_branch: dev
projects: [ai-parrot-server, ai-parrot]
tags: [crew, persistence, postgres, redis, migration]
research_state: sdd/state/FEAT-860/
created: 2026-11-09
updated: 2026-11-09
---

# FEAT-860 — Postgres CrewDefinition storage beside CrewRedis, with a Redis → Postgres migration flag

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-860/`](../state/FEAT-860/)

---

## 0. Origin

The original request, preserved verbatim. The full source is at `sdd/state/FEAT-860/source.md`.

> postgres-crew-storage -- vamos a definir un Postgres Crew Definition Storage para el CrewDefinition
> de Redis a Postgres, con este nuevo storage se inicializan los dos (redis y luego postgres) y un flag
> "migration=True" permite "mover" desde redis a postgres los Crew existentes, una tabla
> `navigator.crew_definitions` en postgres de donde se pueden re-hidratar los crew tal como se realiza
> desde Redis.

**Initial signals** (extracted, not interpreted):
- Verbs: "definir", "se inicializan los dos", "mover", "re-hidratar" → additive, feature-shaped
- Named entities: `CrewDefinition`, Redis, Postgres, `navigator.crew_definitions`, `migration=True`
- Components / labels: none (inline source)
- Acceptance criteria provided: no

---

## 1. Synthesis Summary

Crew definitions are persisted only in Redis today, by `CrewRedis`, and the only production consumer is
`BotManager`, which rehydrates every tenant's crews at startup in `BotManager.load_crews` and writes
through on `add_crew` / `remove_crew`. The request adds a Postgres store over a new
`navigator.crew_definitions` table that is initialized after Redis, becomes the source of truth, and can
absorb the existing Redis crews when `migration=True`. The store must mirror the seven `CrewRedis` methods
`BotManager` uses, keep `(tenant, name)` plus `(tenant, crew_id)` identity, reuse the unknown-key
compatibility step of `CrewRedis._deserialize_crew`, and store the definition as one `jsonb` document.
`PgUISurfaceStore` is the pattern to follow; the migration must be idempotent and serialized because
`load_crews` runs in every gunicorn worker. Recommendation: `/sdd-spec FEAT-860` — every open question
was answered in the proposal phase.

---

## 2. Codebase Findings

> All entries in this section are grounded in the research findings persisted
> at `sdd/state/FEAT-860/findings/`. Each cites the finding ID(s) that justify
> its inclusion. **No fabricated paths or symbols.**

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py` | `CrewRedis` | 17-587 | only CrewDefinition store today; its 7 BotManager-used methods are the contract to mirror | F001, F014 |
| 2 | `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py` | `CrewRedis._deserialize_crew` | 180-218 | unknown-key stripping that keeps historical crews loadable; Postgres reads must share it | F001, F011 |
| 3 | `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py` | `CrewRedis.list_all_crews` | 397-419 | enumerates every `(tenant, name)` incl. legacy `global` keys — the migration's source iterator | F001 |
| 4 | `packages/ai-parrot-server/src/parrot/manager/manager.py` | `BotManager.__init__` | 227-271 | builds `self.crew_redis` when `enable_crews`; where the Postgres store is wired | F002, F015 |
| 5 | `packages/ai-parrot-server/src/parrot/manager/manager.py` | `BotManager.load_crews` | 3457-3502 | startup rehydration of all tenants; hook for "Redis, then Postgres, then migrate" | F002, F018 |
| 6 | `packages/ai-parrot-server/src/parrot/manager/manager.py` | `BotManager.add_crew` | 3255-3292 | write-through save; failure logged, crew stays memory-only | F002 |
| 7 | `packages/ai-parrot-server/src/parrot/manager/manager.py` | `BotManager.get_crew` | 3294-3367 | cache miss → `load_crew` → `load_crew_by_id` | F002 |
| 8 | `packages/ai-parrot-server/src/parrot/manager/manager.py` | `BotManager.remove_crew` | 3383-3429 | delete path (also half of the HTTP PUT update) | F002 |
| 9 | `packages/ai-parrot-server/src/parrot/manager/manager.py` | `BotManager.sync_crews` | 3504-3555 | cross-worker reconciliation via `list_all_crews` before listing | F002 |
| 10 | `packages/ai-parrot/src/parrot/models/crew_definition.py` | `CrewDefinition` | 216-309 | persisted model: `crew_id` uuid4 str, `tenant` default `"global"`, `name`; `extra="forbid"` | F003, F012 |
| 11 | `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` | `PgUISurfaceStore` | 457-520 | closest `navigator.*` store: `default_dsn`, `ensure_schema`, `CREATE SCHEMA IF NOT EXISTS navigator`, `ON CONFLICT` upsert | F005 |
| 12 | `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py` | `PostgresResultStorage._ensure_table` | 58-110 | lazy idempotent DDL precedent; its `_TABLE_RE` (line 19) rejects schema-qualified names | F004 |
| 13 | `packages/ai-parrot/src/parrot/conf.py` | `ENABLE_CREWS` | 96 | only flag gating crew-definition persistence; new keys go next to it | F007 |
| 14 | `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/migrate.py` | `migrate_store` | 101-135 | idempotent sweep + `dry_run` + `MigrationReport` precedent | F010 |
| 15 | `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py` | `ensure_studio_storage` | 155 | backend-selection precedent: explicit setting, probe, fail closed | F021 |
| 16 | `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py` | `test_load_database_bots_untouched` | 268-283 | FEAT-621 gates: `creation.sql` and `_load_database_bots` frozen | F018 |
| 17 | `packages/ai-parrot/tests/test_botmanager_flags.py` | `test_enable_crews_true_creates_crew_redis` | 186-194 | pins `bm.crew_redis` and the `CrewRedis` patch target | F015, F008 |

### 2.2 Constraints Discovered

- **Seven-method contract.** `BotManager` is the only production consumer of `CrewRedis` and calls
  `save_crew`, `load_crew`, `load_crew_by_id`, `delete_crew`, `ping`, `get_all_crews`, `list_all_crews`.
  *Implication*: the Postgres store offers exactly these with the same return conventions; `CrewHandler`
  and the other `get_crew` consumers stay untouched.
  *Evidence*: F002

- **Identity.** `(tenant, name)` is the natural key, `(tenant, crew_id)` a secondary lookup; `None`
  normalizes to `"global"`; legacy un-tenanted keys are read for `global` only.
  *Implication*: `UNIQUE (tenant, name)` and `UNIQUE (tenant, crew_id)`; the migration must also pick up
  legacy `global` crews (`list_all_crews` already folds them in).
  *Evidence*: F001, F003

- **Read-side compatibility.** Historical crews load only because `CrewRedis._deserialize_crew` strips
  unknown keys before `CrewDefinition(**dict)` under `extra="forbid"` (commit `60811a57bd`).
  *Implication*: extract that step into a shared helper used by both stores.
  *Evidence*: F001, F011

- **Schema churn.** `CrewDefinition` keeps gaining fields (ToolNode, execution wiki, infographic theme),
  and a column-per-field table already broke every load of `navigator.ai_bots`.
  *Implication*: one `jsonb` document column plus identity/listing columns.
  *Evidence*: F012, F006

- **DDL policy.** In-module auto-create (`PgUISurfaceStore`, `PostgresResultStorage`) coexists with
  Studio's migration-files-only policy; the FEAT-621 gates are scoped to the Studio stack, but
  `creation.sql` and `BotManager._load_database_bots` are byte-frozen.
  *Implication*: crew DDL lives in its own module; never edit `creation.sql` or `_load_database_bots`.
  *Evidence*: F005, F016, F018, F004

- **No helper reuse.** `PostgresResultStorage` validates table names with `^[a-z_][a-z0-9_]*$`, which
  rejects `navigator.crew_definitions`.
  *Implication*: follow the `PgUISurfaceStore` schema-qualified idiom instead.
  *Evidence*: F004

- **Connection timing.** `CrewRedis` is built in `BotManager.__init__`, before the aiohttp app and its
  `app["database"]` pool exist; `default_dsn` is `None` when DB settings are absent.
  *Implication*: connect lazily with a DSN (`AsyncDB("pg", dsn=...)` per call) and define the behaviour
  when no DSN is configured.
  *Evidence*: F006, F007, F002

- **Multi-worker startup.** `load_crews` runs in every gunicorn worker.
  *Implication*: the startup migration is idempotent and serialized with a pg advisory lock.
  *Evidence*: F002, F010

- **Swallowed write errors.** `CrewRedis` returns `False`/`None`; `BotManager` logs and keeps the crew
  memory-only.
  *Implication*: before deleting anything from Redis, the migration re-reads the crew from Postgres.
  *Evidence*: F001, F002

- **Tested surface.** `test_botmanager_flags.py` pins `bm.crew_redis` and patches
  `parrot.manager.manager.CrewRedis`.
  *Implication*: keep `crew_redis` and add a sibling patch target for the Postgres store.
  *Evidence*: F015, F008

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `03e9a7cf51` | 2026-09-17 | Jesus Lara | feat(crew): configurable infographic theme on CrewDefinition/AgentCrew | `crew_definition.py` |
| `413d4067a8` | 2026-08-24 | Jesus Lara | fix(saas-auth-hardening): close cross-tenant gaps found in code review | `redis_persistence.py`, `crew_definition.py`, `handler.py`, `execution_handler.py` (19 files) |
| `3f6a5d3ffa` | 2026-08-20 | Jesus | fix(flows): address code-review findings on workflow authoring | `crew_definition.py`, `redis_persistence.py` |
| `60811a57bd` | 2026-08-17 | Claude | fix(crew): keep already-stored crews loadable under extra="forbid" | `redis_persistence.py`, `flow_authoring.py` |
| `0e221d75c8` | 2026-08-16 | Claude | feat(crew): validate CrewDefinition instead of failing silently | `crew_definition.py` |

`413d4067a8` is hidden from `git log -- redis_persistence.py` by history simplification; it appears only
with `--full-history` or `--grep=FEAT-446` (F011).

---

## 3. Probable Scope

### What's New

- **Postgres crew store** (in `handlers/crew/`, e.g. `CrewPostgres`) over `navigator.crew_definitions`:
  `tenant`, `name`, `crew_id`, `description`, `execution_mode`, `definition jsonb`,
  `created_at`/`updated_at timestamptz`; `UNIQUE (tenant, name)`, `UNIQUE (tenant, crew_id)`; the seven
  `BotManager` methods plus `close`; `save_crew` = `INSERT ... ON CONFLICT (tenant, name) DO UPDATE`.
- **In-module DDL** — `CREATE SCHEMA IF NOT EXISTS navigator` + `CREATE TABLE IF NOT EXISTS
  navigator.crew_definitions` + indexes, applied lazily by an `ensure_schema()` that tolerates races
  (U4).
- **Storage composition** — Redis initialized first, then Postgres; Postgres serves reads and writes;
  Redis is a read-only fallback for crews not yet migrated (U1).
- **Migration** (`migration=True`) — under a pg advisory lock in `BotManager.load_crews`: iterate
  `CrewRedis.list_all_crews()` + `load_crew()`, upsert into Postgres, re-read and compare, then delete
  the crew's Redis keys through `CrewRedis.delete_crew` (which also clears legacy keys); per-crew report,
  one failure never aborts the sweep (U2, U3).
- **Config** — `CREW_DEFINITION_STORAGE`, `CREW_DEFINITION_MIGRATION`, `CREW_DEFINITION_PG_DSN`
  (fallback `default_dsn`) in `parrot.conf`, overridable by `BotManager` / store kwargs (U5).
- **Shared deserialization helper** extracted from `CrewRedis._strip_unknown_keys` / `_deserialize_crew`.
- **Tests** — fake-`AsyncDB` unit tests (the `test_ui_surfaces_store.py` pattern), a live test gated on a
  DSN env var, and migration tests (copy, verify, delete, idempotent re-run, per-crew failure).

### What Changes

- **`packages/ai-parrot-server/src/parrot/manager/manager.py`::`BotManager`** — `__init__` builds the
  Postgres store; `load_crews` initializes both, runs the migration when enabled, then rehydrates from
  Postgres (+ Redis fallback); `add_crew` / `get_crew` / `remove_crew` / `sync_crews` go through the
  composition.  *Evidence*: F002
- **`packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`::`CrewRedis._deserialize_crew`**
  — delegates to the shared compatibility helper.  *Evidence*: F001, F011
- **`packages/ai-parrot/src/parrot/conf.py`** — new `CREW_DEFINITION_*` keys next to `ENABLE_CREWS`.
  *Evidence*: F007
- **`README_BOTMANAGER_PERSISTENCE.md` / `README_REDIS_PERSISTENCE.md`** — fix the stale pre-tenant key
  layout and document the Postgres backend and the migration flag.  *Evidence*: F009
- **`packages/ai-parrot/tests/test_botmanager_flags.py`** — cover the second store's construction and
  patch target.  *Evidence*: F015

### What's Untouched (Non-Goals)

- The `CrewHandler` HTTP surface (`/api/v1/crew` GET/PUT/DELETE; no PATCH here).
- Execution results: `PostgresResultStorage` / `crew_executions` (FEAT-147 / FEAT-307).
- `packages/ai-parrot-server/src/parrot/handlers/creation.sql` and `BotManager._load_database_bots`
  (FEAT-621 AC17 frozen).
- `CrewDefinition` model fields.
- The Studio migration runner (`apply_studio_migrations`).

### Patterns to Follow

- `PgUISurfaceStore`: `AsyncDB("pg", dsn=default_dsn)` per call, `_DDL_STATEMENTS` starting with
  `CREATE SCHEMA IF NOT EXISTS navigator`, `ensure_schema()` tolerating "already exists", `ON CONFLICT`
  upsert.  *Evidence*: F005
- `migrate_store`: idempotent sweep, per-item `try/except` into a report, `dry_run` never writes.
  *Evidence*: F010
- Conf flag + constructor override (FEAT-042 `BotManager` flags; `CREW_RESULT_STORAGE*` naming).
  *Evidence*: F007, F015
- Studio backend selection: explicit setting, read-only probe, fail closed when Postgres is required.
  *Evidence*: F021

### Integration Risks

- **Deleted crews resurrected by the Redis fallback**: a crew deleted from Postgres but still present in
  Redis would reappear through the fallback read or `sync_crews`. *Mitigation*: `remove_crew` also
  deletes the Redis copy while the fallback is active.  *Evidence*: F002
- **Concurrent startup migration**: every worker runs `load_crews`. *Mitigation*: pg advisory lock +
  `ON CONFLICT` upsert; workers that lose the lock skip the migration.  *Evidence*: F010, F002
- **Deleting Redis keys after a swallowed Postgres failure**: permanent crew loss. *Mitigation*: delete
  only after re-reading the crew from Postgres and comparing it to the Redis copy.  *Evidence*: F001, F002
- **Crews that no longer validate** (model validators, not unknown keys): *Mitigation*: per-crew error
  isolation; the crew stays in Redis and appears in the report.  *Evidence*: F003, F010
- **Naive vs tz-aware timestamps** (`CrewRedis` writes `datetime.utcnow()` at `redis_persistence.py:235`
  and `:538`): *Mitigation*: treat naive values as UTC on write to `timestamptz`.  *Evidence*: F003, F001

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `CrewRedis` is the only CrewDefinition store; no `crew_definitions` table or `CREW_DEFINITION_STORAGE` key exists in `packages/` | F014, F001, F005, F016 | high | wiki + grep, confirmed by absent probes |
| C2 | `BotManager` is the only production caller of `CrewRedis` and uses 7 of its methods | F002 | high | repo-wide grep with call sites |
| C3 | `load_crews` eagerly rehydrates every tenant's crews at startup via `get_all_crews(tenant=None)` | F002 | high | read of `load_crews` |
| C4 | Identity is `(tenant, name)` with a secondary `(tenant, crew_id)` lookup; legacy keys apply to `global` only | F001, F003 | high | read of key helpers and model fields |
| C5 | Unknown-key stripping in `_deserialize_crew` keeps historical crews loadable under `extra="forbid"` | F001, F011 | high | code read + commit `60811a57bd` rationale |
| C6 | A `jsonb` document column (plus identity columns) is safer than column-per-field for `CrewDefinition` | F012, F006, F003 | medium | design inference from schema churn and the `ai_bots` drift lesson |
| C7 | `PostgresResultStorage`'s table-name regex rejects schema-qualified names | F004 | high | anchor verified at `postgres.py:19` |
| C8 | `PgUISurfaceStore` is the closest pattern for a `navigator.*` store | F005 | high | read of DDL list, `ensure_schema`, `save` |
| C9 | The Postgres store must connect lazily because `CrewRedis` is built before `app["database"]` exists | F006, F002 | medium | inferred from construction order; `on_startup` construction is also possible |
| C10 | The FEAT-621 gates do not cover `handlers/crew/` but encode "no DDL outside migrations, no migration at startup" | F018, F016 | high | gate scope read directly |
| C11 | No Redis → Postgres data migration or `migration=` flag exists; `migrate_store` and `apply_studio_migrations` are the precedents | F010, F020 | high | grep + wiki query, both empty for the pattern |
| C12 | A startup migration needs idempotency and a cross-worker lock | F010, F002 | medium | inferred from multi-worker startup and the Studio runner's advisory lock |
| C13 | `test_botmanager_flags.py` pins `bm.crew_redis` and the `CrewRedis` patch target | F015, F008 | high | symbols verified by probe |
| C14 | Both crew persistence READMEs document the pre-tenant key layout | F009 | high | direct read |
| C15 | `CrewRedis` writes naive `datetime.utcnow()` while model defaults are tz-aware | F003, F001 | high | anchors at `redis_persistence.py:235` and `:538` |
| C16 | `creation.sql` and `_load_database_bots` are byte-frozen, so crew DDL and rehydration live elsewhere | F018, F017 | high | gate test read |
| C17 | `default_dsn` is `None` when DB settings are absent; `CREW_RESULT_STORAGE*` is the naming precedent | F007 | high | `conf.py` read |
| C18 | Persistence write failures are logged and swallowed, leaving the crew memory-only | F001, F002 | high | `save_crew` / `add_crew` read |

Distribution: **15** high, **3** medium, **0** low.

> Overall confidence stays **medium**: localization and the median claim are high, but three
> design-level claims (C6, C9, C12) are inferences, and two behaviours are left for the spec (§5).

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Once Postgres is enabled, which store is the source of truth?** — *Resolved*: Postgres
  primary: reads and writes go to Postgres; Redis is a read-only fallback for crews not yet migrated.
  *Resolves claims*: C3, C12
- [x] **U2 — Does "mover" delete the Redis keys or keep them?** — *Resolved*: copy, re-read each crew
  from Postgres to verify it, then delete its Redis keys.
  *Resolves claims*: C18
- [x] **U3 — Where does the migration run?** — *Resolved*: in `BotManager.load_crews` at startup when
  `migration=True`, serialized across workers with a pg advisory lock and idempotent via upsert.
  *Resolves claims*: C10, C12
- [x] **U4 — How is `navigator.crew_definitions` created?** — *Resolved*: the store auto-creates it
  (`CREATE SCHEMA/TABLE IF NOT EXISTS` in-module, `PgUISurfaceStore` idiom).
  *Resolves claims*: C10
- [x] **U5 — Where do the flags live, and which DSN?** — *Resolved*: `parrot.conf` keys
  (`CREW_DEFINITION_STORAGE`, `CREW_DEFINITION_MIGRATION`, `CREW_DEFINITION_PG_DSN` → `default_dsn`),
  overridable by `BotManager` / store kwargs.
  *Resolves claims*: C9, C17

### Unresolved (defer to spec / implementation)

- [ ] **Conflict during migration** — a `(tenant, name)` already in Postgres and also in Redis: keep
  the Postgres row (it is the source of truth) and still delete the Redis copy, or compare `updated_at`?
  — *Owner*: tbd
  *Blocks claims*: C12
  *Plausible answers*: a) Postgres wins, Redis copy deleted · b) newer `updated_at` wins
- [ ] **Postgres unreachable or no DSN while `CREW_DEFINITION_STORAGE=postgres`** — fail closed at
  startup (Studio precedent) or degrade to Redis-only with a warning? — *Owner*: tbd
  *Blocks claims*: C9
  *Plausible answers*: a) fail closed · b) degrade to Redis with a loud warning

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-860`** — *Rationale*: localization is high-confidence and the request already fixes
the architecture (Redis + Postgres store + migration flag); the policy forks (U1–U5) were answered in this
proposal, leaving two behaviours for the spec to pin down.

### Alternatives

- **`/sdd-brainstorm FEAT-860`** — to explore a different shape (for example a generic pluggable
  `CrewDefinitionStorage` ABC + factory like `ResultStorage`) before writing the spec.
- **`/sdd-task FEAT-860`** — not suitable: the change spans `BotManager`, a new store, config, docs and
  tests.
- **Manual review** — not needed; research completed without truncation.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-860/state.json` |
| Source (raw) | `sdd/state/FEAT-860/source.md` |
| Research plan | `sdd/state/FEAT-860/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-860/findings/F001-*.md` … `F021-*.md` (lane originals in `findings/.audit/`) |
| Synthesis (JSON) | `sdd/state/FEAT-860/synthesis.json` |
| Synthesis reasoning | not persisted |

**Budget consumed**:
- Files read: 15 / 40
- Grep calls: 17 / 25
- Git calls: 10 / 10
- Wall time: 333.6s / 300s (the codebase lane exceeded its 255s quota; all queries completed)
- Truncated: **no**

**Research mode**: three parallel lanes (codebase 12 findings, git 3, wiki 14), merged 29 → 21 findings;
99 citations probed, 98 verified, 1 ambiguous (the `utcnow` anchor matches two lines).

**Mode determination**: `auto` → resolved to `enrichment` (additive verbs: "definir", "mover",
"re-hidratar").

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Claude Code (Opus 5.5) for Jesus Lara |
