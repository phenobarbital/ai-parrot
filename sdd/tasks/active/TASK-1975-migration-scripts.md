# TASK-1975: Migration scripts for form_uid

**Feature**: FEAT-389 — Stable UUID-Based Form Identity
**Spec**: `sdd/specs/form-uid-stable-identity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-1974
**Assigned-to**: unassigned

---

## Context

Existing databases need a migration path to add the `form_uid` column and
backfill it from the existing `id` (UUID primary key). The submissions table
(`form_data`) also needs a `form_uid` column joined from `form_schemas`.
Implements Module 3b from the spec.

---

## Scope

- Create `packages/parrot-formdesigner/migrations/` directory.
- Create `001_add_form_uid.sql`: DDL migration for `form_schemas` table:
  - `ALTER TABLE form_schemas ADD COLUMN IF NOT EXISTS form_uid VARCHAR(36)`.
  - Backfill: `UPDATE form_schemas SET form_uid = id::text WHERE form_uid IS NULL`.
  - `ALTER TABLE form_schemas ALTER COLUMN form_uid SET NOT NULL`.
  - Add UNIQUE constraint `(form_uid, version)`.
  - Add UNIQUE constraint `(tenant, form_id, version)`.
  - All statements idempotent (IF NOT EXISTS / IF EXISTS guards).
- Create `002_add_form_uid_submissions.sql`: DDL migration for `form_data` table:
  - `ALTER TABLE form_data ADD COLUMN IF NOT EXISTS form_uid VARCHAR(36)`.
  - Backfill: `UPDATE form_data fd SET form_uid = fs.form_uid FROM form_schemas fs WHERE fd.form_id = fs.form_id`.
  - Create index `idx_form_data_form_uid ON form_data(form_uid)`.
- Create `003_migrate_form_data.py`: Python script for complex backfill:
  - Connect to database using asyncpg.
  - Backfill `form_data.form_uid` via JOIN in batches.
  - Report orphaned `form_data` rows (no matching `form_schemas` entry).
  - Idempotent: skip already-backfilled rows.
  - CLI interface with `--dry-run` flag.

**NOT in scope**: Changing the greenfield DDL (TASK-1974), API changes, application code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/migrations/` | CREATE dir | Migration artifacts directory |
| `packages/parrot-formdesigner/migrations/001_add_form_uid.sql` | CREATE | DDL for form_schemas: add form_uid, backfill, constraints |
| `packages/parrot-formdesigner/migrations/002_add_form_uid_submissions.sql` | CREATE | DDL for form_data: add form_uid, backfill, index |
| `packages/parrot-formdesigner/migrations/003_migrate_form_data.py` | CREATE | Python script for backfill + orphan report |
| `packages/parrot-formdesigner/migrations/README.md` | CREATE | Migration usage instructions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncpg  # verified: used in services/storage.py for DB connections
import asyncio   # stdlib
import argparse  # stdlib — for CLI interface in 003
```

### Existing Signatures to Use
```sql
-- form_schemas DDL (services/storage.py:148)
-- Existing columns:
--   id UUID PRIMARY KEY DEFAULT gen_random_uuid()
--   form_id VARCHAR(255) NOT NULL
--   tenant VARCHAR(255) NOT NULL DEFAULT 'default'
--   version VARCHAR(50) NOT NULL DEFAULT '1.0'
--   UNIQUE(form_id, version)  -- line 161

-- form_data DDL (services/submissions.py:168-204)
-- Existing columns:
--   form_id VARCHAR(255) NOT NULL
--   CREATE INDEX idx_form_data_form_id ON form_data(form_id)
```

### Does NOT Exist
- ~~`migrations/` directory~~ — does not exist. This task creates it.
- ~~Any existing migration infrastructure~~ — no Alembic, no versioning table.
  These are standalone SQL + Python scripts.
- ~~`form_uid` column in either table~~ — TASK-1974 adds it to greenfield DDL;
  this task provides the ALTER TABLE path for existing databases.

---

## Implementation Notes

### 001_add_form_uid.sql
```sql
-- Migration: Add form_uid to form_schemas
-- Idempotent: safe to run multiple times

