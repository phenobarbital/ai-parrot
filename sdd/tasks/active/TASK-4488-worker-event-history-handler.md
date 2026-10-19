# TASK-4488: Worker event-history handler and worker-reference resolver

**Feature**: FEAT-706 — Workday Worker Event History and Job Changes
**Spec**: `sdd/specs/workday-worker-event-history-and-job-changes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4487
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 and §2 Overview "Worker reference resolution" / "Event history". This
task adds the `get_worker_event_history` handler and the module-level helpers that
TASK-4489 reuses: `resolve_worker_reference` (any id → WID, with the Employee→Contingent
fallback decided in spec §8 resolution 2) and the `Get_Worker_Event_History` request
builders. Registration in the service is TASK-4490.

---

## Scope

- Create `handlers/worker_event_history.py` with the constants, the four functions and
  `WorkerEventHistoryType` exactly as spec §3 M2's skeleton.
- `resolve_worker_reference` copies (does not import) the `"Invalid ID value"` fallback loop
  of `WorkerType._fetch_single_worker` (`workers.py:101-130`), one `Get_Workers` per candidate.
- `build_event_date_range` validates client-side and raises `ValueError` before any SOAP call.
- `WorkerEventHistoryType.execute` returns a DataFrame sorted by `(effective_date, completed_at)`
  whose columns are exactly `WorkerEvent.model_fields`, and keeps `self.parsed: list[WorkerEvent]`.
- Write `test_worker_event_history.py` with the M2 rows of spec §4.

**NOT in scope**: job-change snapshots/diffs (TASK-4489), `service.py` / `config.py` /
`handlers/__init__.py` registration (TASK-4490), toolkit tools (TASK-4491). Do NOT modify
`workers.py` or `WorkerType` (spec "Does NOT Exist": do not extend it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/worker_event_history.py` | CREATE | Resolver, request builders, `WorkerEventHistoryType` |
| `packages/ai-parrot-tools/tests/workday/test_worker_event_history.py` | CREATE | M2 unit tests (fake service, no live tenant) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.interfaces.workday.handlers.base import WorkdayTypeBase          # handlers/base.py:11 (use relative: from .base import WorkdayTypeBase)
from parrot_tools.interfaces.workday.utils.utils import ensure_list, extract_by_type, first   # utils/utils.py:22, :32, :76
from parrot_tools.interfaces.workday.models.worker_event import ResolvedWorkerReference, WorkerEvent   # TASK-4487
from zeep.exceptions import Fault                                                  # used by tool.py:69
import pandas as pd
```

### Existing Signatures to Use
```python
# handlers/base.py
class WorkdayTypeBase(ABC):                                                        # line 11
    def __init__(self, service: Any, max_retries: int = 3, retry_delay: float = 0.5)   # line 21 — sets self.service, self._logger, self.request_payload (= _get_default_payload()), self.max_retries, self.retry_delay
    def _get_default_payload(self) -> Dict[str, Any]                               # line 42
    @abstractmethod async def execute(self, **kwargs) -> Any                       # line 53

# service.py
async def call_operation(self, operation: str, **kwargs: Any) -> Any               # line 319 — called as call_operation(operation="Get_Workers", **payload) (workers.py:113)
def serialize_object(self, obj: Any) -> Any                                         # line 586 — keeps IDs as {"type","_value_1"}

# handlers/workers.py — the loop to COPY (lines 101-130):
#   for id_type in id_types: payload with Request_References.Worker_Reference=[{"ID": {"type": id_type, "_value_1": worker_id}}]
#     try: return await self.service.call_operation(operation="Get_Workers", **payload)
#     except Exception as exc: if "Invalid ID value" in str(exc): last_invalid = exc; break   (line 115)
#     else retry up to max_retries with asyncio.sleep(retry_delay), then raise
#   raise last_invalid
```

### Verified request / response shapes (zeep, HR WSDL, 2026-10-19)
```python
# Get_Workers by id (reference lookup)
{"Request_References": {"Worker_Reference": [{"ID": {"type": "<WID|Employee_ID|Contingent_Worker_ID>", "_value_1": worker_id}}]},
 "Response_Group": {"Include_Reference": True, "Include_Personal_Information": True}}
