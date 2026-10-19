# TASK-4489: Worker job-changes handler (as-of snapshots + diff)

**Feature**: FEAT-706 — Workday Worker Event History and Job Changes
**Spec**: `sdd/specs/workday-worker-event-history-and-job-changes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4487, TASK-4488
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, §2 Overview "Job changes" and "Compensation opt-in" (G7, §8 resolution 1).
`Get_Worker_Event_History` only says *that* a job change happened. This handler reconstructs
*what* changed: it filters the events to job types, takes two `Get_Workers` snapshots per
distinct effective date (as-of the day before and the day of), parses each into a
`JobSnapshot` through the existing worker parsers, and diffs them into `JobChange` rows.

---

## Scope

- Create `handlers/worker_job_changes.py` with `SNAPSHOT_RESPONSE_GROUP`, `parse_job_snapshot`,
  `diff_snapshots`, `group_job_events` and `WorkerJobChangesType` per spec §3 M3's skeleton.
- Build `JobSnapshot` ONLY by composing `parse_employment_data`, `parse_business_site`,
  `parse_worker_organization_data`, `parse_management_chain_data`, `parse_worker_status`, and
  (with `include_compensation=True`) `parse_compensation_data` — no new XML-path walking.
- Snapshots run under `asyncio.Semaphore(snapshot_concurrency=4)` and are memoised per as-of date
  within one `execute()`.
- `include_compensation=True`: adds `Include_Compensation` to the snapshot `Response_Group`, fills the
  eight pay fields, and (only when `event_types is None`) widens the filter with `COMPENSATION_EVENT_TYPES`.
- Write `test_worker_job_changes.py` with every M3 row of spec §4 plus the end-to-end fixture test.

**NOT in scope**: service/config registration (TASK-4490), toolkit tools (TASK-4491), docs (TASK-4492),
changes to `worker_parsers.py` or `workers.py`, multi-job workers (only `Worker_Job_Data[0]`, spec §7).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/worker_job_changes.py` | CREATE | Snapshot, diff, grouping, `WorkerJobChangesType` |
| `packages/ai-parrot-tools/tests/workday/test_worker_job_changes.py` | CREATE | M3 unit tests + end-to-end fixture test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .base import WorkdayTypeBase                                                  # handlers/base.py:11
from .worker_event_history import (                                               # TASK-4488
    INVALID_ID_FAULT, build_event_date_range, build_event_history_worker_reference, resolve_worker_reference,
)
from ..models.worker_event import (                                                 # TASK-4487
    COMPENSATION_EVENT_TYPES, JOB_CHANGE_EVENT_TYPES, FieldChange, JobChange, JobSnapshot, WorkerEvent,
)
from ..parsers.worker_parsers import (                                              # parsers/__init__.py:5-16 re-exports these
    parse_business_site,             # worker_parsers.py:1247
    parse_compensation_data,         # worker_parsers.py:757
    parse_employment_data,           # worker_parsers.py:1030
    parse_management_chain_data,     # worker_parsers.py:1292
    parse_worker_organization_data,  # worker_parsers.py:669
    parse_worker_status,             # worker_parsers.py:1159
)
from ..utils.utils import ensure_list                                               # utils/utils.py:22
from zeep.exceptions import Fault
import pandas as pd
```

### Existing Signatures to Use
```python
# Every parser takes the serialized Worker_Data dict (call site: workers.py:323 `wd = w.get("Worker_Data", {}) or {}`, :384-390)
parse_employment_data(wd) -> dict        # keys used: position_id, position_title, business_title, position_effective_date (RAW date — str() it),
                                         #   job_profile_id, job_profile_name, job_family (list|None), management_level, job_category,
                                         #   worker_type, position_time_type, pay_rate_type, scheduled_weekly_hours (float|None),
                                         #   full_time_equivalent_percentage (float|None). Reads Employment_Data.Worker_Job_Data[0].
