---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, dev-loop]
tags: [sdd-coder, execution-pool, suspensions, encapsulation, ledger-fix]
---

# Feature Specification: sdd-coder engine fixes 2 (suspension attribution + pool encapsulation + settlement hygiene)

**Feature ID**: FEAT-599
**Date**: 2026-09-24
**Author**: Jesus Lara (with Claude, via `/sdd-fix`)
**Status**: approved
**Target version**: next patch
**Source**: ledger fix group `fixgroup:bc587b6b428c` (`wikitoolkit ledger plan-fix`)

---

## 1. Motivation & Business Requirements

### Problem Statement

Three independent defects in the `sdd_coder` engine/pool pair, all filed
against `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`:

1. **Suspension attribution never reaches the worker (AC-12 of FEAT-559).**
   `render_suspension_history()` in `coder_suspensions.py` is the only place
   that assembles the AC-12 summary (model, incident id, source
   task/execution, reason, remaining cooldown), yet nothing outside its own
   unit test calls it. `PoolSeatView` carries `suspension_id` / `reason` /
   `suspended_until`, but no field says *which task or execution* caused the
   suspension, so `coder_begin_execution` / `coder_plan` / `coder_end_execution`
   cannot show what `.claude/agents/sdd-worker.md` tells the worker to print.
2. **`end_execution` / `status()` build an invalid `AttemptRecord` eagerly.**
   Both snapshot-enrichment loops evaluate
   `self._latest_attempt.get(task_id, AttemptRecord(attempt=1))`. Python
   evaluates the default eagerly and `AttemptRecord` requires `seat_label`
   and `started_at`, so the expression raises `pydantic.ValidationError` for
   every iteration — the exact case where a native reservation exists for a
   task not in `_latest_attempt` (native dispatch never populates it). Today
   the busy gate usually raises `execution_busy` first, but the idempotent
   re-close path (`status == "closed"`) and the `status()` persistence retry
   reach the loop directly.
3. **`engine.py` reaches into `ExecutionPool` private state.** 35 sites read
   or write `pool._status`, `_seats`, `_admitted`, `_condition`,
   `_busy_seats`, `_seat_views`, `_initial_exclusions`, `_local_exclusions`,
   `_fallback_required`, `_fallback_reason`, `_persistence_degraded`, and five
   methods locally import the private `_effective_key`. This erosion already
   enabled a confirmed critical bug (commit `84ede6b60`). `ExecutionPool`'s
   own docstring promises an admit/release/suspend/view/assigner API and
   "never shares mutable state".

