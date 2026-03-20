# TASK-231: Database Tools — BigQuery Engine Fix & `_search_in_database` (`bq.py`)

**Feature**: Database Schema Tools — Completion & Hardening (FEAT-032)
**Spec**: `sdd/specs/tools-database.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-229
**Assigned-to**: claude-opus-4-6

---

## Context

> `BQSchemaSearchTool` inherits from `AbstractSchemaManagerTool` and overrides `analyze_schema`
> and `analyze_table` for BigQuery.  Two problems exist:
>
> 1. **Wrong engine**: `AbstractSchemaManagerTool._get_engine` creates an asyncpg engine
>    (`postgresql+asyncpg://...`), which cannot connect to BigQuery.  `BQSchemaSearchTool` must
>    override `_get_engine` to build a `bigquery://` connection via `sqlalchemy-bigquery`.
>
> 2. **Missing `_search_in_database`**: `PgSchemaSearchTool` has a two-step cache → database
>    fallback (`_search_in_database`), but `BQSchemaSearchTool` does not override `_execute`
>    or implement `_search_in_database`, so on cache miss it has no database fallback.

---

## Acceptance Criteria

- [x] `BQSchemaSearchTool.__init__` stores `_bq_credentials_path` and `_bq_project_id`
- [x] `BQSchemaSearchTool._get_engine` returns an engine with `bigquery` dialect (not asyncpg)
- [x] `BQSchemaSearchTool._search_in_database` is implemented and returns `List[TableMetadata]`
- [x] `BQSchemaSearchTool._execute` implements cache-first → database-fallback strategy
- [x] `ImportError` is raised with a clear message when `sqlalchemy-bigquery` is not installed
- [x] `ruff check parrot/tools/database/bq.py` passes

---

## Completion Note

**Completed by**: claude-opus-4-6
**Date**: 2026-03-08
**Notes**:
- Added `__init__` that stores `_bq_credentials_path` and `_bq_project_id` from credentials dict or navconfig fallback, forces `database_type="bigquery"`
- Overrode `_get_engine` to build a `bigquery://` engine via `sqlalchemy-bigquery` with optional `google.oauth2.service_account.Credentials`; raises clear `ImportError` when packages are missing
- Implemented `_execute` with cache-first → database-fallback strategy mirroring `PgSchemaSearchTool`
- Implemented `_search_in_cache` for cache lookups (specific table or similarity search)
- Implemented `_search_in_database` querying `INFORMATION_SCHEMA.TABLES` per schema with pattern matching, calling `analyze_table` and storing results in cache
- Existing `analyze_schema` and `analyze_table` methods preserved unchanged
- `ruff check` passes clean

**Deviations from spec**: None.
