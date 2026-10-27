# TASK-4479: Security-gated raw SQL and guarded hand-off tools (M10b)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4478
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M10; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Extend existing toolkit.py run_sql/save_result_as_dataset exposure only after the real security suite passes. Preserve ordinary toolkit core behavior.
- run_sql is off by default and follows identical governance/audit; retain resolved exact physical provenance for any result handle.
- save_result_as_dataset claims with trusted identity, rechecks every member/physical usage and PBAC, validates the M9H sink then publishes with authorize_read. Some unrelated visible member must never authorize a hidden member.
- Missing factory/capability means no tool. Reject raw managers and shared owner scope. Verify changed policy/PBAC/metadata/session/expiry before publish and subsequent cached/derived reads. S5 is a release gate.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py` | MODIFY | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_e2e_handoff.py` | CREATE | Focused regression evidence |

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

- TASK-4478: consumes packages/ai-parrot-semantic/tests/test_e2e_governed.py (Real-DuckDB governed-query security gate (M10 gate))

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
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_e2e_handoff.py",
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

### `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py` (MODIFY)

Dependency-created anchor `class SemanticLayerToolkit` — expected occurrences: **1** in the producer blueprint. It is absent on dev; re-read its actual line/count after the producer lands, before any edit.

```python
# MODIFY dependency-created class SemanticLayerToolkit (expected occurrences: 1).
# Add methods below inside the class; preserve existing core methods.
async def run_sql(self, model: str, sql: str) -> SemanticQueryResult:
    """Run opt-in SQL through identical governance, provenance and audit checks."""
    # FILL IN: raw SQL flag + complete pipeline, disabled by default (AC12).
    ...

async def save_result_as_dataset(self, result_id: str, name: str,
                                 description: str | None = None) -> dict:
    """Publish an owned result only through a conforming guarded host sink."""
    # FILL IN: require_identity, claim, exact-member + PBAC recheck, guarded sink
    # capability/owner validation, authorize_read callback, audited publish (AC27).
    ...
# FILL IN: conditional per-instance exposure; never enable via caller flags or
# accept plain DatasetManager. Preserve audit-before-return and deny stale snapshots.
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_e2e_handoff.py` (CREATE)

```python
"""Regression contract: Security-gated raw SQL and guarded hand-off tools (M10b)."""
from pathlib import Path
import pytest


def test_raw_sql_opt_in_and_same_governance(tmp_path: Path) -> None:
    """Verify raw sql opt in and same governance."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_unrelated_visible_member_does_not_authorize_handle(tmp_path: Path) -> None:
    """Verify unrelated visible member does not authorize handle."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_guarded_sink_read_after_revocation(tmp_path: Path) -> None:
    """Verify guarded sink read after revocation."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_e2e_handoff.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Extend existing toolkit.py run_sql/save_result_as_dataset exposure only after the real security suite passes. Preserve ordinary toolkit core behavior.
- [ ] run_sql is off by default and follows identical governance/audit; retain resolved exact physical provenance for any result handle.
- [ ] save_result_as_dataset claims with trusted identity, rechecks every member/physical usage and PBAC, validates the M9H sink then publishes with authorize_read. Some unrelated visible member must never authorize a hidden member.
- [ ] Missing factory/capability means no tool. Reject raw managers and shared owner scope. Verify changed policy/PBAC/metadata/session/expiry before publish and subsequent cached/derived reads. S5 is a release gate.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_e2e_handoff.py -q`

## Test Specification

- `test_raw_sql_opt_in_and_same_governance`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_unrelated_visible_member_does_not_authorize_handle`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_guarded_sink_read_after_revocation`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4479` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Seat: qwen (nova), 1 attempt delivered a stub save_result_as_dataset (fake success); reworked by opus in fix commit e50b9bf1e600c9f2b7fbc2cc3001ef5ee57afe33. Open caveat: durable audit write occurs after sink publish (if audit required and write fails, dataset already exists in private sink). Failed claims are not audited by design.
Engine fidelity gate clean; merge-tier validation green; orchestrator review approved.
