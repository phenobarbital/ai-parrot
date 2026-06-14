# TASK-303-3: Missed Reasons (per-tenant) + ad-hoc stops

**Feature**: FEAT-303 — Visit & Event Lifecycle (multi-shift)
**Spec**: `sdd/specs/visit-event-lifecycle.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-303-1
**Assigned-to**: unassigned

> **⚠️ CROSS-REPO**: code in ai-parrot monorepo `packages/parrot-formdesigner`;
> worktree `.claude/worktrees/feat-303-visit-lifecycle`.

## Context
Module 3. Per-tenant Missed Reasons catalogue (decision §8: per-tenant, hard
isolation, `fieldsync` schema) + ad-hoc/guerilla stop creation.

## Scope
- `services/visit/missed_reasons.py`: `MissedReasonService` — CRUD for a
  **per-tenant** `MissedReason` catalogue persisted in the `fieldsync` schema
  (DDL idempotent `CREATE TABLE IF NOT EXISTS fieldsync.missed_reasons`,
  identifier-safe; in-memory impl for tests). Every method takes `tenant` and
  filters by it (no global rows).
- `VisitService.set_missed_reason(event_id, shift_id, reason_id, *, tenant)`:
  assigns the reason to the Visit, transitions the Shift→`MISSED`, and the
  Event→`MISSED` when ALL shifts are missed.
- `VisitService.create_adhoc(org_node_id, staff_id, *, tenant)`: creates an
  Event flagged `is_adhoc=True` with a single Shift and immediately starts the
  Visit (check-in).
- Unit tests: per-tenant isolation (tenant A cannot see tenant B reasons),
  missed-reason assignment + state transitions, adhoc creation.

**NOT in scope**: geofence (303-2), payroll hook/API (303-4).

## Codebase Contract (verified 2026-06-14, monorepo)
```python
# TASK-303-1: MissedReason model, EventService, VisitService scaffolding,
#   EventStorage, state machine (MISSED transitions)
# services/storage.py + services/_identifiers.py — DDL/identifier-safety pattern
#   for the fieldsync.missed_reasons table (same as FEAT-302 fieldsync tables)
```
### Does NOT Exist
- ~~MissedReasonService~~, ~~fieldsync.missed_reasons~~ — created here.
- ~~global (cross-tenant) catalogue~~ — per-tenant only (§8).

## Acceptance Criteria
- [ ] Per-tenant isolation enforced (test: A ≠ B)
- [ ] set_missed_reason transitions Shift→MISSED and Event→MISSED when all missed
- [ ] create_adhoc yields is_adhoc Event with one started Visit
- [ ] Full suite green + `ruff check`

## Completion Note
*(Agent fills this in when done)*