# serialized → Response_Data.Worker[0].Worker_Reference.ID[] (types WID, Employee_ID | Contingent_Worker_ID)
#              Response_Data.Worker[0].Worker_Data.Personal_Data.Name_Data.Legal_Name_Data.Name_Detail_Data.Formatted_Name
# Response_Data may be a list of blocks or a dict — normalise with ensure_list (pattern: tool.py:1311-1313).

# Get_Worker_Event_History
{"Worker_Reference": {"Employee_Reference" | "Contingent_Worker_Reference":
     {"Integration_ID_Reference": {"ID": {"_value_1": wid, "System_ID": "WD-WID"}}}},
 "Event_Date_Range_Data": {"Effective_From": datetime, "Effective_Through": datetime,
                           "Updated_From": datetime, "Updated_Through": datetime}}   # optional, pairs only
# serialized → Worker_Event_History_Data.Event_Data[]:
#   {Event_ID, Event_Type_Reference: {Event_Type_Name}, Description, Completed_DateTime, Effective_Date}
```

### Does NOT Exist
- ~~`WorkerType` accepting `worker_id_type="WID"`~~ — never tried there (`workers.py:175`); resolve WIDs here.
- ~~`Worker_Event_History_Get.Event_Type_Reference`~~ — no event-type request filter; filtering is client-side (TASK-4489).
- ~~`Integration_ID_ReferenceType`~~ — the zeep type is `External_Integration_ID_Reference_DataType`; you only build dicts.
- ~~`WD-EMPLID` fallback~~ — not verified live; do not add it (spec §7 gotchas).
- ~~`packages/ai-parrot-tools/tests/workday/conftest.py`~~ — none; fixtures are module-local.
- ~~`WorkdayTypeBase._paginate_soap_operation` for this op~~ — the operation is unpaged.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/worker_event_history.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/workday/test_worker_event_history.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/base.py#WorkdayTypeBase",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/workers.py#WorkerType._fetch_single_worker",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py#WorkdayService.call_operation",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py#WorkdayService.serialize_object",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/utils/utils.py#ensure_list",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/utils/utils.py#extract_by_type"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `resolve_worker_reference` takes the **service** (not a handler) so TASK-4489 can call it; read `max_retries`/`retry_delay` as parameters with the base defaults (3, 0.5) for non-invalid errors.
- Dates: accept `date | str`, normalise with `date.fromisoformat`; From → `datetime.combine(d, time.min)`, Through → `datetime.combine(d, time(23, 59, 59))` (spec §7 "Dates").
- `Updated_Through` "in the future" means `> date.today()`.
- Empty result → `pd.DataFrame(columns=list(WorkerEvent.model_fields))`, `self.parsed = []`.
- Log through `self._logger` / a module `logging.getLogger(__name__)`; never `print`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module from the block below — *why*: signatures are fixed by spec §3 M2 and TASK-4489 imports them.
2. Complete `resolve_worker_reference` by copying the loop shape from `workers.py:101-130` — *why*: spec §8 resolution 2 requires the same fault-text contract `WorkerType` relies on.
3. Complete `execute` — *why*: AC rows/sort/columns.
4. Write the tests with a `_FakeService` that records `(operation, kwargs)` and can raise `Fault` per id type — *why*: spec G6, no live tenant.

### `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/worker_event_history.py` (CREATE)
```python
"""Worker event history handler (FEAT-706, HR WSDL ``Get_Worker_Event_History``)."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, time
from typing import Any

import pandas as pd
from zeep.exceptions import Fault

from ..models.worker_event import ResolvedWorkerReference, WorkerEvent
from ..utils.utils import ensure_list, extract_by_type, first
from .base import WorkdayTypeBase

logger = logging.getLogger(__name__)

WORKER_ID_TYPES: tuple[str, ...] = ("WID", "Employee_ID", "Contingent_Worker_ID")
SYSTEM_ID_WID: str = "WD-WID"
INVALID_ID_FAULT: str = "Invalid ID value"  # verified: workers.py:115
_WID_RE = re.compile(r"^[0-9a-f]{32}$")


def candidate_worker_id_types(worker_id: str, worker_id_type: str | None = None) -> tuple[str, ...]:
    """Return the id types to try, in order.

    Explicit type → ``(type,)``; 32-char lowercase-hex id → ``("WID",)``; anything else →
    ``("Employee_ID", "Contingent_Worker_ID")``.

    Raises:
        ValueError: ``worker_id_type`` is given and not in ``WORKER_ID_TYPES``.
    """
    # FILL IN: the three branches above — bounded by spec §4 test_candidate_worker_id_types.


def build_event_history_worker_reference(ref: ResolvedWorkerReference) -> dict[str, Any]:
    """Build the ``Worker_Reference`` choice element for ``Worker_Event_History_Get``."""
    key = "Contingent_Worker_Reference" if ref.is_contingent else "Employee_Reference"
    return {key: {"Integration_ID_Reference": {"ID": {"_value_1": ref.wid, "System_ID": SYSTEM_ID_WID}}}}


def _as_date(value: date | str | None) -> date | None:
    """Normalise ``date | str | None`` (ISO ``YYYY-MM-DD``) to ``date | None``."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


