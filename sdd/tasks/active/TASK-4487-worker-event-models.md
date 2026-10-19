# TASK-4487: Worker-event Pydantic models

**Feature**: FEAT-706 — Workday Worker Event History and Job Changes
**Spec**: `sdd/specs/workday-worker-event-history-and-job-changes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Every other task of FEAT-706 builds on these typed rows: the
event-history handler (TASK-4488) emits `WorkerEvent`, the job-changes handler
(TASK-4489) emits `JobChange` built from `JobSnapshot` + `FieldChange`, and both
share `ResolvedWorkerReference`. The two event-type tuples drive the job-change
filter, including the opt-in compensation widening (spec G7, §8 resolution 1).

---

## Scope

- Create `models/worker_event.py` with `ResolvedWorkerReference`, `WorkerEvent`,
  `JobSnapshot`, `FieldChange`, `JobChange` exactly as spec §2 "Data Models", plus the
  module constants `JOB_CHANGE_EVENT_TYPES` and `COMPENSATION_EVENT_TYPES` (§3 M1).
- Export the five model classes from `models/__init__.py` (import + `__all__`).
- Write `test_worker_event_models.py` covering defaults, `is_contingent`, `DIFF_EXCLUDE`,
  the two tuples, and the nested `JobChange` round-trip through `model_dump()`.

**NOT in scope**: handlers, diffing logic (`diff_snapshots` lives in TASK-4489), service
registration (`_OPERATION_MODEL_MAP`, TASK-4490), the tuples in `models/__init__.py`
(they are imported from `models.worker_event` directly).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/worker_event.py` | CREATE | Five models + two event-type tuples |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/__init__.py` | MODIFY | Import and export the five models |
| `packages/ai-parrot-tools/tests/workday/test_worker_event_models.py` | CREATE | Model unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field   # pattern verified: models/worker.py:3
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/__init__.py
from .clock_event import ClockEvent, ClockEventResult, ClockEventType, ReportedTimeBlock   # line 15 (last import)
__all__ = [ ... "ReportedTimeBlock", ]                                                    # line 36 (last entry), list closes at 37
```

### Does NOT Exist
- ~~`models/worker_event.py`~~ — created by this task.
- ~~`JobSnapshot.diff()`~~ / ~~`JobChange.from_snapshots()`~~ — no model methods beyond `ResolvedWorkerReference.is_contingent`; diffing is a TASK-4489 function.
- ~~`parrot_tools.interfaces.workday.models.base`~~ — models subclass `pydantic.BaseModel` directly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/worker_event.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/workday/test_worker_event_models.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Pydantic v2 only; no validators beyond type coercion (spec §3 delegation table).
- `DIFF_EXCLUDE` is a `ClassVar` so it is not a model field — it must not appear in `model_fields`.
- `compensation_elements` is `Optional[list[dict[str, Any]]]`; each dict carries only `plan`, `element`, `amount`, `currency`, `frequency` (filled by TASK-4489).
- Google-style docstrings, 120-column lines.

---

## Implementation Blueprint

### Steps (in order)
1. Write `worker_event.py` from the block below and complete the `JobSnapshot` field list from spec §2 "Data Models" verbatim — *why*: TASK-4489 maps parser keys onto these exact names and the tests assert them.
2. Add the two lines to `models/__init__.py` — *why*: TASK-4490's `service.py` and outside callers import from the package.
3. Write the tests and run the Validation Commands — *why*: AC.

### `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/worker_event.py` (CREATE)
```python
"""Typed rows for Workday worker event history and job changes (FEAT-706)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, ClassVar, Literal, Optional

from pydantic import BaseModel, Field

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


class ResolvedWorkerReference(BaseModel):
    """Identifiers of one worker as returned by Get_Workers Include_Reference."""

    wid: str
    employee_id: Optional[str] = None
    contingent_worker_id: Optional[str] = None
    formatted_name: Optional[str] = None

    @property
    def is_contingent(self) -> bool:
        """True when the worker has a Contingent_Worker_ID and no Employee_ID."""
        return bool(self.contingent_worker_id) and not self.employee_id


class WorkerEvent(BaseModel):
    """One Event_Data entry of Worker_Event_History."""

    worker_wid: str
    event_id: str
    event_type: Optional[str] = None
    description: Optional[str] = None
    effective_date: Optional[date] = None
    completed_at: Optional[datetime] = None


class JobSnapshot(BaseModel):
    """Worker job + organization data (and, opt-in, compensation) as of one effective date."""

    as_of: date
    # FILL IN: every remaining field of spec §2 "Data Models" JobSnapshot, verbatim, in order —
    #   position_id … hire_date, then the eight compensation fields wage … compensation_elements.
    #   All Optional[...] = None. Bounded by AC "parse_job_snapshot fields" (TASK-4489 maps onto these names).

    DIFF_EXCLUDE: ClassVar[frozenset[str]] = frozenset({"as_of"})


class FieldChange(BaseModel):
    """One field whose value differs between two snapshots."""

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
    includes_compensation: bool = False
```
**Why this shape**: names, types and defaults are fixed by spec §2 and consumed unchanged by
TASK-4488/4489/4490/4491. `ClassVar` keeps `DIFF_EXCLUDE` out of `model_fields`, which the
event-history DataFrame columns and the diff both iterate.

