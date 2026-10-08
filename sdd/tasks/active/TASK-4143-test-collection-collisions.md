# TASK-4143: Fix order-dependent test collection collisions

**Feature**: FEAT-642 — graph-test-models-fixes
**Spec**: `sdd/specs/graph-test-models-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: agent:sdd-fix

## Context
Ledger issue:da0151296f53. See spec §1.

## Scope
- Create `packages/ai-parrot/tests/outputs/a2ui/graph/__init__.py` (empty).
- Delete `packages/ai-parrot/tests/unit/scripts/__init__.py` (empty).

**NOT in scope**: `tests/unit/__init__.py`; BotManager collection errors (FEAT-641).

## Files to Create / Modify
- `packages/ai-parrot/tests/outputs/a2ui/graph/__init__.py` (create)
- `packages/ai-parrot/tests/unit/scripts/__init__.py` (delete)

## Acceptance Criteria
- [ ] Full `--collect-only` of `packages/ai-parrot/tests` no longer errors on either file.
- [ ] Affected files pass together.

## Validation Commands
```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src pytest --collect-only -q packages/ai-parrot/tests
PYTHONPATH=packages/ai-parrot/src pytest -q packages/ai-parrot/tests/knowledge/wiki/inbox/test_models.py packages/ai-parrot/tests/outputs/a2ui/graph packages/ai-parrot/tests/unit/scripts
```

## Completion Note
