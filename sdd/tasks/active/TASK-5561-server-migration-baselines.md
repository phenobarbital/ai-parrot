# TASK-5561: Metrics, recipes and scheduler baselines

**Feature**: FEAT-884 — Packaged PostgreSQL migrations
**Spec**: `sdd/specs/db-upgrade.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5554, TASK-5560
**Assigned-to**: unassigned


---

## Context

Complete M4 remaining three baseline/check pairs. Match verified runtime shape, with fresh UUID defaults using gen_random_uuid and compatible existing defaults retained.

---

## Scope

Complete M4 remaining three baseline/check pairs. Match verified runtime shape, with fresh UUID defaults using gen_random_uuid and compatible existing defaults retained.

**NOT in scope**: application-model/loader refactors, Studio or task-memory migration ownership changes, new dependencies, production database execution. Implement only declared targets.

**Parallelism**: Consumes MigrationSet/catalog from TASK-5554 and registered factories plus UI/crew resource pairs from TASK-5560; tests cover the complete five-set inventory.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/metric_definitions/001_baseline.sql` | CREATE | Idempotent metric_definitions fixed navigator schema with safe additive catch-up Use complete statements/DO blocks; never split SQL on semicolons. |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/metric_definitions/001_baseline.check.sql` | CREATE | Current columns/types/defaults/keys/indexes and constraints; compatible existing UUID function accepted Missing relations are screened by checks.verify_postconditions; remain valid after every successor. |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/recipes/001_baseline.sql` | CREATE | Idempotent recipes fixed navigator schema with safe additive catch-up Use complete statements/DO blocks; never split SQL on semicolons. |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/recipes/001_baseline.check.sql` | CREATE | Current columns/types/defaults/keys/indexes and constraints; compatible existing UUID function accepted Missing relations are screened by checks.verify_postconditions; remain valid after every successor. |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/scheduler/001_baseline.sql` | CREATE | Idempotent scheduler fixed navigator schema with safe additive catch-up Use complete statements/DO blocks; never split SQL on semicolons. |
| `packages/ai-parrot-server/src/parrot/server/migrations/sql/scheduler/001_baseline.check.sql` | CREATE | Current columns/types/defaults/keys/indexes and constraints; compatible existing UUID function accepted Missing relations are screened by checks.verify_postconditions; remain valid after every successor. |
| `packages/ai-parrot-server/tests/migrations/test_runtime_baselines.py` | CREATE | Full five-set inventory and source parity; metrics nullable-tenant partial uniqueness; recipes default-schema composite key; scheduler all fields and indexes; no dropped incompatible constraints/no runtime fallback edits |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest
from parrot.migrations.catalog import load_migrations
from parrot.server.migrations import providers
```

Standard-library imports are available on supported Python 3.11–3.13. Pydantic and Click are declared in core pyproject.toml at lines 54 and 149; asyncpg is already supplied through asyncdb (line 137). Pytest is the existing test runner. Relative/new `parrot.migrations` imports above are declared by this task or its dependencies, **not existing base-branch APIs**. Imports inside TYPE_CHECKING or callbacks must remain lazy where specified.

### Existing Signatures to Use

- `packages/ai-parrot-server/src/parrot/handlers/models/metric_definitions.py` — _DDL_STATEMENTS line 21; nullable-tenant global partial unique index and visibility check
- `packages/ai-parrot-server/src/parrot/handlers/models/recipes.py` — _ddl_statements(schema: str) -> list[str] line 39; default navigator only, composite name/owner PK
- `packages/ai-parrot-server/src/parrot/scheduler/models.py` — ServiceSchedule line 21; complete model/docstring schema including runtime state fields and two indexes

### Dependency interfaces

- `TASK-5554` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5560` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.

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
      "path": "packages/ai-parrot-server/src/parrot/server/migrations/sql/metric_definitions/001_baseline.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/server/migrations/sql/metric_definitions/001_baseline.check.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/server/migrations/sql/recipes/001_baseline.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/server/migrations/sql/recipes/001_baseline.check.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/server/migrations/sql/scheduler/001_baseline.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/server/migrations/sql/scheduler/001_baseline.check.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/migrations/test_runtime_baselines.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/models/metric_definitions.py#_DDL_STATEMENTS",
    "sym:packages/ai-parrot-server/src/parrot/handlers/models/recipes.py#_ddl_statements",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/models.py#ServiceSchedule"
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

### `packages/ai-parrot-server/src/parrot/server/migrations/sql/metric_definitions/001_baseline.sql` (CREATE)

