---
type: feature
base_branch: dev
projects: [ai-parrot-tools]
tags: [workday, soap, worker-history, job-changes, toolkit]
---

# Feature Specification: Workday Worker Event History and Job Position Changes

**Feature ID**: FEAT-706
**Date**: 2026-10-19
**Author**: Jesus Lara (spec drafted with Claude)
**Status**: approved
**Target version**: TBD

> Adds two read capabilities to the vendored Workday composable
> (`WorkdayService`) and the agent-facing `WorkdayToolkit`:
> **(1)** `Get_Worker_Event_History` — the workflow events recorded for a
> worker (hire, change job, compensation change, time entry, …) — and
> **(2)** **job position / profile change detection** — the before/after
> values of each job-related event (position, business title, job profile,
> job family, management level, location, worker/time type, supervisory
> organization, cost center, company, pay group, manager, and — opt-in —
> compensation: wage, currency, frequency, package / grade / profile), reconstructed
> from as-of-date `Get_Workers` snapshots because Workday exposes no read
> operation that returns the delta of a `Change Job` event.
>
> Everything below was verified on 2026-10-19 against the tenant's
> Human Resources v44.2 WSDL (`env/workday/humanresources_troc_44_2.wsdl`)
> and a live production worker (122 events; a `Change Job` effective
> 2026-06-08 moved position `MEX559647 / Payroll Coordinator` to
> `P104998 / Payroll Specialist`). A throw-away prototype lives in
> `examples/workday_worker_event_history.py` (git-ignored; reference only).

---

## 1. Motivation & Business Requirements

### Problem Statement

`WorkdayToolkit` can describe a worker **as of today** (`wd_get_worker`,
`wd_get_worker_job_data`, `wd_get_position`, `wd_get_job_profile`) but has no
notion of **history**: an agent cannot answer "what happened to this
employee?", "when did they change department / job profile / manager?", or
"what was their title before the last promotion?".

Workday offers the data in two pieces that must be combined:

- `Get_Worker_Event_History` (Human Resources web service) returns one
  reference per workflow event — `Event_ID`, `Event_Type_Name`,
  `Description`, `Completed_DateTime`, `Effective_Date` — but **no
  before/after values**. The `Get_Workers` transaction log
  (`Include_Transaction_Log_Data`) is the same kind of reference list.
- No `Get_Change_Job`-style read exists in the HR or Staffing WSDLs
  (verified: Staffing has only the `Change_Job` / `Import_Change_Job`
  writes; HR has `Get_Change_*` reads for personal data only).
- `Get_Workers` accepts `Response_Filter.As_Of_Effective_Date`, so the
  worker's job and organization data **as of the day before** and **as of
  the day of** a job event, diffed, yields the actual change.

The current codebase also has two smaller gaps this feature closes on the
way: the `WorkerType` handler only tries `Employee_ID` / `Contingent_Worker_ID`
references (never `WID`, which `Get_Workers` accepts directly), and
`Get_Worker_Event_History` needs an `Integration_ID_Reference` whose
`System_ID` form (`WD-WID`) no existing code produces.

### Goals

- **G1 — Event history handler.** A composable handler
  `get_worker_event_history` (HR WSDL) that resolves any worker identifier
  (WID, Employee ID, Contingent Worker ID — without the caller having to
  state which) and returns the worker's events,
  optionally bounded by effective and/or updated date ranges, as a
  `DataFrame` / `list[WorkerEvent]`.
- **G2 — Job change handler.** A composable handler
  `get_worker_job_changes` that filters the event history to job-related
  event types, snapshots `Get_Workers` as-of the day before and the day of
  each distinct effective date, and returns one `JobChange` per date with a
  typed `before` / `after` `JobSnapshot` and the list of changed fields.
- **G3 — Snapshot covers job AND organization data.** `JobSnapshot` carries
  `Worker_Job_Data.Position_Data` fields (position id/title, business title,
  job profile id/name, job family, management level, job category, worker
  type, time type, pay rate type, location, position effective date, FTE,
  weekly hours) and `Organization_Data` fields (supervisory org, cost
  center, cost center hierarchy, company, pay group, primary org) plus the
  direct manager from `Management_Chain_Data`.
- **G4 — Toolkit tools.** Two new agent tools on `WorkdayToolkit`,
  `wd_get_worker_event_history` and `wd_get_worker_job_changes`, that
  delegate through `_get_composable(...)` like every other FEAT-233 tool and
  return JSON-serializable `list[dict]`.
- **G5 — Reuse, don't re-parse.** Snapshot parsing composes the existing
  `parsers.worker_parsers` functions (`parse_employment_data`,
  `parse_worker_organization_data`, `parse_management_chain_data`,
  `parse_business_site`, `parse_worker_status`, and — opt-in —
  `parse_compensation_data`) instead of adding a parallel XML-path walker.
- **G6 — No live tenant in CI.** Every test runs against recorded,
  redacted SOAP response fixtures via the `_FakeService` /
  `_get_composable` monkeypatch patterns already used in
  `packages/ai-parrot-tools/tests/workday/`.
- **G7 — Opt-in compensation delta.** `get_worker_job_changes(
  include_compensation=True)` adds `Include_Compensation` to the snapshot
  `Response_Group`, fills the compensation fields of `JobSnapshot` through
  the existing `parse_compensation_data`, widens the default event filter
  with the two compensation event types, and diffs pay like any other
  field. Off by default: a default call never requests the compensation
  security domain.

### Non-Goals (explicitly out of scope)

- A standalone compensation-history feed. Pay is diffed only through G7
  (`include_compensation=True`, per effective date, same snapshot/diff
  engine); bonus / one-time payment / stock plans beyond
  `Salary_and_Hourly_Data` and the compensation summary totals are not
  surfaced. The default `JobSnapshot` carries no pay data.
- `Get_Previous_System_Job_History` (pre-Workday legacy job history). Not
  loaded in this tenant; separate operation, separate feature if needed.
- The `Get_Workers` transaction log (`Include_Transaction_Log_Data` /
  `Transaction_Log_Criteria_Data`). It duplicates the event history for this
  purpose.
- Changing the `WorkerType` handler's ID-type fallback order (FEAT-591's
  `test_worker_id_type_fallback.py` contract stays untouched); the new
  handlers resolve WIDs themselves.
- Multi-worker / bulk history extraction, pagination of the event list
  (`Get_Worker_Event_History` is not paged), caching, or persistence.
- Any Workday **write** operation.

---

## 2. Architectural Design

### Overview

Two new read handlers join the FEAT-230/233 composable in
`parrot_tools/interfaces/workday/handlers/`, both routed to the Human
Resources WSDL (`Get_Workers` and `Get_Worker_Event_History` are both
present in `humanresources_troc_44_2.wsdl`; verified with zeep on
2026-10-19).

**Worker reference resolution (shared).** Both handlers start with one
`Get_Workers` call (`Response_Group.Include_Reference=True`,
`Include_Personal_Information=True`) using the caller's identifier typed as
`WID`, `Employee_ID` or `Contingent_Worker_ID`. When `worker_id_type` is not
given, the candidates come from the value: a 32-character lowercase hex
string is tried as `WID` only; anything else is tried as `Employee_ID`
first and, when Workday rejects the reference with an `"Invalid ID value"`
fault, as `Contingent_Worker_ID` — the same loop
`WorkerType._fetch_single_worker` runs (`workers.py:101-130`), so a
contingent worker costs one extra call and an employee none. An explicit
`worker_id_type` disables the fallback. The response's `Worker_Reference.ID[]` yields the WID, the
Employee ID or Contingent Worker ID, and the legal `Formatted_Name`. From
then on every call uses the **WID**:

- `Get_Workers` → `Worker_Reference.ID = {type: "WID", _value_1: <wid>}`
  (verified live).
- `Get_Worker_Event_History` → `Worker_Reference` is an XSD **choice**
  `Employee_Reference | Contingent_Worker_Reference`, each holding
  `Integration_ID_Reference.ID = {_value_1: <wid>, System_ID: "WD-WID"}`
  (verified live with `Employee_Reference`; the contingent branch uses the
  same shape and is chosen when the resolved reference carries a
  `Contingent_Worker_ID`).

