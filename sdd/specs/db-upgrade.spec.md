---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server]
tags: [database, schema-migrations, cli, ai-bots, postgres]
docs:
  policy: required
  pages: [wiki/deployment/database-migrations.md]
  api_modules: [parrot.migrations.catalog, parrot.migrations.runner, parrot.migrations.checks]
---

# Feature Specification: Packaged PostgreSQL migrations

**Feature ID**: FEAT-884
**Date**: 2026-11-12
**Author**: Jesus Lara / Codex
**Status**: approved
**Target version**: next minor release

## 1. Motivation & Business Requirements

### Problem Statement

BotModel evolves independently of hand-run SQL and the destructive creation.sql bootstrap. Missing
columns break bot loading, and deployed databases have unknown combinations of legacy columns and
partially applied changes. Provide `parrot self migration` to discover packaged SQL, report its state,
apply it transactionally at deployment, and adopt verified existing installations.

Source: `sdd/proposals/db-upgrade.proposal.md`, including the accepted review corrections. FEAT-884
was allocated for this slug by reservation commit `35a395efb200f75781534907d3fc0336f5035f24`;
the proposal/state already owns that allocation. This is its first spec, not a multi-spec ID reuse.

### Goals

- Ship migrations in wheels, discover distribution-contributed sets, and track immutable files in a ledger.
- Support fresh, legacy, fully folded and partially folded bots schemas without losing configuration.
- Establish explicit ownership for the selected server runtime tables; retain first-use compatibility.
- Provide status, upgrade, baseline and new verbs, read-only doctor diagnostics, and startup warnings.
- Preserve separate Studio and task-memory migration mechanisms.

### Non-Goals (explicitly out of scope)

- Down migrations, non-PostgreSQL databases, new database dependencies, or application-startup migration execution.
- Studio ledger adoption, task-memory migration changes, arbitrary per-collection/database storage schemas.
- Unrelated domain seeds or automatic migration of users_bots; preserve its split manual embedding fold.
- Modifying BotModel fields, its legacy hydration shim, or BotManager._load_database_bots.

## Governing Decisions

<!-- decision-audit: input_digest=sha256:2fdf73f3ea2e476583317db8068a713431c8e36408c5f12feb08a38a453ef4d8 evaluation_digest=sha256:93bae0e2bb2512d09e36b867bce2b530f3820899ae803fe1a1d41dd3b80cf805 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

The new core `parrot.migrations` package owns discovery, rendering, reporting and execution. It has no
import-time database connection or server dependency. Core contributes `bots`; server contributes five
sets through the `parrot.migrations` entry-point group. Entry points return metadata only and never
import application handlers to discover SQL. Resources are loaded with `importlib.resources`.

Commands operate on the interpreter/environment in which `parrot` runs; they do not silently dispatch
to another managed virtualenv. Help distinguishes database schema migration from `self update`.

```text
self migration ── catalog ── installed distribution entry points ── packaged SQL
       │
       └── runner ── dedicated asyncpg connection ── PostgreSQL + parrot_schema_migrations
startup / doctor ── checks ── read-only transaction ── ledger and schema postconditions
```

### Ownership inventory and targets

| Set | Distribution | Owned tables | Verified source |
|---|---|---|---|
| bots | ai-parrot | configured PARROT_SCHEMA.PARROT_BOTS_TABLE | core models/bots.py:100, :461 |
| ui_surfaces | ai-parrot-server | navigator.ui_surfaces, navigator.ui_surface_shares | handlers/models/ui_surfaces.py:107 |
| crew_definitions | ai-parrot-server | navigator.crew_definitions | handlers/crew/postgres_persistence.py:21 |
| metric_definitions | ai-parrot-server | navigator.metric_definitions | handlers/models/metric_definitions.py:21 |
| recipes | ai-parrot-server | navigator.infographic_recipes | handlers/models/recipes.py:39 |
| scheduler | ai-parrot-server | navigator.service_scheduler | scheduler/models.py:21 |

These are the exact v1 managed sets. Server paths above are relative to
`packages/ai-parrot-server/src/parrot/`; core paths to `packages/ai-parrot/src/parrot/`.
The proposal's inventory mixed runtime DDL with model-docstring SQL: `service_scheduler` is included
explicitly even though the inspected declaration is a docstring. Studio already owns `studio_drafts`
and `ai_skills_catalog` (migrations 0005 and 0004); neither gets a new-set baseline or ledger entry.
Task-memory keeps its own migration owner. Core flow result/checkpoint and harness stores use
unqualified or dynamically selected tables and separate DSNs, and knowledge catalogs use dedicated
schemas (manuals/contracts/parrot_memory); they are not silently adopted as navigator tables.
Other distributions may contribute future sets without extending this v1 inventory.

Retain existing runtime create-on-first-use paths unchanged for compatibility. They never stamp the
new ledger. Packaged baselines match the current runtime DDL (including existing additive ALTERs),
and parity tests prevent divergence. Future evolution belongs to versioned files. The existing
runtime paths are not called by this runner; deploy with writers stopped to avoid competing DDL.
No new DDL runs at application startup. Recipes v1 covers the default navigator schema only; custom
PgRecipeStore schemas remain explicitly outside this inventory. Server sets retain their fixed
navigator targets even when PARROT_SCHEMA changes, matching current runtime SQL.

### Catalog, rendering and ledger

- Entry-point name equals set name; factory signature `() -> MigrationSet`. Duplicate names, absent
  resources, invalid identifiers, invalid sequence numbers and invalid UTF-8 are configuration errors.
- Each set contains `sql/<set>/NNN_<name>.sql` and paired `NNN_<name>.check.sql`. Only body files enter
  the sequence. Numbers start at 001 and are contiguous; checks must have a matching body. Sort by
  numeric sequence within a set and by set name between independent sets. There are no cross-set
  dependencies in v1; ui_surface_shares follows ui_surfaces inside the same file.
