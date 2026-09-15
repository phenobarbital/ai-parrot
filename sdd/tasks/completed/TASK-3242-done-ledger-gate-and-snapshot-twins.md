# TASK-3242: Done merge gate and base-branch ledger snapshot twins

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3226, TASK-3236
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12. Merge stops for current-feature unacknowledged criticals and every feature done flow snapshots issues on `base_branch` without touching active worktrees.

## Scope

- Add blocker checking for `--merge`; PR flow reports blockers without refusing.
- Add feature-only snapshot procedure for PR/merge flows via detached throwaway worktree at `origin/<base_branch>`.
- Specify bounded rejected-push retry, re-export, cleanup, and hotfix exclusion across twins.
- Extend parity/safety tests.

**NOT in scope**: CLI implementation, changing the shared main worktree, snapshotting hotfixes, or broad Git cleanup.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-done.md` | MODIFY | Claude done flow. |
| `.agent/workflows/sdd-done.md` | MODIFY | Antigravity done flow. |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | Codex done flow. |
| `tests/sdd/test_ledger_workflow_twins.py` | MODIFY | Gate/snapshot parity tests. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
`wikitoolkit ledger blockers <FEAT-ID>` and `wikitoolkit ledger export` are supplied by TASK-3236.

### Existing Signatures to Use
The existing `/sdd-done` default is PR flow and `--merge` is opt-in.

### Does NOT Exist
- ~~snapshot committed from feature branch~~ — forbidden.
- ~~blockers from a different feature~~ — forbidden.
- ~~unbounded retry/reset outside throwaway worktree~~ — forbidden.

## Acceptance Criteria

- [x] Merge gate scopes blockers to current feature; only close/human acknowledgement resolves them.
- [x] PR and merge feature flows snapshot only changed output from throwaway base worktree.
- [x] Hotfix skips snapshot; failed retry is bounded and non-fatal.
- [x] Twin parity assertions pass.

## Test Specification

Verify command order and prohibit unsafe reset outside documented throwaway context.

### Completion Note

Dispatched via the pool (codex-spark hit the 1800s wall-clock cap with no
output; the qwen retry completed and merged, files exactly as declared).

This task's own file list correctly said MODIFY (not CREATE) for
`tests/sdd/test_ledger_workflow_twins.py`, acknowledging TASK-3240 (run
in the same parallel chunk) already created it — but the executed merge
still replaced the whole file with a from-scratch rewrite, discarding
TASK-3240's codereview-twin tests (no conflict was flagged since both
branches' diffs applied against a common "file doesn't exist" base).
Reconciled post-merge into one file with `TestDoneTwins` (this task) and
`TestCodereviewTwins` (TASK-3240) as separate classes, and fixed a
CWD-fragility bug present in both original versions: bare relative
workflow-file paths silently resolved against the MAIN checkout under
pytest (an unrelated navconfig chdir side-effect during test collection),
so every "parity" assertion was reading stale main-checkout content
without ever failing loudly. Strengthened those checks from bare
`len() > 1000` into real content assertions ("ledger blockers", "ledger
export", "hotfix").

`pytest tests/sdd/test_ledger_workflow_twins.py -q` → 8 passed (4 for
this task's own `TestDoneTwins`). `ruff check` / `black --check` clean.

Seat: qwen (nova) · Backend: nova · Model: qwen.qwen3-coder-480b-a35b-instruct
· Attempts: 2 (codex-spark timeout, qwen success) · Duration: 1801.2s +
238.4s · Tokens: n/a (codex-spark) + 1,917,811 in / 11,916 out (qwen).
Post-merge reconciliation applied by sdd-worker (sonnet), shared with
TASK-3240's fix commit.

