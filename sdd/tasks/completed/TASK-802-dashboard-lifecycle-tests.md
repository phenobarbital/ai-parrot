# TASK-802: Regression tests for dashboard draft/publish lifecycle

**Feature**: FEAT-114 — Dashboard Draft/Publish Lifecycle
**Spec**: `sdd/specs/navigator-dashboard-draft-publish-lifecycle.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-800, TASK-801
**Assigned-to**: unassigned

---

## Context

TASK-800 and TASK-801 shipped the lifecycle feature during a live
iteration without tests. This task backfills the regression coverage
so that the business-rule invariants are asserted:

- **Always-draft invariant**: `is_system=True` is not reachable via
  `create_dashboard` under any circumstances.
- **Publish atomicity**: `is_system=True` AND `user_id=NULL` always
  change together via `publish_dashboard`.
- **Authorization**: only owner or superuser can publish.
- **Idempotency**: republishing is a no-op.
- **Clone coherence**: cloned dashboards are drafts owned by the caller.

Implements **Module 3** of the spec.

---

## Scope

Create `tests/unit/test_navigator_dashboard_lifecycle.py` with:

### Test group A — `create_dashboard` shape invariants

- `test_dashboard_create_input_has_no_is_system_field`:
  `"is_system" not in DashboardCreateInput.model_fields`.
- `test_create_dashboard_has_no_is_system_kwarg`:
  `"is_system" not in inspect.signature(NavigatorToolkit.create_dashboard).parameters`.
- `test_create_dashboard_insert_payload_is_system_false`:
  With `insert_row` monkeypatched to capture kwargs, calling
  `create_dashboard(..., confirm_execution=True)` must produce
  `data["is_system"] is False` (not `None`, not `True`).

### Test group B — `clone_dashboard` owner coherence

- `test_clone_dashboard_defaults_user_id_to_self`:
  When called with `user_id=None`, captured INSERT has
  `data["user_id"] == self.user_id`.
- `test_clone_dashboard_respects_explicit_user_id`:
  When `user_id=999` is explicitly passed, captured INSERT has
  `data["user_id"] == 999`.

### Test group C — `publish_dashboard` authorization

- `test_publish_rejects_non_owner_non_superuser`:
  Non-superuser caller with `user_id=42` trying to publish a
  dashboard owned by `user_id=99` → `PermissionError`.
- `test_publish_allows_owner`:
  `self.user_id == dashboard.user_id`, not superuser → executes.
- `test_publish_allows_superuser_any_owner`:
  Superuser with `self.user_id != dashboard.user_id` → executes.
- `test_publish_allows_superuser_orphan`:
  Superuser publishing a dashboard with `user_id=NULL` → executes.
- `test_publish_rejects_non_superuser_orphan`:
  Non-superuser trying to publish a `user_id=NULL` dashboard →
  `PermissionError`.

### Test group D — `publish_dashboard` plan/confirm

- `test_publish_plan_then_confirm`:
  First call with `confirm_execution=False` → returns
  `{"status": "confirm_execution", "action": "..."}` without UPDATE.
  Second call with `confirm_execution=True` → executes UPDATE.
- `test_publish_plan_shows_before_after`:
  Plan message contains both `is_system: False → True` and
  `user_id: <N> → NULL`.

### Test group E — `publish_dashboard` idempotency + UPDATE shape

- `test_publish_idempotent_on_already_system`:
  Dashboard with `is_system=True` → returns `{"already_published":
  True}`; `update_row` never called.
- `test_publish_update_payload_atomic`:
  With `update_row` monkeypatched, verifies
  `data == {"is_system": True, "user_id": None}`.
- `test_publish_missing_dashboard_returns_error`:
  Unknown `dashboard_id` → returns `{"status": "error"}`.

### Fixtures

- Helper that builds a `NavigatorToolkit` instance with
  monkeypatched `_check_program_access`, `_check_write_access`,
  `_load_user_permissions` (all no-ops), `select_rows` (returns
  canned dashboard row), `update_row` / `insert_row` (capture
  kwargs into a list so tests can assert on the payload), and
  `_is_superuser` / `user_id` set per-test.

**NOT in scope**:
- Integration tests against live DB (optional, not required).
- Tests for `update_dashboard` (unchanged in this feature).
- Tests for widget creation inside a transaction (covered by
  FEAT-112 TASK-799 in a different way).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/unit/test_navigator_dashboard_lifecycle.py` | CREATE | New regression test module (~300 LOC including stubs and fixtures). |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import os, sys
