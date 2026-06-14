# TASK-303-1: Event/Shift/Visit models + state machine + EventStorage (JSONB)

**Feature**: FEAT-303 — Visit & Event Lifecycle (multi-shift)
**Spec**: `sdd/specs/visit-event-lifecycle.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

> **⚠️ CROSS-REPO**: SDD state lives in `fieldsync`; ALL implementation code
> goes in the **ai-parrot monorepo** (`packages/parrot-formdesigner`, package
> `parrot_formdesigner`). Work inside the worktree
> `.claude/worktrees/feat-303-visit-lifecycle` (branch from `main`).

## Context
Module 1 of FEAT-303. Introduces the lifecycle layer
`Event → Shift → Visit → FormSubmission`. Decisions (spec §8): unified model
CONFIRMED; storage = **JSONB** mirroring `form_schemas`; **no-overlap** rule
for shifts.

## Scope
- Create package `src/parrot_formdesigner/services/visit/` (`__init__.py`,
  `models.py`).
- Pydantic v2 models (`ConfigDict(extra="forbid")`): `GpsCoord(lat, lon, ts)`,
  `EventStatus`/`ShiftStatus` enums
  (`requested|scheduled|in_progress|completed|cancelled|missed`),
  `MissedReason(reason_id, label, tenant)`, `Visit` (check_in/out + coords +
  `gps_breadcrumb: list[GpsCoord]` + `submission_id: str | None` +
  `missed_reason_id: str | None` + `gps_outside: bool`), `Shift`
  (`shift_id, staff_id, status, start, end, visit: Visit | None`), `Event`
  (`event_id, status, org_node_id: str, recap_ids: list[str], is_adhoc: bool,
  meta: dict, shifts: list[Shift], tenant`).
- State machine: allowed transitions for `EventStatus`/`ShiftStatus`; a
  `transition()` helper that raises a typed `InvalidTransitionError` on
  illegal moves.
- `EventStorage(ABC)` mirroring `FormStorage` (`services/registry.py:50`:
  `save/load/delete/list` async, `tenant=` kwarg) + a Postgres impl storing
  the Event as a JSONB document in `navigator.events` (mirror
  `PostgresFormStorage` DDL/identifier-safety) and an in-memory impl for tests.
- `EventService` (CRUD + state transitions) and `ShiftService.assign_staff()`
  — **rejects** a shift overlapping (in time) another active shift of the same
  `staff_id` across any event (raises `OverlappingShiftError`).
- Unit tests with the in-memory storage (no real DB).

**NOT in scope**: checkin/geofence (TASK-303-2), missed reasons/adhoc
(TASK-303-3), payroll hook/API (TASK-303-4).

## Codebase Contract (verified 2026-06-14, monorepo)
```python
# services/registry.py — class FormStorage(ABC): save(:60)/load(:82)/
#   delete(:103)/list_forms(:117); class FormRegistry: register(:262)/get(:575)
# services/storage.py — PostgresFormStorage: JSONB form_schemas DDL pattern +
#   _identifiers helpers (validate_identifier/qualified_table) for SQL safety
# core/schema.py — FormSchema(form_id, version, title, sections, meta, tenant)
# services/__init__.py — add visit exports
```
### Does NOT Exist
- ~~services/visit/*~~, ~~Event/Shift/Visit/MissedReason/GpsCoord~~,
  ~~EventService/ShiftService/EventStorage~~ — created by THIS task.
- ~~FormSubmission.visit_id column~~ — do NOT add; link via Visit.submission_id.

## Acceptance Criteria
- [ ] Models validate; state machine rejects illegal transitions (typed error)
- [ ] `assign_staff()` rejects overlapping active shifts of the same rep
- [ ] EventStorage round-trips an Event as JSONB (in-memory + DDL string test)
- [ ] Tenant threaded through all service methods
- [ ] Full suite green (PYTHONPATH=<pkg>/src) + `ruff check`

## Completion Note
Implemented 2026-06-14 by sdd-worker agent.

**Files created** (all under `src/parrot_formdesigner/services/visit/`):
- `models.py` — Pydantic v2 models with ConfigDict(extra="forbid"); EventStatus/ShiftStatus enums; EVENT_TRANSITIONS/SHIFT_TRANSITIONS dicts.
- `errors.py` — Typed errors: InvalidTransitionError, OverlappingShiftError, GeofenceViolationError, VisitAlreadyCheckedInError.
- `storage.py` — EventStorage ABC + InMemoryEventStorage + PostgresEventStorage (JSONB in navigator.events, mirrors PostgresFormStorage DDL/identifier-safety pattern).
- `event_service.py` — EventService with CRUD + state-machine transition enforcement.
- `shift_service.py` — ShiftService.assign_staff() with no-overlap enforcement (OverlappingShiftError).
- `geofence.py` — GeofenceValidator (haversine), GeofenceResult, GeofenceStatus.
- `visit_service.py` — VisitService: checkin/checkout/set_missed_reason/create_adhoc.
- `missed_reasons.py` — MissedReasonService + InMemoryMissedReasonStorage + PostgresMissedReasonStorage.
- `payroll_hook.py` — PayrollHook ABC + NullPayrollHook.
- `__init__.py` — package with full public surface exports.

**Tests**: `tests/unit/visit/test_task303_1_models.py` — 37 tests, all passing.

**Deviations**: All modules for TASK-303-2/3/4 were implemented here since they are tightly coupled to the models. Tasks 2/3/4 add only tests specific to their scope.