- Check files return exactly one boolean column and one row. They verify current postconditions,
  including required columns/types/nullability, defaults, keys/indexes/triggers, and data invariants
  for folds. Execute checks in read-only transactions (or SET TRANSACTION READ ONLY for baseline).
  Before executing a check, the verifier probes its set's target relations through pg_catalog; a
  missing relation returns a failed postcondition without parsing SQL that names the absent table.
  Checks must remain valid after later files; 001 does not assert a default later removed by 005.
- Body checksum is sha256 of exact shipped bytes; `check_checksum` separately covers check bytes.
  A change in either is CHANGED. No platform newline normalization. Published files are immutable;
  normal fixes add a numbered successor. `--reapply-changed` is an explicit repair escape hatch.
- Replace only exact `{schema}` / `{bots_table}` tokens, never Python `str.format` on SQL containing
  JSON paths or object literals. Validate each configured identifier against `[a-z_][a-z0-9_]{0,62}`;
  quote identifiers at use sites and reject invalid values before connection. Each SQL token has a
  documented identifier or literal context; catalog existence queries use bound values where possible.
  Do not split statements on semicolons: execute the complete body, preserving DO/function blocks.
  Strip historical transaction wrappers during conversion, not dynamically at runtime.
- Ledger: `<PARROT_SCHEMA>.parrot_schema_migrations`, primary key `(migration_set, filename)`,
  columns `checksum text NOT NULL`, `check_checksum text NOT NULL`, `target_identity jsonb NOT NULL`,
  `applied_at timestamptz NOT NULL DEFAULT now()`, `applied_by text NOT NULL DEFAULT current_user`,
  `operation text NOT NULL CHECK (operation IN ('upgrade','baseline','reapply'))`.
  Identity records the fully qualified owned tables. A target change for an already recorded set is
  a configuration error, not a clean status for another table. Ledger table name is reserved and
  cannot equal a target table. Different configured ledger schemas still share one database-wide lock.
- Missing ledger means all selected files PENDING. Unknown ledger filenames in a selected set are an
  error (possibly older code); do not delete or ignore them. Unselected/uninstalled sets are not failures.
  Matching checksums are APPLIED, but failed postconditions also make the report unhealthy; status is
  not proof of health from checksums alone. Missing objects return false, not a SQL name-resolution crash.

### Connection, locking and failure semantics

Use existing asyncpg (available via asyncdb) on a dedicated connection, never asyncdb execute's
error-as-return-value API. Database work is async; only the synchronous Click boundary uses asyncio.run.
PostgreSQL >=14 is required; fresh UUID defaults use gen_random_uuid(), avoiding uuid-ossp installation.
Keep compatible existing UUID defaults; existing defaults must resolve to a usable function.

Mutating DSN precedence: explicit `--dsn`, `PARROT_ADMIN_DSN`, runtime `default_dsn`. Log a credential-free
fallback notice when using the runtime DSN. Read-only commands/probes use explicit `--dsn` or runtime
`default_dsn`, never implicitly elevate to the admin DSN. Missing DSN is CLI configuration exit 3;
unconfigured doctor is informational. The default_dsn construction is not changed in this feature.

Acquire `pg_try_advisory_lock(884000001)` with an asyncio sleep/retry loop and a monotonic deadline
(default 30 seconds), before creating the schema/ledger or taking an execution snapshot. Unlock in
finally; always close the dedicated connection on success, failure or cancellation. Connection timeout
is 5 seconds; DDL lock timeout 5 seconds; statement timeout 60 seconds, configurable through CLI options
`--connect-timeout`, `--lock-timeout`, `--statement-timeout` (positive seconds). Startup's total budget
is 2 seconds and doctor's is 5 seconds. Transaction failure rolls back SQL and ledger writes together.

Read ledger state again while holding the advisory lock. One transaction per body + postcondition
check + ledger insert/update. Failed postconditions fail the migration. On failure, stop the current
set (successor files are dependent); without --fail-fast continue other selected independent sets.
With --fail-fast stop the whole run. Report FAILED/SKIPPED outcomes separately from catalog states;
any failure returns 2 even if other sets succeeded. Cancellation propagates after cleanup.
Changed files block their set unless explicitly reapplying; a reapply updates checksums only after
body and postconditions succeed. Reapply in sequence, then recheck the entire selected set to detect
regressions caused by replaying older SQL. Do not continue a set after an unacknowledged changed file.

Migration errors contain set/filename, SQLSTATE and a safe category, never raw DSNs, driver exception
text, SQL bodies, parameter values or tracebacks. Runtime-role DML, schema USAGE and ledger SELECT
grants remain DBA-owned; documentation explains them, and permission errors never masquerade as
pending/clean state. No automatic broad grants or credential-file writes.

### Bots migration chain and adoption

| File | Required effect |
|---|---|
| 001_baseline.sql | Complete current 49-field CREATE-if-missing, then additive catch-up; guarded indexes, constraints and schema-qualified updated_at function/trigger; no example rows |
| 002_fold_embedding.sql | ai_bots-only guarded embedding backfill, normalize model to model_name, then drop the legacy column |
| 003_fold_llm.sql | Independently guard each legacy tuning column, backfill absent JSONB keys, mirror model_name to model, then drop that source column |
| 004_tool_names.sql | Existing order-preserving WebScraperTool/Ibis/Tickertool remapping, preserving other array elements |
| 005_language_schema.sql | Drop language DEFAULT and NOT NULL if present; retain every stored language value |

001 derives full columns from BotModel and creation.sql, incorporates prompt_config/tooling/homologate/
FEAT-752 additions, and contains no DROP TABLE or sample-data insertion. Existing rows must survive.
For missing required foundational columns on a non-empty incompatible table, fail with a clear schema
precondition rather than invent identities or overwrite data. Add missing optional/defaulted fields;
report incompatible existing types/constraints instead of destructively coercing them. Index and
constraint names are scoped to the configured bots table; multiple custom tables cannot collide.

Fold guards check each source column in the configured table before executing SQL that references it.
Explicit destination JSONB keys win, including explicit JSON null. Preserve existing model aliases;
normalization still runs if the source column is already absent. Backfill and drop are atomic. Tests
must snapshot values before migration to prove preservation; absence of a source column alone cannot
prove that an earlier manual migration retained its data.

