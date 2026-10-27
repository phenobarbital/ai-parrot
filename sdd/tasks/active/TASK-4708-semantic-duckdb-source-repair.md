# TASK-4708: Repair stock DuckDB source execution (M9D)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4463
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M9D; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Manually reapply branch b9f9983d67 behavior to current DuckDBSource: lazy duckdb import, one per-call connection in asyncio.to_thread, close in finally; preserve all existing source APIs.
- Repair query/query_row/get_metadata without asyncdb awaiting synchronous fetchall. Preserve named/positional params, metadata validation, empty-result column names and source error behavior.
- No authorizing/datasets-handler fix or other core edits; M12 was already delivered. Verify real file queries, cleanup, concurrent responsiveness and no import-time duckdb requirement.
- Never copy branch lockfiles or use a mocked DuckDB source to make the semantic integration pass.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py` | MODIFY | Scoped deliverable per blueprint |
| `packages/ai-parrot/tests/test_semantic_duckdb_source.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from pathlib import Path
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py:29
class DuckDBSource(AbstractDatabaseSource):
    # line 40
    def __init__(self) -> None:
    # line 67
    async def get_metadata(self, credentials: dict[str, Any], tables: list[str] | None=None) -> MetadataResult:
    # line 130
    async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> QueryResult:
    # line 171
    async def query_row(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> RowResult:
```

```python
# packages/ai-parrot/src/parrot/tools/databasequery/base.py:148
class QueryResult(BaseModel):
```

```python
# packages/ai-parrot/src/parrot/tools/databasequery/base.py:166
class RowResult(BaseModel):
```

```python
# packages/ai-parrot/src/parrot/tools/databasequery/base.py:134
class MetadataResult(BaseModel):
```

### Dependency Contracts and Parallelism Evidence

- TASK-4463: consumes packages/ai-parrot-semantic/pyproject.toml, packages/ai-parrot-semantic/src/parrot/semantic/__init__.py (MIT satellite packaging, workspace and CI (M1))

### Does NOT Exist

- `parrot.semantic` on dev — the package and symbols are created by this graph, never imported from the salvage branch environment.
- A semantic engine selector, sidemantic adapter or sidemantic parity oracle — native SQL generation is the only path.
- `PermissionContext.session_id` or `.agent_id` — the satellite identity contract carries trusted scope; request_id is not a session id.
- Automatic semantic authorization in `DatasetManager.add_dataframe()` — retained snapshots require the guarded host-sink contract.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/test_semantic_duckdb_source.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py#DuckDBSource",
    "sym:packages/ai-parrot/src/parrot/tools/databasequery/base.py#QueryResult",
    "sym:packages/ai-parrot/src/parrot/tools/databasequery/base.py#RowResult",
    "sym:packages/ai-parrot/src/parrot/tools/databasequery/base.py#MetadataResult"
  ]
}
```

## Implementation Notes

- Keep the scope and signatures fixed by spec rev 0.4. Complete the bounded blueprint gaps, not a broad refactor. Preserve the clean-room rule: do not open sidemantic source/API glue.
- Use async I/O, Pydantic v2, strict types and Google-style docstrings. CPU SQL passes run off the event loop. Use logging, not print; black/ruff are the format/lint gates.
- Run in the feature worktree with the existing venv activated; never repair the shared environment. Write test logs to `artifacts/logs/`.
- The full-file snippets below are starting points. Recheck dependency-created MODIFY anchors after their tasks land; they cannot be falsely reported verified on dev today.

## Implementation Blueprint

### Steps (in order)

1. Verify existing anchors and dependency contracts — because stale signatures invalidate a mechanical implementation.
2. Implement the listed targets in their blueprint order — because each target has one explicit owner and the graph orders shared writers.
3. Complete all scope-specific validation branches and regression scenarios — because success-path-only tests cannot establish the required fail-closed behavior.
4. Run this task's validation commands and focused lint — because only evidence from its declared files closes this task.

### `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py` (MODIFY)

Anchor `class DuckDBSource(AbstractDatabaseSource):` — occurrences: **1**, freshly verified at `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py:29`.

```python
# MODIFY verified class DuckDBSource(AbstractDatabaseSource): (occurrences: 1).
# Preserve query(credentials, sql, params=None), query_row, get_metadata and driver.
# Keep optional duckdb import INSIDE the synchronous execution helper.
# FILL IN: short-lived connection/execute/fetch/description/close in try/finally;
# await asyncio.to_thread from async methods. Return QueryResult/RowResult/MetadataResult.
# Translate named/positional params without SQL interpolation. Metadata identifiers
# continue through _validate_sql_identifier. Empty results keep cursor column names.
# Preserve async source error semantics; never block the event loop (AC28).
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot/tests/test_semantic_duckdb_source.py` (CREATE)

```python
"""Regression contract: Repair stock DuckDB source execution (M9D)."""
from pathlib import Path
import pytest


def test_real_file_queries_params_and_empty_columns(tmp_path: Path) -> None:
    """Verify real file queries params and empty columns."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_metadata_validation_and_connection_cleanup(tmp_path: Path) -> None:
    """Verify metadata validation and connection cleanup."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_event_loop_responsiveness_and_lazy_import(tmp_path: Path) -> None:
    """Verify event loop responsiveness and lazy import."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot/tests/test_semantic_duckdb_source.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Manually reapply branch b9f9983d67 behavior to current DuckDBSource: lazy duckdb import, one per-call connection in asyncio.to_thread, close in finally; preserve all existing source APIs.
- [ ] Repair query/query_row/get_metadata without asyncdb awaiting synchronous fetchall. Preserve named/positional params, metadata validation, empty-result column names and source error behavior.
- [ ] No authorizing/datasets-handler fix or other core edits; M12 was already delivered. Verify real file queries, cleanup, concurrent responsiveness and no import-time duckdb requirement.
- [ ] Never copy branch lockfiles or use a mocked DuckDB source to make the semantic integration pass.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot/tests/test_semantic_duckdb_source.py -q`

## Test Specification

- `test_real_file_queries_params_and_empty_columns`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_metadata_validation_and_connection_cleanup`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_event_loop_responsiveness_and_lazy_import`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4708` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.
