# TASK-3239: Emit task.closed from deterministic task closure

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3226, TASK-3236
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12. `close_task.sh` remains the authoritative move/index mechanism and adds `task.closed` only after its existing post-condition succeeds.

## Scope

- Invoke `wikitoolkit ledger` after verified closure to record task ID, feature, status, and verification.
- Preserve idempotent closure and exit codes; contention is soft success because the event log is durable.
- Add shell-level coverage using a controlled CLI stub.

**NOT in scope**: task-index schema changes, service implementation, instruction twins, or shell claim emission.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/close_task.sh` | MODIFY | Post-verification event emission. |
| `tests/sdd/test_close_task_ledger.py` | CREATE | Ordering/idempotency tests. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
`close_task.sh` currently moves active tasks, updates `sdd/tasks/index/<slug>.json` with `jq`, and hard-verifies no active twin remains.

### Existing Signatures to Use
`scripts/sdd/close_task.sh <TASK-ID> <feature-slug> [verified|partial|forced]` is the established interface.

### Does NOT Exist
- ~~task lifecycle ledger emission~~ — this task adds `task.closed` only.
- ~~shell-side claim emission~~ — forbidden.

## Acceptance Criteria

- [ ] Successful closure emits after the active-copy post-condition.
- [ ] Ledger contention cannot undo/misreport closure.
- [ ] Existing close/move/index behavior remains idempotent.
- [ ] `pytest tests/sdd/test_close_task_ledger.py -q` passes.

## Test Specification

Exercise success, already-closed, missing task, and soft-success paths with temporary indexes.

