# TASK-229: Database Tools — Credential Resolution (`abstract.py`)

**Feature**: Database Schema Tools — Completion & Hardening (FEAT-032)
**Spec**: `sdd/specs/tools-database.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-3h)
**Depends-on**: none
**Assigned-to**: claude-opus-4-6

---

## Context

> `AbstractSchemaManagerTool.__init__` always falls back to the module-level
> `asyncpg_sqlalchemy_url` constant when no `dsn` or `engine` is provided.  This makes the
> tool unusable in environments that configure database credentials via navconfig env vars
> (`POSTGRES_HOST`, `POSTGRES_PASSWORD`, etc.) without also setting that specific constant.
> The `DatabaseQueryTool._get_default_credentials` pattern already solves this problem and
> should be replicated here.

---

## Scope

Modify `parrot/tools/database/abstract.py`:

1. Add `_get_default_credentials(database_type: str) -> dict` method that reads from
   `navconfig.config` (with `os.environ` fallback):

   ```
   postgresql → POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
   bigquery   → BIGQUERY_CREDENTIALS_PATH, BIGQUERY_PROJECT_ID
   ```

2. Add `_build_dsn_from_credentials(credentials: dict, database_type: str) -> str` helper that
   assembles an `asyncpg`-compatible DSN string for PostgreSQL
   (`postgresql+asyncpg://user:pwd@host:port/db`).  For BigQuery, return a `bigquery://`
   DSN string (handled further in TASK-231).

3. Update `__init__` resolution logic:

   ```
   engine provided?  → use it directly
   dsn provided?     → call _get_engine(dsn, search_path)  (unchanged)
   neither?          → _get_default_credentials(database_type) → _build_dsn_from_credentials
                       → _get_engine(dsn, search_path)
   ```

   Keep existing `_get_engine` unchanged.

**Reference**: `parrot/tools/databasequery.py:543` — `_get_default_credentials` for the exact
env-var names and navconfig call pattern to follow.

**NOT in scope**: BigQuery engine creation (TASK-231), cache changes (TASK-230), exports (TASK-228).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/database/abstract.py` | MODIFY | Add credential resolution methods; update `__init__` |

---

## Implementation Notes

- Read the whole file before editing.
- Import `os` and `from navconfig import config` at the top if not already present.
- `_get_default_credentials` must not raise — return an empty dict with a logged warning if env
  vars are missing, so the engine creation fails with a clear SQLAlchemy error rather than a
  silent `None` DSN.
- Do not change any existing public method signatures (`analyze_schema`, `analyze_table`,
  `search_schema`, etc.).

---

## Acceptance Criteria

- [x] `_get_default_credentials("postgresql")` returns a dict with keys `host`, `port`,
  `database`, `user`, `password` populated from env vars
- [x] `_get_default_credentials("bigquery")` returns a dict with keys `credentials` and
  `project_id` populated from env vars
- [x] `AbstractSchemaManagerTool(allowed_schemas=["public"])` (no `dsn`, no `engine`) builds
  a DSN from env vars without raising `AttributeError` or `TypeError`
- [x] Existing `PgSchemaSearchTool` behaviour is unchanged when `dsn` or `engine` is explicitly
  provided
- [x] `ruff check parrot/tools/database/abstract.py` passes

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/tools-database.spec.md` for full context
2. **Read** `parrot/tools/databasequery.py` lines 543–620 for the credential pattern to follow
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Read** `parrot/tools/database/abstract.py` in full before editing
5. **Implement** the changes as described in Scope
6. **Verify**:
   ```bash
   source .venv/bin/activate
   ruff check parrot/tools/database/abstract.py
   python -c "
   import os; os.environ.update({'POSTGRES_HOST':'localhost','POSTGRES_PORT':'5432',
   'POSTGRES_DB':'test','POSTGRES_USER':'test','POSTGRES_PASSWORD':'test'})
   from parrot.tools.database.abstract import AbstractSchemaManagerTool
   creds = AbstractSchemaManagerTool._get_default_credentials.__func__(None, 'postgresql')
   print('Creds OK:', list(creds.keys()))
   "
   ```
7. **Move this file** to `sdd/tasks/completed/TASK-229-database-tools-credential-resolution.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-4-6
**Date**: 2026-03-08
**Notes**:
- Added `_get_default_credentials(database_type)` method reading from navconfig with os.environ fallback
- Added `_build_dsn_from_credentials(credentials, database_type)` helper for PostgreSQL (`postgresql+asyncpg://...`) and BigQuery (`bigquery://...`) DSNs
- Updated `__init__` with 3-tier resolution: engine → dsn → env vars
- Removed unused `asyncpg_sqlalchemy_url` import (no longer needed as fallback)
- navconfig import is lazy (inside `_get_default_credentials`) to avoid circular imports
- Logs warnings when critical env vars (POSTGRES_PASSWORD, BIGQUERY_PROJECT_ID) are missing
- All public method signatures unchanged
- `ruff check` passes clean

**Deviations from spec**: None.