Convert and remove the eight superseded ai_bots upgrade scripts listed in §6. Exclude the destructive
botmodel-recreate-table.sql from the chain; leave it as a manual file with a warning and command pointer.
Split the embedding script's users_bots portion into a separate manual file with relation/column guards.
The historical FEAT-638 file also modifies users_bots and clears language='en' on both tables. Preserve
those operations in a separately named manual language-reset script, with the lossy behavior explicit;
they do not run automatically. This preserves the legacy operation for operators without silently
changing stored preferences. The packaged bots chain must not reference users_bots at all.

Retain creation.sql as a fresh-install-only compatibility artifact, add the five missing suggestion
fields, and replace obsolete migration pointers with the command. It is not a required bootstrap for
upgrade. Register exact sanctioned text deltas in the freeze gate; do not weaken the gate or modify
BotModel's embedded DDL. The new baseline is the authoritative deployment path.

### CLI contract

Options appear after the verb. `--set NAME` is repeatable for status/upgrade; default is bots, so installing
the server wheel cannot silently migrate optional stores or a crew DSN. `--all` selects all installed
sets on the one explicitly targeted database; mutually exclusive with --set. Unknown/uninstalled sets
are exit 3 with an install hint. Crew deployments with a separate CREW_DEFINITION_PG_DSN run the crew
set explicitly against that database. Output always identifies selected sets, target tables and ledger.

| Command | Contract |
|---|---|
| status [--set NAME ... / --all] [--dsn DSN] | Read-only, 0 healthy, 1 pending/changed/postcondition drift, 2 database/unknown-ledger error, 3 configuration |
| upgrade [selection] [--dsn DSN] [--fail-fast] [--reapply-changed] | Apply pending; 0 healthy completion, 1 blocked by unacknowledged changes, 2 failed, 3 config |
| baseline --set NAME --through NNN [--dsn DSN] | Explicit single-set prefix only; verify every selected postcondition before recording any new rows; no SQL bodies; reject changed or unknown entries |
| new SET NAME --directory PATH [--dsn DSN] | Local scaffolding; --dsn accepted for uniformity but unused; no connection; explicit source directory, no writes into installed wheels |

Baseline takes the same lock, verifies in a read-only transaction, then atomically creates needed
ledger objects and records the verified prefix in a write transaction. Hold the advisory lock across
both; deployment must be quiescent because the lock does not block application writers. Recheck schema
identity before commit. No --force verification bypass. Later files remain pending. Normal repeat
baseline is a no-op for identical recorded entries. Data-loss recovery is never implied by stamping.

New validates SET and snake_case NAME, verifies an existing set directory, computes max(sequence)+1,
and exclusively creates a body/check pair. The generated body has only a descriptive comment; the
check is SELECT FALSE with a comment requiring a real postcondition, so an unfinished scaffold cannot
be recorded as applied. If either exclusive create fails, retain any created file with a clear partial
scaffold error; never overwrite existing files. Entry-point registration is a separate documented step.

### Read-only integrations

Register a lightweight `migration` group in self_/cli.py with local imports of the new CLI on actual
execution; help must work without asyncpg/server imports. Extend doctor in its existing CLI boundary:
after run_doctor, append the migration DoctorCheck only outside runtime-only scope. This avoids
introducing asyncio.run into the reusable synchronous doctor library. The check is informational;
explicit status remains the deployment gate. Unconfigured, unavailable and drift states are distinct.

In BotManager.load_bots, inside `if self.enable_database_bots`, await the bounded bots-only warning
before calling the unchanged _load_database_bots. Use the same runtime default_dsn and configured bots
target. Fail open on probe errors/timeouts, with sanitized warnings; propagate cancellation. No probe
when database bots are disabled. Startup and doctor never CREATE the ledger or acquire a migration
lock; missing ledger is reported through SELECT-only probes.

## 3. Module Breakdown

All paths use workspace distribution roots, not a top-level parrot directory. Public interfaces below
are new unless marked verified. Interface bodies intentionally belong to task implementation blueprints.

### M1: Catalog, models and core provider

Paths: core `parrot/migrations/{__init__,models,catalog,providers}.py`; core pyproject entry points and
package data. Own immutable Pydantic models, identifier rendering, deterministic resource loading and
scaffolding. No network calls. Depends on standard library, Pydantic and existing packaging conventions.

```python
class MigrationSet(BaseModel):
    """Resource owner: name, package, resource_dir, and tuple of qualified target tables."""
    name: str
    package: str
    resource_dir: str
    tables: tuple[str, ...]

class MigrationFile(BaseModel):
    """Loaded immutable body/check pair with SHA256 values and sequence."""
    migration_set: str
    filename: str
    sequence: int
    sql: str
    check_sql: str
    checksum: str
    check_checksum: str

class MigrationItem(BaseModel):
    """One file's APPLIED/PENDING/CHANGED state, postcondition result and safe diagnostic."""
    migration_set: str
    filename: str
    state: Literal["APPLIED", "PENDING", "CHANGED"]
    postcondition_ok: bool | None
    diagnostic: str | None

class MigrationReport(BaseModel):
    """Safe structured result; never stores credentials or raw driver errors."""
    items: list[MigrationItem]
    applied: list[str]
    failed: list[str]
    skipped: list[str]
    diagnostics: list[str]
    exit_code: Literal[0, 1, 2, 3]

def bots_set() -> MigrationSet:
    """Return bots metadata without importing BotModel or server code."""

def discover_sets() -> tuple[MigrationSet, ...]:
    """Load sorted parrot.migrations entry points; reject ambiguous providers."""

def load_migrations(migration_set: MigrationSet) -> tuple[MigrationFile, ...]:
    """Validate and load contiguous paired resources, excluding check files from ordering."""

def render_sql(sql: str, *, schema: str, bots_table: str) -> str:
    """Replace documented tokens only after identifier validation; preserve JSON braces."""

def scaffold(set_name: str, name: str, *, directory: Path) -> tuple[Path, Path]:
    """Exclusively create the next body/check pair in a caller-selected source directory."""
```

