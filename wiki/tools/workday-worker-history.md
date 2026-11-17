# Workday worker history

Two tools expose Workday's worker event history and job change detection:
`wd_get_worker_event_history` returns the raw workflow events (hire, change job,
compensation change, time off, etc.), while `wd_get_worker_job_changes` reconstructs
what actually changed in each job-related event by comparing snapshots taken before
and after the event effective date. Use event history when you only need the timeline;
use job changes when you need the before/after details of position, title, organization,
or compensation.

## Tools and operation keys

| Toolkit tool | Operation key | Returns |
|---|---|---|
| `wd_get_worker_event_history` | `get_worker_event_history` | `List[WorkerEvent]` — one dict per event with `worker_wid`, `event_id`, `event_type`, `description`, `effective_date`, `completed_at` |
| `wd_get_worker_job_changes` | `get_worker_job_changes` | `List[JobChange]` — one dict per effective date with `worker_wid`, `effective_date`, `kind` ("hire" \| "change" \| "no_change"), `event_ids`, `event_types`, `descriptions`, `before`, `after`, `changes`, `includes_compensation` |

Both tools delegate through `WorkdayService.fetch_models()` to the Human Resources
WSDL.

## How a worker is identified

The tools accept a `worker_id` parameter that can be a **WID** (32-character
hexadecimal string), **Employee ID**, or **Contingent Worker ID**. When
`worker_id_type` is omitted, the handler resolves the identifier automatically:

1. **WID by shape** — if `worker_id` is a 32-character lowercase hex string,
   it is tried as a WID only.
2. **Employee ID first** — otherwise, the value is tried as an Employee ID.
3. **Contingent Worker ID fallback** — if Workday returns an `"Invalid ID value"`
   fault, the value is retried as a Contingent Worker ID.

An explicit `worker_id_type` (`"WID"`, `"Employee_ID"`, or `"Contingent_Worker_ID"`)
disables the fallback chain.

Once resolved, the worker's **WID** is used for all subsequent calls:
- `Get_Workers` receives `Worker_Reference.ID = {type: "WID", _value_1: <wid>}`.
- `Get_Worker_Event_History` receives an `Integration_ID_Reference` with
  `System_ID="WD-WID"`:
  ```xml
  <Employee_Reference>
    <Integration_ID_Reference ID="_value_1" System_ID="WD-WID"/>
  </Employee_Reference>
  ```
  (The contingent branch uses the same shape when the resolved reference carries
  a `Contingent_Worker_ID`.)

## Event history is references only

`Get_Worker_Event_History` returns **references only** — each event contains
`Event_ID`, `Event_Type_Name`, `Description`, `Effective_Date`, and
`Completed_DateTime`, but **no before/after field values**. This is a Workday
limitation: the operation provides the timeline, not the delta.

To see what actually changed in a job-related event, use
`wd_get_worker_job_changes`, which reconstructs the delta:

1. Fetch the event history and filter to job-related event types
   (`Hire`, `Change Job`, `Change Organization Assignments for Worker`,
   `Edit Position`).
2. Group events by distinct `effective_date`.
3. For each date, fetch two as-of snapshots via `Get_Workers`:
   - **Before**: the day before the effective date
   - **After**: the effective date itself
4. Diff the two snapshots field-by-field into `FieldChange` rows.
5. Classify the date:
   - `kind="hire"` — the `before` snapshot has no position (pre-hire or first day)
   - `kind="change"` — at least one field differs between before/after
   - `kind="no_change"` — snapshots are identical (e.g., a compensation-only edit
     with `include_compensation=False`)

```
Event: "Change Job" effective 2026-06-08
├── Before snapshot (as-of 2026-06-07)
│   └── position_title: "Payroll Coordinator"
│       position_id: "MEX559647"
│       supervisory_organization_name: "Payroll"
│       ...
└── After snapshot (as-of 2026-06-08)
    └── position_title: "Payroll Specialist"
        position_id: "P104998"
        supervisory_organization_name: "Payroll"
        ...
└── Changes
    ├── field: "position_title", before: "Payroll Coordinator", after: "Payroll Specialist"
    └── field: "position_id", before: "MEX559647", after: "P104998"
```

## Job event types and compensation

### Default event types

The job changes tool filters events by these default event types:

| Event type | Meaning |
|---|---|
| `Hire` | New worker hire |
| `Change Job` | Position, title, job profile, or organization change |
| `Change Organization Assignments for Worker` | Organization reassignment without a formal job change |
| `Edit Position` | Position data edited (affects the worker's current assignment) |

### Compensation opt-in

The `include_compensation` flag enables compensation snapshotting:

- **Extra fields populated**: `wage`, `pay_currency`, `pay_frequency`,
  `compensation_package`, `compensation_grade`, `compensation_grade_profile`,
  `compensation_effective_date`, `compensation_elements` (list of plan/element/
  amount/currency/frequency rows).
- **Widened event filter**: when `include_compensation=True`, the tool also
  includes compensation event types:
  - `Propose Compensation Change`
  - `Request Compensation Change`
- **Security domain requirement**: the Workday account must have access to the
  **Compensation** security domain. If the domain is missing, compensation
  fields return `None` (or the tool may raise a security fault, depending on
  tenant configuration).

When `include_compensation=False` (the default), compensation fields are `None`
on both `before` and `after` snapshots, and compensation-only events are excluded.

## Cost and performance

### Call budget

For `N` distinct event dates, the job changes tool makes:

- **1 call** to resolve the worker (if not already a WID)
- **1 call** to fetch the event history
- **2 × N calls** to fetch before/after snapshots (concurrency limited to 4)

**Total: `2 + 2N` calls** (worst case: 6 calls for 2 dates, 10 calls for 4 dates).

### Concurrency

Snapshot fetches run concurrently under an `asyncio.Semaphore(4)` — up to 4
as-of requests are in flight simultaneously. This limits latency for workers
with many event dates.

### Date range lever

To reduce the call count, narrow the date range with `effective_from` and
`effective_through`. Fewer distinct effective dates means fewer snapshot pairs.

## Limitations

- **Primary job only** — the tool reads `Worker_Job_Data[0]` (the primary job).
  Secondary assignments, concurrent jobs, or multiple positions are not included.
- **Tenant-specific event names** — the default event types (`Hire`, `Change Job`,
  etc.) match the observed Workday tenant. Other tenants may use different
  `Event_Type_Name` values; pass an explicit `event_types` tuple to override.
- **Contingent Worker ID path** — the fallback from Employee ID to Contingent
  Worker ID is tested against fixtures only; real contingent workers were not
  available during development.
- **`Updated_Through` cannot be in the future** — the Workday API rejects
  `Updated_Through` dates greater than today. The client raises `ValueError`
  before making the SOAP call if this constraint is violated.

## Examples

### Event history

```python
from parrot_tools.workday import WorkdayToolkit

toolkit = WorkdayToolkit(tenant_name="acme_prod")
await toolkit.wd_start()

events = await toolkit.wd_get_worker_event_history(
    worker_id="100001",  # Employee ID
    effective_from="2025-01-01",
    effective_through="2025-12-31",
)
# Returns:
# [
#   {
#     "worker_wid": "0123456789abcdef0123456789abcdef",
#     "event_id": "EVT-123456",
#     "event_type": "Hire",
#     "description": "Hire of Jane Doe",
#     "effective_date": "2025-03-15",
#     "completed_at": "2025-03-15T14:30:00Z"
#   },
#   {
#     "worker_wid": "0123456789abcdef0123456789abcdef",
#     "event_id": "EVT-234567",
#     "event_type": "Change Job",
#     "description": "Promotion to Senior Analyst",
#     "effective_date": "2025-09-01",
#     "completed_at": "2025-09-01T09:00:00Z"
#   }
# ]
```

### Job changes

```python
changes = await toolkit.wd_get_worker_job_changes(
    worker_id="0123456789abcdef0123456789abcdef",  # WID
    effective_from="2025-01-01",
    effective_through="2025-12-31",
    include_compensation=False,
)
# Returns:
# [
#   {
#     "worker_wid": "0123456789abcdef0123456789abcdef",
#     "effective_date": "2025-03-15",
#     "kind": "hire",
#     "event_ids": ["EVT-123456"],
#     "event_types": ["Hire"],
#     "descriptions": ["Hire of Jane Doe"],
#     "before": None,
#     "after": {
#       "as_of": "2025-03-15",
#       "position_id": "P100001",
#       "position_title": "Analyst",
#       "business_title": "Junior Analyst",
#       "job_profile_id": "JP-001",
#       "job_profile_name": "Analyst",
#       "supervisory_organization_id": "ORG-100",
#       "supervisory_organization_name": "Finance",
#       ...
#     },
#     "changes": [],
#     "includes_compensation": False
#   },
#   {
#     "worker_wid": "0123456789abcdef0123456789abcdef",
#     "effective_date": "2025-09-01",
#     "kind": "change",
#     "event_ids": ["EVT-234567"],
#     "event_types": ["Change Job"],
#     "descriptions": ["Promotion to Senior Analyst"],
#     "before": {
#       "as_of": "2025-08-31",
#       "position_id": "P100001",
#       "position_title": "Analyst",
#       "business_title": "Junior Analyst",
#       "job_profile_id": "JP-001",
#       "job_profile_name": "Analyst",
#       ...
#     },
#     "after": {
#       "as_of": "2025-09-01",
#       "position_id": "P100002",
#       "position_title": "Senior Analyst",
#       "business_title": "Senior Analyst",
#       "job_profile_id": "JP-002",
#       "job_profile_name": "Senior Analyst",
#       ...
#     },
#     "changes": [
#       {"field": "position_id", "before": "P100001", "after": "P100002"},
#       {"field": "position_title", "before": "Analyst", "after": "Senior Analyst"},
#       {"field": "business_title", "before": "Junior Analyst", "after": "Senior Analyst"},
#       {"field": "job_profile_id", "before": "JP-001", "after": "JP-002"},
#       {"field": "job_profile_name", "before": "Analyst", "after": "Senior Analyst"}
#     ],
#     "includes_compensation": False
#   }
# ]
```

### Job changes with compensation

```python
changes = await toolkit.wd_get_worker_job_changes(
    worker_id="100001",
    effective_from="2025-01-01",
    effective_through="2025-12-31",
    include_compensation=True,
)
# Compensation fields are populated in before/after snapshots:
# "before": { ..., "wage": 50000.0, "pay_currency": "USD", "pay_frequency": "Annual", ... }
# "after": { ..., "wage": 60000.0, "pay_currency": "USD", "pay_frequency": "Annual", ... }
# "changes": [ ..., {"field": "wage", "before": 50000.0, "after": 60000.0} ]
```