---
type: Wiki Overview
title: 'TASK-1106: Postgres schema (security_reports table + indexes)'
id: doc:sdd-tasks-completed-task-1106-postgres-schema-sql-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Defines the Postgres DDL for the `security_reports` table that backs the
---

# TASK-1106: Postgres schema (security_reports table + indexes)

**Feature**: FEAT-162 — Cross-Session Security Report Catalog
**Spec**: `sdd/specs/security-report-catalog.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1105
**Assigned-to**: unassigned

---

## Context

Defines the Postgres DDL for the `security_reports` table that backs the
catalog's metadata layer. Column names match the `ReportRef` Pydantic
model from TASK-1105. The schema lives as a bare `.sql` file
co-located with the storage module — there is **no migration framework**
project-wide (resolved brainstorm OQ #2; confirmed via finding F016).

Implements Spec §3 Module 2 and §5 Acceptance Criteria entries on schema
idempotency.

---

## Scope

- Create `parrot/storage/security_reports/schema.sql` with:
  - `CREATE TABLE IF NOT EXISTS security_reports (...)` matching the
    column shape in Spec §2 Data Models. All `JSONB` for `scope`,
    `severity_summary`, `top_findings`. `TIMESTAMPTZ` for
    `produced_at` and `created_at`.
  - 3 indexes (`IF NOT EXISTS` semantics):
    - `idx_security_reports_scanner_framework_produced`
      ON `(scanner, framework, produced_at DESC)`.
    - `idx_security_reports_kind_produced`
      ON `(report_kind, produced_at DESC)`.
    - `idx_security_reports_scope_gin` GIN ON `scope`.
- Add a small unit test (or integration test using a test Postgres)
  that runs the schema twice and asserts no error on the second run.
  Defer the actual idempotent-execution machinery (running the SQL from
  Python) to TASK-1107's `bootstrap_schema()`.

**NOT in scope**: `bootstrap_schema()` method on the store (TASK-1107);
asyncdb wiring (TASK-1107); any data fixture seeding.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/storage/security_reports/schema.sql` | CREATE | Bare DDL — CREATE TABLE + 3 indexes |
| `tests/storage/security_reports/test_schema.py` | CREATE | Schema-shape sanity test (parse SQL, optional dry-run if test Postgres available) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

*None for the .sql file itself. Test imports may use pytest only.*

### Existing Signatures to Use

```text
# parrot/security/security_events.sql (style precedent, finding F016)
# - Uses CREATE TABLE IF NOT EXISTS
# - Uses CREATE INDEX IF NOT EXISTS (when supported)
# - Co-located with the module that owns the table
# - No Python loader — ops applies it out-of-band
```

### Does NOT Exist

- ~~Alembic / `alembic.ini` / `migrations/` directory~~ — finding F016
  confirms no migration framework anywhere in the project.
- ~~`parrot/storage/migrations/`~~ — does not exist; do not create.
- ~~Any centralized schema loader / runner~~ — schema files are applied
  manually by ops or by the new `bootstrap_schema()` helper (TASK-1107).

---

## Implementation Notes

### Pattern to Follow

```sql
-- parrot/storage/security_reports/schema.sql
CREATE TABLE IF NOT EXISTS security_reports (
    report_id           UUID PRIMARY KEY,
    report_kind         TEXT NOT NULL,
    scanner             TEXT NOT NULL,
    framework           TEXT,
    provider            TEXT NOT NULL,
    scope               JSONB NOT NULL DEFAULT '{}'::jsonb,
    severity_summary    JSONB NOT NULL,
    top_findings        JSONB NOT NULL DEFAULT '[]'::jsonb,
    uri                 TEXT NOT NULL,
    content_type        TEXT NOT NULL DEFAULT 'application/json',
    content_bytes       BIGINT,
    produced_at         TIMESTAMPTZ NOT NULL,
    produced_by         TEXT NOT NULL,
    parser_version      TEXT NOT NULL,
    retention_class     TEXT NOT NULL DEFAULT 'compliance',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_security_reports_scanner_framework_produced
    ON security_reports (scanner, framework, produced_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_reports_kind_produced
    ON security_reports (report_kind, produced_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_reports_scope_gin
    ON security_reports USING GIN (scope);
```

### Key Constraints

- Idempotent — running the file twice in a row MUST NOT error.
- Column names match the `ReportRef` Pydantic field names from TASK-1105
  one-for-one. The store (TASK-1107) translates JSONB ↔ Pydantic; no
  field renaming.
- No foreign keys, no triggers, no functions — keep it bare per
  precedent (F016).

### References in Codebase

- `parrot/security/security_events.sql` — exact style precedent.
- Spec §2 Data Models — column shape source.
- Finding F016 — confirms no migration framework exists.

---

## Acceptance Criteria

- [ ] `parrot/storage/security_reports/schema.sql` exists and is committed.
- [ ] The schema can be applied twice consecutively to an empty Postgres
      database without error (acceptance via the schema-idempotency test
      OR manually verified and recorded in the completion note).
- [ ] Column names match `ReportRef` field names from TASK-1105 verbatim.
- [ ] All 3 indexes are present and use the patterns above.

---

## Test Specification

```python
# tests/storage/security_reports/test_schema.py
from pathlib import Path

SCHEMA_PATH = Path("parrot/storage/security_reports/schema.sql")


class TestSchemaSql:
    def test_file_exists(self):
        assert SCHEMA_PATH.exists()

    def test_idempotent_keywords_present(self):
        sql = SCHEMA_PATH.read_text()
        assert "CREATE TABLE IF NOT EXISTS security_reports" in sql
        assert "CREATE INDEX IF NOT EXISTS idx_security_reports_scanner_framework_produced" in sql
        assert "CREATE INDEX IF NOT EXISTS idx_security_reports_kind_produced" in sql
        assert "CREATE INDEX IF NOT EXISTS idx_security_reports_scope_gin" in sql

    def test_required_columns(self):
        sql = SCHEMA_PATH.read_text()
        for col in (
            "report_id", "report_kind", "scanner", "framework", "provider",
            "scope", "severity_summary", "top_findings", "uri",
            "content_type", "content_bytes", "produced_at", "produced_by",
            "parser_version", "retention_class", "created_at",
        ):
            assert col in sql, f"Column {col} missing from schema.sql"


# Optional: if a test Postgres DSN is available, exercise idempotent execution.
# This may be deferred to the integration test in TASK-1107.
```

---

## Agent Instructions

1. Read the spec section §3 Module 2 and Finding F016.
2. Create the .sql file per the pattern above.
3. Add the static-checks test.
4. Move this file to `sdd/tasks/completed/`; update the per-spec index; commit.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: Created schema.sql with all 16 required columns, 3 indexes (IF NOT EXISTS).
All column names match ReportRef field names verbatim. 7 static-check tests pass.

**Deviations from spec**: none
