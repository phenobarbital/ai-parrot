# TASK-4701: Research-first FEAT-742 Rust compiler proposal (manual follow-up)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4706
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 follow-up U3; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited. Owner-requested manual research follow-up, retained in index.manual_followups and deliberately absent from the runnable tasks array; the scheduler has no manual-mode flag.

## Scope

- Preserve the owner-requested research follow-up: invoke sdd-proposal for already reserved FEAT-742 after the final Python compiler/IR lands. No Rust code/crate, dependency or THIRD_PARTY file is implemented by FEAT-704.
- Research the SemaFlow derivation slice/attribution and navrules packaging precedents, grounded in the rev2 proposal dossier; author the follow-up proposal and bounded research source/findings/synthesis artifacts.
- Run interactively from dev under sdd-proposal; this is not an autonomous implementation task or part of the FEAT-704 runtime gate. Do not reserve a new feature id or claim source/licensing facts without research.
- Add a deterministic document-contract test for the produced proposal: FEAT-742 identity, inputs from the final compiler, attribution-before-code decision and no reopened Ibis dependency. No tests depend on network.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/proposals/semantic-layer-rust-compiler.proposal.md` | CREATE | Scoped deliverable per blueprint |
| `sdd/state/FEAT-742/source.md` | CREATE | Scoped deliverable per blueprint |
| `sdd/state/FEAT-742/findings.md` | CREATE | Scoped deliverable per blueprint |
| `sdd/state/FEAT-742/synthesis.json` | CREATE | Scoped deliverable per blueprint |
| `tests/sdd_scripts/test_semantic_rust_proposal.py` | CREATE | Focused regression evidence |

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

- TASK-4706: consumes packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py (Join-grain safety, filtered and derived metrics (M5b))

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
      "path": "sdd/proposals/semantic-layer-rust-compiler.proposal.md",
      "action": "CREATE"
    },
    {
      "path": "sdd/state/FEAT-742/source.md",
      "action": "CREATE"
    },
    {
      "path": "sdd/state/FEAT-742/findings.md",
      "action": "CREATE"
    },
    {
      "path": "sdd/state/FEAT-742/synthesis.json",
      "action": "CREATE"
    },
    {
      "path": "tests/sdd_scripts/test_semantic_rust_proposal.py",
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

### `sdd/proposals/semantic-layer-rust-compiler.proposal.md` (CREATE)

```markdown
---
id: FEAT-742
status: review
type: feature
base_branch: dev
---
# Rust/PyO3 semantic compiler proposal
<!-- FILL IN via sdd-proposal: landed Python IR, derivable SemaFlow slice,
MIT attribution before code, navrules packaging, deterministic SQL equivalence,
ABI/wheels/native_group risks, sources/confidence and explicitly deferred joins. -->
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `sdd/state/FEAT-742/source.md` (CREATE)

```markdown
# FEAT-742 research source

<!-- FILL IN: sourced research evidence from the invoked proposal workflow; never claim unperformed research. -->
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `sdd/state/FEAT-742/findings.md` (CREATE)

```markdown
# FEAT-742 research findings

<!-- FILL IN: sourced research evidence from the invoked proposal workflow; never claim unperformed research. -->
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `sdd/state/FEAT-742/synthesis.json` (CREATE)

```json
{
  "feature_id": "FEAT-742",
  "source_feature": "FEAT-704",
  "findings": [],
  "open_questions": []
}
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `tests/sdd_scripts/test_semantic_rust_proposal.py` (CREATE)

```python
"""Regression contract: Research-first FEAT-742 Rust compiler proposal (manual follow-up)."""
from pathlib import Path
import pytest


def test_proposal_identity_and_final_ir(tmp_path: Path) -> None:
    """Verify proposal identity and final ir."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_attribution_and_scope_constraints(tmp_path: Path) -> None:
    """Verify attribution and scope constraints."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `sdd/proposals/semantic-layer-rust-compiler.proposal.md` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `sdd/state/FEAT-742/source.md` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `sdd/state/FEAT-742/findings.md` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `sdd/state/FEAT-742/synthesis.json` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `tests/sdd_scripts/test_semantic_rust_proposal.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Preserve the owner-requested research follow-up: invoke sdd-proposal for already reserved FEAT-742 after the final Python compiler/IR lands. No Rust code/crate, dependency or THIRD_PARTY file is implemented by FEAT-704.
- [ ] Research the SemaFlow derivation slice/attribution and navrules packaging precedents, grounded in the rev2 proposal dossier; author the follow-up proposal and bounded research source/findings/synthesis artifacts.
- [ ] Run interactively from dev under sdd-proposal; this is not an autonomous implementation task or part of the FEAT-704 runtime gate. Do not reserve a new feature id or claim source/licensing facts without research.
- [ ] Add a deterministic document-contract test for the produced proposal: FEAT-742 identity, inputs from the final compiler, attribution-before-code decision and no reopened Ibis dependency. No tests depend on network.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest tests/sdd_scripts/test_semantic_rust_proposal.py -q`

## Test Specification

- `test_proposal_identity_and_final_ir`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_attribution_and_scope_constraints`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Run this manual follow-up under the sdd-proposal workflow on dev after its compiler dependency lands. Do not dispatch it as a runtime implementation task. Preserve FEAT-742 identity and generate the bounded research deliverables before running its document-contract test.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.