MigrationSet factories resolve configured bots names lazily. Freeze models with ConfigDict(frozen=True).
Define `MigrationConfigurationError(ValueError)` in models.py; boundary mapping is exit 3.
New SQL creates no application-model instances during discovery.

### M2: Runner and postcondition checks

Paths: core `parrot/migrations/{runner,checks}.py`. Depends on M1. Own raw asyncpg connection lifecycle,
lock, ledger and transaction rules. checks.py is the sole shared SELECT-only path for status and probes;
it never imports mutation functions from runner.py.

```python
async def status(dsn: str, *, sets: tuple[MigrationSet, ...], connect_timeout: float = 5.0,
                 statement_timeout: float = 60.0) -> MigrationReport:
    """Read selected ledger/check state without creating schema objects or taking a write lock."""

async def verify_postconditions(conn: asyncpg.Connection, migrations: tuple[MigrationFile, ...],
                                *, schema: str, bots_table: str) -> tuple[str, ...]:
    """Return failed file identities; check SQL must return exactly one boolean value."""

async def upgrade(dsn: str, *, sets: tuple[MigrationSet, ...], fail_fast: bool = False,
                  reapply_changed: bool = False, connect_timeout: float = 5.0,
                  lock_timeout: float = 30.0, statement_timeout: float = 60.0) -> MigrationReport:
    """Apply ordered files and ledger records atomically under a bounded session lock."""

async def baseline(dsn: str, *, migration_set: MigrationSet, through: int,
                   connect_timeout: float = 5.0, lock_timeout: float = 30.0,
                   statement_timeout: float = 60.0) -> MigrationReport:
    """Verify and stamp only an explicit prefix; reject changed/unknown history."""
```

Each runner resolves PARROT_SCHEMA/PARROT_BOTS_TABLE once per invocation. Target identity is checked
against ledger rows before body execution. Postcondition checks for missing relations use guarded
catalog probes, so newly pending migrations can be inspected safely.

### M3: Packaged bots SQL and legacy conversion

Paths: core migrations/sql/bots (five pairs named in §2), conversion/removal sites in §6,
server creation.sql and its sanctioned rewrite gate. Depends on M1's rendering/check contract.
Interface: each numbered body is a transaction-free PostgreSQL script; each paired check is a
SELECT-only single-boolean postcondition compatible with all later files. No Python public callable.
Document source provenance in SQL comments. New tests cover data survival, object shape and users_bots
isolation. No changes to BotModel or its shim.

### M4: Server providers and runtime baselines

Paths: server `parrot/server/migrations/{__init__,providers}.py`, five SQL/check pairs, server pyproject.
Depends on M1. Keep runtime DDL modules unchanged; test parity against their verified declarations.

```python
# All new, in parrot.server.migrations.providers

def ui_surfaces_set() -> MigrationSet:
    """Own navigator.ui_surfaces and ui_surface_shares in one ordered baseline."""

def crew_definitions_set() -> MigrationSet:
    """Own navigator.crew_definitions; never migrate Redis or execution-result stores."""

def metric_definitions_set() -> MigrationSet:
    """Own navigator.metric_definitions including partial uniqueness indexes."""

def recipes_set() -> MigrationSet:
    """Own the default navigator.infographic_recipes schema only."""

def scheduler_set() -> MigrationSet:
    """Own navigator.service_scheduler, deriving all current model fields and indexes."""
```

Fresh and existing-runtime baselines must converge on the same schema; additive catch-up must precede
indexes referencing new columns. Existing incompatible data causes explicit failure, never silent
constraint removal. Entry-point names match these set names (recipes/scheduler, not function names).

### M5: CLI, configuration and read-only integration

Paths: core migrations/{cli,startup}.py, core self_/cli.py and conf.py, server manager/manager.py.
Depends on M1/M2. Add optional `PARROT_ADMIN_DSN = config.get("PARROT_ADMIN_DSN")` alongside DB config;
no default_dsn change. CLI resolves mutation/read DSNs separately and maps errors to §2 exit codes.

```python
# New in parrot.migrations.cli; Click adapters expose exactly the verbs/options in §2.
def migration_group() -> None:
    """Manage packaged PostgreSQL schema migrations in the active Python environment."""

def resolve_dsn(explicit: str | None, *, mutating: bool) -> str:
    """Resolve mode-specific precedence; raise MigrationConfigurationError if absent."""

# New in parrot.migrations.startup; local imports keep normal startup/CLI help lightweight.
async def warn_pending_migrations(dsn: str | None, *, logger: logging.Logger) -> None:
    """Bound bots-only SELECT probes to two seconds; warn without blocking startup."""

async def migration_doctor_check(dsn: str | None) -> DoctorCheck:
    """Return a five-second informational result, including an explicit unconfigured state."""
# DoctorCheck verified: packages/ai-parrot/src/parrot/self_/doctor.py:39

# Existing signatures retained:
def self_group() -> None:
    """Register the lightweight migration group alongside current self commands."""
# verified: packages/ai-parrot/src/parrot/self_/cli.py:18

def doctor(sdd_scope: bool, runtime_only: bool) -> None:
    """Append the migration check at the synchronous CLI boundary outside runtime-only scope."""
# verified: packages/ai-parrot/src/parrot/self_/cli.py:61

async def load_bots(self, app: web.Application) -> None:
    """Warn before enabled database loading; retain the existing bot-loading behavior."""
# verified: packages/ai-parrot-server/src/parrot/manager/manager.py:464
```

### M6: Validation and documentation

Paths: new core/server migration tests, existing self CLI test, and the wiki page in §10. Depends on
M1–M5 for integration; test fixtures may be prepared independently. Interface skeletons (test contracts):

