# TASK-436: DatabaseToolkit — Unit & Integration Tests

**Feature**: DatabaseToolkit
**Feature ID**: FEAT-062
**Spec**: `sdd/specs/databasetoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-427, TASK-428, TASK-429, TASK-430, TASK-431, TASK-432, TASK-433, TASK-434, TASK-435
**Assigned-to**: unassigned

---

## Context

This task creates comprehensive test coverage for the entire DatabaseToolkit feature.
While individual source tasks include minimal test scaffolds, this task provides
the full test suite covering all result models, registry, sources, toolkit, and
end-to-end integration flows.

Implements **Module 10** from the spec.

---

## Scope

- Consolidate and expand tests from all previous task scaffolds into proper test files.
- Create `tests/tools/database/test_base_types.py` — result model tests.
- Create `tests/tools/database/test_registry.py` — registry + alias resolution tests.
- Create `tests/tools/database/test_sources.py` — all source validation tests.
- Create `tests/tools/database/test_toolkit.py` — toolkit, tools, schemas tests.
- Create `tests/tools/database/test_integration.py` — end-to-end flow tests with
  mocked asyncdb.
- Add `sqlglot` to project dependencies in `pyproject.toml`.
- Ensure `tests/tools/database/__init__.py` exists.

**NOT in scope**: Implementation code (all previous tasks), live database tests
(those require infrastructure).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/tools/database/__init__.py` | MODIFY | Ensure it exists (may already exist from FEAT-032) |
| `tests/tools/database/test_base_types.py` | CREATE | Result models + AbstractDatabaseSource tests |
| `tests/tools/database/test_registry.py` | CREATE | Registry + normalize_driver tests |
| `tests/tools/database/test_sources.py` | CREATE | All source validation + driver/dialect tests |
| `tests/tools/database/test_toolkit.py` | CREATE | Toolkit, tools, schemas tests |
| `tests/tools/database/test_integration.py` | CREATE | E2E flow with mocked asyncdb |
| `pyproject.toml` | MODIFY | Add `sqlglot>=20.0` to dependencies |

---

## Implementation Notes

### Tests to Include

#### test_base_types.py
- All result model instantiation tests (ValidationResult, ColumnMeta, TableMeta,
  MetadataResult, QueryResult, RowResult)
- ABC cannot-instantiate test
- `resolve_credentials()` precedence test
- `validate_query()` with/without dialect

#### test_registry.py
- `normalize_driver()` parametrized test for ALL aliases in the spec table
- `register_source()` + `get_source_class()` round-trip
- Unknown driver raises `ValueError`
- Idempotent normalization: `normalize_driver("pg")` → `"pg"`

#### test_sources.py
- For each source: driver attribute, dialect attribute, validate valid/invalid queries
- MSSQL: EXEC/EXECUTE statement validation
- MongoDB: JSON filter, pipeline, invalid JSON, non-object JSON
- InfluxDB: Flux pattern, non-Flux rejection
- Elasticsearch: valid JSON DSL, missing keys, non-JSON
- DocumentDB/Atlas: extends MongoSource, correct dbtype

#### test_toolkit.py
- `get_tools()` returns 4 tools
- Tool names match expected set
- `get_schema()` produces valid JSON for each tool
- `get_source()` caching
- `get_source()` alias resolution
- `get_tool_by_name()` found/not-found
- `cleanup()` clears cache
- Arg schema validation tests

#### test_integration.py
- Mock asyncdb to simulate database responses
- Three-step flow: metadata → validate → execute
- Validate → execute with invalid query (should fail at validate)
- Fetch single row flow

### Key Constraints
- Use `pytest` and `pytest-asyncio` for async tests
- Use `unittest.mock.AsyncMock` and `patch` for mocking asyncdb
- Do NOT require real database connections
- Existing test files in `tests/tools/database/` (from FEAT-032) must not be broken
- New test files should be independent and self-contained

### References in Codebase
- Existing test files: `tests/tools/database/test_*.py` (FEAT-032)
- Test patterns: `tests/tools/` for other tool test examples

---

## Acceptance Criteria

- [ ] All tests pass: `pytest tests/tools/database/test_base_types.py tests/tools/database/test_registry.py tests/tools/database/test_sources.py tests/tools/database/test_toolkit.py tests/tools/database/test_integration.py -v`
- [ ] `sqlglot` added to `pyproject.toml` dependencies
- [ ] Test coverage for all 13 source validation methods
- [ ] Test coverage for all 4 toolkit tools
- [ ] Test coverage for driver alias resolution (all aliases)
- [ ] No interference with existing FEAT-032 tests
- [ ] No tests require live database connections

---

## Test Specification

See the test scaffolds in each previous task (TASK-427 through TASK-435) plus
the spec's test specification table in section 4. This task consolidates and
expands all of them.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/databasetoolkit.spec.md` for full context
2. **Check dependencies** — ALL previous tasks (TASK-427 through TASK-435) must be completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Run**: `pytest tests/tools/database/ -v` and verify all pass
6. **Move this file** to `sdd/tasks/completed/TASK-436-dbtoolkit-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-03-25
**Notes**: All 138 tests pass across 5 test files (test_base_types.py, test_registry.py,
test_sources.py, test_toolkit.py, test_integration.py). sqlglot>=20.0 added to
pyproject.toml core dependencies. All acceptance criteria met. Existing FEAT-032 tests
continue to pass (9 tests). No live database connections required.

**Deviations from spec**: none
