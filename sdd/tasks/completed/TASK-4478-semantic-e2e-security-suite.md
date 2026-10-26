# TASK-4478: Real-DuckDB governed-query security gate (M10 gate)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4477, TASK-4708
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M10; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Exercise stock repaired DuckDBSource end to end with model/policy fixtures and trusted identity binding; no source mocks and no LLM/network.
- Validate RLS below aggregation for two subjects with identical roles/tenant and different programs, including warm compile cache; prove cached compiler output unchanged.
- Cover PBAC denial/no-context/evaluator failure, compile-only/catalog/dimension-value/saved-query paths, masks/lineage, role-filtered suggestions and audit failure withholding.
- Test concurrent identity isolation and cleanup after cancellation, context-only queries without handles, stale versions and exact result provenance. This gate is consumed before exposing raw SQL and hand-off.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/tests/test_e2e_governed.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from pathlib import Path
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

No existing project symbol is extended; consume only dependency-created satellite contracts and the installed libraries below.

### Dependency Contracts and Parallelism Evidence

- TASK-4477: consumes packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py, packages/ai-parrot-semantic/src/parrot/semantic/__init__.py (Governed catalog, compile and query toolkit (M10a))
- TASK-4708: consumes packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py (Repair stock DuckDB source execution (M9D))

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
      "path": "packages/ai-parrot-semantic/tests/test_e2e_governed.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
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

### `packages/ai-parrot-semantic/tests/test_e2e_governed.py` (CREATE)

```python
"""Regression contract: Real-DuckDB governed-query security gate (M10 gate)."""
from pathlib import Path
import pytest


def test_real_source_two_subjects_warm_cache(tmp_path: Path) -> None:
    """Verify real source two subjects warm cache."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_all_denial_paths_and_no_sql_leak(tmp_path: Path) -> None:
    """Verify all denial paths and no sql leak."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_concurrent_context_and_required_audit_failure(tmp_path: Path) -> None:
    """Verify concurrent context and required audit failure."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/tests/test_e2e_governed.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Exercise stock repaired DuckDBSource end to end with model/policy fixtures and trusted identity binding; no source mocks and no LLM/network.
- [ ] Validate RLS below aggregation for two subjects with identical roles/tenant and different programs, including warm compile cache; prove cached compiler output unchanged.
- [ ] Cover PBAC denial/no-context/evaluator failure, compile-only/catalog/dimension-value/saved-query paths, masks/lineage, role-filtered suggestions and audit failure withholding.
- [ ] Test concurrent identity isolation and cleanup after cancellation, context-only queries without handles, stale versions and exact result provenance. This gate is consumed before exposing raw SQL and hand-off.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_e2e_governed.py -q`

## Test Specification

- `test_real_source_two_subjects_warm_cache`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_all_denial_paths_and_no_sql_leak`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_concurrent_context_and_required_audit_failure`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4478` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Seat: gpt-5.6-terra (codex), 1 attempt, 207s.
Engine fidelity gate clean; merge-tier validation green; orchestrator review approved.