**Event history (M2).** Build `Worker_Event_History_Get` with the resolved
reference and an optional `Event_Date_Range_Data`
(`Effective_From`/`Effective_Through`, `Updated_From`/`Updated_Through`;
Workday requires each pair to be set together, `From <= Through`, and
`Updated_Through` not in the future — enforced client-side with
`ValueError` before any SOAP call). Flatten
`Worker_Event_History_Data.Event_Data[]` into `WorkerEvent` rows sorted by
`(effective_date, completed_at)`.

**Job changes (M3).** Reuse M2 to fetch the events, keep those whose
`event_type` is in `JOB_CHANGE_EVENT_TYPES` (default: `Hire`, `Change Job`,
`Change Organization Assignments for Worker`, `Edit Position` — all four
observed live; callers may pass their own tuple), group by distinct
`effective_date`, and for each date fetch two as-of snapshots with
`Get_Workers` (`Response_Filter.As_Of_Effective_Date`, `Response_Group`:
`Include_Reference`, `Include_Employment_Information`,
`Include_Organizations`, `Include_Management_Chain_Data`): `after` as-of the
effective date, `before` as-of the previous calendar day. Snapshots run
concurrently under an `asyncio.Semaphore(4)` and are memoised per as-of date
within one call (adjacent events share dates). Each snapshot is parsed into
a `JobSnapshot` by composing the existing worker parsers; `before` and
`after` are diffed field-by-field into `FieldChange` rows. A date whose
`before` snapshot has no position (the hire date, or Workday returning no
worker for a pre-hire as-of date) is reported with `kind="hire"` and
`before=None`; a date whose diff is empty (e.g. a `Change Job` that only
carried compensation / service-date edits) is `kind="no_change"` and is
dropped unless `include_unchanged=True`.

**Compensation opt-in (M3, G7).** `include_compensation=True` adds
`Include_Compensation` to the snapshot `Response_Group`, runs the existing
`parse_compensation_data` over each snapshot to fill the compensation
fields of `JobSnapshot` (`wage`, `pay_currency`, `pay_frequency`,
`compensation_package`, `compensation_grade`, `compensation_grade_profile`,
`compensation_effective_date`, `compensation_elements`), and — unless the
caller passed an explicit `event_types` — widens the default filter to
`JOB_CHANGE_EVENT_TYPES + COMPENSATION_EVENT_TYPES` (`Propose Compensation
Change`, `Request Compensation Change`) so a pay-only date is snapshotted
too. `wage` / `pay_currency` / `pay_frequency` come from the first
`Salary_and_Hourly_Data` node carrying an `Amount` (exactly what
`parse_compensation_data` already does); `compensation_elements` keeps
every node (`plan`, `element`, `amount`, `currency`, `frequency`) so
allowance-level edits are still visible. With the default `False` the
compensation fields stay `None` on both sides — hence never produce a
`FieldChange` — and the compensation security domain is never requested.

**Toolkit (M5).** `wd_get_worker_event_history` and
`wd_get_worker_job_changes` are thin `@tool_schema` wrappers that call
`svc.fetch_models(...)` on the matching composable and `model_dump(mode="json")`
the results — identical in shape to `wd_get_position` / `wd_get_job_profile`
(FEAT-591).

### Component Diagram

```
WorkdayToolkit (workday/tool.py)
  ├─ wd_get_worker_event_history ──┐
  └─ wd_get_worker_job_changes ────┤  _get_composable(<operation_type>)
                                   ▼
WorkdayService (interfaces/workday/service.py)  ── get_wsdl_path() ──► HR WSDL
  _type_handlers["get_worker_event_history"] ─► WorkerEventHistoryType  (M2)
  _type_handlers["get_worker_job_changes"]   ─► WorkerJobChangesType    (M3)
                                                  │        │
          resolve_worker_reference() ◄────────────┘        │  (M2 helper, shared)
          Get_Workers (WID / Employee_ID / CWID)           │
          Get_Worker_Event_History (WD-WID)                │
                                                           ▼
                                       snapshot: Get_Workers As_Of_Effective_Date
                                       parse_job_snapshot() ─► JobSnapshot (M1)
                                       diff_snapshots()     ─► FieldChange[] (M1)
                                                           ▼
                                       JobChange rows ─► DataFrame / fetch_models()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `WorkdayTypeBase` (`handlers/base.py:11`) | extends | both handlers subclass it; `execute(**kwargs) -> pd.DataFrame`; use `self.service.call_operation` and `self._logger` |
| `WorkdayService._type_handlers` (`service.py:279`) | registers | two new keys |
| `WorkdayService._OPERATION_MODEL_MAP` (`service.py:102`) | registers | `WorkerEvent`, `JobChange` for `fetch_models()` |
| `config._WSDL_ROUTING` (`config.py:67`) | registers | both keys → `WORKDAY_WSDL_HUMAN_RESOURCES` |
| `handlers/__init__.py`, `models/__init__.py` | exports | new handler and model classes |
| `parsers.worker_parsers` (`parsers/__init__.py:5`) | uses | `parse_employment_data`, `parse_worker_organization_data`, `parse_management_chain_data`, `parse_business_site`, `parse_worker_status` |
| `utils.utils` (`ensure_list`, `extract_by_type`, `first`) | uses | reference/ID flattening |
| `WorkdayToolkit._get_composable` (`tool.py:484`) | uses | per-operation composable cache |
| `tool_schema` decorator (`parrot_tools/decorators.py`) | uses | input schemas for the two tools |

### Data Models

```python
# parrot_tools/interfaces/workday/models/worker_event.py  (NEW — M1)
from datetime import date, datetime
from typing import Any, ClassVar, Literal, Optional
from pydantic import BaseModel, Field


class ResolvedWorkerReference(BaseModel):
    """Identifiers of one worker as returned by Get_Workers Include_Reference."""
    wid: str
    employee_id: Optional[str] = None
    contingent_worker_id: Optional[str] = None
    formatted_name: Optional[str] = None

    @property
    def is_contingent(self) -> bool: ...   # True when contingent_worker_id and not employee_id


class WorkerEvent(BaseModel):
    """One Event_Data entry of Worker_Event_History."""
    worker_wid: str
    event_id: str
    event_type: Optional[str] = None          # Event_Type_Reference.Event_Type_Name
    description: Optional[str] = None
    effective_date: Optional[date] = None
    completed_at: Optional[datetime] = None


class JobSnapshot(BaseModel):
    """Worker job + organization data as of one effective date."""
    as_of: date
    # Worker_Job_Data.Position_Data (via parse_employment_data)
    position_id: Optional[str] = None
    position_title: Optional[str] = None
    business_title: Optional[str] = None
    position_effective_date: Optional[str] = None
    job_profile_id: Optional[str] = None
    job_profile_name: Optional[str] = None
    job_family: Optional[list[str]] = None
    management_level: Optional[str] = None
    job_category: Optional[str] = None
    worker_type: Optional[str] = None
    position_time_type: Optional[str] = None
    pay_rate_type: Optional[str] = None
    scheduled_weekly_hours: Optional[float] = None
    full_time_equivalent_percentage: Optional[float] = None
    # Business_Site_Summary_Data (via parse_business_site)
    location_name: Optional[str] = None
    location_id: Optional[str] = None
    # Organization_Data (via parse_worker_organization_data)
    supervisory_organization_id: Optional[str] = None
    supervisory_organization_name: Optional[str] = None
    cost_center_id: Optional[str] = None
    cost_center_name: Optional[str] = None
    cost_center_hierarchy_name: Optional[str] = None
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    pay_group_id: Optional[str] = None
    pay_group_name: Optional[str] = None
    primary_organization_name: Optional[str] = None
    # Management_Chain_Data (via parse_management_chain_data)
    direct_manager_id: Optional[str] = None
    direct_manager_name: Optional[str] = None
    # Worker_Status_Data (via parse_worker_status)
    active: Optional[bool] = None
    hire_date: Optional[str] = None
    # Compensation_Data (via parse_compensation_data) — populated only with include_compensation=True
    wage: Optional[float] = None
    pay_currency: Optional[str] = None
    pay_frequency: Optional[str] = None
    compensation_package: Optional[str] = None
    compensation_grade: Optional[str] = None
    compensation_grade_profile: Optional[str] = None
    compensation_effective_date: Optional[str] = None
    compensation_elements: Optional[list[dict[str, Any]]] = None   # salary_and_hourly rows: plan, element, amount, currency, frequency

    DIFF_EXCLUDE: ClassVar[frozenset[str]] = frozenset({"as_of"})


