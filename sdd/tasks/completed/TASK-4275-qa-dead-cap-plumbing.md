# TASK-4275: Remove dead cap-escalation plumbing from qa.py

**Feature**: FEAT-659 — nodes-qa-tech-debt
**Spec**: sdd/specs/nodes-qa-tech-debt.spec.md
**Status**: done
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: agent

## Context

`_record_green_escalations` in qa.py reads `plan.cap_hits` and passes
`impact_files`/`impacted_hashes` to `record_green_escalation`. But QANode
calls `plan_tests(tier="feature")`, and `select.py` only computes
`cap_hits`/`cap_impacted` when `tier == "merge"`. At feature tier these are
always `{}`, making the plumbing dead code.

The test `test_qa_records_cap_escalation_from_plan` only passes because it
monkeypatches `plan_tests` to return a hand-constructed `ScopePlan` with
`cap_hits` filled — a state the real function never produces at that tier.

Resolves ledger issue:488a64ba2023.

## Scope

Remove the dead cap-escalation reads from `_record_green_escalations` and its
`impact_files`/`impacted_hashes` parameters. Remove the unreachable test.

### NOT in scope
- Enabling cap detection at feature tier (larger change)
- Modifying select.py's tier gating logic

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | Remove cap_hits/cap_impacted reads from _record_green_escalations |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | MODIFY | Add comment confirming cap detection is merge-tier-only |

## Acceptance Criteria

- [ ] `grep -c 'cap_hits\|cap_impacted' packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` returns 0
- [ ] No `impact_files`/`impacted_hashes` parameters remain in `_record_green_escalations`
- [ ] `test_qa_records_cap_escalation_from_plan` is removed
- [ ] Existing QA node tests pass

## Validation Commands

```bash
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/ -x -q -k 'qa' --timeout=30
```

## Completion Note

Implemented and merged to `dev`. Index status `done`, verification `verified`,
recorded at 2026-10-13T23:13:27+00:00.

Implementing commit: `cea8655b3`

Files changed:
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py`
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py`
- `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py`

(3 files changed, 8 insertions(+), 68 deletions(-))

> Backfilled from the per-spec index and git history during worktree cleanup —
> `close_task.sh` stamps the index but never rewrites this section, so the
> implementing agent left it as the template placeholder.