```python
async def test_fresh_and_partial_bots_upgrade() -> None:
    """Exercise every supported starting shape and assert configuration/row preservation."""

async def test_upgrade_lock_and_rollback() -> None:
    """Competing connections apply once; failed SQL and cancellation leave no partial ledger row."""

async def test_runtime_baseline_parity() -> None:
    """Compare migrated tables with existing runtime declarations and prove Studio isolation."""

def test_wheels_contain_migrations() -> None:
    """Built core/server wheels expose all registered paired SQL resources without repository files."""
```

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 | yes | entry-point group, frozen models, paired resources, literal token renderer | — |
| M2 | no | APIs and transaction/lock/error rules fixed above | SQL adoption and concurrency need adversarial implementation review |
| M3 | no | five-file chain and no-loss rules fixed | destructive legacy conversion needs careful state-matrix verification |
| M4 | yes | five factories, fixed targets, parity fixtures, one baseline pair per set | — |
| M5 | yes | verb table, precedence, bounded informational probes and exact attachment sites | — |
| M6 | yes | validation matrix and documentation content fixed | — |

## 4. Test Specification

### Unit Tests

| Test group | Module | Required cases |
|---|---|---|
| Catalog | M1 | deterministic ordering, duplicates, missing entry points/resources, gaps, check pairing, invalid identifiers, JSON braces, immutable bytes/checksums |
| Scaffolding | M1 | sequence allocation, traversal rejection, no overwrite, partial pair failure, no DB contact |
| Runner fakes | M2 | rollback, cancellation, bounded lock timeout, stop failed set, continue independent set, safe errors |
| CLI | M5 | all four verbs, help without server/asyncpg import, selection, timeout validation, DSN precedence, exact exit codes |
| Probes | M5 | disabled/unconfigured, missing ledger, drift, inaccessible DB, timeout, cancellation; no DDL or mutation imports |
| Packaging | M1/M4 | built wheel resources and metadata for core-only and core+server installations |

### Integration Tests

| Scenario | Assertions |
|---|---|
| Fresh PostgreSQL >=14 | full bots chain, every BotModel column and required object, no uuid-ossp/manual bootstrap, no example data |
| Legacy / partial / current | individual source columns present/absent, nullable JSON config, explicit JSON keys win, normalized embedding/model aliases, rows/values retained |
| Language migration | existing en/es/NULL values unchanged, no default and nullable after migration |
| Alternate target | non-default schema/table work, valid quoted SQL, target identity mismatch rejected, index names do not collide |
| users_bots isolation | absent table succeeds; sentinel rows/table shape unchanged when present; no packaged users_bots SQL |
| Atomic failures | error between backfill and drop rolls back both; failed checks do not stamp; cancellation releases lock |
| Concurrency | two fresh runners create ledger safely and apply each file once; bounded losing contender |
| Baseline | explicit prefix only, missing postcondition fails without stamps, changed/unknown rejected, remaining files pending |
| Changed/unknown | body or check change detected; explicit reapply required; unknown selected-set filename rejected |
| Runtime sets | fresh and pre-existing schema parity including ui tenant ALTERs, crew tombstones/keys, metrics partial indexes |
| Separate ownership | Studio ledger/tables untouched; runtime fallbacks do not mark migrations applied |
| Roles | read-only status needs no DDL rights; missing SELECT is unavailable; runtime/admin precedence never leaks credentials |
| Repeat | second upgrade no-op, directly replay idempotent bodies on completed schema to test adoption independently of ledger skipping |

Use isolated disposable PostgreSQL databases selected only by PARROT_MIGRATION_TEST_DSN; never application
DSNs. Local tests may skip without that variable, but release/feature verification must run the live
matrix and reject missing evidence. No live LLM or external service is involved. Each test database has
its own ledger; concurrency tests deliberately share one. Record logs under artifacts/logs/.

### Validation Contract

tests:
- packages/ai-parrot/tests/self_/test_self_cli.py
- packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py
- packages/ai-parrot/tests/migrations/test_catalog.py
- packages/ai-parrot/tests/migrations/test_runner.py
- packages/ai-parrot/tests/migrations/test_cli.py
- packages/ai-parrot/tests/migrations/test_startup.py
- packages/ai-parrot/tests/migrations/test_bots_db.py
- packages/ai-parrot/tests/migrations/test_runner_db.py
- packages/ai-parrot/tests/migrations/test_packaging.py
- packages/ai-parrot-server/tests/migrations/test_runtime_baselines.py
- packages/ai-parrot-server/tests/migrations/test_runtime_db.py
- packages/ai-parrot-server/tests/migrations/test_startup.py
- packages/ai-parrot-server/tests/migrations/test_packaging.py
- packages/ai-parrot/tests/migrations/test_checks.py
- packages/ai-parrot/tests/migrations/test_bots_baseline.py
- packages/ai-parrot/tests/migrations/test_legacy_conversion.py
- packages/ai-parrot-server/tests/migrations/test_ui_crew_baselines.py
- packages/ai-parrot/tests/migrations/test_documentation.py
markers: none

### Validation Contract Notes

The task decomposition splits checks, baseline, legacy-conversion and UI/crew parity tests into
the additional files listed above. The documentation test runs the required techwiki CLI check
through pytest because the task graph does not register that CLI as a test runner.

The first two operands exist and guard CLI integration and the frozen database loader. The migration
operands are explicit CREATE deliverables in §6, not claims of existing tests. Task decomposition must
create their test scaffolding before enabling this complete contract; feature closeout requires the
entire matrix. It must not silently reduce the contract to the two pre-existing files.

### Test Data / Fixtures

A fresh DB, an old 44-column bots table, missing FEAT-593/752 fields, a pre-fold table with independent
scalar and JSON values, mixed already-dropped columns, explicit JSON null, SQL NULL configs, a malformed
incompatible schema, users_bots sentinels, and runtime baseline schemas. Snapshot rows before each
migration; compare required retained values afterward, not just column counts. No production data.

## 5. Acceptance Criteria