parse_business_site(wd) -> dict          # business_site_name → location_name, business_site_location_id → location_id
parse_worker_organization_data(wd) -> dict   # supervisory_organization_{id,name}, cost_center_{id,name}, cost_center_hierarchy_name,
                                             #   company_{id,name}, pay_group_{id,name}, primary_organization_name
parse_management_chain_data(wd) -> dict  # direct_manager_id, direct_manager_name
parse_worker_status(wd) -> dict          # active, hire_date (RAW date — str() it)
parse_compensation_data(wd) -> dict      # wage (float, first Salary_and_Hourly node with Amount), compensation_effective_date (str|None),
                                         #   compensation_guidelines {package, grade, profile},
                                         #   salary_and_hourly [{plan, element, amount, currency, frequency, assignment_effective_date}]

# TASK-4488 (handlers/worker_event_history.py)
async def resolve_worker_reference(service, worker_id, worker_id_type=None, max_retries=3, retry_delay=0.5) -> ResolvedWorkerReference
def build_event_history_worker_reference(ref: ResolvedWorkerReference) -> dict
def build_event_date_range(effective_from, effective_through, updated_from, updated_through) -> dict[str, datetime] | None
INVALID_ID_FAULT: str = "Invalid ID value"
```

### Verified request shape (Get_Workers as-of, HR WSDL, verified live 2026-10-19)
```python
{"Request_References": {"Worker_Reference": [{"ID": {"type": "WID", "_value_1": wid}}]},
 "Response_Filter": {"As_Of_Effective_Date": "2026-06-08"},          # ISO string (pattern: workers.py:71)
 "Response_Group": {**SNAPSHOT_RESPONSE_GROUP, "Include_Compensation": True}}   # the last key only with include_compensation
