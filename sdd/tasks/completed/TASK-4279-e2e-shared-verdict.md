# TASK-4279: Extract shared verdict helper for E2E runner/evidence

**Feature**: FEAT-660 — e2e-runner-fixes
**Spec**: sdd/specs/e2e-runner-fixes.spec.md
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-4278
**Assigned-to**: agent

## Context

`runner.py`'s `_verdict_status` and `evidence.py`'s `verify_evidence`
independently recompute overlapping "required node → pass/fail/blocked" logic
across two modules with no shared helper. Currently consistent, but a future
edit to one could silently diverge from the other.

Resolves ledger issue:b8ccc87e9274.

## Scope

Extract the shared required-node pass/fail computation into a new
`e2e/_verdict.py` module. Both `runner.py` and `evidence.py` call it.

### NOT in scope
- Changing verdict semantics
- Modifying the E2E plan schema

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/_verdict.py` | CREATE | Shared verdict helper |
| `packages/ai-parrot-server/src/parrot/e2e/runner.py` | MODIFY | Delegate to shared helper |
| `packages/ai-parrot-server/src/parrot/e2e/evidence.py` | MODIFY | Delegate to shared helper |

## Acceptance Criteria

- [ ] `_verdict_status` and `verify_evidence` share one helper for required-node logic
- [ ] No duplicated pass/fail computation between runner.py and evidence.py
- [ ] `ruff check` passes on all modified/created files
- [ ] Existing e2e tests pass

## Validation Commands

```bash
ruff check packages/ai-parrot-server/src/parrot/e2e/_verdict.py packages/ai-parrot-server/src/parrot/e2e/runner.py packages/ai-parrot-server/src/parrot/e2e/evidence.py
PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src pytest packages/ai-parrot-server/tests/e2e/ -x -q --timeout=30
```

## Completion Note

Added e2e/_verdict.py evaluate_required_nodes() returning per-node findings (missing/blocked/not_passed/phase_failure); runner._verdict_status and evidence.verify_evidence both delegate. Semantics unchanged. Unit e2e suite: 451 pass; 1 pre-existing failure test_mcp_targets real_subprocess (fails on clean tree too).
