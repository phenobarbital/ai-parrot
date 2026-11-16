# TASK-5560: Server providers and UI/crew baselines

**Feature**: FEAT-884 — Packaged PostgreSQL migrations
**Spec**: `sdd/specs/db-upgrade.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5554
**Assigned-to**: unassigned


---

## Context

Implement M4 metadata factories for all five optional sets, distribution registration, and baseline/check pairs for ui_surfaces and crew_definitions. Keep runtime fallback modules unchanged.

---

## Scope

Implement M4 metadata factories for all five optional sets, distribution registration, and baseline/check pairs for ui_surfaces and crew_definitions. Keep runtime fallback modules unchanged.

**NOT in scope**: application-model/loader refactors, Studio or task-memory migration ownership changes, new dependencies, production database execution. Implement only declared targets.

**Parallelism**: Consumes MigrationSet from TASK-5554. Exclusive: edits packages/ai-parrot-server/pyproject.toml, a shared distribution manifest.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/server/migrations/__init__.py` | CREATE | Keep provider discovery independent of runtime stores. |
| `packages/ai-parrot-server/src/parrot/server/migrations/providers.py` | CREATE | Factories return metadata only, fixed navigator targets even with custom bots schema. All five resources are completed across two tasks. |
| `packages/ai-parrot-server/pyproject.toml` | MODIFY | Add a separate [project.entry-points."parrot.migrations"] table mapping ui_surfaces, crew_definitions, metric_definitions, recipes, scheduler to parrot.server.migrations.providers:<name>_set. Add "parrot.server.migrations" = ["sql/*/*.sql"] under package-data; keep existing metadata/dependencies. |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/ui_surfaces/001_baseline.sql` | CREATE | Idempotent ui_surfaces schema and additive catch-up Use complete statements/DO blocks; never split SQL on semicolons. |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/ui_surfaces/001_baseline.check.sql` | CREATE | Match current runtime columns/types/defaults/keys/indexes, rejecting incompatible existing rows Missing relations are screened by checks.verify_postconditions; remain valid after every successor. |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/crew_definitions/001_baseline.sql` | CREATE | Idempotent crew_definitions schema and additive catch-up Use complete statements/DO blocks; never split SQL on semicolons. |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/crew_definitions/001_baseline.check.sql` | CREATE | Match current runtime columns/types/defaults/keys/indexes, rejecting incompatible existing rows Missing relations are screened by checks.verify_postconditions; remain valid after every successor. |
| `packages/ai-parrot-server/tests/migrations/test_ui_crew_baselines.py` | CREATE | Five metadata factories names and fixed targets/no handler imports; UI/crew SQL parity and correct additive-before-index ordering; no Studio/task-memory ownership; no transaction wrappers in packaged SQL |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.migrations.models import MigrationSet
import pytest
from parrot.server.migrations import providers
```

Standard-library imports are available on supported Python 3.11–3.13. Pydantic and Click are declared in core pyproject.toml at lines 54 and 149; asyncpg is already supplied through asyncdb (line 137). Pytest is the existing test runner. Relative/new `parrot.migrations` imports above are declared by this task or its dependencies, **not existing base-branch APIs**. Imports inside TYPE_CHECKING or callbacks must remain lazy where specified.

### Existing Signatures to Use

- `packages/ai-parrot-server/pyproject.toml` — anchor at line 132, one exact occurrence: `[tool.setuptools.package-data]`
- `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` — _DDL_STATEMENTS line 107; tenant/visibility/allowed_groups catch-up before their index; share FK cascade and indexes
- `packages/ai-parrot-server/src/parrot/handlers/crew/postgres_persistence.py` — _DDL_STATEMENTS line 21; tenant/name PK, tenant/crew_id unique, deleted_at tombstones

### Dependency interfaces

- `TASK-5554` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.

### Does NOT Exist

- The generic migration packages are absent at planning HEAD; only declared dependency artifacts supply the new APIs.
- No core `PARROT_ADMIN_DSN` setting exists until the CLI task; no existing generic `parrot_schema_migrations` runner may be reused.
- No root-level `parrot/` directory or server `scheduler/store.py` exists. Do not infer executable migration APIs from model docstrings.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/server/migrations/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/server/migrations/providers.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/pyproject.toml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/server/migrations/sql/ui_surfaces/001_baseline.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/server/migrations/sql/ui_surfaces/001_baseline.check.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/server/migrations/sql/crew_definitions/001_baseline.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/server/migrations/sql/crew_definitions/001_baseline.check.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/migrations/test_ui_crew_baselines.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py#_DDL_STATEMENTS",
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/postgres_persistence.py#_DDL_STATEMENTS"
  ]
}
```

