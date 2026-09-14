# TASK-3244: End-to-end SDD ledger lifecycle acceptance gate

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3226, TASK-3235, TASK-3236, TASK-3239, TASK-3240, TASK-3241, TASK-3242, TASK-3243
**Assigned-to**: unassigned

---

## Context

Final FEAT-566 acceptance gate: deferred finding, promotion, start/context, close event, blocker, acknowledgement, snapshot, and twin parity.

## Scope

- Add isolated lifecycle acceptance coverage spanning workflow instructions, CLI behavior, and close-task integration.
- Verify blocker scoping, human acknowledgement, event durability, and snapshot changed/unchanged behavior.
- Run focused SDD/wiki ledger suites and store `artifacts/logs/feat-566-lifecycle.log`.

**NOT in scope**: broad docs refactors, real remote pushes, multi-machine coordination, or unrelated production changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd/test_ledger_lifecycle_acceptance.py` | CREATE | Lifecycle acceptance test. |
| `artifacts/logs/feat-566-lifecycle.log` | CREATE | Final evidence. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
`LedgerService` is the public programmatic facade; `close_task.sh` and `wikitoolkit ledger blockers/export` are the lifecycle boundaries.

### Existing Signatures to Use
`close_task.sh <TASK-ID> <feature-slug> [verification]`; `ledger blockers <FEAT-ID>`; `ledger export`.

### Does NOT Exist
- ~~automatic critical acknowledgement~~ — only a `human:` acknowledgement resolves it.
- ~~feature-branch snapshot commit~~ — snapshot belongs to base-branch throwaway flow.

## Acceptance Criteria

- [ ] Lifecycle creates durable deferred/task records and surfaces them at start/next.
- [ ] Merge blocks only current-feature open/unacknowledged criticals.
- [ ] Snapshot is deterministic and twins remain equivalent.
- [ ] Focused acceptance commands pass with evidence retained.

## Test Specification

Use temporary paths and CLI stubs for Git network boundaries; do not perform a real push.