class FieldChange(BaseModel):
    field: str
    before: Any = None
    after: Any = None


class JobChange(BaseModel):
    """One job-related change, keyed by effective date."""
    worker_wid: str
    effective_date: date
    kind: Literal["hire", "change", "no_change"]
    event_ids: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    descriptions: list[str] = Field(default_factory=list)
    before: Optional[JobSnapshot] = None
    after: JobSnapshot
    changes: list[FieldChange] = Field(default_factory=list)
    includes_compensation: bool = False      # echoes the flag so consumers know None pay fields mean "not requested"
```

### New Public Interfaces

```python
# WorkdayService (no signature change) — two new operation keys:
await svc.fetch("get_worker_event_history", worker_id=..., worker_id_type=None,
                effective_from=None, effective_through=None,
                updated_from=None, updated_through=None) -> pd.DataFrame
await svc.fetch_models("get_worker_event_history", ...) -> list[WorkerEvent]
await svc.fetch("get_worker_job_changes", worker_id=..., worker_id_type=None,
                effective_from=None, effective_through=None,
                event_types=None, include_unchanged=False, include_compensation=False) -> pd.DataFrame
await svc.fetch_models("get_worker_job_changes", ...) -> list[JobChange]

# WorkdayToolkit — two new agent tools (auto-exposed by AbstractToolkit):
await toolkit.wd_get_worker_event_history(worker_id, worker_id_type=None,
        effective_from=None, effective_through=None,
        updated_from=None, updated_through=None) -> List[Dict[str, Any]]
await toolkit.wd_get_worker_job_changes(worker_id, worker_id_type=None,
        effective_from=None, effective_through=None,
        include_unchanged=False, include_compensation=False) -> List[Dict[str, Any]]
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Models | yes | Pydantic v2 classes exactly as in §2 Data Models; `pydantic.BaseModel`, `Field`; no validators beyond type coercion | — |
| M2: Event history handler | yes | `WorkdayTypeBase` subclass; request shapes fixed in §2 Overview and §6; candidate id types + `"Invalid ID value"` fallback loop copied from `workers.py:101-130`; `ValueError` on date-pair misuse; `LookupError` when every candidate is rejected or no worker is returned | — |
| M3: Job changes handler | yes | Imports M2's `resolve_worker_reference` and `WorkerEventHistoryType`; snapshot `Response_Group` fixed (+ `Include_Compensation` when `include_compensation`); `parse_compensation_data` fills the pay fields; `asyncio.Semaphore(4)`; memo dict keyed by as-of date; diff excludes `as_of` | — |
| M4: Registration | yes | Four edit sites in §6 Edit Sites; names fixed here | — |
| M5: Toolkit tools | yes | Mirror `wd_get_position` (`tool.py:1258-1314`): `@tool_schema`, `_get_composable`, `fetch_models`, `model_dump(mode="json")` | — |
| M6: Tests & docs | yes | Fixture + `_FakeService` + `monkeypatch _get_composable` patterns from existing tests; doc page path fixed | — |

### Module 1: Worker-event models
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/worker_event.py` (new) + export in `models/__init__.py`
- **Responsibility**: Typed rows for both handlers (`WorkerEvent`, `JobSnapshot`, `FieldChange`, `JobChange`) and the shared `ResolvedWorkerReference`.
- **Depends on**: nothing new (pydantic only).
- **Interface Skeleton**:
  ```python
  # parrot_tools/interfaces/workday/models/worker_event.py  (new)
  from pydantic import BaseModel, Field   # pattern verified: models/worker.py:3

  class ResolvedWorkerReference(BaseModel): ...   # §2 Data Models
  class WorkerEvent(BaseModel): ...
  class JobSnapshot(BaseModel): ...
  class FieldChange(BaseModel): ...
  class JobChange(BaseModel): ...

  JOB_CHANGE_EVENT_TYPES: tuple[str, ...] = (
      "Hire",
      "Change Job",
      "Change Organization Assignments for Worker",
      "Edit Position",
  )
  """Event_Type_Name values treated as job-related (all four observed live 2026-10-19)."""

  COMPENSATION_EVENT_TYPES: tuple[str, ...] = (
      "Propose Compensation Change",
      "Request Compensation Change",
  )
  """Appended to the default filter only when include_compensation=True (both observed live 2026-10-19)."""
  ```
  ```python
  # parrot_tools/interfaces/workday/models/__init__.py  (modifies models/__init__.py:15, :36)
  from .worker_event import FieldChange, JobChange, JobSnapshot, ResolvedWorkerReference, WorkerEvent
  # + the five names appended to __all__
  ```

### Module 2: Worker event-history handler
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/worker_event_history.py` (new)
- **Responsibility**: Resolve any worker identifier to a WID-based reference; call `Get_Worker_Event_History`; flatten to `WorkerEvent` rows.
- **Depends on**: Module 1.
- **Interface Skeleton**:
  ```python
  # parrot_tools/interfaces/workday/handlers/worker_event_history.py  (new)
  from .base import WorkdayTypeBase                       # verified: handlers/base.py:11
  from ..models.worker_event import ResolvedWorkerReference, WorkerEvent   # M1
  from ..utils.utils import ensure_list, extract_by_type  # verified: utils/utils.py:22, :32

  WORKER_ID_TYPES: tuple[str, ...] = ("WID", "Employee_ID", "Contingent_Worker_ID")
  SYSTEM_ID_WID: str = "WD-WID"

  INVALID_ID_FAULT: str = "Invalid ID value"      # verified: workers.py:115

  def candidate_worker_id_types(worker_id: str, worker_id_type: str | None = None) -> tuple[str, ...]:
      """Explicit type → (type,); 32-char lowercase-hex id → ("WID",); anything else →
      ("Employee_ID", "Contingent_Worker_ID"). Raises ValueError for an unknown explicit type."""

  def build_event_history_worker_reference(ref: ResolvedWorkerReference) -> dict:
      """Build the Worker_Reference choice element for Worker_Event_History_Get.

      Returns ``{"Contingent_Worker_Reference" | "Employee_Reference":
      {"Integration_ID_Reference": {"ID": {"_value_1": ref.wid, "System_ID": "WD-WID"}}}}``.
      """

  def build_event_date_range(
      effective_from: date | None, effective_through: date | None,
      updated_from: date | None, updated_through: date | None,
  ) -> dict[str, datetime] | None:
      """Build Event_Date_Range_Data; raises ValueError when a pair is half-set,
      From > Through, or Updated_Through is in the future. Returns None when empty."""

  async def resolve_worker_reference(
      service: Any, worker_id: str, worker_id_type: str | None = None,
  ) -> ResolvedWorkerReference:
      """Try each candidate id type in order with one Get_Workers call each
      (Include_Reference + Include_Personal_Information). A zeep Fault whose message
      contains INVALID_ID_FAULT moves on to the next type (pattern: workers.py:111-118);
      any other error propagates. Raises LookupError when every candidate was rejected
      or the accepted response carries no worker, ValueError for an unknown
      worker_id_type. Uses service.call_operation and service.serialize_object
      (verified: service.py:319, :586)."""

  class WorkerEventHistoryType(WorkdayTypeBase):
      """Handler for ``get_worker_event_history`` (HR WSDL, Get_Worker_Event_History)."""
      def _get_default_payload(self) -> dict: ...        # {} — operation is unpaged
      async def execute(
          self, worker_id: str, worker_id_type: str | None = None,
          effective_from: date | str | None = None, effective_through: date | str | None = None,
          updated_from: date | str | None = None, updated_through: date | str | None = None,
          **kwargs: Any,
      ) -> pd.DataFrame:
          """Resolve the worker, call Get_Worker_Event_History, return one row per
          WorkerEvent sorted by (effective_date, completed_at); self.parsed holds the
          list[WorkerEvent]. Empty DataFrame (with WorkerEvent columns) when no events."""
  ```

