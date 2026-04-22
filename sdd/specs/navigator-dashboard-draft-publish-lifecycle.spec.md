# Feature Specification: NavigatorToolkit — Dashboard Draft/Publish Lifecycle

**Feature ID**: FEAT-119
**Date**: 2026-04-21
**Author**: Javier León
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

The `nav_create_dashboard` tool defaulted to `is_system=True`, producing
published/system dashboards by default. Operationally, the required
admin workflow is two-phase:

1. **Draft phase** — administrator creates a dashboard, configures it,
   adds widgets. The dashboard is personal (`user_id=<admin>`) and
   *not* visible to other users yet (`is_system=False`).
2. **Publish phase** — when editing is finished, the admin publishes
   the dashboard, making it part of the system view shared across the
   program. Ownership is released (`user_id=NULL`) and it becomes
   system-wide (`is_system=True`).

The previous state of the toolkit made step 1 impossible by default
and provided no explicit step 2, so `is_system` and `user_id` were
being set in ad-hoc, inconsistent ways (or not set at all).

### Goals

- Make `create_dashboard` produce drafts by default — always.
- Provide an explicit, auditable tool to publish a draft
  (`nav_publish_dashboard`) with the correct atomic state transition.
- Make `clone_dashboard` consistent with the "draft = personal" model
  (cloned dashboards are drafts owned by the caller).

### Non-Goals

- Unpublishing (system → draft) — deferred. Requires a product
  decision on *which* user should re-own the dashboard.
- Allowing `update_dashboard` to modify `is_system` directly —
  intentionally *not* exposed. Publishing is a distinct semantic
  action and must go through `publish_dashboard` so the ownership
  release happens atomically.
- Soft-deletion, versioning, draft history — out of scope.

---

## 2. Architectural Design

### Overview

Three coordinated edits to `packages/ai-parrot-tools/src/parrot_tools/
navigator/` (schemas + toolkit), no framework changes:

1. **`create_dashboard` always draft**
   - Remove `is_system` from the `DashboardCreateInput` Pydantic
     schema so the LLM never sees it as a tool arg.
   - Remove the `is_system` kwarg from the function signature so
     programmatic callers can no longer set it either.
   - Hardcode `"is_system": False` in the INSERT payload.

2. **New `publish_dashboard` tool**
   - New `PublishDashboardInput` Pydantic schema.
   - `async def publish_dashboard(dashboard_id, confirm_execution=False)`:
     - Fetch current `(name, program_id, module_id, is_system, user_id)`.
     - Authorization: `_check_program_access` + `_check_write_access`
       *and* (owner of record OR superuser). Non-superuser callers
       whose `user_id` does not match the dashboard's `user_id` are
       rejected with `PermissionError`.
     - Idempotent: if already `is_system=True`, returns
       `{"already_published": True}` without executing the UPDATE.
     - Plan/confirm pattern (matches existing Navigator tools): first
       call with `confirm_execution=False` returns the plan; user
       approves; second call with `confirm_execution=True` executes.
     - Atomic UPDATE: `SET is_system=TRUE, user_id=NULL`.

3. **`clone_dashboard` owner coherence**
   - Default `user_id` to `self.user_id` when not explicitly provided.
     Cloned dashboards are drafts *owned* by whoever cloned them
     (rather than orphans).

### Component Diagram

```
Admin workflow:
  nav_create_dashboard    → is_system=False,  user_id=<admin>
         ↓
  nav_create_widget (×N)  → widgets accumulate on the draft
         ↓
  nav_publish_dashboard   → is_system=True,   user_id=NULL   (atomic)
         ↑
  nav_clone_dashboard     → is_system=False,  user_id=<admin>   (always draft)
```

### Integration Points

| Component | Change | Notes |
|---|---|---|
| `DashboardCreateInput` (schemas.py) | remove `is_system` field | Breaking for LLM arg shape (field disappears from tool schema). |
| `NavigatorToolkit.create_dashboard` | remove kwarg + hardcode | Breaking for programmatic callers passing `is_system=`. Grep of repo found no such callers. |
| `NavigatorToolkit.publish_dashboard` | **new method** | Exposed to LLM as `nav_publish_dashboard`. |
| `PublishDashboardInput` | **new schema** | `dashboard_id: str`, `confirm_execution: bool`. |
| `NavigatorToolkit.clone_dashboard` | default `user_id` to `self.user_id` | Backward-compatible: explicit `user_id=` still honoured. |
| `NavigatorToolkit.update_dashboard` | **no change** | `is_system` remains intentionally out of its schema. |

### Data Models

No DB schema changes — uses existing `navigator.dashboards` columns
(`is_system`, `user_id`).

### New Public Interfaces

