---
type: Wiki Overview
title: 'TASK-303-4: PayrollHook interface + visit API endpoints'
id: doc:packages-parrot-formdesigner-sdd-tasks-completed-task-303-4-payroll-hook-api-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 4. PayrollHook ABC (concrete Workday/claims impls are external) +
---

# TASK-303-4: PayrollHook interface + visit API endpoints

**Feature**: FEAT-303 — Visit & Event Lifecycle (multi-shift)
**Spec**: `sdd/specs/visit-event-lifecycle.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-303-2, TASK-303-3
**Assigned-to**: unassigned

> **⚠️ CROSS-REPO**: code in ai-parrot monorepo `packages/parrot-formdesigner`;
> worktree `.claude/worktrees/feat-303-visit-lifecycle`.

## Context
Module 4. PayrollHook ABC (concrete Workday/claims impls are external) +
the `/api/v1/visits/*` endpoints. Decision §8: PayrollHook registered via the
existing `callback_registry` pattern.

## Scope
- `services/visit/payroll_hook.py`: `PayrollHook` ABC with
  `async def on_checkout(self, visit, *, hours: float, tenant) -> None` and a
  no-op `NullPayrollHook`. `VisitService.checkout()` (303-2) invokes the
  registered hook AFTER a successful GPS-validated checkout with the computed
  GPS-validated hours. The hook MUST NOT write to `troc.worked_hours` directly
  (downstream FEAT-321 staging path) — this package only defines the interface.
- Register/resolve the hook via the existing `services/callback_registry.py`
  (`register_form_callback`/`get_form_callback` pattern) — do NOT inject via
  the VisitService constructor.
- Add handler methods to `FormAPIHandler` + routes in `setup_form_api()`
  (all wrapped with `_wrap_auth`):
  - `POST /api/v1/visits/events` → create Event (+shifts)
  - `POST /api/v1/visits/{event_id}/shifts/{shift_id}/checkin`
  - `POST /api/v1/visits/{event_id}/shifts/{shift_id}/checkout`
  - `POST /api/v1/visits/{event_id}/shifts/{shift_id}/missed`
  staff_id extracted from `AuthContext` JWT claims; tenant via `_get_tenant`.
  409 on geofence-blocked checkout, 409 on overlapping-shift assign, 404 on
  unknown event/shift.
- Lazy-init the visit services on the handler (like the FEAT-300/302 services).
- Endpoint tests (mocked-request style of `tests/unit/test_api_feat300.py`).

**NOT in scope**: real Workday/claims impl; worked_hours writes.

## Codebase Contract (verified 2026-06-14, monorepo)
```python
# services/callback_registry.py — register_form_callback(:65)/get_form_callback(:130)/
#   list_form_callbacks(:161)
# api/handlers.py — class FormAPIHandler; _build_auth_context(request)->AuthContext;
#   _get_tenant(request)->str; mirror get_form/create_form for parsing+json_response
# api/routes.py — _wrap_auth(:67); setup_form_api(:92); add_post/add_get pattern (:203+)
# services/auth_context.py — AuthContext.claims (JWT incl. sub/user_id)
# TASK-303-1/2/3: EventService, VisitService (checkin/checkout/set_missed_reason)
```
### Does NOT Exist
- ~~PayrollHook/NullPayrollHook~~, ~~/api/v1/visits/*~~ — created here.
- ~~Workday client / worked_hours write~~ — external (FEAT-026/321).

## Acceptance Criteria
- [ ] `on_checkout` invoked after successful checkout (NullPayrollHook in tests)
- [ ] 4 routes respond with fixture data (200/201/404/409 as appropriate)
- [ ] Hook resolved via callback_registry (not constructor injection)
- [ ] Full suite green + `ruff check`

## Completion Note
Implemented 2026-06-14 by sdd-worker agent.

**Files modified**:
- `src/parrot_formdesigner/api/handlers.py` — Added 4 handler methods: `_get_visit_service()` (lazy init), `create_event()`, `visit_checkin()`, `visit_checkout()`, `visit_set_missed()`.
- `src/parrot_formdesigner/api/routes.py` — Added 4 routes under `/api/v1/visits/`: `POST /events`, `POST /{event_id}/shifts/{shift_id}/checkin`, `POST /{event_id}/shifts/{shift_id}/checkout`, `POST /{event_id}/shifts/{shift_id}/missed`.

**PayrollHook**: ABC + NullPayrollHook implemented in TASK-303-1 (`services/visit/payroll_hook.py`). Hook resolved via `_CALLBACK_REGISTRY` in `visit_service._fire_payroll_hook()` using the `"payroll_hook"` key — not injected via constructor.

**Tests**: `tests/unit/visit/test_task303_4_payroll_hook_api.py` — 23 tests covering:
- PayrollHook ABC/NullPayrollHook behaviour
- Hook invoked after successful checkout; NOT invoked on geofence block; failures don't block checkout
- All 4 API endpoints: 200/201/400/404/409 responses
- callback_registry isolation per test (autouse fixture)