### Module 3: Worker job-changes handler
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/worker_job_changes.py` (new)
- **Responsibility**: Filter events to job types, snapshot `Get_Workers` as-of before/after each effective date, diff, emit `JobChange` rows.
- **Depends on**: Module 1, Module 2 (`resolve_worker_reference`, `WorkerEventHistoryType`).
- **Interface Skeleton**:
  ```python
  # parrot_tools/interfaces/workday/handlers/worker_job_changes.py  (new)
  from .base import WorkdayTypeBase                                   # verified: handlers/base.py:11
  from .worker_event_history import WorkerEventHistoryType, resolve_worker_reference   # M2
  from ..models.worker_event import (                                  # M1
      COMPENSATION_EVENT_TYPES, JOB_CHANGE_EVENT_TYPES, FieldChange, JobChange, JobSnapshot, WorkerEvent,
  )
  from ..parsers.worker_parsers import (                               # verified: parsers/__init__.py:5-16
      parse_business_site, parse_compensation_data, parse_employment_data,
      parse_management_chain_data, parse_worker_organization_data, parse_worker_status,
  )

  SNAPSHOT_RESPONSE_GROUP: dict[str, bool] = {
      "Include_Reference": True, "Include_Employment_Information": True,
      "Include_Organizations": True, "Include_Management_Chain_Data": True,
  }
  # + {"Include_Compensation": True} when include_compensation (pattern: workers.py:75)

  def parse_job_snapshot(worker: dict[str, Any], as_of: date, include_compensation: bool = False) -> JobSnapshot | None:
      """Compose the five worker parsers (six with include_compensation, adding
      parse_compensation_data — verified: worker_parsers.py:757) over one serialized
      Get_Workers Worker element. Returns None when the element has no
      Worker_Data.Employment_Data.Worker_Job_Data (pre-hire as-of date)."""

  def diff_snapshots(before: JobSnapshot | None, after: JobSnapshot) -> list[FieldChange]:
      """Field-by-field comparison over JobSnapshot fields minus DIFF_EXCLUDE;
      returns [] when before is None (hire) — the caller sets kind="hire"."""

  def group_job_events(events: list[WorkerEvent], event_types: tuple[str, ...]) -> dict[date, list[WorkerEvent]]:
      """Keep events whose event_type is in event_types (exact match) and group by effective_date."""

  class WorkerJobChangesType(WorkdayTypeBase):
      """Handler for ``get_worker_job_changes`` (HR WSDL: Get_Worker_Event_History + as-of Get_Workers)."""
      snapshot_concurrency: int = 4
      def _get_default_payload(self) -> dict: ...        # {}
      async def _snapshot(self, wid: str, as_of: date, include_compensation: bool = False) -> JobSnapshot | None:
          """Get_Workers by WID with Response_Filter.As_Of_Effective_Date=as_of (ISO string) and
          SNAPSHOT_RESPONSE_GROUP (+ Include_Compensation when asked); memoised per as_of for
          the lifetime of one execute()."""
      async def execute(
          self, worker_id: str, worker_id_type: str | None = None,
          effective_from: date | str | None = None, effective_through: date | str | None = None,
          event_types: tuple[str, ...] | None = None, include_unchanged: bool = False,
          include_compensation: bool = False, **kwargs: Any,
      ) -> pd.DataFrame:
          """One JobChange row per distinct effective date, ascending; before = as_of - 1 day.
          event_types=None means JOB_CHANGE_EVENT_TYPES, plus COMPENSATION_EVENT_TYPES when
          include_compensation. Rows with kind="no_change" are dropped unless include_unchanged.
          self.parsed holds the list[JobChange]."""
  ```

### Module 4: Registration (service, config, package exports)
- **Path**: `interfaces/workday/service.py`, `interfaces/workday/config.py`, `interfaces/workday/handlers/__init__.py`
- **Responsibility**: Make both operation keys reachable through `fetch` / `fetch_models` / `get_wsdl_path`.
- **Depends on**: Modules 1–3.
- **Interface Skeleton**:
  ```python
  # config.py  (modifies config.py:99 — append after the "get_job_profiles" row)
  "get_worker_event_history": WORKDAY_WSDL_HUMAN_RESOURCES,
  "get_worker_job_changes": WORKDAY_WSDL_HUMAN_RESOURCES,

  # handlers/__init__.py  (modifies handlers/__init__.py:30-31 and :62)
  from .worker_event_history import WorkerEventHistoryType
  from .worker_job_changes import WorkerJobChangesType
  # + "WorkerEventHistoryType", "WorkerJobChangesType" in __all__

  # service.py  (modifies service.py:69, :96, :117, :310)
  from parrot_tools.interfaces.workday.handlers import (..., WorkerEventHistoryType, WorkerJobChangesType, WorkerType)
  from parrot_tools.interfaces.workday.models.worker_event import JobChange, WorkerEvent
  _OPERATION_MODEL_MAP[...]: "get_worker_event_history": WorkerEvent, "get_worker_job_changes": JobChange
  self._type_handlers[...]: "get_worker_event_history": WorkerEventHistoryType(self),
                            "get_worker_job_changes": WorkerJobChangesType(self),
  ```

### Module 5: Toolkit tools
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py`
- **Responsibility**: Agent-facing wrappers with `@tool_schema` input models.
- **Depends on**: Module 4.
- **Interface Skeleton**:
  ```python
  # tool.py  (modifies tool.py:313 — insert input models before the FEAT-230 block;
  #           modifies tool.py:1359 — insert tool methods before _parse_job_profile)
  class GetWorkerEventHistoryInput(BaseModel):   # pattern verified: tool.py:293-302
      """Input for retrieving a worker's Workday event history."""
      worker_id: str = Field(description="Worker WID, Employee ID or Contingent Worker ID")
      worker_id_type: Optional[str] = Field(default=None, description="WID | Employee_ID | Contingent_Worker_ID; omit to auto-detect (WID by shape, else Employee_ID then Contingent_Worker_ID)")
      effective_from: Optional[str] = Field(default=None, description="YYYY-MM-DD; requires effective_through")
      effective_through: Optional[str] = Field(default=None, description="YYYY-MM-DD; requires effective_from")
      updated_from: Optional[str] = Field(default=None, description="YYYY-MM-DD; requires updated_through")
      updated_through: Optional[str] = Field(default=None, description="YYYY-MM-DD; requires updated_from")

  class GetWorkerJobChangesInput(BaseModel):
      """Input for detecting a worker's job position / profile / organization changes."""
      worker_id: str = Field(...)
      worker_id_type: Optional[str] = Field(default=None, ...)
      effective_from: Optional[str] = Field(default=None, ...)
      effective_through: Optional[str] = Field(default=None, ...)
      include_unchanged: bool = Field(default=False, description="Also return job events whose snapshots are identical")
      include_compensation: bool = Field(default=False, description="Also snapshot and diff compensation (wage, currency, frequency, package/grade/profile) and include compensation-change events")

  class WorkdayToolkit(AbstractToolkit):                   # verified: tool.py:368
      @tool_schema(GetWorkerEventHistoryInput)             # tool_schema verified: tool.py:71
      async def wd_get_worker_event_history(self, worker_id: str, worker_id_type: Optional[str] = None,
              effective_from: Optional[str] = None, effective_through: Optional[str] = None,
              updated_from: Optional[str] = None, updated_through: Optional[str] = None) -> List[Dict[str, Any]]:
          """Get the Workday event history (hire, change job, time entry, …) for a worker.
          Returns one dict per event: event_id, event_type, description, effective_date, completed_at."""
          # svc = await self._get_composable("get_worker_event_history")  — verified: tool.py:484
          # models = await svc.fetch_models("get_worker_event_history", ...)
          # return [m.model_dump(mode="json") for m in models]

      @tool_schema(GetWorkerJobChangesInput)
      async def wd_get_worker_job_changes(self, worker_id: str, worker_id_type: Optional[str] = None,
              effective_from: Optional[str] = None, effective_through: Optional[str] = None,
              include_unchanged: bool = False, include_compensation: bool = False) -> List[Dict[str, Any]]:
          """Get a worker's job position / job profile / organization changes over time,
          optionally with compensation. Returns one dict per effective date with kind,
          before, after and changed fields."""
  ```

