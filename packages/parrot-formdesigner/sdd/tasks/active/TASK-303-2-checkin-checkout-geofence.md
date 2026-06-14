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
*(Agent fills this in when done)*