```python
# LLM-facing:
nav_publish_dashboard(dashboard_id, confirm_execution=False) -> Dict

# Input:
class PublishDashboardInput(BaseModel):
    confirm_execution: bool = Field(default=False)
    dashboard_id: str = Field(...)
```

---

## 3. Module Breakdown

### Module 1: Draft-by-default on `create_dashboard` + owner on `clone_dashboard`
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/navigator/schemas.py` + `toolkit.py`
- **Responsibility**: Remove `is_system` from the public API of
  `create_dashboard`; hardcode `False` in the INSERT. Default
  `clone_dashboard.user_id` to `self.user_id`.
- **Depends on**: none.

### Module 2: `publish_dashboard` tool
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/navigator/schemas.py` + `toolkit.py`
- **Responsibility**: New Pydantic schema + async method implementing
  auth, idempotency, plan/confirm, atomic UPDATE.
- **Depends on**: Module 1 (semantics aligned: drafts exist by default).

### Module 3: Regression tests
- **Path**: `tests/unit/test_navigator_dashboard_lifecycle.py` (new)
- **Responsibility**: Lock down the three properties:
  1. `create_dashboard` always emits `is_system=False` (the kwarg
     no longer exists on the method).
  2. `publish_dashboard` rejects non-owner non-superuser callers;
     accepts owner; is idempotent; plan-then-confirm flow works.
  3. `clone_dashboard` defaults `user_id` to `self.user_id` when
     not provided.
- **Depends on**: Modules 1 + 2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_create_dashboard_has_no_is_system_kwarg` | 1 | `inspect.signature(create_dashboard).parameters` does not contain `is_system`. |
| `test_dashboard_create_input_has_no_is_system_field` | 1 | `DashboardCreateInput.model_fields` does not contain `is_system`. |
| `test_create_dashboard_insert_hardcodes_is_system_false` | 1 | With `insert_row` mocked, calling `create_dashboard(..., confirm_execution=True)` passes `"is_system": False` in the `data=` kwarg. |
| `test_clone_dashboard_defaults_user_id_to_self` | 1 | When `user_id=None`, INSERT uses `self.user_id`. |
| `test_publish_dashboard_rejects_non_owner_non_superuser` | 2 | Non-superuser caller whose `user_id` differs from the dashboard's `user_id` → `PermissionError`. |
| `test_publish_dashboard_allows_owner` | 2 | Owner path executes the UPDATE. |
| `test_publish_dashboard_allows_superuser_orphan` | 2 | Superuser can publish even if `dashboard.user_id IS NULL`. |
| `test_publish_dashboard_plan_then_confirm` | 2 | First call returns `status=confirm_execution`; second call with `confirm_execution=True` executes. |
| `test_publish_dashboard_idempotent` | 2 | When `dashboard.is_system=True`, returns `already_published=True`, no UPDATE. |
| `test_publish_dashboard_missing_returns_error` | 2 | Unknown `dashboard_id` returns `{"status": "error"}`. |

### Integration Tests

| Test | Description |
|---|---|
| `test_lifecycle_end_to_end` (optional, live-DB) | create → publish → verify DB state (`is_system=True`, `user_id=NULL`). |

### Test Data / Fixtures

Mock-based — no live DB required for Module 3 unit tests. Reuse
`conftest_db.py` pattern for worktree imports.

---

## 5. Acceptance Criteria

- [ ] `DashboardCreateInput` has no `is_system` field.
- [ ] `NavigatorToolkit.create_dashboard` signature has no `is_system` kwarg.
- [ ] Every row inserted by `create_dashboard` has `is_system=False`.
- [ ] `nav_publish_dashboard` appears in the tool list exposed by the LLM.
- [ ] `publish_dashboard` enforces owner-or-superuser authorization.
- [ ] `publish_dashboard` is idempotent on already-published dashboards.
- [ ] `publish_dashboard` plan/confirm cycle matches the pattern of
      other Navigator write tools.
- [ ] Clone dashboards default `user_id` to `self.user_id` when
      not explicitly provided.
- [ ] Unit tests in Module 3 pass.
- [ ] No files outside
      `packages/ai-parrot-tools/src/parrot_tools/navigator/` and
      `tests/unit/` are modified.

---

## 6. Codebase Contract

> Verified 2026-04-21 against `dev` at the time of implementation
> (commit `dca007f8` already merged).

### Verified Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/navigator/schemas.py
class DashboardCreateInput(BaseModel):    # post-change: no is_system
    confirm_execution: bool
    name: str
    module_id: Optional[int]
    module_slug: Optional[str]
    program_id: Optional[int]
    program_slug: Optional[str]
    description: Optional[str]
    dashboard_type: str
    position: int
    enabled: bool
    shared: bool
    published: bool
    allow_filtering: bool
    allow_widgets: bool
    params: Dict[str, Any]
    attributes: Dict[str, Any]
    ...

class PublishDashboardInput(BaseModel):   # NEW
    confirm_execution: bool
    dashboard_id: str
```