---

## Implementation Notes

Follow spec §2 for all safety and exit semantics. Use black (120 columns), strict types, Google-style docstrings and module logging. No synchronous database I/O. New SQL is transaction-wrapper-free; checks run read-only. Tests inject fake DSNs or use only `PARROT_MIGRATION_TEST_DSN`. Never contact application configuration DSNs. Local live tests may skip without the test DSN; feature closeout must provide passing live evidence, not skips. Keep logs under artifacts/logs/.

---

## Implementation Blueprint

### Steps (in order)

1. Verify dependencies and the cited source/anchors — because drift must be caught before editing.
2. Apply the per-file starting points below and complete their bounded logic — because file ownership and public signatures are fixed.
3. Exercise the behavioral matrix, including failures and cleanup — because happy-path checks alone cannot establish migration safety.
4. Run Validation Commands and inspect the scoped diff — because unrelated schema/loader changes are forbidden.

---

### `packages/ai-parrot-server/src/parrot/server/migrations/__init__.py` (CREATE)

```python
"""Optional server migration resources; no runtime handlers are imported here."""
```

**Why**: Keep provider discovery independent of runtime stores.

---

### `packages/ai-parrot-server/src/parrot/server/migrations/providers.py` (CREATE)

```python
"""Fixed navigator ownership for optional server sets."""
from parrot.migrations.models import MigrationSet


def ui_surfaces_set() -> MigrationSet:
    """Own navigator.ui_surfaces, navigator.ui_surface_shares only."""
    return MigrationSet(name="ui_surfaces", package="parrot.server.migrations",
                        resource_dir="sql/ui_surfaces", tables=('navigator.ui_surfaces', 'navigator.ui_surface_shares'))


def crew_definitions_set() -> MigrationSet:
    """Own navigator.crew_definitions only."""
    return MigrationSet(name="crew_definitions", package="parrot.server.migrations",
                        resource_dir="sql/crew_definitions", tables=('navigator.crew_definitions',))


def metric_definitions_set() -> MigrationSet:
    """Own navigator.metric_definitions only."""
    return MigrationSet(name="metric_definitions", package="parrot.server.migrations",
                        resource_dir="sql/metric_definitions", tables=('navigator.metric_definitions',))


def recipes_set() -> MigrationSet:
    """Own navigator.infographic_recipes only."""
    return MigrationSet(name="recipes", package="parrot.server.migrations",
                        resource_dir="sql/recipes", tables=('navigator.infographic_recipes',))


def scheduler_set() -> MigrationSet:
    """Own navigator.service_scheduler only."""
    return MigrationSet(name="scheduler", package="parrot.server.migrations",
                        resource_dir="sql/scheduler", tables=('navigator.service_scheduler',))
```

**Why**: Factories return metadata only, fixed navigator targets even with custom bots schema. All five resources are completed across two tasks.

---

### `packages/ai-parrot-server/pyproject.toml` (MODIFY)

```toml
# Anchor (exact full line): [tool.setuptools.package-data]
# occurrences: 1; verified at packages/ai-parrot-server/pyproject.toml:132
# FILL IN: Add a separate [project.entry-points."parrot.migrations"] table mapping ui_surfaces, crew_definitions, metric_definitions, recipes, scheduler to parrot.server.migrations.providers:<name>_set. Add "parrot.server.migrations" = ["sql/*/*.sql"] under package-data; keep existing metadata/dependencies.
```

**Why**: Add a separate [project.entry-points."parrot.migrations"] table mapping ui_surfaces, crew_definitions, metric_definitions, recipes, scheduler to parrot.server.migrations.providers:<name>_set. Add "parrot.server.migrations" = ["sql/*/*.sql"] under package-data; keep existing metadata/dependencies.

---

### `packages/ai-parrot-server/src/parrot/server/migrations/sql/ui_surfaces/001_baseline.sql` (CREATE)