# serialized → Response_Data.Worker[0].Worker_Data  (Response_Data may be list or dict — ensure_list)
```

### Does NOT Exist
- ~~`Get_Change_Job`~~ / ~~`Get_Worker_History`~~ — no read op returns job deltas; the as-of diff IS the design.
- ~~An event-type request filter~~ — filter client-side in `group_job_events`.
- ~~`parse_job_snapshot` in `worker_parsers.py`~~ — created here; do NOT add it to the parsers package.
- ~~`WorkdayTypeBase._paginate_soap_operation`~~ for snapshots — single-worker calls, unpaged.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/worker_job_changes.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/workday/test_worker_job_changes.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/base.py#WorkdayTypeBase",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/parsers/worker_parsers.py#parse_employment_data",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/parsers/worker_parsers.py#parse_business_site",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/parsers/worker_parsers.py#parse_worker_organization_data",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/parsers/worker_parsers.py#parse_management_chain_data",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/parsers/worker_parsers.py#parse_worker_status",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/parsers/worker_parsers.py#parse_compensation_data",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py#WorkdayService.call_operation",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/utils/utils.py#ensure_list"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Call budget (AC): `1` reference lookup + `1` event history + `2 × distinct dates` snapshots, never more; memoisation can only lower it. Do NOT call `WorkerEventHistoryType.execute` — it resolves the worker again (one extra call). Resolve once with `resolve_worker_reference`, then issue the history call yourself in `_fetch_events` with TASK-4488's `build_event_history_worker_reference` + `build_event_date_range` — because the budget is an acceptance criterion.
- Pre-hire as-of: `parse_job_snapshot` returns `None` when `Worker_Job_Data` is empty; `_snapshot` maps an empty `Response_Data` or a `Fault` containing `INVALID_ID_FAULT` to `None`. Any other `Fault` propagates.
- `kind`: `before is None` → `"hire"` with `changes=[]`; empty diff → `"no_change"` (dropped unless `include_unchanged`); else `"change"`.
- `after` snapshot missing (`None`) for an event date: log a warning and skip that date — `JobChange.after` is required.
- Compensation off: pay fields stay `None` on both sides so they never produce a `FieldChange`.
- `compensation_elements`: keep only `plan, element, amount, currency, frequency` per node (drop `assignment_effective_date`, it changes on every edit and would add noise); convert `amount` to `float`.
- `pay_currency` / `pay_frequency`: from the first `salary_and_hourly` row with a non-null `amount` (same node `wage` comes from).
- Keep `before`/`after`/`changes` as Python objects (`model_dump()` dicts / lists) in the DataFrame, never JSON strings — `fetch_models` rebuilds `JobChange` from rows (spec §7).

---

## Implementation Blueprint

### Steps (in order)
1. Write the module-level parts (block 1) — *why*: pure functions, tested in isolation.
2. Write `WorkerJobChangesType` (block 2) — *why*: orchestration with the semaphore and memo.
3. Build fixtures: a compact event history (Hire 2022-09-26, Change Job 2026-05-25 with Propose Compensation Change same day, Change Job 2026-06-08, Change Organization Assignments for Worker 2026-06-08, Edit Position 2026-07-06, plus noise like Enter Time) and per-as-of `Get_Workers` snapshots — *why*: spec §4 fixtures; synthetic names/ids only, but keep position ids `MEX559647`/`P104998` and titles `Payroll Coordinator`/`Payroll Specialist` the AC asserts.
4. Write the tests and run Validation Commands.

### `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/worker_job_changes.py` (CREATE) — block 1
```python
"""Worker job-changes handler (FEAT-706): as-of Get_Workers snapshots diffed per job event date."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

import pandas as pd
from zeep.exceptions import Fault

from ..models.worker_event import (
    COMPENSATION_EVENT_TYPES, JOB_CHANGE_EVENT_TYPES, FieldChange, JobChange, JobSnapshot, WorkerEvent,
)
from ..parsers.worker_parsers import (
    parse_business_site, parse_compensation_data, parse_employment_data,
    parse_management_chain_data, parse_worker_organization_data, parse_worker_status,
)
from ..utils.utils import ensure_list
from .base import WorkdayTypeBase
from .worker_event_history import (
    INVALID_ID_FAULT, build_event_date_range, build_event_history_worker_reference, resolve_worker_reference,
)

SNAPSHOT_RESPONSE_GROUP: dict[str, bool] = {
    "Include_Reference": True,
    "Include_Employment_Information": True,
    "Include_Organizations": True,
    "Include_Management_Chain_Data": True,
}


def parse_job_snapshot(worker: dict[str, Any], as_of: date, include_compensation: bool = False) -> JobSnapshot | None:
    """Compose the worker parsers over one serialized ``Get_Workers`` Worker element.

    Returns:
        ``None`` when ``Worker_Data.Employment_Data.Worker_Job_Data`` is absent (pre-hire as-of date).
    """
    wd = (worker or {}).get("Worker_Data") or {}
    if not ensure_list((wd.get("Employment_Data") or {}).get("Worker_Job_Data")):
        return None
    emp = parse_employment_data(wd)
    site = parse_business_site(wd)
    org = parse_worker_organization_data(wd)
    mgr = parse_management_chain_data(wd)
    status = parse_worker_status(wd)
    # FILL IN: build JobSnapshot(as_of=as_of, ...) mapping every key listed in §Existing Signatures;
    #   str() position_effective_date and hire_date when not None (JobSnapshot types them str);
    #   when include_compensation: comp = parse_compensation_data(wd) → wage, compensation_effective_date,
    #   package/grade/profile from comp["compensation_guidelines"], pay_currency/pay_frequency from the first
    #   salary_and_hourly row with an amount, compensation_elements trimmed to 5 keys with float amount.
    #   Bounded by AC "JobSnapshot built only through the parsers".


def diff_snapshots(before: JobSnapshot | None, after: JobSnapshot) -> list[FieldChange]:
    """Field-by-field diff over ``JobSnapshot.model_fields`` minus ``DIFF_EXCLUDE``; ``[]`` when ``before`` is None."""
    if before is None:
        return []
    return [
        FieldChange(field=name, before=getattr(before, name), after=getattr(after, name))
        for name in JobSnapshot.model_fields
        if name not in JobSnapshot.DIFF_EXCLUDE and getattr(before, name) != getattr(after, name)
    ]


def group_job_events(events: list[WorkerEvent], event_types: tuple[str, ...]) -> dict[date, list[WorkerEvent]]:
    """Keep events whose ``event_type`` is in ``event_types`` (exact match), grouped by ``effective_date`` ascending."""
    # FILL IN: skip events without effective_date; return a dict ordered by date — bounded by test_group_job_events.
```
**Why this shape**: the three functions are pure and individually tested. The diff iterates
`model_fields`, so fields added to `JobSnapshot` are diffed automatically and `as_of` never is.

### same file — block 2
```python
class WorkerJobChangesType(WorkdayTypeBase):
    """Handler for ``get_worker_job_changes`` (HR WSDL: Get_Worker_Event_History + as-of Get_Workers)."""

    snapshot_concurrency: int = 4

    def _get_default_payload(self) -> dict[str, Any]:
        return {}

    async def _snapshot(
        self, wid: str, as_of: date, include_compensation: bool = False,
        memo: dict[date, JobSnapshot | None] | None = None, sem: asyncio.Semaphore | None = None,
    ) -> JobSnapshot | None:
        """``Get_Workers`` by WID as-of ``as_of``; memoised per date for one ``execute()``."""
        # FILL IN: return memo[as_of] when present; under `sem`, call_operation(operation="Get_Workers", ...)
        #   with the §Contract request shape; Fault containing INVALID_ID_FAULT or empty Response_Data → None;
        #   parse_job_snapshot(first worker, as_of, include_compensation); store in memo. Note: two concurrent
        #   callers for the same date must not both call — store an asyncio.Task/Future in the memo, not the result.

    async def _fetch_events(self, ref: Any, effective_from: Any, effective_through: Any) -> list[WorkerEvent]:
        """One ``Get_Worker_Event_History`` call for the resolved reference, flattened to WorkerEvent."""
        # FILL IN: reuse build_event_history_worker_reference / build_event_date_range (effective pair only);
        #   flatten exactly like TASK-4488's execute — bounded by the 1 + 1 + 2N call budget.

    async def execute(
        self, worker_id: str, worker_id_type: str | None = None,
        effective_from: date | str | None = None, effective_through: date | str | None = None,
        event_types: tuple[str, ...] | None = None, include_unchanged: bool = False,
        include_compensation: bool = False, **kwargs: Any,
    ) -> pd.DataFrame:
        """One ``JobChange`` row per distinct effective date, ascending; ``before`` is as-of the previous day."""
        if event_types is None:
            event_types = JOB_CHANGE_EVENT_TYPES + (COMPENSATION_EVENT_TYPES if include_compensation else ())
        ref = await resolve_worker_reference(self.service, worker_id, worker_id_type, self.max_retries, self.retry_delay)
        events = await self._fetch_events(ref, effective_from, effective_through)
        groups = group_job_events(events, tuple(event_types))
        memo: dict[date, Any] = {}
        sem = asyncio.Semaphore(self.snapshot_concurrency)
        # FILL IN: gather (before=d - timedelta(days=1), after=d) snapshots for every date; build JobChange rows
        #   (kind rules in Implementation Notes; event_ids/event_types/descriptions from the group;
        #   includes_compensation=include_compensation); drop no_change unless include_unchanged;
        #   self.parsed = rows; return pd.DataFrame([r.model_dump() for r in rows],
        #   columns=list(JobChange.model_fields)) — bounded by AC "call budget" and "hire / no_change".
```
**Why this shape**: resolution happens once and the WID is reused for every later call, which is
what keeps the budget at `2 + 2N`. A memo of tasks (not results) lets adjacent dates that share an
as-of day reuse one in-flight call under concurrency.

### `packages/ai-parrot-tools/tests/workday/test_worker_job_changes.py` (CREATE)
```python
"""FEAT-706 — worker job-changes handler (fake service, no live tenant)."""
from datetime import date, datetime

import pytest
from zeep.exceptions import Fault

from parrot_tools.interfaces.workday.handlers.worker_job_changes import (
    SNAPSHOT_RESPONSE_GROUP, WorkerJobChangesType, diff_snapshots, group_job_events, parse_job_snapshot,
)
from parrot_tools.interfaces.workday.models.worker_event import JobChange, JobSnapshot, WorkerEvent

WID = "0123456789abcdef0123456789abcdef"  # synthetic


# FILL IN: _ref helper; REFERENCE_RESPONSE; EVENT_HISTORY_RESPONSE (Step 3 dates);
#   _worker(position_id, title, profile, cost_center, wage, ...) building a serialized Worker element with
#   Employment_Data.Worker_Job_Data[0].Position_Data, Worker_Status_Data, Organization_Data,
#   Management_Chain_Data, Compensation_Data; SNAPSHOTS keyed by ISO as-of date (pre-hire 2022-09-25 → no Worker_Job_Data;
#   2026-05-24/25 same job, wage 20.00 → 22.00; 2026-06-07 MEX559647 Payroll Coordinator → 2026-06-08 P104998 Payroll Specialist).
# FILL IN: _FakeService answering Get_Workers by Response_Filter.As_Of_Effective_Date (reference lookup when absent)
#   and Get_Worker_Event_History; records (operation, kwargs).
# FILL IN: spec §4 M3 rows — test_parse_job_snapshot_fields, test_parse_job_snapshot_prehire_returns_none,
#   test_parse_job_snapshot_compensation_opt_in, test_snapshot_response_group_compensation_flag,
#   test_job_changes_compensation_diff, test_diff_snapshots, test_group_job_events_filters_and_groups,
#   test_job_changes_execute_before_after, test_job_changes_include_unchanged, test_job_changes_snapshot_memoised,
#   and the integration test test_job_changes_end_to_end_fixture.
```

### FILL IN checklist
- [ ] `parse_job_snapshot` — key mapping, `str()` dates, compensation branch.
- [ ] `group_job_events` — filter + group + order.
- [ ] `_snapshot` — request, `None` mapping, task memo under the semaphore.
- [ ] `_fetch_events` — single history call, flatten.
- [ ] `execute` — gather, kind rules, drop/keep, DataFrame.
- [ ] Fixtures, `_FakeService` and the eleven tests.

---

## Acceptance Criteria

- [ ] `execute` issues exactly `1 + 1 + 2 × (distinct effective dates)` SOAP calls before memoisation and never more after it; snapshots use `Response_Filter.As_Of_Effective_Date` as an ISO date string.
- [ ] `JobSnapshot` is built only through the five parsers (+ `parse_compensation_data` with the flag).
- [ ] With `include_compensation=False`: no request carries `Include_Compensation`, every pay field is `None`, no `FieldChange` names a pay field. With `True`: `Include_Compensation` sent, pay fields populated, default filter includes `COMPENSATION_EVENT_TYPES`, the 2026-05-25 fixture yields `kind="change"` with a `wage` `FieldChange`; `includes_compensation` echoes the flag.
- [ ] End-to-end fixture: 2026-06-08 is `kind="change"` with `FieldChange` rows for `position_id` (`MEX559647 → P104998`), `position_title`, `business_title`, `job_profile_name` (`Payroll Coordinator → Payroll Specialist`), none for unchanged organization fields.
- [ ] Hire-date row: `kind="hire"`, `before=None`, `changes=[]`; `no_change` rows absent by default, present with `include_unchanged=True`.
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/workday/test_worker_job_changes.py -q`

---

## Test Specification

See the test block in the Implementation Blueprint and spec §4 (M3 rows, integration test).

---

## Agent Instructions

1. Work in the feature worktree; TASK-4487 and TASK-4488 must be `done`.
2. Verify the Codebase Contract (parser keys in `worker_parsers.py`, TASK-4488 helper names).
3. Mark `in-progress`, implement from the blueprint, complete every `FILL IN`.
4. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`.
5. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4489 workday-worker-event-history-and-job-changes verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