### Module 6: Tests and documentation
- **Path**: `packages/ai-parrot-tools/tests/workday/test_worker_event_history.py`, `test_worker_job_changes.py`, `test_worker_history_toolkit.py` (new); `docs/tools/workday-worker-history.md` (new)
- **Responsibility**: Fixture-driven coverage of M1–M5 and a user-facing doc page (request shapes, the WD-WID detail, call budget, limitations).
- **Depends on**: Modules 1–5.
- **Interface Skeleton**: see §4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_candidate_worker_id_types` | M2 | 32-hex → `("WID",)`; `835104` → `("Employee_ID", "Contingent_Worker_ID")`; explicit type → that one only; unknown explicit type → `ValueError` |
| `test_build_event_history_worker_reference_employee` / `_contingent` | M2 | choice element + `WD-WID` System_ID |
| `test_build_event_date_range_pairs` | M2 | half-set pair, From > Through, future Updated_Through → `ValueError`; both pairs → 4 datetimes |
| `test_resolve_worker_reference_by_wid` / `_by_employee_id` | M2 | request `ID.type` matches; returns wid/employee_id/name from fixture |
| `test_resolve_worker_reference_contingent_fallback` | M2 | fake raises `Fault("... Invalid ID value ...")` for `Employee_ID` → second call uses `Contingent_Worker_ID`; exactly 2 calls; non-matching `Fault` propagates after 1 call |
| `test_resolve_worker_reference_not_found` | M2 | empty `Response_Data` → `LookupError`; both candidates rejected → `LookupError` |
| `test_event_history_execute_rows_sorted` | M2 | fixture of 6 events → DataFrame sorted; `parsed` is `list[WorkerEvent]` |
| `test_event_history_passes_date_range` | M2 | `Event_Date_Range_Data` forwarded only when given |
| `test_parse_job_snapshot_fields` | M3 | fixture (redacted live 2026-06-08 snapshot) → every `JobSnapshot` field |
| `test_parse_job_snapshot_prehire_returns_none` | M3 | worker without `Worker_Job_Data` → `None` |
| `test_parse_job_snapshot_compensation_opt_in` | M3 | fixture with `Compensation_Data`: default → all pay fields `None`; `include_compensation=True` → `wage`, `pay_currency`, `pay_frequency`, package/grade/profile, `compensation_elements` populated |
| `test_snapshot_response_group_compensation_flag` | M3 | `Include_Compensation` present in `Response_Group` only when `include_compensation=True` |
| `test_job_changes_compensation_diff` | M3 | 2026-05-25 fixture (same job, wage 20.00 → 22.00): default → `no_change` (dropped); `include_compensation=True` → `kind="change"` with `FieldChange(wage)` and `FieldChange(compensation_elements)`, `includes_compensation=True`; `Propose Compensation Change` dates enter the filter only with the flag |
| `test_diff_snapshots` | M3 | position/title/profile change → 4 `FieldChange`; identical → `[]`; `as_of` never diffed |
| `test_group_job_events_filters_and_groups` | M3 | 122-event fixture → 5 dates for the default types; custom tuple honoured |
| `test_job_changes_execute_before_after` | M3 | fake service answering Get_Workers by `As_Of_Effective_Date` → `kind="change"` on 2026-06-08, `kind="hire"` on 2022-09-26, `no_change` dropped; call count = 1 + 1 + 2×dates |
| `test_job_changes_include_unchanged` | M3 | `include_unchanged=True` keeps `no_change` rows |
| `test_job_changes_snapshot_memoised` | M3 | adjacent dates share a snapshot → fewer `Get_Workers` calls |
| `test_routing_and_registry` | M4 | `get_wsdl_path()` → HR WSDL; both keys in `_type_handlers` and `_OPERATION_MODEL_MAP` |
| `test_fetch_models_roundtrip` | M4 | `fetch_models("get_worker_job_changes")` rebuilds `JobChange` with nested `before`/`after` |
| `test_tools_are_exposed` | M5 | both names in `toolkit.get_tools()` |
| `test_wd_get_worker_event_history_delegates` / `_job_changes_delegates` | M5 | `_get_composable` called with the right key; result is JSON-serializable |

### Integration Tests
| Test | Description |
|---|---|
| `test_job_changes_end_to_end_fixture` | Full `WorkerJobChangesType.execute` over the recorded event history + per-date snapshot fixtures of the prototype worker (names/ids redacted); asserts the 2026-06-08 row reports `MEX559647 → P104998` and `Payroll Coordinator → Payroll Specialist` |

No test contacts a live tenant (G6).

### Validation Contract

tests:
- packages/ai-parrot-tools/tests/workday/test_worker_event_history.py
- packages/ai-parrot-tools/tests/workday/test_worker_job_changes.py
- packages/ai-parrot-tools/tests/workday/test_worker_history_toolkit.py
- packages/ai-parrot-tools/tests/workday/test_toolkit_delegates.py
- packages/ai-parrot-tools/tests/workday/test_position_job_profile.py
markers: none

### Test Data / Fixtures
```python
# packages/ai-parrot-tools/tests/workday/conftest.py does not exist today — fixtures
# live in each test module (pattern: test_position_job_profile.py:11-80, test_payroll_handlers.py:18-28).

def _ref(**ids):  # verified pattern: test_position_job_profile.py:11
    return {"ID": [{"type": t, "_value_1": v} for t, v in ids.items()], "Descriptor": None}

EVENT_HISTORY_RESPONSE = {           # serialized Worker_Event_History (6 events: Hire, Enter Time,
    "Worker_Reference": {...},       # Change Job ×2, Change Organization Assignments for Worker, Edit Position)
    "Worker_Event_History_Data": {"Event_Date_Range_Data": None, "Event_Data": [
        {"Event_ID": "EV-1", "Event_Type_Reference": {"Event_Type_Name": "Change Job"},
         "Description": "Data Change: Worker", "Completed_DateTime": datetime(...), "Effective_Date": date(2026, 6, 8)},
        ...]}}

SNAPSHOTS = {  # As_Of_Effective_Date → serialized Get_Workers response (Worker_Data with
    "2026-06-07": {...},  # Employment_Data.Worker_Job_Data[0].Position_Data, Organization_Data,
    "2026-06-08": {...},  # Management_Chain_Data, Compensation_Data) — redacted copy of the prototype's live output
}

class _FakeService:   # pattern verified: test_payroll_handlers.py:18
    """Answers Get_Workers from SNAPSHOTS by As_Of_Effective_Date (or the reference lookup
    when no Response_Filter), and Get_Worker_Event_History from EVENT_HISTORY_RESPONSE;
    records every (operation, kwargs)."""
    def serialize_object(self, obj): return obj     # service.py:586 contract — fixtures are pre-serialized
