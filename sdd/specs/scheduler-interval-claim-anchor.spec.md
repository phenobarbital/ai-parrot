---
type: feature
base_branch: dev
feature_id: FEAT-676
projects: [ai-parrot-server]
tags: [scheduler, multi-worker, coordination, ledger-fix]
---

# Feature Specification: Scheduler interval/once claim anchor

**Feature ID**: FEAT-676
**Date**: 2026-10-15
**Author**: Jesus Lara (via /sdd-fix)
**Status**: approved
**Target version**: next ai-parrot-server patch

Resolves ledger issue:aa813ccc1927 (discovered from spec:FEAT-631).

---

## 1. Motivation & Business Requirements

### Problem Statement

`RedisFireCoordinator.claim()` (`parrot/scheduler/coordination.py`) keys a scheduled fire on
`fire:{job_id}:{run_times[-1].isoformat()}`. That only deduplicates across workers when every
worker computes the **same** due time for the same fire. `SchedulerManager._create_trigger()`
(now in `parrot/scheduler/base.py:360`; `manager.py` is a facade since FEAT-644) builds
`IntervalTrigger(**config)` with no `start_date`, so APScheduler anchors the interval grid at
each worker's own trigger-creation time (`now + interval`). Two workers that load the same DB
row or `@schedule` interval job a few milliseconds apart get different run times, both win
their claim, and the agent runs twice. `once` schedules without `run_date` default to
`utcnow()` per worker, with the same effect. Cron/daily/weekly/monthly triggers are
deterministic and unaffected. FEAT-644 made the fire context use the exact claimed due time,
but never fixed the anchor; `test_multiworker.py` hands both managers an identical run time, so
the gap was never exercised.

### Goals
- G1. Every worker builds an identical fire-time grid for the same `interval` schedule, so the
  Redis claim key is identical and exactly one worker runs each fire.
- G2. A persisted (`db`/`redis`) `once` schedule without `run_date` fires at a shared
  deterministic instant (the definition's `created_at`) on every worker.
- G3. Regression test with **independently built** triggers on two managers.
- G4. `docs/scheduler/multi-worker.md` documents the anchoring rule.

### Non-Goals
- Changing the claim-key format or the `FireCoordinator` protocol.
- `@schedule` (code) `once` jobs without `run_date`: they have no shared row, stay
  "run at startup" per process (documented).
- Jitter (the sanitizer already strips `start_date`/`jitter` from interval configs).

---

## 2. Architectural Design

### Overview

Introduce one shared constant `INTERVAL_ANCHOR = datetime(1970, 1, 1, tzinfo=timezone.utc)` in
`coordination.py` — the claim-key contract module — and make `_create_trigger()` pass it as
`start_date` (with `timezone="UTC"`) to every `IntervalTrigger`. Fire times become
`epoch + n * interval`, a pure function of the interval, identical on every worker and across
restarts. `_create_trigger()` gains an optional keyword `anchor: Optional[datetime] = None`;
for `once` without `run_date` it uses `anchor` before falling back to `utcnow()`. Call sites
that hold a persisted `JobDefinition` (add, update, DB load, fingerprint reschedule) pass
`anchor=definition.created_at`.

Behaviour change: the first interval fire is aligned to the epoch grid (e.g. every 5 minutes
→ :00, :05, …) instead of "creation time + interval". This is the price of a shared anchor
without plumbing per-row state, and matches what operators usually expect.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.scheduler.coordination` | modifies | adds `INTERVAL_ANCHOR` |
| `SchedulerManager._create_trigger` (`base.py:360`) | modifies | anchor for interval/once |
| `RedisFireCoordinator.claim` | uses (unchanged) | key now stable across workers |

### New Public Interfaces
```python
# parrot/scheduler/coordination.py
INTERVAL_ANCHOR: datetime  # 1970-01-01T00:00:00+00:00

# parrot/scheduler/base.py
def _create_trigger(self, schedule_type: str, config: Dict[str, Any], *, anchor: Optional[datetime] = None) -> Any:
    """Interval triggers start at INTERVAL_ANCHOR; once without run_date uses anchor, else utcnow()."""
```

---

## 3. Module Breakdown

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: deterministic trigger anchor | yes | as §2 | — |

### Module 1: Deterministic trigger anchor
- **Path**: `packages/ai-parrot-server/src/parrot/scheduler/coordination.py`,
  `packages/ai-parrot-server/src/parrot/scheduler/base.py`
- **Responsibility**: shared interval anchor + `anchor` for persisted `once` schedules.
- **Depends on**: existing scheduler (FEAT-644).

---

## 4. Test Specification

| Test | Description |
|---|---|
| `test_interval_triggers_built_independently_share_fire_times` | two managers build `interval` triggers at different instants; next N fire times equal and lie on the epoch grid |
| `test_independent_interval_triggers_claim_once` | each manager's own trigger yields its run time; two `RedisFireCoordinator`s (real Redis db 15, unique prefix, skip if unreachable) — exactly one claim wins |
| `test_once_without_run_date_uses_anchor` | `once` with `anchor` uses it on both managers; explicit `run_date` still wins |

---

## 5. Acceptance Criteria

- [ ] AC1: `IntervalTrigger`s from `_create_trigger("interval", cfg)` built on different managers at different times return identical `get_next_fire_time` sequences.
- [ ] AC2: Claims for those run times on two Redis coordinators: exactly one wins.
- [ ] AC3: `once` without `run_date` uses `anchor` when given; persisted call sites pass `definition.created_at`.
- [ ] AC4: Existing scheduler tests pass; `ruff check` clean on touched files.
- [ ] AC5: `docs/scheduler/multi-worker.md` documents the anchoring rule.

---

## 6. Worktree Strategy

Single task, single worktree `feat-FEAT-676-scheduler-interval-claim-anchor` from `origin/dev`.
