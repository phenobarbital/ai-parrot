# TASK-4350: Deterministic interval/once trigger anchor for cross-worker fire claims

**Feature**: FEAT-676 — Scheduler interval/once claim anchor
**Spec**: `sdd/specs/scheduler-interval-claim-anchor.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Resolves ledger issue:aa813ccc1927. `RedisFireCoordinator.claim()` keys on the fire's due time,
but `_create_trigger()` anchors `IntervalTrigger` at each worker's own creation time (and `once`
without `run_date` at each worker's `utcnow()`), so workers compute different due times and
all win their claim. Implements spec §2 / Module 1.

---

## Scope

- Add `INTERVAL_ANCHOR` (UTC epoch) to `coordination.py`.
- `_create_trigger(..., *, anchor=None)`: interval → `IntervalTrigger(**config, start_date=INTERVAL_ANCHOR, timezone="UTC")`;
  once → `config.get("run_date") or anchor or utcnow()`.
- Pass `anchor=<definition>.created_at` at the persisted call sites (add_schedule, update, load_schedules_from_db,
  fingerprint reschedule). Leave the code-job call site (`register_object_schedules`) without anchor.
- New regression tests with independently built triggers on two managers + real-Redis claim test.
- Document the anchoring rule in `docs/scheduler/multi-worker.md`.

**NOT in scope**: claim-key format, `FireCoordinator` protocol, code `once` jobs without `run_date`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/coordination.py` | MODIFY | `INTERVAL_ANCHOR` constant |
| `packages/ai-parrot-server/src/parrot/scheduler/base.py` | MODIFY | anchored `_create_trigger` + call sites |
| `packages/ai-parrot-server/tests/scheduler/test_trigger_anchor.py` | CREATE | regression tests |
| `docs/scheduler/multi-worker.md` | MODIFY | anchoring rule |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from apscheduler.triggers.interval import IntervalTrigger  # verified: base.py:32
from apscheduler.triggers.date import DateTrigger  # verified: base.py:31
from parrot.scheduler.coordination import RedisFireCoordinator  # verified: coordination.py
from parrot.scheduler import SchedulerManager  # verified: tests/scheduler/test_ledger_regressions.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/base.py:360
def _create_trigger(self, schedule_type: str, config: Dict[str, Any]) -> Any: ...
# packages/ai-parrot-server/src/parrot/scheduler/coordination.py
class RedisFireCoordinator:
    async def claim(self, job_id: str, run_time: datetime) -> bool: ...
# packages/ai-parrot-server/src/parrot/scheduler/models.py:161
class JobDefinition(BaseModel):
    created_at: Optional[datetime] = None  # set to utcnow() in model_post_init
```

### Does NOT Exist
- ~~`parrot.scheduler.manager._create_trigger`~~ — moved to `base.py` (FEAT-644); `manager.py` is a facade.
- ~~fakeredis~~ — not installed; use real Redis db 15 via `scheduler_redis` fixture (tests/scheduler/conftest.py).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/scheduler/coordination.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/scheduler/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/scheduler/test_trigger_anchor.py", "action": "CREATE"},
    {"path": "docs/scheduler/multi-worker.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/base.py#SchedulerManager._create_trigger",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/coordination.py#RedisFireCoordinator.claim"
  ]
}
```

---

## Implementation Notes

- APScheduler 3.11: with `start_date` in the past, `IntervalTrigger.get_next_fire_time(None, now)` returns
  `start_date + ceil((now - start_date)/interval) * interval` — a pure function of the interval.
- Interval configs are sanitized to `weeks/days/hours/minutes/seconds` only (`sanitize.py::_sanitize_interval`),
  so no user `start_date`/`jitter` can conflict.

---

## Acceptance Criteria

- [ ] Spec AC1–AC5.
- [ ] `ruff check` clean on touched Python files.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/scheduler/test_trigger_anchor.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_multiworker.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_base_crud.py -q`

---

## Test Specification

See spec §4.

---

## Agent Instructions

Follow `docs/sdd/WORKFLOW.md` "Implementing a task by hand".

---

## Completion Note

**Completed by**: sdd-fix subagent (Claude Opus 5.5)
**Date**: 2026-10-15
**Notes**: Added `INTERVAL_ANCHOR` (UTC epoch) to `coordination.py`; `_create_trigger()` in `base.py` now builds
`IntervalTrigger(**config, start_date=INTERVAL_ANCHOR, timezone="UTC")` and takes keyword `anchor` used for `once`
without `run_date`. Persisted call sites (add, update, DB load, fingerprint reschedule) pass
`anchor=<definition>.created_at`; the code-job site does not (no shared row; documented). New
`tests/scheduler/test_trigger_anchor.py` builds triggers independently on two `SchedulerManager`s at different instants
and checks identical fire times and a single winning claim (dict SET-NX double offline + real Redis db 15 variant that
skips when Redis is unreachable — it was unreachable locally, so that variant skipped). Reproduced the bug on raw
`IntervalTrigger(minutes=5)` built 50 ms apart (next fire times differ). Scheduler suite: 312 passed, 13 skipped.
Docs: `docs/scheduler/multi-worker.md` documents the anchoring rule.

**Deviations from spec**: Added an offline claim test (`_SetNxRedis` double) in addition to the real-Redis one, since
fakeredis is not installed and local Redis was down. Behaviour change: interval first fire aligns to the epoch grid
instead of creation time + interval.