```

---

## 5. Acceptance Criteria

- [ ] `get_wsdl_path("get_worker_event_history")` and `get_wsdl_path("get_worker_job_changes")` both return `WORKDAY_WSDL_HUMAN_RESOURCES`.
- [ ] `WorkdayService._type_handlers` contains both keys; `_OPERATION_MODEL_MAP` maps them to `WorkerEvent` / `JobChange`; `fetch_models` returns typed instances with nested `before`/`after` intact.
- [ ] `resolve_worker_reference` sends `ID.type` equal to the explicit type when given; otherwise `WID` for a 32-hex id, else `Employee_ID` and — only after a `Fault` containing `"Invalid ID value"` — `Contingent_Worker_ID`. It returns the WID, Employee ID / Contingent Worker ID and formatted name; raises `LookupError` when every candidate is rejected or no worker is returned; any other `Fault` propagates unchanged.
- [ ] `Get_Worker_Event_History` requests use `Employee_Reference` (or `Contingent_Worker_Reference` for contingent workers) → `Integration_ID_Reference.ID` with `_value_1=<wid>` and `System_ID="WD-WID"`.
- [ ] Date-range validation raises `ValueError` client-side for a half-set pair, `From > Through`, or `Updated_Through` in the future; no SOAP call is made.
- [ ] `WorkerEventHistoryType.execute` returns rows sorted by `(effective_date, completed_at)` with columns exactly `WorkerEvent.model_fields`.
- [ ] `WorkerJobChangesType.execute` issues exactly `1 + 1 + 2 × (distinct effective dates)` SOAP calls before memoisation and never more than that after it; snapshots are fetched with `Response_Filter.As_Of_Effective_Date` as an ISO date string.
- [ ] `JobSnapshot` is built only through `parse_employment_data`, `parse_business_site`, `parse_worker_organization_data`, `parse_management_chain_data`, `parse_worker_status` and, with `include_compensation=True`, `parse_compensation_data` (no new XML-path walking of `Position_Data` / `Organization_Data` / `Compensation_Data`).
- [ ] With the default `include_compensation=False`, no `Get_Workers` request carries `Include_Compensation`, every `JobSnapshot` pay field is `None`, and no `FieldChange` names a pay field. With `True`, `Include_Compensation` is sent, the pay fields are populated, the default event filter includes `COMPENSATION_EVENT_TYPES`, and the 2026-05-25 fixture yields `kind="change"` with a `wage` `FieldChange`; `JobChange.includes_compensation` echoes the flag.
- [ ] The end-to-end fixture reports for 2026-06-08: `kind="change"`, `FieldChange` rows for `position_id` (`MEX559647 → P104998`), `position_title`, `business_title`, `job_profile_name` (`Payroll Coordinator → Payroll Specialist`), and no `FieldChange` for unchanged organization fields.
- [ ] The hire-date row has `kind="hire"`, `before=None`, `changes=[]`; `no_change` rows are absent by default and present with `include_unchanged=True`.
- [ ] `WorkdayToolkit.get_tools()` exposes `wd_get_worker_event_history` and `wd_get_worker_job_changes`; both return `list[dict]` that `json.dumps` accepts.
- [ ] No existing test under `packages/ai-parrot-tools/tests/workday/` changes behaviour (`test_worker_id_type_fallback.py` in particular is untouched).
- [ ] `ruff check` passes on every touched file; no `requests`/`httpx`/LangChain imports.
- [ ] `docs/tools/workday-worker-history.md` documents both tools, the WID/`WD-WID` resolution and the Employee→Contingent fallback, the `include_compensation` flag and its security-domain requirement, the call budget formula, and the "references only, no delta" limitation of `Get_Worker_Event_History`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**. Verified against `bc93fe741` (dev, 2026-10-19).

### Verified Imports
```python
from parrot_tools.interfaces.workday.handlers.base import WorkdayTypeBase          # verified: handlers/base.py:11
from parrot_tools.interfaces.workday.service import WorkdayService                 # verified: service.py:170
from parrot_tools.interfaces.workday.config import WorkdayConfig, get_wsdl_path    # verified: config.py:103 (get_wsdl_path), class WorkdayConfig below it
from parrot_tools.interfaces.workday.utils.utils import ensure_list, extract_by_type, first   # verified: utils/utils.py:22, :32, :76
from parrot_tools.interfaces.workday.parsers.worker_parsers import (                # verified: parsers/__init__.py:5-16 re-exports the same names
    parse_employment_data,            # worker_parsers.py:1030
    parse_worker_status,              # worker_parsers.py:1159
    parse_business_site,              # worker_parsers.py:1247
    parse_management_chain_data,      # worker_parsers.py:1292
    parse_worker_organization_data,   # worker_parsers.py:669
    parse_worker_reference,           # worker_parsers.py:260
    parse_compensation_data,          # worker_parsers.py:757 (M3, include_compensation only)
)
from parrot_tools.interfaces.workday.models.worker import Worker                   # verified: models/worker.py:13
from parrot_tools.workday.tool import WorkdayToolkit                               # verified: tool.py:368
from parrot_tools.decorators import tool_schema                                    # verified: tool.py:71 (`from ..decorators import tool_schema`)
from parrot.conf import WORKDAY_WSDL_HUMAN_RESOURCES                               # verified: parrot/conf.py:657
from zeep.helpers import serialize_object                                          # verified: service.py:36, handlers/base.py:8
from zeep.exceptions import Fault                                                  # verified: tool.py:69
import pandas as pd                                                                # verified: service.py:34
```

### Existing Class Signatures
```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/base.py
class WorkdayTypeBase(ABC):                                                        # line 11
    def __init__(self, service: Any, max_retries: int = 3, retry_delay: float = 0.5)   # line 21
    self.service; self._logger: logging.Logger; self.request_payload: Dict[str, Any]   # lines 34-38
    def _get_default_payload(self) -> Dict[str, Any]                               # line 42 — returns {"Response_Filter": {}, "Response_Group": {}}
    @abstractmethod async def execute(self, **kwargs) -> Any                       # line 53
    async def _paginate_soap_operation(...)                                        # line 60 (NOT used by this feature — both ops are unpaged)

# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py
class WorkdayService(SOAPClient):                                                  # line 170
    def __init__(self, *, config: WorkdayConfig | None = None, operation_type: str = "get_workers", **kwargs)  # line 190
    _OPERATION_MODEL_MAP: dict[str, type]   (module level)                         # line 102 — last entry "get_references": WorkdayReference (117)
    self._type_handlers: dict[str, Any]                                            # line 279 — last entry "get_time_off_eligibility" (310), closes at 311
    async def call_operation(self, operation: str, **kwargs: Any) -> Any           # line 319 — raw zeep call (SOAPClient.run, parrot/interfaces/soap.py:237)
    async def fetch(self, operation_type: str, **params: Any) -> pd.DataFrame      # line 334 — dispatches to _type_handlers[op].execute(**params)
    async def fetch_models(self, operation_type: str, **params: Any) -> list       # line 359 — model_class(**_record_to_model_kwargs(model_class, record)) per DataFrame row
    async def start(self, **_kwargs) -> None                                       # line 519
    async def close(self) -> None                                                  # line 523
    def serialize_object(self, obj: Any) -> Any                                    # line 586 — keeps zeep IDs as {"type","_value_1"} dicts

# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py
_WSDL_ROUTING: dict[str, Any]                                                      # line 67 — last entry "get_job_profiles": WORKDAY_WSDL_HUMAN_RESOURCES (99)
def get_wsdl_path(operation_type: str) -> Any                                      # line 103 — falls back to WORKDAY_WSDL_PATH (staffing)

# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/workers.py
class WorkerType(WorkdayTypeBase)                                                  # __init__ line 36
    def _get_default_payload(self) -> Dict[str, Any]                               # line 46 — Request_Criteria + Response_Filter(As_Of 1y ahead) + Response_Group
    async def _fetch_single_worker(self, worker_id: str, id_types: List[str]) -> Any   # line 87 — payload {"Request_References": {"Worker_Reference": [{"ID": {"type": id_type, "_value_1": worker_id}}]}}; `"Invalid ID value" in str(exc)` → next id type (line 115), else retry/raise; raises last_invalid at line 130 — M2 copies this loop, it does NOT import it
    async def execute(self, **kwargs) -> pd.DataFrame                              # line 132 — worker_id_type ∈ {Employee_ID, Contingent_Worker_ID}; WID is NOT tried (line 175)

# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/parsers/worker_parsers.py  (all take the serialized Worker_Data dict)
def parse_worker_organization_data(worker_data) -> Dict   # 669 → keys: organizations, primary_organization_{id,name,type,code}, company_{id,name}, cost_center_{id,name}, cost_center_hierarchy_name, pay_group_{id,name}, supervisory_organization_{id,name}   (return at 740-755)
def parse_employment_data(worker_data) -> Dict            # 1030 → keys: position_id, position_title, business_title, start_date, end_employment_date, position_effective_date, worker_type, position_time_type, pay_rate_type, job_exempt, scheduled_weekly_hours, default_weekly_hours, full_time_equivalent_percentage, …, job_profile_id, job_profile_name, management_level, job_category, job_family (list|None), job_classifications, critical_job   (return at 1127-1156)
def parse_worker_status(worker_data) -> Dict              # 1159 → keys: active, active_status_date, hire_date, original_hire_date, hire_reason, …, terminated, termination_date, …   (return at 1219-1245)
def parse_business_site(worker_data) -> Dict              # 1247 → business_site_name, business_site_location_id, …
def parse_management_chain_data(worker_data) -> Dict      # 1292 → management_chain, direct_manager_id, direct_manager_name, matrix_management_chain   (return at 1395-1400)
def parse_worker_reference(worker_response) -> Dict       # 260 — main Worker_Reference WID
def parse_compensation_data(worker_data) -> Dict          # 757 → keys: wage (first Salary_and_Hourly node with Amount), compensation_effective_date, compensation_guidelines{package,grade,profile}, salary_and_hourly[{plan,element,amount,currency,frequency,assignment_effective_date}] (via _parse_salary_nodes:1675), compensation_summary, reason_references   (return at 815-825)

# packages/ai-parrot-tools/src/parrot_tools/workday/tool.py
class WorkdayToolkit(AbstractToolkit)                                              # line 368
    async def _get_composable(self, operation_type: str) -> WorkdayComposable      # line 484 — lazily builds WorkdayService(config, operation_type) and start()s it
    @tool_schema(GetPositionInput) async def wd_get_position(self, position_id: str, include_closed: bool = True) -> Dict[str, Any]   # line 1258 — reference implementation for M5
    def _parse_job_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]       # line 1359 — M5 inserts its two tools immediately before this line
```

### Verified Workday request / response shapes (zeep, HR WSDL, 2026-10-19)
```python
# Get_Worker_Event_History — input signature (WSDL)
# Worker_Reference: Worker_ReferenceType(( {Employee_Reference: Employee_ReferenceType} | {Contingent_Worker_Reference: Contingent_Worker_Reference_DataType} ))
# Employee_ReferenceType(Integration_ID_Reference: External_Integration_ID_Reference_DataType)
# External_Integration_ID_Reference_DataType(ID: IDType, Descriptor: xsd:string);  IDType(xsd:string, System_ID: xsd:string)
# Event_Date_Range_Data: Effective_And_Updated_DateTime_DataType(Updated_From, Updated_Through, Effective_From, Effective_Through: xsd:dateTime)
# Response: Worker_Event_HistoryType(Worker_Reference, Worker_Event_History_Data: {Event_Date_Range_Data, Event_Data: Event_History_DataType[]})
# Event_History_DataType(Event_ID: str, Event_Type_Reference: {Event_Type_Name: str}, Description: str, Completed_DateTime: dateTime, Effective_Date: date)
request = {
    "Worker_Reference": {"Employee_Reference": {"Integration_ID_Reference": {"ID": {"_value_1": wid, "System_ID": "WD-WID"}}}},
    "Event_Date_Range_Data": {"Effective_From": datetime, "Effective_Through": datetime},   # optional
}
# Live Event_Type_Name values seen (prod, 2026-10-19): Hire, Change Job, Change Organization Assignments for Worker,
# Edit Position, Propose Compensation Change, Request Compensation Change, Service Dates Change, Assign Pay Group,
# Enter Time, Request Time Off, Correct Time Off, Change Benefits, Change Benefits for Life Event, Assign Work Schedule, …

# Get_Workers by WID (HR WSDL) — verified live
request = {
    "Request_References": {"Worker_Reference": [{"ID": {"type": "WID", "_value_1": wid}}]},
    "Response_Filter": {"As_Of_Effective_Date": "2026-06-08"},          # ISO string accepted (pattern: workers.py:71)
    "Response_Group": {"Include_Reference": True, "Include_Employment_Information": True,
                       "Include_Organizations": True, "Include_Management_Chain_Data": True},
    # + "Include_Compensation": True  (workers.py:75 already sends it) → Worker_Data.Compensation_Data.{Salary_and_Hourly_Data[], Compensation_Guidelines_Data[], Compensation_Effective_Date, Reason_Reference}
}
# serialized: Response_Data.Worker[0] → Worker_Reference.ID[] (types WID, Employee_ID), Worker_Data.{Personal_Data.Name_Data.Legal_Name_Data.Name_Detail_Data.Formatted_Name,
#             Employment_Data.{Worker_Job_Data[0].Position_Data, Worker_Status_Data}, Organization_Data.Worker_Organization_Data[], Management_Chain_Data}
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `WorkerEventHistoryType` / `WorkerJobChangesType` | `WorkdayService.call_operation()` | `self.service.call_operation("Get_Worker_Event_History" / "Get_Workers", **req)` | `service.py:319` |
| both handlers | `WorkdayService.serialize_object()` | `self.service.serialize_object(raw)` | `service.py:586` |
| both handlers | `WorkdayService._type_handlers` | registry entries | `service.py:279-311` |
| `WorkerEvent`, `JobChange` | `WorkdayService.fetch_models()` | `_OPERATION_MODEL_MAP` | `service.py:102-118`, `:359-396` |
| both keys | `get_wsdl_path()` | `_WSDL_ROUTING` | `config.py:67-100` |
| `parse_job_snapshot` | worker parsers | function calls on `Worker_Data` | `worker_parsers.py:669, :1030, :1159, :1247, :1292` (+ `:757` with `include_compensation`) |
| `wd_get_worker_*` tools | `WorkdayToolkit._get_composable()` | `await self._get_composable(<key>)` then `fetch_models` | `tool.py:484` |

### Does NOT Exist (Anti-Hallucination)
- ~~`Get_Change_Job`~~, ~~`Get_Job_Change_Events`~~, ~~`Get_Worker_History`~~ — no such SOAP operations in the HR or Staffing WSDLs; Staffing only has the `Change_Job` / `Import_Change_Job` writes.
- ~~`Worker_Event_History_Get.Event_Type_Reference`~~ / any event-type **request** filter — the request has only `Worker_Reference` and `Event_Date_Range_Data`; event type exists only in the response, so filtering is client-side.
- ~~`Integration_ID_ReferenceType`~~ — the zeep type is `External_Integration_ID_Reference_DataType`.
- ~~`WorkdayService.get_worker_event_history()`~~ / ~~`WorkdayToolkit.wd_get_worker_history()`~~ — nothing history-related exists today (only `get_current_user_time_off_history`, `tool.py:1858`, which is time-off requests).
- ~~`WorkerType` accepting `worker_id_type="WID"`~~ — only `Employee_ID` / `Contingent_Worker_ID` (`workers.py:175`); do not extend it, M2 resolves WIDs itself.
- ~~`packages/ai-parrot-tools/tests/workday/conftest.py`~~ — no shared conftest in that directory; fixtures are module-local.
- ~~`docs/tools/`~~ directory — does not exist yet; M6 creates it with the single doc page.
- ~~`handlers/base.py` write-template `build_request` / `parse_ack`~~ for these handlers — that template (`base.py:198-260`) is for write operations; the new handlers implement `execute` directly like `payroll.py:27`.
- ~~`WORKDAY_WSDL_PATH` for these keys~~ — the default fallback is the **Staffing** WSDL, which has no `Get_Worker_Event_History`; both keys must be routed explicitly to `WORKDAY_WSDL_HUMAN_RESOURCES`.

### Edit Sites (Blueprint Anchors)