def build_event_date_range(
    effective_from: date | str | None, effective_through: date | str | None,
    updated_from: date | str | None, updated_through: date | str | None,
) -> dict[str, datetime] | None:
    """Build ``Event_Date_Range_Data``; ``None`` when no bound is given.

    Raises:
        ValueError: a pair is half-set, ``From > Through``, or ``Updated_Through`` is after today.
    """
    # FILL IN: normalise with _as_date; validate both pairs; From at time.min, Through at time(23, 59, 59);
    #   keys Effective_From/Effective_Through/Updated_From/Updated_Through — bounded by AC "date-range validation".


async def resolve_worker_reference(
    service: Any, worker_id: str, worker_id_type: str | None = None,
    max_retries: int = 3, retry_delay: float = 0.5,
) -> ResolvedWorkerReference:
    """Resolve any worker identifier to its WID-based reference (one Get_Workers per candidate).

    Raises:
        LookupError: every candidate was rejected as an invalid id, or no worker came back.
        ValueError: unknown ``worker_id_type``.
    """
    # FILL IN: loop candidate_worker_id_types(...) copying workers.py:101-130 (Fault/Exception text containing
    #   INVALID_ID_FAULT → next candidate; other errors retried then re-raised); payload per §Contract shapes;
    #   serialize with service.serialize_object; take the first Worker across ensure_list(Response_Data) blocks;
    #   extract wid / Employee_ID / Contingent_Worker_ID with extract_by_type and Formatted_Name;
    #   no worker → LookupError; all rejected → LookupError(...) from the last fault.
