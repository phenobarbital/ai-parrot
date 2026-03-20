# TASK-232: Database Tools — Tests (`tests/tools/database/`)

**Feature**: Database Schema Tools — Completion & Hardening (FEAT-032)
**Spec**: `sdd/specs/tools-database.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-3h)
**Depends-on**: TASK-228, TASK-229, TASK-230, TASK-231
**Assigned-to**: claude-opus-4-6

---

## Acceptance Criteria

- [x] `tests/tools/database/` directory with `__init__.py` exists
- [x] All four test files exist
- [x] `pytest tests/tools/database/ -v` — all tests pass, 0 failures (14 passed)
- [x] No live database connection required for any test

---

## Completion Note

**Completed by**: claude-opus-4-6
**Date**: 2026-03-08
**Notes**:
Created 5 files in `tests/tools/database/`:
- `__init__.py` — empty package marker
- `test_init_exports.py` (3 tests) — verifies `PgSchemaSearchTool` and `BQSchemaSearchTool` are importable from `parrot.tools.database` and present in `__all__`
- `test_cache_vector_tier.py` (5 tests) — verifies FAISSStore auto-creation, LRU-only fallback, `_store_in_vector_store` calls `add_documents` with `Document` objects, `_convert_vector_results` round-trips YAML, and `search_similar_tables` falls back on vector store errors
- `test_abstract_credentials.py` (2 tests) — verifies `_get_default_credentials` reads PostgreSQL and BigQuery env vars correctly
- `test_bq_tool.py` (4 tests) — verifies import, `ImportError` when `sqlalchemy-bigquery` is missing, credential storage, and `_search_in_database` returns a list with mocked session

All 14 tests pass. No live database connections needed.

**Deviations from spec**:
- Adapted `test_store_calls_add_documents` to check `Document.page_content` instead of dict `content` key (matching actual implementation which uses `Document` objects)
- Used a stub class instead of `__func__` for credential tests (simpler, same effect)
- Added `test_bq_engine_raises_without_sqlalchemy_bigquery` to directly verify the ImportError behavior