Verified against: `bc93fe741`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/worker_event.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/__init__.py` | MODIFY | `from .clock_event import ClockEvent, ClockEventResult, ClockEventType, ReportedTimeBlock` | `models/__init__.py:15` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/__init__.py` | MODIFY | `    "ReportedTimeBlock",` | `models/__init__.py:36` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/worker_event_history.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/worker_job_changes.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/__init__.py` | MODIFY | `    CompanyPaymentDatesType,` (import block, followed by `)`) | `handlers/__init__.py:30` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/__init__.py` | MODIFY | `    "CompanyPaymentDatesType",` (`__all__`) | `handlers/__init__.py:62` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py` | MODIFY | `    "get_job_profiles": WORKDAY_WSDL_HUMAN_RESOURCES,` | `config.py:99` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py` | MODIFY | `    WorkerType,` (handlers import block) | `service.py:69` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py` | MODIFY | `from parrot_tools.interfaces.workday.models.worker import Worker` | `service.py:96` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py` | MODIFY | `    "get_references": WorkdayReference,` | `service.py:117` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py` | MODIFY | `            "get_time_off_eligibility": TimeOffEligibilityType(self),` | `service.py:310` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py` | MODIFY | `# Homologated read-tool input schemas (FEAT-230 Module 3)` (insert the two input models above it) | `tool.py:313` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py` | MODIFY | `    def _parse_job_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:` (insert the two tools above it) | `tool.py:1359` | 1 |
| `packages/ai-parrot-tools/tests/workday/test_worker_event_history.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/tests/workday/test_worker_job_changes.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/tests/workday/test_worker_history_toolkit.py` | CREATE | — | — | — |
| `docs/tools/workday-worker-history.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Handlers: subclass `WorkdayTypeBase`, override `_get_default_payload` to `{}` (unpaged ops) and implement `execute(**kwargs) -> pd.DataFrame`; keep the parsed Pydantic list on `self.parsed` (mirrors `payroll.py`). Use `self.service.call_operation` for every SOAP call and `self.service.serialize_object` for responses.
- Wrap `zeep.exceptions.Fault` only where a specific message is expected: in `resolve_worker_reference` an `"Invalid ID value"` fault advances to the next candidate id type (loop copied from `workers.py:101-130`) and becomes `LookupError` once the candidates are exhausted (pattern `tool.py:1303-1307`); let other faults propagate.
- Dates: accept `date | str` in handlers, normalise with `date.fromisoformat`; send `As_Of_Effective_Date` as an ISO string (as `workers.py:71` does) and `Event_Date_Range_Data` values as `datetime` (From at `00:00:00`, Through at `23:59:59`).
- Toolkit tools: `@tool_schema(<Input>)`, `if not self._initialized: await self.wd_start()`, `svc = await self._get_composable(<key>)`, `fetch_models`, return `[m.model_dump(mode="json") for m in models]`.
- Async-first, `self._logger` / `self.logger` only, Pydantic v2, Google docstrings, 120 columns, no `requests`/`httpx`.
- Tests: module-local fixtures, `_FakeService` recording calls, `monkeypatch.setattr(WorkdayToolkit, "_get_composable", ...)`; `pytest.ini` sets `asyncio_mode = auto`. Run with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src` inside a worktree.

### Known Risks / Gotchas
- **`WD-WID` is the only verified `System_ID`.** `WD-EMPLID` (Employee ID as integration id) is the standard Workday value but was not exercised; the design avoids it entirely by resolving to a WID first. Do not add an Employee-ID fallback without a live check.
- **Contingent branch untested live.** `Contingent_Worker_Reference` has the identical `Integration_ID_Reference` shape in the WSDL, and the `Employee_ID → Contingent_Worker_ID` fallback relies on the same `"Invalid ID value"` fault text `WorkerType` already depends on (`workers.py:115`), but the tenant worker used was an employee. Both are covered by fixture tests only; flagged in the doc page.
- **Compensation security domain.** `Include_Compensation` needs the integration user to hold the compensation domains; a tenant that denies them returns `Worker_Data` without `Compensation_Data` (pay fields `None`, no error) or a security `Fault`. The flag is opt-in precisely so the default call never depends on it; document the symptom. `wage` is the first `Salary_and_Hourly_Data` node with an `Amount` (parser behaviour, `worker_parsers.py:773-776`), so a worker with several plans still gets one scalar plus the full `compensation_elements` list.
- **Pre-hire as-of snapshot.** `Get_Workers` as-of a date before the hire may return the worker with no `Worker_Job_Data`, or a validation `Fault`. `parse_job_snapshot` returns `None` for the former; `_snapshot` must map a `Fault` whose message contains `"Invalid ID value"` or an empty `Response_Data` to `None` as well, so the row becomes `kind="hire"` rather than an error.
- **Same-day multiple positions.** `parse_employment_data` reads `Worker_Job_Data[0]` only (primary job). Additional jobs are out of scope; documented.
- **`fetch_models` reconstruction.** `_record_to_model_kwargs` (`service.py:136`) rebuilds models from DataFrame rows; nested `before`/`after`/`changes` must survive as dicts/lists in the row (keep them as Python objects in the DataFrame, never JSON strings). AC covers the round-trip; if it fails, expose `handler.parsed` through `fetch_models` for these two keys instead of changing `_record_to_model_kwargs`.
- **Call budget.** Worst case `2 + 2N` SOAP calls for `N` distinct job-event dates (the prototype worker: 5 dates → 12 calls, ≈1 s each). Bounded by `asyncio.Semaphore(4)`; `effective_from/through` is the caller's lever to cut `N`.
- **Event names are tenant-visible labels.** `JOB_CHANGE_EVENT_TYPES` matches `Event_Type_Name` exactly; a tenant that renamed business processes passes its own tuple. The toolkit tool does not expose the tuple (keep the agent surface small); the handler does.
- **`Updated_Through` in the future is rejected by Workday** — validated client-side so the agent gets a clear `ValueError`.
- **WSDL fallback trap.** An unregistered key silently routes to the Staffing WSDL (`config.py:116`), where `Get_Worker_Event_History` does not exist → `ValueError: Operation ... not found in WSDL` from `soap.py:245`. The routing test in M4 guards this.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `zeep` | already a dependency (`ai-parrot-tools[workday]`) | SOAP client / `serialize_object` |
| `pandas` | already a dependency | handler return type (`WorkdayTypeBase` contract) |
| `pydantic` | `>=2` (workspace) | models |

No new dependencies.

---

## 8. Open Questions

- [x] Should `wd_get_worker_job_changes` also surface compensation deltas behind an opt-in flag? — *Resolved 2026-10-19 by Jesus Lara*: **yes, behind `include_compensation=False`.** Landed as G7, the §2 "Compensation opt-in" paragraph, the pay fields on `JobSnapshot`, `COMPENSATION_EVENT_TYPES` (M1), the `include_compensation` parameter on M3 / M5, three M3 tests and one acceptance criterion. Reuses `parse_compensation_data` (`worker_parsers.py:757`); no new parser.
- [x] Should a non-WID id fall back from `Employee_ID` to `Contingent_Worker_ID` automatically? — *Resolved 2026-10-19 by Jesus Lara*: **yes, auto-fallback like `WorkerType`.** `candidate_worker_id_types` yields `("Employee_ID", "Contingent_Worker_ID")` for a non-32-hex id; `resolve_worker_reference` advances on an `"Invalid ID value"` fault (loop copied from `workers.py:101-130`, not imported); an explicit `worker_id_type` disables the fallback. One extra call only on a miss.
- [x] Doc page location? — *Resolved 2026-10-19 by Jesus Lara*: **`docs/tools/workday-worker-history.md`** (new `docs/tools/` directory in the repo-wide docs tree, indexed by the wiki build). M6 path unchanged.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document: this spec was written from
> verified live findings and the `--` notes, with no brainstorm/proposal to brief the codex seat on)
> · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-19 | Jesus Lara / Claude | Initial draft from live WSDL + tenant verification |
| 0.2 | 2026-10-19 | Jesus Lara / Claude | §8 resolved: opt-in `include_compensation` (G7), Employee→Contingent id fallback, docs path confirmed |