Two further issues in the same fix group — `issue:5944887877e1` (FEAT-592
review) and `issue:971e11917b19` (FEAT-591 review) — describe the
"`review_checkpoint prepare` always fails `checkpoint_busy` after any
`coder_run_chunk`" defect. That defect was fixed on `dev` by **FEAT-594 /
TASK-3670** (commit `d40f43e82`, merged in PR #1476): `_outstanding_job_ids()`
now derives "outstanding" from the live `JobTable` state. Both reports predate
the fix and are duplicates of `issue:93abecaf1152` / `issue:00e1ae81e08d` /
`issue:cc372f700a47`. This feature adds one settlement-level regression test
that pins the published artifact contract they describe (empty
`outstanding_job_ids` after a `done` job) so they can be closed by evidence.

Ledger issues covered:

| Issue | Severity | Kind | Summary |
|---|---|---|---|
| `issue:bd1c792a5afc` | major | feature_gap | `render_suspension_history()` has no caller; AC-12 fields never surfaced |
| `issue:5944887877e1` | major | bug | review_checkpoint prepare always `checkpoint_busy` after `coder_run_chunk` (duplicate of FEAT-594 scope; pinned by test) |
| `issue:971e11917b19` | major | bug | `coder_end_execution` never clears `_job_worktrees` (duplicate of FEAT-594 scope; pinned by test) |
| `issue:700660c7f663` | minor | tech_debt | engine reaches into `ExecutionPool` private state |
| `issue:c1e28856ab0c` | minor | bug | eager invalid `AttemptRecord` as `dict.get` default |

### Goals
- Every pool-bearing response (`ExecutionPoolView`, `CoderPlan`) carries a
  bounded `suspension_summary` rendered by `render_suspension_history()`, and
  every suspended `PoolSeatView` carries `suspension_source`,
  `source_task_id` and `source_execution_id`.
- The two enrichment loops never construct an `AttemptRecord`; the attempt
  number comes from a lazy lookup that defaults to `1`.
- `engine.py` uses only `ExecutionPool`'s public API: no `pool._<name>`
  access and no `_effective_key` import remain.
- A regression test pins the FEAT-594 settlement contract for the two
  duplicate reports.

### Non-Goals (explicitly out of scope)
- Changing `prepare_review_checkpoint` or `_outstanding_job_ids` semantics.
- Changing which seats `coder_plan.roster` lists (suspended seats included today).
- Adding `suspension_summary` to the `compact` response projection
  (`views.py` keeps its explicit field allowlist).
- Pruning `_job_worktrees`.
- Touching tests' own `pool._…` assertions (tests may keep inspecting internals).

---

## 2. Architectural Design

### Overview

**M1 — lazy attempt number (`engine.py`).** Add
`SddCoderEngine._latest_attempt_number(task_id) -> int` returning
`self._latest_attempt[task_id].attempt` when present, else `1`. Both
`manager_key = f"{task_id}.a{...}"` sites use it.

**M2 — suspension attribution (`models.py`, `pool.py`, `engine.py`).**
- `PoolSeatView` gains `suspension_source: str = ""`, `source_task_id: str = ""`,
  `source_execution_id: str = ""`.
- `ExecutionPoolView` and `CoderPlan` gain `suspension_summary: str = ""`.
- `ExecutionPool.__init__` accepts `inherited_records: Sequence[SuspensionRecord] = ()`
  (in addition to `initial_exclusions`, which stays the exclusion authority).
  The pool keeps `self._suspension_records: List[SuspensionRecord]` =
  inherited records + every record passed to `suspend()`. Seat views whose
  key is in a record's `blocked_keys` get the attribution fields
  (`source`, `task_id or probe_uid or ""`, `execution_id`) plus
  `suspension_id` / `suspended_until` for inherited ones (their `reason`
  stays `"inherited_suspension"`).
- `ExecutionPool.view()` sets
  `suspension_summary=render_suspension_history(self._suspension_records, datetime.now(timezone.utc))`.
- `SddCoderEngine.begin_execution` passes the `recent` records to the new
  pool on the fresh path; on the restore path it queries
  `self._suspension_store.recent(self._roster_model_keys(), now)` best-effort
  (a failure logs a warning and passes `()`). The model-key list building is
  factored into `_roster_model_keys()` so both paths share it.
- `SddCoderEngine.plan` (pool path) fills `CoderPlan.suspension_summary`
  from `pool.view().suspension_summary`, on both the exhausted early return
  and the normal return.

**M3 — pool public API (`pool.py`, `engine.py`).** New public surface on
`ExecutionPool`:

```python
def effective_key(seat: RosterSeat) -> Optional[ModelKey]   # module-level; `_effective_key = effective_key` alias kept
@property status -> ExecutionStatus
@property seats -> List[RosterSeat]                          # copy
@property persistence_degraded -> bool
def resolve_admission(self, attempt_uid: str) -> Optional[Tuple[str, ModelKey]]
def restore_local_exclusions(self, keys: Iterable[ModelKey]) -> None
def require_fallback(self, reason: str) -> None
def set_persistence_degraded(self, degraded: bool) -> None
async def mark_exhausted(self) -> None
async def select_free_seat(self, *, kind: SeatKind, tried_seats: Set[str],
                           eligible_labels: Optional[Set[str]] = None,
                           wait: bool = False) -> Optional[RosterSeat]
```

`select_free_seat` is the engine's two seat-selection loops moved behind the
condition: it returns the first seat of `kind` whose effective key is not
busy, not excluded (initial or local), and whose view is available, not
suspended, not probe-failed, skipping `tried_seats` and (when given) labels
outside `eligible_labels`. It returns `None` immediately when the pool is
`closed` / `recovery_required`. With `wait=True` it waits on the condition
while at least one *busy but healthy* candidate exists (exact behavior of
today's `_select_retry_seat`), otherwise returns `None`.

Engine call-site mapping (all 35 sites):

| Today | After |
|---|---|
| `pool._local_exclusions = set(...)` (restore) | `pool.restore_local_exclusions(...)` |
| `pool._status = "recovery_required"` | `await pool.mark_recovery_required()` |
| `pool._status = "exhausted"` | `await pool.mark_exhausted()` |
| `pool._status = "closed"` (end_execution) | `await pool.close()` |
| `pool._fallback_required = True; pool._fallback_reason = X` | `pool.require_fallback(X)` |
| `pool._persistence_degraded` read / write | `pool.persistence_degraded` / `pool.set_persistence_degraded(...)` |
| `pool._seats` | `pool.seats` |
| `pool._admitted.get(uid)` | `pool.resolve_admission(uid)` |
| `_select_native_retry_seat` body | `await pool.select_free_seat(kind="native", tried_seats=..., eligible_labels=..., wait=False)` |
| `_select_retry_seat` pool body | `await pool.select_free_seat(kind="mcp", tried_seats=..., eligible_labels=..., wait=True)` |
| local `from ...pool import _effective_key` | module-level `effective_key` in the existing pool import |

### Integration Points

| Existing Component | Change | Notes |
|---|---|---|
| `PoolSeatView`, `ExecutionPoolView`, `CoderPlan` (models.py) | modify | additive defaulted fields; `extra="forbid"` unaffected |
| `ExecutionPool` (pool.py) | modify | records + attribution + public API |
| `SddCoderEngine.begin_execution/plan/end_execution/status/suspend_model/_classify_and_suspend/_select_*_seat/_run_task/run_chunk` | modify | call-site conversions |
| `views.py` compact projection | none | allowlist unchanged |
| `toolkit.py` | none | `model_dump()` serializes the new fields |

### Data Models
Additive only. No serialized artifact changes shape except gaining defaulted
fields (`ExecutionSnapshot` untouched).

---

## 3. Module Breakdown

### Module 1: lazy attempt number + settlement regression (`engine.py`, tests)
Covers `issue:c1e28856ab0c`; pins `issue:5944887877e1` / `issue:971e11917b19`.

### Module 2: suspension attribution (`models.py`, `pool.py`, `engine.py`, tests)
Covers `issue:bd1c792a5afc`.

### Module 3: pool encapsulation (`pool.py`, `engine.py`, tests)
Covers `issue:700660c7f663`.

---

## 4. Test Specification

### Unit / integration tests (`packages/ai-parrot/tests/flows/dev_loop/sdd_coder/`)
| Test | Module | Description |
|---|---|---|
| `test_end_execution_reclose_with_native_reservation_does_not_raise` | M1 | closed pool + `_native_reservations` entry for a task absent from `_latest_attempt` → re-close succeeds, `native_reservations["TASK-1"] == "TASK-1.a1"` |
| `test_status_persistence_retry_with_native_reservation` | M1 | degraded pool + native reservation → `status()` re-persists without `ValidationError` |
| `test_settlement_artifact_after_done_job_has_no_outstanding_ids` | M1 | run gated job → release → wait → `end_execution` → evidence artifact `outstanding_job_ids == []` |
| `test_suspend_sets_seat_attribution` | M2 | after `suspend(record)` the seat view has `suspension_source`, `source_task_id`, `source_execution_id` |
| `test_inherited_records_attribute_seats_and_summary` | M2 | pool built with `inherited_records` → seat attribution + `view().suspension_summary` mentions the incident id |
| `test_plan_carries_suspension_summary_after_suspension` | M2 | engine: begin → suspend → `plan()` → `suspension_summary` contains task id and execution id |
| `test_select_free_seat_*` | M3 | native no-wait; mcp returns None when only busy-healthy and `wait=False`; mcp `wait=True` returns after `release()`; None when closed |
| `test_public_state_accessors` | M3 | `resolve_admission`, `require_fallback`, `set_persistence_degraded`, `mark_exhausted`, `restore_local_exclusions`, `seats` copy |
| `test_engine_has_no_private_pool_access` | M3 | regex over `engine.py` source: no `pool._<name>` and no `_effective_key` |

---

## 5. Acceptance Criteria
- [ ] AC1: `end_execution` and `status()` never construct an `AttemptRecord`; a native reservation for a task without a recorded attempt maps to `<task>.a1`.
- [ ] AC2: `ExecutionPoolView.suspension_summary` and `CoderPlan.suspension_summary` are non-empty after a suspension and contain the incident id, model, source task/execution, reason and remaining cooldown (via `render_suspension_history`).
- [ ] AC3: A suspended `PoolSeatView` carries `suspension_source`, `source_task_id` (or probe uid) and `source_execution_id`; inherited suspensions are attributed from durable history.
- [ ] AC4: `engine.py` contains no `pool._<name>` access and no `_effective_key` import (enforced by test).
- [ ] AC5: Settlement artifact published by `end_execution` after a `done` `run_chunk` job has empty `outstanding_job_ids` (regression for the duplicate reports).
- [ ] AC6: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ -q` passes; `ruff check` clean on touched files.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.pool import ExecutionPool, SeatBusyError, roster_fingerprint
from parrot.flows.dev_loop.sdd_coder.models import PoolSeatView, ExecutionPoolView, CoderPlan, RosterConfig, RosterSeat, AttemptRecord
from parrot.knowledge.wiki.ledger.coder_suspensions import CoderSuspensionStore, ModelKey, SuspensionRecord, render_suspension_history
```

### Existing Class Signatures
- `render_suspension_history(records: Sequence[SuspensionRecord], now: datetime, max_tokens: int = 1200) -> str` (`coder_suspensions.py:350`).
- `CoderSuspensionStore.recent(keys: list[ModelKey], now: datetime) -> list[SuspensionRecord]` (`coder_suspensions.py:332`).
- `SuspensionRecord` fields: `execution_id`, `task_id | None`, `probe_uid | None`, `source`, `suspension_id`, `reason`, `expires_at`, `blocked_keys` (`coder_suspensions.py:109`).
- `ExecutionPool.__init__(*, execution_id, feature_id, worktree_path, roster, seats, suspension_store, initial_exclusions)` (`pool.py:93`); `view()` (`:186`), `snapshot()` (`:221`), `admit()` (`:242`), `release()` (`:285`), `suspend()` (`:303`), `assigner()` (`:358`), `is_exhausted()` (`:383`), `close()` (`:394`), `mark_recovery_required()` (`:399`).
- `_effective_key(seat: RosterSeat) -> Optional[ModelKey]` (`pool.py:53`).
- `AttemptRecord(attempt: int, seat_label: str, started_at: str, ...)` — `seat_label`/`started_at` required (`models.py:304`).
- `SddCoderEngine._latest_attempt: Dict[str, AttemptRecord]` (`engine.py:413`); `_native_reservations: Dict[Tuple[str, str], str]`; `_manager_execution: Dict[str, str]`.
- engine module-level import: `from parrot.flows.dev_loop.sdd_coder.pool import ExecutionPool, roster_fingerprint, SeatBusyError` (`engine.py:114`).

### Edit Sites (Blueprint Anchors)
| File | Anchor | Verified | Count |
|---|---|---|---|
| engine.py | `manager_key = f"{task_id}.a{self._latest_attempt.get(task_id, AttemptRecord(attempt=1)).attempt}"` | :910 | 1 |
| engine.py | `f"{task_id}.a{self._latest_attempt.get(task_id, AttemptRecord(attempt=1)).attempt}"` (status retry) | :2844 | 1 (multi-line) |
| engine.py | `pool._local_exclusions = set(durable_snapshot.local_exclusions)` | :686 | 1 |
| engine.py | `pool._status = "recovery_required"` | :695 | 1 |
| engine.py | `pool._fallback_required = True` | :700, :772, :801 | 3 |
| engine.py | `pool._status = "exhausted"` | :777 | 1 |
| engine.py | `pool._status = "closed"` | :901 | 1 |
| engine.py | `pool._persistence_degraded = True` | :922, :936 | 2 |
| engine.py | `seats = pool._seats` | :1495 | 1 |
| engine.py | `entry = pool._admitted.get(attempt_uid)` | :2046 | 1 |
| engine.py | `if pool._persistence_degraded:` | :2837 | 1 |
| engine.py | `pool._persistence_degraded = False` | :2858 | 1 |
| engine.py | `from parrot.flows.dev_loop.sdd_coder.pool import _effective_key` | :2922, :3299, :3403, :3465, :3496 | 5 |
| engine.py | `async with pool._condition:` | :3399, :3457 | 2 |
| engine.py | `[candidate for candidate in pool._seats if candidate.label in remaining]` | :3634 | 1 |
| engine.py | `seats = {s.label: s for s in pool._seats}` | :3788 | 1 |
| engine.py | `recent = await self._suspension_store.recent(model_keys, now)` | :747 | 1 |
| engine.py | `return CoderPlan(` / `result = CoderPlan(` | :1482, :1593 | 2 |
| pool.py | `self._seat_views: Dict[ModelKey, PoolSeatView] = {}` | :143 | 1 |
| pool.py | `seat_view.suspended_until = record.expires_at.isoformat()` | :320 | 1 |
| pool.py | `roster_warnings=self._roster_warnings(),` | :198 | 1 |
| models.py | `suspended_until: str = ""` | :450 | 1 |
| models.py | `"""FEAT-588 advisory notes about unavailable complex-task retry capacity."""` | :474 | 1 |
| models.py | `rejects a stale plan (`plan_stale`) once the generation has moved on."""` | :301 | 1 |

### Does NOT Exist (Anti-Hallucination)
- No `ExecutionPool.status` / `.seats` / `.resolve_admission` / `.select_free_seat` / `.require_fallback` / `.set_persistence_degraded` / `.mark_exhausted` / `.restore_local_exclusions` today — M3 creates them.
- No `inherited_records` kwarg on `ExecutionPool` today — M2 creates it.
- No `suspension_summary` on any model today; no `source_task_id` on `PoolSeatView`.
- `CoderSuspensionStore` has no synchronous `recent`; it is `async`.

---

## 7. Implementation Notes & Constraints
- Keep `_effective_key` as a module alias — `test_engine_dispatch.py` imports it.
- `select_free_seat` must preserve the native-seat "never wait" rule (a busy native seat is released only by `merge()`, which may be sequenced after this job's `coder_wait`).
- `view()` may be called without the condition held (as today); the records list is append-only under the condition.
- `render_suspension_history` is display-only; the pool's exclusion sets remain the selection authority.
- Tasks modify the same files → serialized: TASK-3677 → TASK-3678 → TASK-3679.

## 8. Open Questions
None.

## 9. Design Research Cross-Check
Status: skipped (ledger-driven fix lane; scope fully determined by the filed issues)

## Revision History
| Version | Date | Notes |
|---|---|---|
| 0.1 | 2026-09-24 | Authored by `/sdd-fix` from fixgroup:bc587b6b428c |
