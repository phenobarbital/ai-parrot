# TASK-827: Dashboard draft-by-default + clone owner coherence

**Feature**: FEAT-119 — Dashboard Draft/Publish Lifecycle
**Spec**: `sdd/specs/navigator-dashboard-draft-publish-lifecycle.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: Claude Code (retroactive)

---

## Context

Admin workflow requires dashboards to be created as drafts
(`is_system=False`, owned by the creator) and explicitly published
later via a dedicated tool (TASK-828). This task implements the
draft-default half of the contract plus the coherent "owner of a
clone = whoever cloned it" semantic.

---

## Scope

- Remove `is_system: bool = Field(default=True)` from
  `DashboardCreateInput` (schemas.py:194).
- Remove `is_system: bool = True` kwarg from
  `NavigatorToolkit.create_dashboard` signature (toolkit.py:1467).
- Hardcode `"is_system": False` in the `insert_row(...)` payload of
  `create_dashboard` (toolkit.py:1545).
- In `clone_dashboard`, default `user_id` to `self.user_id` when not
  explicitly provided (toolkit.py ~1770).

**NOT in scope**:
- `publish_dashboard` — separate task (TASK-828).
- Tests — TASK-829.
- `unpublish_dashboard` — out of scope per spec.

---

## Files Modified

| File | Action |
|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/navigator/schemas.py` | Removed `is_system` field from `DashboardCreateInput`. |
| `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` | Signature + insert payload change for `create_dashboard`; `user_id` default for `clone_dashboard`. |

---

## Acceptance Criteria

- [x] `DashboardCreateInput.model_fields` does not contain `is_system`.
- [x] `inspect.signature(NavigatorToolkit.create_dashboard).parameters`
      does not contain `is_system`.
- [x] `INSERT` payload in `create_dashboard` body contains
      `"is_system": False` (hardcoded).
- [x] `clone_dashboard` uses `self.user_id` when caller passes
      `user_id=None`.
- [x] Existing regression tests pass (20/20).
- [x] `compileall` clean.

---

## Completion Note

**Completed by**: Claude Code (Opus 4.7)
**Date**: 2026-04-21
**Commits**:
- Worktree: `dca007f8`
- Merge to dev: (via `git merge --no-ff` — same merge commit as TASK-828)

**Notes**:
- Both modules of FEAT-119 (TASK-827 + TASK-828) shipped in a single
  commit `dca007f8` because the lifecycle is a single coherent
  feature and splitting the Pydantic + signature change from the new
  tool would have produced an incoherent intermediate state (draft
  by default but no way to publish).
- Breaking change for programmatic `create_dashboard(is_system=...)`
  callers; repo grep found none.

**Deviations from spec**: none.
