# TASK-4277: Fix QA / background nitpicks

**Feature**: FEAT-659 — nodes-qa-tech-debt
**Spec**: sdd/specs/nodes-qa-tech-debt.spec.md
**Status**: pending
**Priority**: low
**Estimated effort**: XS
**Depends-on**: none
**Assigned-to**: agent

## Context

Three one-line cleanups from the FEAT-604 adversarial code review.

Resolves ledger issue:4394a29b9202.

## Scope

(a) Remove `log_path.write_bytes(b"")` dead I/O in background.py's
empty-invocations branch — `_append_log` opens in "a" mode and creates the
file itself.

(b) Rename criterion suffix `" (core escalation)"` to `" (escalation)"` in
qa.py — it is applied to cap/impact escalations too, which aren't core.

(c) Remove vacuous `assert int(plan.cap_impacted["a"], 16) >= 0` in
`test_cap_escalation_ledger.py` — always true for any valid hex string; the
length-64 check on the preceding line is the real assertion.

### NOT in scope
- Any behavioral changes beyond the cosmetic fixes above

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | Remove dead write_bytes(b"") |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | Rename criterion suffix |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py` | MODIFY | Remove vacuous hex assertion |

## Acceptance Criteria

- [ ] No `write_bytes(b"")` in background.py's empty-invocations branch
- [ ] Criterion suffix is `" (escalation)"`, not `" (core escalation)"`
- [ ] No `assert int(plan.cap_impacted` in test_cap_escalation_ledger.py
- [ ] Existing tests pass

## Validation Commands

```bash
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py -x -q --timeout=30
```

## Completion Note

(filled by implementing agent)