```sql
-- Provenance: packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py::_DDL_STATEMENTS
CREATE SCHEMA IF NOT EXISTS navigator;
CREATE TABLE IF NOT EXISTS navigator.ui_surfaces (
        surface_id UUID PRIMARY KEY,
        kind VARCHAR(32) NOT NULL,
        title TEXT NOT NULL,
        envelope JSONB NOT NULL,
        catalog_id VARCHAR,
        agent_id VARCHAR NOT NULL,
        user_id VARCHAR NOT NULL,
        session_id VARCHAR,
        recipe_name VARCHAR,
        recipe_owner VARCHAR,
        recipe_params JSONB NOT NULL DEFAULT '{}'::jsonb,
        tenant VARCHAR(63),
        visibility VARCHAR(16) NOT NULL DEFAULT 'private',
        allowed_groups JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
CREATE INDEX IF NOT EXISTS ix_ui_surfaces_user ON navigator.ui_surfaces (user_id);
CREATE INDEX IF NOT EXISTS ix_ui_surfaces_user_kind ON navigator.ui_surfaces (user_id, kind);
CREATE TABLE IF NOT EXISTS navigator.ui_surface_shares (
        token TEXT PRIMARY KEY,
        surface_id UUID NOT NULL REFERENCES navigator.ui_surfaces(surface_id) ON DELETE CASCADE,
        permissions VARCHAR(32) NOT NULL DEFAULT 'read+refresh',
        expires_at TIMESTAMPTZ,
        revoked BOOLEAN NOT NULL DEFAULT FALSE,
        claimed_by TEXT,
        claimed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
CREATE INDEX IF NOT EXISTS ix_ui_surface_shares_surface ON navigator.ui_surface_shares (surface_id);
CREATE INDEX IF NOT EXISTS ix_ui_surface_shares_claimed_by ON navigator.ui_surface_shares (claimed_by);
ALTER TABLE navigator.ui_surfaces ADD COLUMN IF NOT EXISTS tenant VARCHAR(63);
ALTER TABLE navigator.ui_surfaces ADD COLUMN IF NOT EXISTS visibility VARCHAR(16) NOT NULL DEFAULT 'private';
ALTER TABLE navigator.ui_surfaces ADD COLUMN IF NOT EXISTS allowed_groups JSONB NOT NULL DEFAULT '[]'::jsonb;
CREATE INDEX IF NOT EXISTS ix_ui_surfaces_tenant_visibility ON navigator.ui_surfaces (tenant, visibility);
-- FILL IN: put additive catch-up before indexes that consume missing columns.
-- FILL IN: reject incompatible existing types/constraints without dropping data.
```

**Why**: Idempotent ui_surfaces schema and additive catch-up Use complete statements/DO blocks; never split SQL on semicolons.

---

### `packages/ai-parrot-server/src/parrot/server/migrations/sql/ui_surfaces/001_baseline.check.sql` (CREATE)

```sql
-- FEAT-884 postcondition: Match current runtime columns/types/defaults/keys/indexes, rejecting incompatible existing rows
-- FILL IN: replace FALSE with a SELECT-only, single-row, single-boolean predicate.
SELECT FALSE;
```

**Why**: Match current runtime columns/types/defaults/keys/indexes, rejecting incompatible existing rows Missing relations are screened by checks.verify_postconditions; remain valid after every successor.

---

### `packages/ai-parrot-server/src/parrot/server/migrations/sql/crew_definitions/001_baseline.sql` (CREATE)

```sql
-- Provenance: packages/ai-parrot-server/src/parrot/handlers/crew/postgres_persistence.py::_DDL_STATEMENTS
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
-- FILL IN: put additive catch-up before indexes that consume missing columns.
-- FILL IN: reject incompatible existing types/constraints without dropping data.
```

**Why**: Idempotent crew_definitions schema and additive catch-up Use complete statements/DO blocks; never split SQL on semicolons.

---

### `packages/ai-parrot-server/src/parrot/server/migrations/sql/crew_definitions/001_baseline.check.sql` (CREATE)

```sql
-- FEAT-884 postcondition: Match current runtime columns/types/defaults/keys/indexes, rejecting incompatible existing rows
-- FILL IN: replace FALSE with a SELECT-only, single-row, single-boolean predicate.
SELECT FALSE;
```

**Why**: Match current runtime columns/types/defaults/keys/indexes, rejecting incompatible existing rows Missing relations are screened by checks.verify_postconditions; remain valid after every successor.

---

### `packages/ai-parrot-server/tests/migrations/test_ui_crew_baselines.py` (CREATE)