- [ ] Core-only and server-installed wheels discover exactly their registered sets and ship all SQL/check pairs.
- [ ] Status performs SELECT-only work and distinguishes pending, changed, drift, unknown history and unavailable DB.
- [ ] Fresh, legacy, partial and current bots schemas converge safely; all 49 model fields and required objects exist.
- [ ] All configuration values survive folds under the specified precedence; language values remain unchanged.
- [ ] No automatic bots migration references users_bots; both split manual operations remain available.
- [ ] Concurrent runners apply once; SQL, checks and ledger are atomic; failures block dependent successors.
- [ ] Baseline cannot stamp unverified/changed history and leaves later files pending; reapply is explicit.
- [ ] Invalid identifiers/sets/DSNs return safe configuration errors; no logs expose credentials or SQL data.
- [ ] Five server runtime sets match their schemas; Studio/task-memory retain sole ownership of their tables.
- [ ] Startup is bounded, bots-enabled-only and SELECT-only; doctor runtime-only remains offline.
- [ ] BotManager._load_database_bots and BotModel DDL/shim remain unchanged; exact creation.sql rewrites pass the freeze gate.
- [ ] Unit, wheel and disposable-Postgres matrix evidence passes; skipping live tests alone cannot satisfy closeout.
- [ ] Documentation page in §10 explains adoption, roles, optional stores, deployment order and recovery.

## 6. Codebase Contract

### Verified Imports and Existing Signatures

Imports verified by declaration reads (not by importing modules with startup side effects):

```python
from parrot.conf import default_dsn, PARROT_SCHEMA, PARROT_BOTS_TABLE
# verified: packages/ai-parrot/src/parrot/conf.py:65 and :121
from parrot.models.bots import BotModel
# verified: packages/ai-parrot/src/parrot/models/bots.py:100; tests only
from parrot.self_.doctor import DoctorCheck, run_doctor
# verified: packages/ai-parrot/src/parrot/self_/doctor.py:39 and :766
from parrot.self_.cli import self_group
# verified: packages/ai-parrot/src/parrot/self_/cli.py:18
```

DoctorCheck has name:str, ok:bool, detail:str="", fix:str="", informational:bool=False.
`run_doctor(root: Path, *, scope: DoctorScope="full", install_root: InstallRoot | None=None)
-> list[DoctorCheck]` is synchronous; do not change that signature or put asyncio.run in it.
`BotManager.load_bots(self, app: web.Application) -> None` is async (:464);
`_load_database_bots(self, app: web.Application) -> None` is async and frozen (:689).
BotModel.Meta names the configured table/schema, strict=True (models/bots.py:461).
The new code imports asyncpg lazily; it is already a dependency through asyncdb>=2.16.2 in core
pyproject.toml:137, with asyncpg>=0.29 also explicitly used by existing extras (:301, :308).
Pydantic>=2.12.5,<3 (:54) and Click>=8.1.7 (:149) already exist. No dependency additions.

### Integration Points