-- Step 1: Add column (nullable first for backfill)
ALTER TABLE form_schemas ADD COLUMN IF NOT EXISTS form_uid VARCHAR(36);

-- Step 2: Backfill from existing UUID primary key
UPDATE form_schemas SET form_uid = id::text WHERE form_uid IS NULL;

-- Step 3: Set NOT NULL after backfill
ALTER TABLE form_schemas ALTER COLUMN form_uid SET NOT NULL;

-- Step 4: Add constraints (idempotent via DO block or IF NOT EXISTS)
-- Use DO $$ blocks for constraint idempotency since ALTER TABLE ADD CONSTRAINT
-- does not support IF NOT EXISTS in all PG versions.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_form_schemas_form_uid_version'
    ) THEN
        ALTER TABLE form_schemas ADD CONSTRAINT uq_form_schemas_form_uid_version
            UNIQUE (form_uid, version);
    END IF;
END$$;
```

### 003_migrate_form_data.py pattern
```python
async def backfill_form_uid(pool, dry_run: bool = False):
    """Backfill form_data.form_uid from form_schemas in batches."""
    BATCH_SIZE = 1000
    # SELECT fd.id, fs.form_uid FROM form_data fd
    # JOIN form_schemas fs ON fd.form_id = fs.form_id
    # WHERE fd.form_uid IS NULL LIMIT $1
```

### Key Constraints
- All SQL must be idempotent — rerunning should be a no-op.
- The Python script must handle the case where `form_data` rows reference
  a `form_id` that doesn't exist in `form_schemas` (orphans).
- Use `DO $$` blocks for constraint idempotency.

---

## Acceptance Criteria

- [ ] `migrations/` directory exists at `packages/parrot-formdesigner/migrations/`
- [ ] `001_add_form_uid.sql` adds `form_uid` column, backfills, sets NOT NULL, adds constraints
- [ ] `002_add_form_uid_submissions.sql` adds `form_uid` to `form_data`, backfills via JOIN
- [ ] `003_migrate_form_data.py` performs batched backfill with `--dry-run` support
- [ ] `003_migrate_form_data.py` reports orphaned `form_data` rows
- [ ] All SQL statements are idempotent (safe to rerun)
- [ ] README.md documents execution order and prerequisites

---

## Test Specification
```python
import pytest
import subprocess

def test_sql_syntax_001():
    """Verify 001_add_form_uid.sql is valid SQL (parse check)."""
    # Read file, check no syntax errors via basic validation
    pass

def test_sql_syntax_002():
    """Verify 002_add_form_uid_submissions.sql is valid SQL."""
    pass

def test_migration_script_dry_run():
    """003_migrate_form_data.py --dry-run exits 0 without DB changes."""
    result = subprocess.run(
        ["python", "migrations/003_migrate_form_data.py", "--dry-run", "--dsn", "postgresql://..."],
        capture_output=True
    )
    # Verify it at least parses and handles missing DB gracefully

def test_idempotency_001():
    """Running 001 twice produces no errors."""
    pass  # Requires test database — integration test

def test_orphan_detection():
    """003 reports orphaned form_data rows."""
    pass  # Requires test database — integration test
```

---

## Agent Instructions

1. Read this task file and the spec (Module 3b).
2. Verify TASK-1974 is complete (storage DDL updated).
3. Read `services/storage.py` and `services/submissions.py` for current DDL.
4. Create the `migrations/` directory.
5. Write all three migration files.
6. Write `README.md` with usage instructions.
7. Test SQL syntax manually or with a basic parse check.
8. Commit with message: `sdd: TASK-1975 — migration scripts for form_uid`
9. Update this task status to `done`.

---

## Completion Note
*(Agent fills this in when done)*