```
(continued in the next block — same file)
```python
class WorkerEventHistoryType(WorkdayTypeBase):
    """Handler for ``get_worker_event_history`` (HR WSDL, ``Get_Worker_Event_History``)."""

    def _get_default_payload(self) -> dict[str, Any]:
        return {}

    async def execute(
        self, worker_id: str, worker_id_type: str | None = None,
        effective_from: date | str | None = None, effective_through: date | str | None = None,
        updated_from: date | str | None = None, updated_through: date | str | None = None,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Return one row per ``WorkerEvent`` sorted by ``(effective_date, completed_at)``."""
        date_range = build_event_date_range(effective_from, effective_through, updated_from, updated_through)
        ref = await resolve_worker_reference(
            self.service, worker_id, worker_id_type, self.max_retries, self.retry_delay,
        )
        request: dict[str, Any] = {"Worker_Reference": build_event_history_worker_reference(ref)}
        if date_range:
            request["Event_Date_Range_Data"] = date_range
        self._logger.info("Get_Worker_Event_History for %s (%s)", ref.wid, ref.formatted_name)
        raw = await self.service.call_operation(operation="Get_Worker_Event_History", **request)
        data = self.service.serialize_object(raw) if raw else {}
        # FILL IN: flatten Worker_Event_History_Data.Event_Data (ensure_list) into WorkerEvent(worker_wid=ref.wid, ...);
        #   sort by (effective_date or date.min, completed_at or datetime.min) — beware tz-aware vs naive datetimes;
        #   self.parsed = events; return a DataFrame of model_dump() rows with columns list(WorkerEvent.model_fields)
        #   (empty DataFrame with those columns when no events) — bounded by AC "rows sorted / columns".
```
**Why this shape**: date validation runs before any SOAP call (AC). The reference builder and
resolver are module functions so TASK-4489 can reuse them without instantiating this handler.
The resolver uses the service directly so retries do not depend on a handler instance.

### `packages/ai-parrot-tools/tests/workday/test_worker_event_history.py` (CREATE)
```python
"""FEAT-706 — worker event-history handler (fake service, no live tenant)."""
from datetime import date, datetime, timedelta

import pytest
from zeep.exceptions import Fault

from parrot_tools.interfaces.workday.handlers.worker_event_history import (
    WorkerEventHistoryType, build_event_date_range, build_event_history_worker_reference,
    candidate_worker_id_types, resolve_worker_reference,
)
from parrot_tools.interfaces.workday.models.worker_event import ResolvedWorkerReference, WorkerEvent

WID = "0123456789abcdef0123456789abcdef"  # synthetic — never a real tenant id


def _ref(**ids):
    return {"ID": [{"type": t, "_value_1": v} for t, v in ids.items()], "Descriptor": None}


# FILL IN: WORKER_RESPONSE (Response_Data.Worker[0] with Worker_Reference=_ref(WID=WID, Employee_ID="100001")
#   and Formatted_Name "Jane Doe"); EVENT_HISTORY_RESPONSE with 6 unsorted Event_Data
#   (Hire, Enter Time, Change Job ×2, Change Organization Assignments for Worker, Edit Position).
# FILL IN: class _FakeService(responses_by_operation, faults_by_id_type) recording calls; serialize_object returns obj.
# FILL IN: tests from spec §4 M2 rows: test_candidate_worker_id_types, test_build_event_history_worker_reference_employee,
#   _contingent, test_build_event_date_range_pairs, test_resolve_worker_reference_by_wid, _by_employee_id,
#   test_resolve_worker_reference_contingent_fallback, test_resolve_worker_reference_not_found,
#   test_event_history_execute_rows_sorted, test_event_history_passes_date_range,
#   plus test_date_range_error_makes_no_call (ValueError raised with zero recorded calls).
```

### FILL IN checklist
- [ ] `candidate_worker_id_types` — three branches; bounded by spec §4 row.
- [ ] `build_event_date_range` — pair / order / future validation; bounded by AC "date-range validation".
- [ ] `resolve_worker_reference` — copied fallback loop + extraction; bounded by AC "resolve_worker_reference".
- [ ] `WorkerEventHistoryType.execute` — flatten, sort, DataFrame; bounded by AC "rows sorted".
- [ ] Test fixtures, `_FakeService` and the eleven tests.

---

## Acceptance Criteria

- [ ] `resolve_worker_reference` sends `ID.type` equal to the explicit type when given; otherwise `WID` for a 32-hex id, else `Employee_ID` and — only after a `Fault` containing `"Invalid ID value"` — `Contingent_Worker_ID`; returns WID, Employee/Contingent ID and formatted name; raises `LookupError` when every candidate is rejected or no worker is returned; any other `Fault` propagates.
- [ ] `Get_Worker_Event_History` requests use `Employee_Reference` (or `Contingent_Worker_Reference`) → `Integration_ID_Reference.ID` with `_value_1=<wid>`, `System_ID="WD-WID"`.
- [ ] Date-range validation raises `ValueError` client-side for a half-set pair, `From > Through`, or `Updated_Through` in the future; no SOAP call is made.
- [ ] `execute` returns rows sorted by `(effective_date, completed_at)` with columns exactly `WorkerEvent.model_fields`; `parsed` is `list[WorkerEvent]`.
- [ ] `Event_Date_Range_Data` is sent only when a bound is given.
- [ ] `ruff check` passes; no `requests`/`httpx` imports.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/workday/test_worker_event_history.py -q`
- `pytest packages/ai-parrot-tools/tests/workday/test_worker_id_type_fallback.py -q`

---

## Test Specification

See the test block in the Implementation Blueprint and spec §4 (M2 rows).

---

## Agent Instructions

1. Work in the feature worktree; TASK-4487 must be `done` in the per-spec index.
2. Verify the Codebase Contract (re-read `workers.py:87-130` before copying the loop).
3. Mark `in-progress`, implement from the blueprint, complete every `FILL IN`.
4. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`.
5. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4488 workday-worker-event-history-and-job-changes verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
