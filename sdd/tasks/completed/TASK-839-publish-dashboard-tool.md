# TASK-839: New `publish_dashboard` tool

**Feature**: FEAT-119 — Dashboard Draft/Publish Lifecycle
**Spec**: `sdd/specs/navigator-dashboard-draft-publish-lifecycle.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-838
**Assigned-to**: Claude Code (retroactive)

---

## Context

With drafts now being the default state of newly-created dashboards
(TASK-838), admins need an explicit "publish" action that atomically:

- Sets `is_system = TRUE`.
- Clears `user_id` (ownership release).

Exposed to the LLM as `nav_publish_dashboard`.

---

## Scope

- Add `class PublishDashboardInput(BaseModel)` to `schemas.py` with
  `confirm_execution: bool` + `dashboard_id: str`.
- Import `PublishDashboardInput` in `toolkit.py`.
- New `async def publish_dashboard(dashboard_id, confirm_execution=False)`
  placed between `list_dashboards` and `clone_dashboard` (toolkit.py
  ~line 1700).
  - Fetch current state: `(name, program_id, module_id, is_system, user_id)`.
  - Authorization: `_check_program_access` + `_check_write_access` +
    (owner match OR superuser). Non-superuser, non-owner → `PermissionError`.
  - Idempotent: if already `is_system=True` → return
    `{"already_published": True}` without UPDATE.
  - Plan/confirm pattern: first call returns plan; second call with
    `confirm_execution=True` executes.
  - Atomic UPDATE via `self.update_row(..., data={"is_system": True,
    "user_id": None}, where={"dashboard_id": <uuid>})`.
  - Return `{"status": "success", "result": {..., "previous_owner_user_id"}}`.

**NOT in scope**:
- Tests (TASK-840).
- `unpublish_dashboard` (deferred per spec Non-Goals).

---

## Files Modified

| File | Action |
|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/navigator/schemas.py` | Added `PublishDashboardInput`. |
| `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` | Imported `PublishDashboardInput`; added `publish_dashboard` method. |

---

## Acceptance Criteria

- [x] `PublishDashboardInput` defined with 2 fields.
- [x] `NavigatorToolkit.publish_dashboard` decorated with `@tool_schema(PublishDashboardInput)`.
- [x] `nav_publish_dashboard` appears in the LLM tool list on a
      running NavigatorToolkit.
- [x] Authorization enforces owner-or-superuser (line-level verified).
- [x] Idempotent on already-published dashboards.
- [x] Plan/confirm flow matches other Navigator write tools.
- [x] Atomic UPDATE uses `update_row` (respects whitelist + safety).

---

## Completion Note

**Completed by**: Claude Code (Opus 4.7)
**Date**: 2026-04-21
**Commits**:
- Worktree: `dca007f8` (same commit as TASK-838; lifecycle feature ships as one unit)
- Merge to dev: same merge commit as TASK-838

**Notes**:
- Co-shipped with TASK-838 for coherence — without both halves, the
  feature is meaningless (drafts you can't publish, or a publish tool
  with nothing to publish).
- Non-superuser path verified via inline ownership check:
  `int(owner_id) != int(self.user_id)` → `PermissionError`.
- Orphan drafts (`is_system=False, user_id=NULL`) are rejected for
  non-superusers (can't prove ownership) but allowed for superusers.

**Deviations from spec**: none.