from conftest_db import setup_worktree_imports
import pytest
import inspect
from parrot_tools.navigator.toolkit import NavigatorToolkit
from parrot_tools.navigator.schemas import (
    DashboardCreateInput,
    PublishDashboardInput,
)
```

### Existing Signatures to test

```python
NavigatorToolkit.create_dashboard(...)              # no is_system kwarg
NavigatorToolkit.clone_dashboard(source, new_name, ..., user_id=None, ...)
NavigatorToolkit.publish_dashboard(dashboard_id, confirm_execution=False) -> Dict
```

### Does NOT Exist

- ~~`NavigatorToolkit.unpublish_dashboard`~~ — deferred. Do not test.
- ~~`_check_dashboard_ownership` helper~~ — inlined in
  `publish_dashboard`; assert behaviour through the method's public
  interface, not a helper.
- ~~A `DashboardState` enum~~ — state is raw columns (`is_system`,
  `user_id`); do not introduce one in tests.

---

## Implementation Notes

Test doubles should monkeypatch at the instance level
(`monkeypatch.setattr(toolkit, "_check_write_access", async_noop)`)
rather than the class level — so tests don't leak between each
other. Use `AsyncMock` from `unittest.mock` for async helpers where
concise, or hand-rolled `async def` stubs for explicit capture.

For authorization tests, the key insight is the inline check in
`publish_dashboard`::

    if not self._is_superuser:
        if owner_id is None: raise PermissionError
        if int(owner_id) != int(self.user_id): raise PermissionError

— so tests can drive the branch by setting `toolkit._is_superuser`
and `toolkit.user_id` directly after bypassing `_load_user_permissions`.

For the "plan then confirm" test, the plan response is a dict (not
a side effect on the DB) so two separate calls are easy to assert.

---

## Acceptance Criteria

- [ ] File `tests/unit/test_navigator_dashboard_lifecycle.py` exists.
- [ ] All 14 tests across groups A-E pass.
- [ ] Prior tests (TASK-796 + refactor + TASK-799) still pass.
- [ ] `compileall` + `pytest -v` green.
- [ ] No changes under `packages/ai-parrot/` or
      `packages/ai-parrot-tools/src/parrot_tools/`.
- [ ] Test module reuses `conftest_db.py`.

---

## Agent Instructions

1. Read the spec at `sdd/specs/navigator-dashboard-draft-publish-lifecycle.spec.md`.
2. Verify TASK-800 + TASK-801 are `done` in the index.
3. Verify the code under test exists:
   - `grep -nE "def publish_dashboard|def create_dashboard|def clone_dashboard" packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`
4. Update `.index.json` → this task to `in-progress`.
5. Create the test file per the pattern.
6. Run `pytest tests/unit/test_navigator_dashboard_lifecycle.py -v`.
7. Verify all 14 tests pass.
8. Move task file to `completed/`, update index to `done`.
9. Fill in the Completion Note.

---

## Completion Note

**Completed by**: Claude Code (Opus 4.7)
**Date**: 2026-04-22
**Commits**: `b93644f0` (worktree), merged to dev.

**Notes**:
- 16 tests created (the spec called for 14; expanded to cover
  `test_clone_dashboard_respects_explicit_user_id` and
  `test_publish_dashboard_input_fields` as bonus invariants).
- 16/16 passing. Full Navigator unit suite: 47 passing.
- `_make_toolkit` helper builds NavigatorToolkit via `__new__` and
  stubs: permission helpers, id resolvers, `select_rows`,
  `insert_row`, `update_row`, `transaction` — so the method under
  test runs against controlled in-memory doubles.
- Clone tests had an initial bug where the `calls_iter` for
  `select_rows` only covered 2 calls; clone_dashboard actually makes
  3 (write-access check + main fetch + widgets fetch). Fixed to
  return 3 entries with a comment.

**Deviations from spec**: +2 bonus tests (16 vs. 14 target); no
negative deviations.
