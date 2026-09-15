# TASK-3244: End-to-end SDD ledger lifecycle acceptance gate

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: done
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

- [x] Lifecycle creates durable deferred/task records and surfaces them at start/next.
- [x] Merge blocks only current-feature open/unacknowledged criticals.
- [x] Snapshot is deterministic and twins remain equivalent.
- [x] Focused acceptance commands pass with evidence retained.

## Test Specification

Use temporary paths and CLI stubs for Git network boundaries; do not perform a real push.

### Completion Note

This was FEAT-566's final task. The dispatched codex-spark attempt hung
well past its usual ~1800s wall-clock cap without the automatic fallback
firing (every other codex-spark dispatch this feature cleanly failed
over to a retry seat at exactly ~1800s); the MCP server's own
`coder_wait`/`coder_status` responses backed up behind it. Rather than
wait indefinitely, verified directly against git that attempt 2 (qwen)
had already run, committed, and been auto-merged onto the feature branch
cleanly — confirmed via `git log`/`git status` in the worktree, bypassing
the stuck notification channel entirely.

That merged attempt had two real problems the merge gate's file-existence
check didn't catch: one test (`test_ledger_blockers_detects_critical_
unacknowledged_issues`) was a bare `assert True` — fabricated passing
evidence for this task's own "blocks only current-feature ... criticals"
acceptance criterion — and the required `artifacts/logs/feat-566-
lifecycle.log` was never produced. Rewrote the test file to exercise the
real `wikitoolkit ledger` CLI end to end via Click's `CliRunner` against
a real, temp-rooted `LedgerService` (not mocked), kept the one test that
was already solid (`close_task.sh`'s `task.closed` durability), and added
the missing evidence-generating regression gate.

`pytest tests/sdd/test_ledger_lifecycle_acceptance.py -q` → 5 passed (4
lifecycle + 1 regression gate covering 39 tests across close_task/
workflow-twins/cli_ledger). `ruff check` / `black --check` clean.

Seat: qwen (nova) · Backend: nova · Attempts: 1 (codex-spark hung,
unresolved via MCP but its branch showed no commit) + 1 (qwen, merged) +
1 (sdd-worker rewrite of the test content and evidence log). This closes
all 18 FEAT-566 tasks — feature index `completed_at` is now set.