### `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .clock_event import ClockEvent, ClockEventResult, ClockEventType, ReportedTimeBlock' models/__init__.py)
# AFTER — insert below `from .clock_event import ClockEvent, ClockEventResult, ClockEventType, ReportedTimeBlock` (verified: models/__init__.py:15)
from .worker_event import FieldChange, JobChange, JobSnapshot, ResolvedWorkerReference, WorkerEvent

# occurrences: 1 (verified: grep -c '    "ReportedTimeBlock",' models/__init__.py)
# AFTER — insert below `    "ReportedTimeBlock",` (verified: models/__init__.py:36)
    "FieldChange",
    "JobChange",
    "JobSnapshot",
    "ResolvedWorkerReference",
    "WorkerEvent",
```
**Why**: the package is the public import surface; the tuples stay module-level in `worker_event.py`.

### `packages/ai-parrot-tools/tests/workday/test_worker_event_models.py` (CREATE)
```python
"""FEAT-706 — worker-event models."""
from datetime import date

from parrot_tools.interfaces.workday.models import (
    FieldChange, JobChange, JobSnapshot, ResolvedWorkerReference, WorkerEvent,
)
from parrot_tools.interfaces.workday.models.worker_event import (
    COMPENSATION_EVENT_TYPES, JOB_CHANGE_EVENT_TYPES,
)


def test_event_type_tuples():
    # FILL IN: assert the exact four JOB_CHANGE and two COMPENSATION names, and no overlap.
    ...


def test_resolved_reference_is_contingent():
    # FILL IN: employee only → False; contingent only → True; both → False.
    ...


def test_job_snapshot_defaults_and_diff_exclude():
    # FILL IN: JobSnapshot(as_of=date(2026, 6, 8)) → every other field None;
    #   "DIFF_EXCLUDE" not in JobSnapshot.model_fields; "as_of" in JobSnapshot.DIFF_EXCLUDE;
    #   the eight compensation fields exist in model_fields.
    ...


def test_job_change_nested_roundtrip():
    # FILL IN: build JobChange(kind="change", before=JobSnapshot(...), after=JobSnapshot(...),
    #   changes=[FieldChange(field="position_id", before="A", after="B")]); dump with model_dump();
    #   JobChange(**dumped) == original; includes_compensation defaults False.
    ...


def test_worker_event_coerces_iso_strings():
    # FILL IN: WorkerEvent(worker_wid="w", event_id="e", effective_date="2026-06-08",
    #   completed_at="2026-06-08T10:00:00") → date / datetime instances.
    ...
```
**Why**: covers the contract other tasks rely on; the round-trip mirrors what `fetch_models` does in TASK-4490.

### FILL IN checklist
- [ ] `worker_event.py::JobSnapshot` — the full field list from spec §2; bounded by names exactly as in the spec.
- [ ] `test_worker_event_models.py` — the five test bodies; bounded by AC below.

---

## Acceptance Criteria

- [ ] `from parrot_tools.interfaces.workday.models import FieldChange, JobChange, JobSnapshot, ResolvedWorkerReference, WorkerEvent` works.
- [ ] `JobSnapshot.model_fields` equals the spec §2 field list (including the eight compensation fields) and excludes `DIFF_EXCLUDE`.
- [ ] `JOB_CHANGE_EVENT_TYPES` / `COMPENSATION_EVENT_TYPES` hold exactly the names in spec §3 M1.
- [ ] A `JobChange` with nested `before`/`after`/`changes` survives `model_dump()` → constructor unchanged.
- [ ] `ruff check` passes on the touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/workday/test_worker_event_models.py -q`

---

## Test Specification

See the test block in the Implementation Blueprint.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug workday-worker-event-history-and-job-changes --feature-id FEAT-706`).
2. Read the spec; this task has no dependencies.
3. Verify the Codebase Contract anchors before editing.
4. Mark `in-progress` in `sdd/tasks/index/workday-worker-event-history-and-job-changes.json`.
5. Implement from the blueprint; complete every `FILL IN`.
6. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4487 workday-worker-event-history-and-job-changes verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