```python
"""Five metadata factories names and fixed targets/no handler imports."""
from __future__ import annotations

import pytest
from parrot.server.migrations import providers


def test_ui_crew_baselines_contract() -> None:
    """Verify the behavioral matrix listed in this task."""
    # FILL IN: replace this starting test with parameterized cases and fixtures
    # bounded by the Test Specification; assert observable outcomes, not implementation details.
    pytest.fail("Complete the behavioral matrix before finalizing this task")
```

**Why**: Five metadata factories names and fixed targets/no handler imports; UI/crew SQL parity and correct additive-before-index ordering; no Studio/task-memory ownership; no transaction wrappers in packaged SQL

---

### FILL IN checklist

- [ ] `packages/ai-parrot-server/src/parrot/server/migrations/__init__.py` — Keep provider discovery independent of runtime stores.
- [ ] `packages/ai-parrot-server/src/parrot/server/migrations/providers.py` — Factories return metadata only, fixed navigator targets even with custom bots schema. All five resources are completed across two tasks.
- [ ] `packages/ai-parrot-server/pyproject.toml` — Add a separate [project.entry-points."parrot.migrations"] table mapping ui_surfaces, crew_definitions, metric_definitions, recipes, scheduler to parrot.server.migrations.providers:<name>_set. Add "parrot.server.migrations" = ["sql/*/*.sql"] under package-data; keep existing metadata/dependencies.
- [ ] `packages/ai-parrot-server/src/parrot/server/migrations/sql/ui_surfaces/001_baseline.sql` — Idempotent ui_surfaces schema and additive catch-up Use complete statements/DO blocks; never split SQL on semicolons.
- [ ] `packages/ai-parrot-server/src/parrot/server/migrations/sql/ui_surfaces/001_baseline.check.sql` — Match current runtime columns/types/defaults/keys/indexes, rejecting incompatible existing rows Missing relations are screened by checks.verify_postconditions; remain valid after every successor.
- [ ] `packages/ai-parrot-server/src/parrot/server/migrations/sql/crew_definitions/001_baseline.sql` — Idempotent crew_definitions schema and additive catch-up Use complete statements/DO blocks; never split SQL on semicolons.
- [ ] `packages/ai-parrot-server/src/parrot/server/migrations/sql/crew_definitions/001_baseline.check.sql` — Match current runtime columns/types/defaults/keys/indexes, rejecting incompatible existing rows Missing relations are screened by checks.verify_postconditions; remain valid after every successor.
- [ ] `packages/ai-parrot-server/tests/migrations/test_ui_crew_baselines.py` — Five metadata factories names and fixed targets/no handler imports; UI/crew SQL parity and correct additive-before-index ordering; no Studio/task-memory ownership; no transaction wrappers in packaged SQL
- [ ] Replace all planning markers with complete working code/tests; no placeholders may remain in implementation files.

---

## Acceptance Criteria

- [ ] All declared files implement the scope and per-file constraints above.
- [ ] Every case in Test Specification asserts observable outcomes, including failure paths.
- [ ] Existing frozen loader, BotModel DDL/shim and unrelated runtime fallback behavior remain unchanged.
- [ ] No credentials, raw driver errors, SQL bodies or parameter values leak into reports/logs.
- [ ] Declared validation succeeds; live-test skips are not release evidence.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/migrations/test_ui_crew_baselines.py -q`

---

## Test Specification

- Five metadata factories names and fixed targets/no handler imports; UI/crew SQL parity and correct additive-before-index ordering; no Studio/task-memory ownership; no transaction wrappers in packaged SQL

---

## Agent Instructions

1. Use `$sdd-start TASK-5560` to provision the feature worktree; do not implement on dev.
2. Read the full spec and confirm predecessor tasks are done.
3. Reverify existing anchors and new dependency signatures before implementing.
4. Complete the blueprint within its acceptance criteria, then run the task validation commands.
5. Commit only declared implementation files and finalize with `parrot sdd task finalize` using real TaskCompletionEvidence and the implementation HEAD; it owns Completion Note and active-to-completed movement.

## Completion Note


- Task: TASK-5560
- Feature: db-upgrade
- Implementation SHA: a57a9ad64cba6b20787ab53d59f374b0a358d5ca
- Closed at (UTC): 2026-11-12T23:28:03+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 324s · Tokens: n/a |
