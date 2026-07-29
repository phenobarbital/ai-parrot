---
type: Wiki Overview
title: 'TASK-1508: `request_my_time_off` write handler (NEW operation)'
id: doc:sdd-tasks-completed-task-1508-request-time-off-write-handler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 4**. No time-off WRITE operation exists in the vendored
relates_to:
- concept: mod:parrot_tools.interfaces.workday.service
  rel: mentions
- concept: mod:parrot_tools.workday.tool
  rel: mentions
---

# TASK-1508: `request_my_time_off` write handler (NEW operation)

**Feature**: FEAT-230 — Workday Composable Interface + Toolkit Homologation
**Spec**: `sdd/specs/workday-tooling-composable-interface.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1507
**Assigned-to**: unassigned

---

## Context

Implements **Module 4**. No time-off WRITE operation exists in the vendored
source (verified). This task builds a net-new Workday Absence Management write
handler (e.g. `Request_Time_Off` / `Enter_Time_Off`) by subclassing the existing
`WorkdayWriteTypeBase`, registers it in the service, and exposes the
`request_my_time_off` toolkit tool guarded by a dry-run/confirm flag.

---

## Scope

- CREATE `handlers/time_off_request.py` subclassing `WorkdayWriteTypeBase`,
  implementing `_operation_name()`, `build_request()`, `parse_ack()`.
- REGISTER the new operation_type in `WorkdayService.__init__`'s `_type_handlers`
  (service.py:218, mirroring the FEAT-027 write entries at service.py:240-242).
- ADD a `_WSDL_MAP` entry → `WORKDAY_WSDL_ABSENCE_MANAGEMENT` (config.py:54).
- ADD the `request_my_time_off` tool + `RequestTimeOffInput` to `WorkdayToolkit`,
  delegating to `WorkdayComposable.call_operation` (or a public service wrapper).
- Guard with a dry-run/confirm flag; mocked-only unit tests; target impl tenant first.

**Unresolved (decide here):** the exact Workday op name + payload schema
(`Request_Time_Off` vs `Enter_Time_Off`) — verify against the Absence Management
WSDL before coding (spec §8).

**NOT in scope**: `get_my_time_off_eligibility` (TASK-1509); real submissions.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/time_off_request.py` | CREATE | `WorkdayWriteTypeBase` subclass for the write op |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py` | MODIFY | Register handler in `_type_handlers` (+ optional public wrapper) |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py` | MODIFY | `_WSDL_MAP` entry → Absence Management |
| `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py` | MODIFY | `request_my_time_off` tool + `RequestTimeOffInput` |
| `packages/ai-parrot-tools/tests/workday/test_request_time_off.py` | CREATE | Write-payload + dry-run guard tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Within the vendored package (relative):
from .base import WorkdayWriteTypeBase     # handlers/base.py:178
# In tool.py:
from ..interfaces.workday import WorkdayService as WorkdayComposable
from pydantic import BaseModel, Field
```

### Existing Signatures to Use
```python
# handlers/base.py — write base (subclass this; do NOT hand-roll):
class WorkdayWriteTypeBase(WorkdayTypeBase):            # line 178
    def _operation_name(self) -> str: ...              # line 202 (override: SOAP op name)
    def build_request(self, **kwargs) -> dict: ...     # line 212 (override: payload dict)
    def parse_ack(self, raw) -> Any: ...               # line 227 (override: ack -> per-row DataFrame)
    async def execute(self, **kwargs) -> Any: ...      # line 243 (template: build->call_operation->parse, with retry)

# Reference write handlers (FEAT-027 — single-call writes):
#   handlers/put_time_clock_events.py        ("Put_Time_Clock_Events")
#   handlers/import_time_clock_events.py     ("Import_Time_Clock_Events")
#   handlers/import_reported_time_blocks.py  ("Import_Reported_Time_Blocks")

# service.py — register here:
self._type_handlers: dict = { ... }                    # line 218 (add new op key here)
#   existing FEAT-027 write entries at lines 240-242 show the exact registration shape
async def call_operation(self, operation, **kwargs): ...  # line 251
async def put_time_clock_events(self, events, *, auto_submit=None): ... # line 364 (public-wrapper pattern)

# config.py — WSDL routing:
_WSDL_MAP: dict                                        # line 54 (add op -> WORKDAY_WSDL_ABSENCE_MANAGEMENT, like get_time_off_balances at line 69)

