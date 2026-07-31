---
type: Wiki Overview
title: 'TASK-303-2: Check-in/out + geofence validation + recap submission'
id: doc:packages-parrot-formdesigner-sdd-tasks-completed-task-303-2-checkin-checkout-geofence-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 2. Check-in/out flow with GPS geofence validation; recap submission
  is
---

# TASK-303-2: Check-in/out + geofence validation + recap submission

**Feature**: FEAT-303 — Visit & Event Lifecycle (multi-shift)
**Spec**: `sdd/specs/visit-event-lifecycle.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-303-1
**Assigned-to**: unassigned

> **⚠️ CROSS-REPO**: code in ai-parrot monorepo `packages/parrot-formdesigner`;
> worktree `.claude/worktrees/feat-303-visit-lifecycle`.

## Context
Module 2. Check-in/out flow with GPS geofence validation; recap submission is
blocked when the rep is outside the geofence.

## Scope
- `services/visit/geofence.py`: `GeofenceValidator` — haversine distance
  between a `GpsCoord` and the event center vs `Event.geofence_radius_m`
  (read from `Event.meta`); returns a `GeofenceResult(inside: bool,
  distance_m: float)`. Pure function, no I/O.
- `services/visit/visit_service.py`: `VisitService`:
  - `checkin(event_id, shift_id, coord, *, tenant)`: sets `check_in` +
    `check_in_coord`, starts `gps_breadcrumb`, transitions Shift→in_progress,
    auto-saves recap start via `PartialSaveStore.save(form_id, {}, user_id=...)`.
  - `checkout(event_id, shift_id, coord, submission_data, *, tenant)`:
    appends to breadcrumb, runs `GeofenceValidator` (sets `gps_outside`),
    **blocks** (raises `GeofenceViolationError`) if `gps_outside=True`;
    otherwise persists the recap via `FormSubmissionStorage.save(...)`, sets
    `Visit.submission_id`, clears the draft via `PartialSaveStore.delete(...)`,
    transitions Shift→completed (and Event→completed when all shifts done).
- Unit tests: inside/outside geofence, breadcrumb accumulation, blocked
  checkout, submission linkage, partial-save lifecycle (in-memory stores).

**NOT in scope**: missed reasons/adhoc (303-3), payroll hook/API (303-4).

## Codebase Contract (verified 2026-06-14, monorepo)
```python
# services/submissions.py — class FormSubmission(:50); class
#   FormSubmissionStorage(:102): async def save(submission, *, tenant) -> str
# services/partial_saves.py — class PartialSaveStore: save(:67)/get(:119)/delete(:141)
#   save(form_id, data, *, user_id, tenant); delete(form_id, *, user_id, tenant)
# services/registry.py — FormRegistry.get(form_id, *, tenant) -> FormSchema|None (:575)
# TASK-303-1: Event/Shift/Visit/GpsCoord, EventService, EventStorage
```
### Does NOT Exist
- ~~GeofenceValidator/GeofenceResult/VisitService~~ — created here.
- ~~WebSocket/SSE breadcrumb streaming~~ — breadcrumb is a list set at checkout.
- ~~Workday/payroll HTTP~~ — not here.

## Acceptance Criteria
- [ ] Geofence haversine correct (inside/outside boundary cases)
- [ ] checkout blocked + no submission persisted when gps_outside=True
- [ ] Successful checkout: submission saved, Visit.submission_id set, draft cleared, states advanced
- [ ] Full suite green + `ruff check`

## Completion Note
Implemented 2026-06-14 by sdd-worker agent.

All code was implemented in TASK-303-1 (services/visit/geofence.py, visit_service.py).
This task added 25 unit tests in `tests/unit/visit/test_task303_2_checkin_checkout.py`:

- `TestHaversine`: same-point=0, known distance ~111km/degree
- `TestGeofenceValidator`: inside/outside/missing meta/accuracy buffer/device accuracy
- `TestCheckin`: timestamp set, breadcrumb started, shift→IN_PROGRESS, partial auto-save, idempotency guard, unknown event/shift
- `TestCheckout`: blocked outside geofence, no submission when outside, submission saved, timestamp set, breadcrumb accumulated, partial draft cleared, shift→COMPLETED, event→COMPLETED when all done, no checkin raises, gps_outside flag persisted

Note: PartialSaveStore.save() signature in actual code is `save(form_id, session_id, answers)` — NOT `save(form_id, data, *, user_id, tenant)` as the spec contract section states. The actual method signature was verified and used correctly. The spec contract section had a stale description.