```python
# packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py
class NavigatorToolkit(PostgresToolkit):
    async def create_dashboard(
        self,
        name: str, module_id: Optional[int]=None, module_slug: Optional[str]=None,
        program_id: Optional[int]=None, program_slug: Optional[str]=None,
        description: Optional[str]=None, dashboard_type: str="3",
        position: int=1, enabled: bool=True, shared: bool=False,
        published: bool=True, allow_filtering: bool=True,
        allow_widgets: bool=True,
        params: Optional[Dict[str, Any]]=None,
        attributes: Optional[Dict[str, Any]]=None,
        conditions: Optional[Dict[str, Any]]=None,
        user_id: Optional[int]=None, save_filtering: bool=True,
        slug: Optional[str]=None,
        cond_definition: Optional[Dict[str, Any]]=None,
        filtering_show: Optional[Dict[str, Any]]=None,
        confirm_execution: bool=False,
    ) -> Dict[str, Any]: ...              # post-change: no is_system kwarg

    async def publish_dashboard(
        self,
        dashboard_id: str,
        confirm_execution: bool=False,
    ) -> Dict[str, Any]: ...              # NEW (line ~1700)

    async def clone_dashboard(
        self, source_dashboard_id: str, new_name: str,
        target_module_id: Optional[int]=None,
        target_program_id: Optional[int]=None,
        user_id: Optional[int]=None,
        confirm_execution: bool=False,
    ) -> Dict[str, Any]: ...              # user_id default → self.user_id
```

### Authorization helpers (reused as-is)

```python
async def _check_program_access(self, program_id: int) -> None: ...
async def _check_write_access(self, program_id: int) -> None: ...
async def _load_user_permissions(self) -> None: ...
self._is_superuser: Optional[bool]
self.user_id: Optional[int]
```

### Does NOT Exist (Anti-Hallucination)

- ~~`unpublish_dashboard`~~ — out of scope (see Non-Goals).
- ~~`DashboardUpdateInput.is_system`~~ — intentionally absent; use
  `publish_dashboard` for lifecycle transitions.
- ~~Bulk-publish multiple dashboards in one call~~ — not required by
  the current admin workflow.
- ~~`_check_dashboard_ownership` helper~~ — inlined inside
  `publish_dashboard` (small enough; no helper needed).

---

## 7. Implementation Notes & Constraints

### Patterns

- Same plan-then-confirm pattern used by every other write tool
  (`create_dashboard`, `update_dashboard`, `create_widget`, etc.).
- Use `self._to_uuid(dashboard_id)` for asyncpg-compatible UUIDs.
- Use `self.update_row(...)` (inherited from PostgresToolkit) for the
  atomic UPDATE — no raw SQL.
- Authorization via existing `_check_*_access` helpers + explicit
  ownership check inline.

### Known Risks

- **User confusion on "publish"** — the LLM may attempt to infer
  publication from `update_dashboard(published=True)`. Mitigation:
  `published` (DB column) is distinct from `is_system`. The
  docstring of `publish_dashboard` explicitly mentions this
  semantic.
- **Orphan drafts** (`is_system=False, user_id=NULL`) — theoretically
  possible via direct DB edits or legacy rows. Covered: non-superuser
  callers raise `PermissionError`; superusers can still publish.
- **Race on publish** — two admins hitting publish simultaneously
  would both succeed. Acceptable: the UPDATE is atomic and idempotent;
  second writer is a no-op.

---

## 8. Open Questions

- [ ] **Q1** — Do we eventually want `unpublish_dashboard`? Currently
      deferred per user directive. Tracker: this spec.
- [ ] **Q2** — Should `create_widget` / `update_widget` have an
      analogous ownership model, or do widgets follow their parent
      dashboard's state? Parked — widgets currently do not carry a
      `user_id` field; revisit if product needs surface.

---

## Worktree Strategy

Implementation already landed on branch
`feat-117-navigator-toolkit-asyncdb-conn-unwrap` (commit `dca007f8`)
and was merged to `dev`. This spec is **retroactive** — it captures
the design of the already-shipped code so the SDD record is complete.

For SDD hygiene going forward, future non-trivial feature work should
branch from `dev` into its own worktree *before* code is written.

Task IDs are assigned as:
- TASK-827 — Module 1 (draft default + clone owner), retroactive.
- TASK-828 — Module 2 (`publish_dashboard`), retroactive.
- TASK-829 — Module 3 (regression tests), to be implemented now.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-21 | Javier León | Initial draft, retroactive. Captures design of code already merged via commit `dca007f8`. Tests (Module 3) still to be implemented under TASK-829. |
