# TASK-4706: Join-grain safety, filtered and derived metrics (M5b)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4468
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M5; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Extend NativeCompiler over LoadedModel.related_models with declared composite-key inner/left joins. Plan at measure grain, allow many-to-one, reject aggregate fan-out, sibling many-side joins and ambiguous paths.
- Lower filtered measures to FILTER/CASE for the target dialect. Expand derived metric dependencies in deterministic order and use CASE to return NULL on divide-by-zero. Preserve dependency provenance.
- Keep immutable inputs and stateless compilation. Test full v1 DuckDB expected rows, all three dialect golden SQL and cross-process SQL hashing under differing PYTHONHASHSEED.
- Only compiler and its new extension test file change; preserve the lower-ID compiler entry points and single-table tests.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py` | MODIFY | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_native_extensions.py` | CREATE | Focused regression evidence |

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

- TASK-4468: consumes packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py, packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py (Native single-table compiler and async compile entry (M5a))

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
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_native_extensions.py",
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

### `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py` (MODIFY)

Dependency-created anchor `class NativeCompiler` — expected occurrences: **1** in the producer blueprint. It is absent on dev; re-read its actual line/count after the producer lands, before any edit.

```python
# MODIFY the dependency-owned class NativeCompiler (expected occurrences: 1).
# Verify the actual post-dependency line/hash before editing; it does not exist on dev.
# Retain compile(self, query: SemanticQuery, dialect: str) -> CompiledQuery.
# FILL IN: add deterministic grain-safe join planning, filtered measures and
# topological derived lowering inside the existing compile pipeline (AC11/AC24).
# Preserve alias/physical provenance and CASE divide-by-zero NULL semantics.
# Do not edit engines/__init__.py or the prior single-table test file.
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_native_extensions.py` (CREATE)

```python
"""Regression contract: Join-grain safety, filtered and derived metrics (M5b)."""
from pathlib import Path
import pytest


def test_many_to_one_and_fanout_rejection(tmp_path: Path) -> None:
    """Verify many to one and fanout rejection."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_filtered_derived_metrics_and_zero_denominator(tmp_path: Path) -> None:
    """Verify filtered derived metrics and zero denominator."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_cross_process_hash_and_golden_sql(tmp_path: Path) -> None:
    """Verify cross process hash and golden sql."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_native_extensions.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Extend NativeCompiler over LoadedModel.related_models with declared composite-key inner/left joins. Plan at measure grain, allow many-to-one, reject aggregate fan-out, sibling many-side joins and ambiguous paths.
- [ ] Lower filtered measures to FILTER/CASE for the target dialect. Expand derived metric dependencies in deterministic order and use CASE to return NULL on divide-by-zero. Preserve dependency provenance.
- [ ] Keep immutable inputs and stateless compilation. Test full v1 DuckDB expected rows, all three dialect golden SQL and cross-process SQL hashing under differing PYTHONHASHSEED.
- [ ] Only compiler and its new extension test file change; preserve the lower-ID compiler entry points and single-table tests.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_native_extensions.py -q`

## Test Specification

- `test_many_to_one_and_fanout_rejection`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_filtered_derived_metrics_and_zero_denominator`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_cross_process_hash_and_golden_sql`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4706` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Seat: sonnet (native), 1 attempt. Notes: related-model members compile but policy/governance only knows root members (for governance tasks); derived division has no float cast (postgres integer division risk); dependencies() public helper added.
Engine fidelity gate clean; merge-tier validation green; orchestrator review approved.