| New component | Connects to | Via | Verified at |
|---|---|---|---|
| CLI adapter | self_group | lightweight Click subgroup registration | packages/ai-parrot/src/parrot/self_/cli.py:132 |
| doctor probe | doctor | append DoctorCheck after existing run_doctor | packages/ai-parrot/src/parrot/self_/cli.py:74 |
| startup probe | BotManager.load_bots | enabled database branch before frozen loader | packages/ai-parrot-server/src/parrot/manager/manager.py:503 |
| SQL packaging | setuptools package-data | new explicit sql/*/*.sql patterns | packages/ai-parrot/pyproject.toml:1007; packages/ai-parrot-server/pyproject.toml:132 |
| ownership boundary | Studio migrations 0004/0005 | exclude ai_skills_catalog/studio_drafts | packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0004_ai_skills_catalog_tenancy.sql:6; 0005_studio_drafts_baseline.sql:4 |
| freeze compatibility | _SANCTIONED_REWRITES | exact old/new strings only | packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py:148 |

### Does NOT Exist (Anti-Hallucination)

- `parrot.migrations` and `parrot.server.migrations` do not exist at the verified base; every API here is new.
- No core PARROT_ADMIN_DSN or parrot_schema_migrations ledger currently exists.
- No `parrot/` directory at repository root. No server scheduler/store.py (the proposal inventory is not an API).
- Homologate SQL does not CREATE ai_bots. Existing fold scripts are not safe on already-dropped columns.
- Studio's `stamp_migrations` is release-time manifest rewriting, not a database adoption baseline.
- Model docstrings containing DDL do not establish that the DDL is executed at runtime.

### Edit Sites (Blueprint Anchors)

Verified against `e26309cf32ee39e07871ec11f1aebefc6de6392b` after the authorized merge.
Paths below are repository-relative. MODIFY/REMOVE anchors are exact full lines counted with grep -Fxc.
CREATE paths are planned, not claims that the files already exist. Downstream tasks must reverify anchors.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/self_/cli.py` | MODIFY | `self = self_group` | `packages/ai-parrot/src/parrot/self_/cli.py:132` | 1 |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `# Main Database:` | `packages/ai-parrot/src/parrot/conf.py:63` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `[tool.setuptools.package-data]` | `packages/ai-parrot/pyproject.toml:1007` | 1 |
| `packages/ai-parrot-server/pyproject.toml` | MODIFY | `[tool.setuptools.package-data]` | `packages/ai-parrot-server/pyproject.toml:132` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `        # Step 4: Load database bots` | `packages/ai-parrot-server/src/parrot/manager/manager.py:502` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/creation.sql` | MODIFY | `-- WARNING: Initial setup DDL only. DO NOT run against production.` | `packages/ai-parrot-server/src/parrot/handlers/creation.sql:1` | 1 |
| `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py` | MODIFY | `_SANCTIONED_REWRITES: tuple[tuple[str, str], ...] = (` | `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py:148` | 1 |
| `packages/ai-parrot/tests/self_/test_self_cli.py` | MODIFY | `def test_self_is_registered() -> None:` | `packages/ai-parrot/tests/self_/test_self_cli.py:13` | 1 |
| `sdd/migrations/botmodel-recreate-table.sql` | MODIFY | `-- Recreate navigator.ai_bots (BotModel) from scratch.` | `sdd/migrations/botmodel-recreate-table.sql:1` | 1 |
| `sdd/migrations/ai-bots-homologate-botmodel.sql` | REMOVE after conversion | `-- Homologate navigator.ai_bots with parrot.models.bots.BotModel` | `sdd/migrations/ai-bots-homologate-botmodel.sql:2` | 1 |
| `sdd/migrations/FEAT-add-prompt-config-ai-bots.sql` | REMOVE after conversion | `-- Add prompt_config to navigator.ai_bots` | `sdd/migrations/FEAT-add-prompt-config-ai-bots.sql:2` | 1 |
| `sdd/migrations/FEAT-593-ai-bots-tooling-columns.sql` | REMOVE after conversion | `-- FEAT-593 (TASK-3652): Agent Studio tooling columns on navigator.ai_bots.` | `sdd/migrations/FEAT-593-ai-bots-tooling-columns.sql:1` | 1 |
| `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql` | REMOVE after conversion | `-- FEAT-752 (TASK-4811): follow-up suggestion chip settings on navigator.ai_bots (Agent Studio).` | `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql:1` | 1 |
| `sdd/migrations/FEAT-fold-embedding-model-into-vector-store-config.sql` | REMOVE after conversion | `-- Fold embedding_model into vector_store_config / vector_config` | `sdd/migrations/FEAT-fold-embedding-model-into-vector-store-config.sql:2` | 1 |
| `sdd/migrations/FEAT-fold-legacy-llm-columns.sql` | REMOVE after conversion | `-- Fold legacy LLM-tuning columns into model_config` | `sdd/migrations/FEAT-fold-legacy-llm-columns.sql:2` | 1 |
| `sdd/migrations/FEAT-fix-stale-bot-tool-names.sql` | REMOVE after conversion | `-- Remap stale bot tool names to canonical TOOL_REGISTRY keys` | `sdd/migrations/FEAT-fix-stale-bot-tool-names.sql:2` | 1 |
| `sdd/migrations/FEAT-638-bot-language-nullable.sql` | REMOVE after conversion | ``-- FEAT-638: bot-level output language — `language` becomes nullable with no default.`` | `sdd/migrations/FEAT-638-bot-language-nullable.sql:1` | 1 |
| `packages/ai-parrot/src/parrot/migrations/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/models.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/catalog.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/providers.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/runner.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/checks.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/cli.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/startup.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/server/migrations/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/server/migrations/providers.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/001_baseline.sql` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/001_baseline.check.sql` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/002_fold_embedding.sql` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/002_fold_embedding.check.sql` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/003_fold_llm.sql` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/003_fold_llm.check.sql` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/004_tool_names.sql` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/004_tool_names.check.sql` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/005_language_schema.sql` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/005_language_schema.check.sql` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/ui_surfaces/001_baseline.sql` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/ui_surfaces/001_baseline.check.sql` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/crew_definitions/001_baseline.sql` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/crew_definitions/001_baseline.check.sql` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/metric_definitions/001_baseline.sql` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/metric_definitions/001_baseline.check.sql` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/recipes/001_baseline.sql` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/recipes/001_baseline.check.sql` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/scheduler/001_baseline.sql` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/scheduler/001_baseline.check.sql` | CREATE | — | — | — |
| `packages/ai-parrot/tests/migrations/test_catalog.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/migrations/test_runner.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/migrations/test_cli.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/migrations/test_startup.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/migrations/test_bots_db.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/migrations/test_runner_db.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/migrations/test_packaging.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/migrations/test_runtime_baselines.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/migrations/test_runtime_db.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/migrations/test_startup.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/migrations/test_packaging.py` | CREATE | — | — | — |
| `sdd/migrations/users-bots-fold-embedding.sql` | CREATE | — | — | — |
| `sdd/migrations/manual-bot-language-reset.sql` | CREATE | — | — | — |
| `packages/ai-parrot/tests/migrations/test_checks.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/migrations/test_bots_baseline.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/migrations/test_legacy_conversion.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/migrations/test_ui_crew_baselines.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/migrations/test_documentation.py` | CREATE | — | — | — |
| `wiki/deployment/database-migrations.md` | CREATE | — | — | — |

## 7. Implementation Notes & Constraints

### Patterns to Follow

Use Pydantic v2 for reports/configuration, async I/O, module loggers, strict type hints and Google-style
docstrings. Apply black (120 columns) and ruff. Keep new package imports lightweight and SQL resources
independent of repository checkout. Use no provider SDK, external migration framework or new dependency.
Existing runtime classes are evidence and parity targets, not imports for provider discovery.

### Known Risks / Gotchas

- Unknown production states: no live database was inspected. Unsupported types or broken data must
  fail explicitly; operators must repair them before stamping. Do not claim every historical schema
  is automatically recoverable. Backups and stopping writers are deployment prerequisites.
- Two ledgers are deliberate: new status names its ledger/selected sets and does not claim Studio is
  current. Documentation keeps `parrot-studio-migrate` as a separate deployment step.
- Existing runtime fallback DDL can race the runner and does not share its lock. Retain it for
  compatibility but perform upgrades while application writers are stopped. No retrofit of all
  runtime lifecycle hooks in this feature.
- Postcondition SQL must tolerate absent objects and remain valid after successors. Transaction-free
  bodies and SELECT-only checks are authoring rules enforced by file tests and read-only DB transactions.
- `baseline` cannot reconstruct data lost before this feature. It verifies observable postconditions
  only; it must never imply historical data recovery.
- Existing raw PostgreSQL defaults and JSON values require semantic comparison in tests, not brittle
  textual equality. Normalize equivalent DDL defaults but retain real type/constraint mismatches.
- Existing FEAT-638 resets intentional English settings and touches two tables. Only its schema
  change belongs in the automatic chain; preserve the original data operation as an explicit manual step.
- Tests must inject fake DSNs and not import configuration to contact any developer database.

### External Dependencies

| Package | Existing constraint | Usage |
|---|---|---|
| asyncdb | >=2.16.2 (core base) | already supplies asyncpg; existing runtime stores unchanged |
| asyncpg | already installed via asyncdb; existing extras use >=0.29 | dedicated migration connection, transactions and read-only checks |
| pydantic | >=2.12.5,<3 | frozen migration metadata and reports |
| click | >=8.1.7 | existing CLI integration |
| PostgreSQL | >=14 | same minimum as existing Studio migration runner |

No dependency or lockfile edits are required. If the installed asyncdb distribution does not supply
asyncpg in a supported build, fail with an install hint and resolve packaging explicitly before implementation;
do not silently add a different database driver.

## Worktree Strategy

- **Isolation**: per-spec; one feature worktree, with task sub-worktrees managed by the SDD engine.
- **Module graph**: M2 → M1 (MigrationSet/File/Report); M3 → M1 (render/check resource contract);
  M4 → M1 (MigrationSet factories); M5 → M1/M2 (selection/status/upgrade/baseline);
  M6 → M1/M2/M3/M4/M5 (end-to-end contract validation). M3 and M4 are independent.
- **Shared files**: core pyproject belongs to M1, server pyproject to M4, self_/cli.py/conf.py and
  manager.py to M5; M3 exclusively owns creation.sql and its sanctioned gate changes. M6 adds tests
  without editing those production files. Split tasks must preserve these ownership boundaries.
- **Exclusive resources**: live DB test tasks that share a PostgreSQL instance/database are
  `parallel: false`; isolated databases may run concurrently. No development or production migration
  is executed while implementing this feature. Wheel tests use per-task temporary build directories.
- **Cross-feature dependencies**: FEAT-860 crew storage is present at the verified base; no pending
  feature merge is required. Studio and task-memory ownership remains unchanged.

## Consequences

<!-- decision-audit: input_digest=sha256:2fdf73f3ea2e476583317db8068a713431c8e36408c5f12feb08a38a453ef4d8 evaluation_digest=sha256:93bae0e2bb2512d09e36b867bce2b530f3820899ae803fe1a1d41dd3b80cf805 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/db-upgrade.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: auth, bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: ai-bots, cli, database, postgres, schema-migrations
- Targets resolved: 0/0
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
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "ai-bots",
      "cli",
      "database",
      "postgres",
      "schema-migrations"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/db-upgrade.spec.md"
    }
  ],
  "evaluation_digest": "sha256:93bae0e2bb2512d09e36b867bce2b530f3820899ae803fe1a1d41dd3b80cf805",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:2fdf73f3ea2e476583317db8068a713431c8e36408c5f12feb08a38a453ef4d8",
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
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

### Resolved in proposal (verbatim)

- [x] **U1 — Which runner should `parrot self migration` build on?** — *Resolved*: navauth-style, Studio
  apart — new generic runner mirroring navauth (sets, `(set, filename)` ledger); Studio keeps its own ledger
  for now. *Resolves claims*: C7, C8
- [x] **U2 — What is the v1 scope?** — *Resolved*: ai_bots + runtime tables — also cover `navigator.*` tables
  that self-create at runtime (ui_surfaces, crew_definitions, …). *Resolves claims*: C8, C9
- [x] **U3 — How are databases with hand-applied changes adopted?** — *Resolved*: idempotent + baseline —
  files stay idempotent through per-column guarded backfills and guarded DDL (first run is a no-op
  where applied). A `baseline`/stamp records explicitly selected files without running them only after
  their postconditions are verified; it does not replace pending work. *Resolves claims*: C5, C16
- [x] **U4 — CLI shape?** — *Resolved*: group with verbs —
  `parrot self migration status | upgrade | baseline | new` (`new` scaffolds the next `NNN_*.sql` for a set).
  *Resolves claims*: C1, C14
- [x] **U5 — Fate of `sdd/migrations/` and `creation.sql`?** — *Resolved*: move ai_bots scripts into the
  package set after safe conversion (removed from `sdd/migrations`); retain the split `users_bots`
  embedding fold as a manual script and exclude destructive rebuild SQL from the chain.
  Planogram/ontology files stay; `creation.sql` becomes fresh-install only and points to the command
  (sanctioned rewrite). The command itself supports fresh databases without that file.
  *Resolves claims*: C3, C4, C13

### Proposal questions resolved by verified design

- [x] Exact v1 inventory and first-use fallback — §2 names bots plus five server sets, excludes
  Studio-owned tables and separate/dynamic schemas, and retains existing runtime fallback code.
- [x] Set locations and entry-point group — bots and runner in core `parrot.migrations`; server
  metadata/resources in `parrot.server.migrations`; group `parrot.migrations`.
- [x] Ledger/admin setting names — `parrot_schema_migrations` in PARROT_SCHEMA; `PARROT_ADMIN_DSN`.
- [x] FEAT-860 coordination — include crew_definitions baseline; do not alter crew runtime methods,
  Redis adoption, tombstone semantics or its separate configured DSN.
- [x] Additional mixed language migration discovered during verification — split users_bots operations
  and explicit lossy reset into a manual file; automatic bots SQL preserves stored language values.

### Remaining release question

- [ ] Exact release number — owner: maintainer; target remains next minor release. Does not block
  task decomposition or alter any runtime/API contract.

## 9. Design Research Cross-Check

Status: skipped (optional independent research requires an accepted exploration document; the input
proposal frontmatter remains `status: review`). No independent design-review pass is claimed.
The earlier code review and source verification informed the explicit corrections in §2/§4.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

## 10. Documentation

- **Policy**: required.
- `wiki/deployment/database-migrations.md` — create: deployment order, CLI examples and exact exits,
  DSN precedence/active environment, runtime-role grants, set ownership/default selection, fresh install,
  partial adoption and baseline limits, changed-file repair, SQL/check authoring, scaffolding and wheel
  packaging, separate crew databases, preserved manual users_bots/language operations, and separate
  Studio/task-memory commands. Explain that success from bots status says nothing about Studio.
- **API modules**: parrot.migrations.catalog, parrot.migrations.runner, parrot.migrations.checks.
- Documentation is informational at SDD closeout, but the acceptance criteria require operator guidance.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-12 | Jesus Lara / Codex | Initial verified spec; carries proposal review fixes and separates the additional mixed/lossy language operation |