# spec input schema (parrot_tools/workday/tool.py):
class RequestTimeOffInput(BaseModel):
    worker_id: str; start_date: str; end_date: str; time_off_type: str
    daily_quantity: float = 8.0; comment: Optional[str] = None
```

### Does NOT Exist
- ~~`Request_Time_Off` / `Enter_Time_Off` / `Submit_Time_Off` handler in the source~~ — NONE exists (grep empty); must be built here.
- ~~a registered `request_time_off` operation_type in `_type_handlers`~~ — must be added.
- ~~an absence-management write op in `_WSDL_MAP`~~ — only the read `get_time_off_balances` is mapped; add the write op.

---

## Implementation Notes

### Pattern to Follow
```python
# handlers/time_off_request.py
from .base import WorkdayWriteTypeBase

class RequestTimeOffType(WorkdayWriteTypeBase):
    def _operation_name(self) -> str:
        return "Request_Time_Off"   # CONFIRM against Absence Management WSDL

    def build_request(self, *, worker_id, start_date, end_date,
                      time_off_type, daily_quantity=8.0, comment=None) -> dict:
        # build the SOAP request body dict
        ...

    def parse_ack(self, raw) -> "pd.DataFrame":
        # one row: {submitted, event_id, error}
        ...
```

### Key Constraints
- Subclass `WorkdayWriteTypeBase` — do NOT build a bespoke handler.
- `request_my_time_off` MUST honor a dry-run/confirm flag (default safe).
- Unit tests mock `call_operation` — NEVER submit to a real tenant.
- Convert the ack DataFrame to JSON at the tool boundary (no DataFrame return).

### References in Codebase
- `handlers/put_time_clock_events.py` — closest reference write handler.
- `service.py:240-242` — registration shape; `service.py:364` — public wrapper.

---

## Acceptance Criteria

- [ ] `handlers/time_off_request.py` subclasses `WorkdayWriteTypeBase` with the 3 overrides.
- [ ] New op registered in `_type_handlers` and routed in `_WSDL_MAP` (Absence Management).
- [ ] `request_my_time_off` tool present, public, async, with `RequestTimeOffInput`.
- [ ] Tool issues a Workday write op (verified via mocked `call_operation`).
- [ ] Dry-run/confirm guard prevents real submission by default.
- [ ] Return is JSON-serializable (no DataFrame).
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/workday/test_request_time_off.py -v`
- [ ] No linting errors.

---

## Test Specification
```python
# packages/ai-parrot-tools/tests/workday/test_request_time_off.py
import pytest
from parrot_tools.workday.tool import WorkdayToolkit


@pytest.mark.asyncio
async def test_request_my_time_off_builds_write_payload(monkeypatch):
    """Builds the write payload and calls call_operation; honors dry-run."""
    captured = {}

    async def fake_call_operation(self, operation, **kwargs):
        captured["operation"] = operation
        captured["payload"] = kwargs
        return {"ack": "ok"}

    monkeypatch.setattr(
        "parrot_tools.interfaces.workday.service.WorkdayService.call_operation",
        fake_call_operation,
    )
    # dry_run=True must NOT call call_operation; confirm=True must.
    ...
```

---

## Agent Instructions

1. **Read the spec** (esp. §3 Module 4, §6, §8 unresolved op name).
2. **Check dependencies** — TASK-1507 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm `WorkdayWriteTypeBase` overrides + registry shape.
4. **Update status** → `"in-progress"`.
5. **Implement** the write handler + tool.
6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`; **update index** → `"done"`.
8. **Fill in the Completion Note** (record the chosen Workday op name + payload).

---

## Completion Note

**Completed by**: Claude Sonnet 4.6
**Date**: 2026-06-08
**SOAP op used**: `Request_Time_Off` (Absence Management WSDL)
**Notes**: Created `handlers/time_off_request.py` (RequestTimeOffType subclassing
WorkdayWriteTypeBase). build_request() assembles Time_Off_Request_Data with
Worker_Reference, Time_Off_Request_Line_Data (type ref, dates, daily_quantity),
and optional Comment. parse_ack() returns one-row status DataFrame. Registered in
handlers/__init__.py, service.py (_type_handlers), config.py (_WSDL_ROUTING →
WORKDAY_WSDL_ABSENCE_MANAGEMENT). Added RequestTimeOffInput schema and
request_my_time_off tool to WorkdayToolkit — defaults to dry_run=True, delegates
to composable.fetch("request_time_off") when False. 11/11 tests pass; ruff clean.

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
