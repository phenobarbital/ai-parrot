---
id: F008
query_id: Q011
type: glob
intent: Map existing test coverage for graphindex extractors and pipeline
executed_at: 2026-06-16T00:00:00Z
duration_ms: 600
parent_id: null
depth: 0
---

# F008 — 19 test files cover all extractors and pipeline stages

## Summary

Comprehensive test suite at `packages/ai-parrot/tests/knowledge/graphindex/` with 19
files. CodeExtractor tests cover module/class/function extraction, rationale nodes,
edge emission, parse error handling. No tests for Odoo-specific extraction, SQLite
persistence, or SQLiteGraphReader (all new).

## Citations

- path: `packages/ai-parrot/tests/knowledge/graphindex/test_code_extractor.py`
  symbol: CodeExtractor tests
- path: `packages/ai-parrot/tests/knowledge/graphindex/test_persist.py`
  symbol: GraphIndexPersistence (ArangoDB) tests
- path: `packages/ai-parrot/tests/knowledge/graphindex/test_builder.py`
  symbol: Full pipeline orchestration tests
- path: `packages/ai-parrot/tests/knowledge/graphindex/test_projection.py`
  symbol: OKF projection tests (FEAT-239)
- path: `packages/ai-parrot/tests/knowledge/graphindex/test_analytics.py`
  symbol: Analytics + knowledge gap tests (FEAT-215)

## Notes

New tests needed:
- test_odoo_extractor.py — Odoo model classes, fields, decorators, inheritance edges
- test_persist_sqlite.py — SQLite persistence, replace_document_slice, is_stale
- test_sqlite_reader.py — Reader navigation, FTS5 search, get_source, LRU cache
