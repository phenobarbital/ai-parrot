# TASK-4283: Add invoke() budget-exhausted regression tests

**Feature**: FEAT-662 — clients-openai-base-tech-debt
**Spec**: sdd/specs/clients-openai-base-tech-debt.spec.md
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-4282
**Assigned-to**: agent

## Context

Before FEAT-579, no test exercised `OpenAIBaseClient.invoke()`'s
budget-exhausted finalize path or the deeper partial (bx2) path. The nested
try/except dispatch-block restructuring at ~openai_base.py:1608-1677
(introduced by FEAT-550) had zero regression coverage until FEAT-579
incidentally added telemetry tests. The underlying budget-exhausted control
flow needs its own direct test coverage, independent of telemetry.

Resolves ledger issue:cfdc7e0cce94.

## Scope

Add direct tests for:
1. Budget-exhausted finalize path — invoke() reaches the budget limit and
   triggers the finalization logic
2. Partial (bx2) path — invoke() enters the deeper partial-budget handling

Tests should be independent of telemetry (no telemetry assertions), testing
the control flow itself.

### NOT in scope
- Modifying the invoke() implementation
- Testing telemetry emission (covered by FEAT-579)

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/unit/clients/test_invoke_budget_exhausted.py` | CREATE | Direct budget-exhausted tests |

## Acceptance Criteria

- [ ] Budget-exhausted finalize path is tested directly
- [ ] Partial (bx2) path is tested directly
- [ ] Tests pass without telemetry opt-in
- [ ] `ruff check` passes on the new test file

## Validation Commands

```bash
ruff check packages/ai-parrot/tests/unit/clients/test_invoke_budget_exhausted.py
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/unit/clients/test_invoke_budget_exhausted.py -x -q --timeout=30
```

## Completion Note

(filled by implementing agent)
