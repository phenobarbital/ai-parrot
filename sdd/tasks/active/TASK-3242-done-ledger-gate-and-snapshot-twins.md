# TASK-3242: Done merge gate and base-branch ledger snapshot twins

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
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

- [ ] Merge gate scopes blockers to current feature; only close/human acknowledgement resolves them.
- [ ] PR and merge feature flows snapshot only changed output from throwaway base worktree.
- [ ] Hotfix skips snapshot; failed retry is bounded and non-fatal.
- [ ] Twin parity assertions pass.

## Test Specification

Verify command order and prohibit unsafe reset outside documented throwaway context.

