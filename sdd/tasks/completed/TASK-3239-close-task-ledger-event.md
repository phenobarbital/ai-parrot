# TASK-3239: Emit task.closed from deterministic task closure

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: done
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

- [x] Successful closure emits after the active-copy post-condition.
- [x] Ledger contention cannot undo/misreport closure.
- [x] Existing close/move/index behavior remains idempotent.
- [x] `pytest tests/sdd/test_close_task_ledger.py -q` passes.

## Test Specification

Exercise success, already-closed, missing task, and soft-success paths with temporary indexes.

### Completion Note

The dispatched native (haiku) attempt implemented the right idea but with
two undeclared new files (`scripts/sdd/emit_task_closed.py` and
`tests/sdd/__init__.py` — the latter unnecessary; `tests/sdd/` already
collects fine without one), flagged `fidelity_violation` by the merge
gate and never merged. Reimplemented directly in this worktree using
only the two declared files: the emission is an inline `python3` heredoc
in `close_task.sh` itself (no new `.py` file), using only
`LedgerEvent`/`LedgerLog` (TASK-3228/3229) and `find_shared_root`
(TASK-3227) — log-only append, so there is no SQLite writer contention
for this script to handle at all (append is lock-free per spec §2).

Test file exercises the real script as a subprocess against a temp git
repo. Had to fix the subprocess's `PYTHONPATH`: a bare `python3` (unlike
pytest, which gets this worktree's `packages/ai-parrot/src` prepended by
the root `conftest.py`) resolves `parrot.*` through the shared venv's
main-checkout editable install, which doesn't have this feature's
`ledger/` package yet — without the fix every test would have silently
exercised only the "ledger unavailable" fallback path.

`pytest tests/sdd/test_close_task_ledger.py -q` → 5 passed. `ruff check`
/ `black --check` clean.

Seat: haiku (native) · Backend: none (in-process Claude Code subagent)
· Attempts: 1 (fidelity_violation, discarded) + 1 (sdd-worker rewrite).
Native attempt duration: ~263s, 88,548 tokens (subagent-reported total).