```sql
-- Provenance: packages/ai-parrot-server/src/parrot/handlers/models/metric_definitions.py::_DDL_STATEMENTS
CREATE SCHEMA IF NOT EXISTS navigator;
CREATE TABLE IF NOT EXISTS navigator.metric_definitions (
        metric_id VARCHAR(63) NOT NULL,
        tenant VARCHAR(63) NULL,
        name TEXT NOT NULL,
        owner VARCHAR NULL,
        visibility VARCHAR(16) NOT NULL DEFAULT 'tenant',
        allowed_groups JSONB NOT NULL DEFAULT '[]'::jsonb,
        global_only BOOLEAN NOT NULL DEFAULT FALSE,
        program VARCHAR NULL,
        definition JSONB NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (tenant, metric_id),
        CHECK (tenant IS NOT NULL OR visibility <> 'tenant')
    );
CREATE UNIQUE INDEX IF NOT EXISTS metric_definitions_global_uq ON navigator.metric_definitions (metric_id) WHERE tenant IS NULL;
CREATE INDEX IF NOT EXISTS metric_definitions_tenant_vis_idx ON navigator.metric_definitions (tenant, visibility);
CREATE INDEX IF NOT EXISTS metric_definitions_program_idx ON navigator.metric_definitions (program);
-- FILL IN: put additive catch-up before indexes that consume missing columns.
-- FILL IN: reject incompatible existing types/constraints without dropping data.
```

**Why**: Idempotent metric_definitions fixed navigator schema with safe additive catch-up Use complete statements/DO blocks; never split SQL on semicolons.

---

### `packages/ai-parrot-server/src/parrot/server/migrations/sql/metric_definitions/001_baseline.check.sql` (CREATE)

```sql
-- FEAT-884 postcondition: Current columns/types/defaults/keys/indexes and constraints; compatible existing UUID function accepted
-- FILL IN: replace FALSE with a SELECT-only, single-row, single-boolean predicate.
SELECT FALSE;
```

**Why**: Current columns/types/defaults/keys/indexes and constraints; compatible existing UUID function accepted Missing relations are screened by checks.verify_postconditions; remain valid after every successor.

---

### `packages/ai-parrot-server/src/parrot/server/migrations/sql/recipes/001_baseline.sql` (CREATE)

```sql
-- Provenance: handlers/models/recipes.py::_ddl_statements("navigator").
CREATE SCHEMA IF NOT EXISTS navigator;
CREATE TABLE IF NOT EXISTS navigator.infographic_recipes (
    name VARCHAR NOT NULL,
    owner VARCHAR NOT NULL DEFAULT '',
    schema_version INTEGER NOT NULL,
    title TEXT,
    description TEXT,
    recipe JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (name, owner)
);
-- FILL IN: safe catch-up/preconditions for existing tables before index creation.
CREATE INDEX IF NOT EXISTS ix_infographic_recipes_owner ON navigator.infographic_recipes(owner);
```

**Why**: Idempotent recipes fixed navigator schema with safe additive catch-up Use complete statements/DO blocks; never split SQL on semicolons.

---

### `packages/ai-parrot-server/src/parrot/server/migrations/sql/recipes/001_baseline.check.sql` (CREATE)

```sql
-- FEAT-884 postcondition: Current columns/types/defaults/keys/indexes and constraints; compatible existing UUID function accepted
-- FILL IN: replace FALSE with a SELECT-only, single-row, single-boolean predicate.
SELECT FALSE;
```

**Why**: Current columns/types/defaults/keys/indexes and constraints; compatible existing UUID function accepted Missing relations are screened by checks.verify_postconditions; remain valid after every successor.

---

### `packages/ai-parrot-server/src/parrot/server/migrations/sql/scheduler/001_baseline.sql` (CREATE)

```sql
-- Provenance: packages/ai-parrot-server/src/parrot/scheduler/models.py::ServiceSchedule
CREATE TABLE IF NOT EXISTS navigator.service_scheduler (
    schedule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_kind VARCHAR NOT NULL,                 -- agent | crew | service
    target_name VARCHAR NOT NULL,
    target_id VARCHAR,
    tenant VARCHAR,                               -- reserved; enforcement is §8 Q1
    prompt TEXT,
    method_name VARCHAR,
    schedule_type VARCHAR NOT NULL,
    schedule_config JSONB NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    created_by INTEGER,
    created_email VARCHAR,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_run TIMESTAMPTZ,
    next_run TIMESTAMPTZ,
    run_count INTEGER DEFAULT 0,
    last_status VARCHAR,                          -- success | error | target_missing | lock_unavailable
    last_error TEXT,
    last_error_at TIMESTAMPTZ,
    last_result TEXT,                             -- _format_result(), truncated to _LAST_RESULT_MAX_CHARS
    last_result_at TIMESTAMPTZ,
    consecutive_failures INTEGER DEFAULT 0,
    last_delivery_status VARCHAR,
    last_delivery_at TIMESTAMPTZ,
    last_callbacks JSONB DEFAULT '[]'::JSONB,
    metadata JSONB DEFAULT '{}'::JSONB,           -- call kwargs ONLY
    send_result JSONB DEFAULT '{}'::JSONB,
    callbacks JSONB DEFAULT '[]'::JSONB
);
CREATE INDEX IF NOT EXISTS idx_service_scheduler_enabled ON navigator.service_scheduler(enabled);
CREATE INDEX IF NOT EXISTS idx_service_scheduler_target ON navigator.service_scheduler(target_kind, target_name);
-- FILL IN: guarded additive catch-up and incompatible-shape checks before indexes.
```

