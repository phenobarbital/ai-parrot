# TASK-4282: Fix ruff violations in openai_base.py

**Feature**: FEAT-662 — clients-openai-base-tech-debt
**Spec**: sdd/specs/clients-openai-base-tech-debt.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: XS
**Depends-on**: none
**Assigned-to**: agent

## Context

`openai_base.py` has 2 pre-existing ruff errors:
- Line 67: B039 — mutable `ContextVar` default
- Line ~1715: B904 — `raise` without `from` in except-chain

Pre-existing on origin/dev, not introduced by any recent feature.

Resolves ledger issue:8d1149254f88.

## Scope

Fix the two ruff violations:
- B039: Replace mutable ContextVar default with factory pattern (use
  `ContextVar("name")` with no default, or wrap default in a factory)
- B904: Add `from exc` to the flagged `raise` in the except-chain

### NOT in scope
- Any behavioral changes to OpenAIBaseClient
- Fixing other style issues in the file

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/openai_base.py` | MODIFY | Fix B039 and B904 violations |

## Acceptance Criteria

- [ ] `ruff check packages/ai-parrot/src/parrot/clients/openai_base.py` passes (0 errors)
- [ ] No behavioral change to the ContextVar usage
- [ ] Existing client tests pass

## Validation Commands

```bash
ruff check packages/ai-parrot/src/parrot/clients/openai_base.py
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/unit/clients/ -x -q --timeout=30
```

## Completion Note

(filled by implementing agent)