**Why**: Idempotent scheduler fixed navigator schema with safe additive catch-up Use complete statements/DO blocks; never split SQL on semicolons.

---

### `packages/ai-parrot-server/src/parrot/server/migrations/sql/scheduler/001_baseline.check.sql` (CREATE)

```sql
-- FEAT-884 postcondition: Current columns/types/defaults/keys/indexes and constraints; compatible existing UUID function accepted
-- FILL IN: replace FALSE with a SELECT-only, single-row, single-boolean predicate.
SELECT FALSE;
```

**Why**: Current columns/types/defaults/keys/indexes and constraints; compatible existing UUID function accepted Missing relations are screened by checks.verify_postconditions; remain valid after every successor.

---

### `packages/ai-parrot-server/tests/migrations/test_runtime_baselines.py` (CREATE)

```python
"""Full five-set inventory and source parity."""
from __future__ import annotations

import pytest
from parrot.migrations.catalog import load_migrations
from parrot.server.migrations import providers


def test_runtime_baselines_contract() -> None:
    """Verify the behavioral matrix listed in this task."""
    # FILL IN: replace this starting test with parameterized cases and fixtures
    # bounded by the Test Specification; assert observable outcomes, not implementation details.
    pytest.fail("Complete the behavioral matrix before finalizing this task")
```

**Why**: Full five-set inventory and source parity; metrics nullable-tenant partial uniqueness; recipes default-schema composite key; scheduler all fields and indexes; no dropped incompatible constraints/no runtime fallback edits

---

### FILL IN checklist

- [ ] `packages/ai-parrot-server/src/parrot/server/migrations/sql/metric_definitions/001_baseline.sql` — Idempotent metric_definitions fixed navigator schema with safe additive catch-up Use complete statements/DO blocks; never split SQL on semicolons.
- [ ] `packages/ai-parrot-server/src/parrot/server/migrations/sql/metric_definitions/001_baseline.check.sql` — Current columns/types/defaults/keys/indexes and constraints; compatible existing UUID function accepted Missing relations are screened by checks.verify_postconditions; remain valid after every successor.
- [ ] `packages/ai-parrot-server/src/parrot/server/migrations/sql/recipes/001_baseline.sql` — Idempotent recipes fixed navigator schema with safe additive catch-up Use complete statements/DO blocks; never split SQL on semicolons.
- [ ] `packages/ai-parrot-server/src/parrot/server/migrations/sql/recipes/001_baseline.check.sql` — Current columns/types/defaults/keys/indexes and constraints; compatible existing UUID function accepted Missing relations are screened by checks.verify_postconditions; remain valid after every successor.
- [ ] `packages/ai-parrot-server/src/parrot/server/migrations/sql/scheduler/001_baseline.sql` — Idempotent scheduler fixed navigator schema with safe additive catch-up Use complete statements/DO blocks; never split SQL on semicolons.
- [ ] `packages/ai-parrot-server/src/parrot/server/migrations/sql/scheduler/001_baseline.check.sql` — Current columns/types/defaults/keys/indexes and constraints; compatible existing UUID function accepted Missing relations are screened by checks.verify_postconditions; remain valid after every successor.
- [ ] `packages/ai-parrot-server/tests/migrations/test_runtime_baselines.py` — Full five-set inventory and source parity; metrics nullable-tenant partial uniqueness; recipes default-schema composite key; scheduler all fields and indexes; no dropped incompatible constraints/no runtime fallback edits
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

- `pytest packages/ai-parrot-server/tests/migrations/test_runtime_baselines.py -q`

---

## Test Specification

- Full five-set inventory and source parity; metrics nullable-tenant partial uniqueness; recipes default-schema composite key; scheduler all fields and indexes; no dropped incompatible constraints/no runtime fallback edits

---

## Agent Instructions

1. Use `$sdd-start TASK-5561` to provision the feature worktree; do not implement on dev.
2. Read the full spec and confirm predecessor tasks are done.
3. Reverify existing anchors and new dependency signatures before implementing.
4. Complete the blueprint within its acceptance criteria, then run the task validation commands.
5. Commit only declared implementation files and finalize with `parrot sdd task finalize` using real TaskCompletionEvidence and the implementation HEAD; it owns Completion Note and active-to-completed movement.

## Completion Note

Populated by the task finalizer after verified implementation.
