# TASK-2140: Clock-event write surface — delete, location/cost-centre override, GPS

**Feature**: FEAT-415 — Workday Interfaces Homologation (flowtask → ai-parrot)
**Spec**: `sdd/specs/workday-interfaces-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of the spec. flowtask's `ClockEvent` model carries
six fields ai-parrot's lacks (+52 lines), and `PutTimeClockEventsType`
emits them (+14 lines). Today ai-parrot can only *add* a punch — it cannot
delete one, cannot override the worked location or cost centre, and cannot
carry GPS captured by a mobile client.

Two subtleties that must be preserved exactly:

1. **`location` is the override.** Workday derives a worker's default
   location from their position; the `Location` field on the clock event is
   the location they *actually* worked at, surfaced on reports as
   `Override_Location` vs `Default_Location`. There is **no separate
   override field** — this single field is the override (verified in the
   WSDL + `Put_Time_Clock_Events` docs v46.1).
2. **GPS is never sent.** The Time Tracking WSDL has **no geo field in any
   version** (verified v27.1 → v46.1). `latitude`/`longitude` are carried on
   the model for the *calling API* to persist in its own store, and must
   never appear in the SOAP payload.

---

## Scope

- Add to `ClockEvent`:
  - `delete: bool = False` — soft-delete via the same `Put_Time_Clock_Events`
    operation (emits `Delete_Time_Clock_Event=Y`; the block stays visible
    with `Is_Deleted=true` on read)
  - `location: Optional[str] = None` — organisational location OVERRIDE
    (plain `xsd:string`, NOT geo coordinates)
  - `cost_center: Optional[str] = None` — cost-centre override
  - `override_rate: Optional[float] = Field(default=None, ge=0)` —
    **presence-based**: a value including `0` is sent, `None` omits it
  - `latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)`
  - `longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)`
- Add the `_delete_requires_event_id` model validator (`mode="after"`):
  `delete=True` without `time_clock_event_id` raises — you can only delete
  an event you can identify.
- Update the pydantic import (currently `BaseModel` only) to include
  `Field` and `model_validator`.
- Emit the new fields in `PutTimeClockEventsType.build_request`:
  `Delete_Time_Clock_Event`, `Location`, `Cost_Center`, `Override_Rate`.
- **Do NOT emit** `latitude`/`longitude`.
- Update the `time_clock_event_id` docstring to note it is required when
  `delete=True`.
- Write unit tests.

**NOT in scope**:
- `import_time_clock_events` / `import_reported_time_blocks` handlers.
- `ReportedTimeBlock` / `ClockEventResult` models.
- Exposing delete as an agent-facing tool.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/clock_event.py` | MODIFY | Six new fields + validator + import update |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/put_time_clock_events.py` | MODIFY | Emit the new fields in `build_request` |
| `packages/ai-parrot-tools/tests/workday/test_clock_event_write_surface.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/clock_event.py
from __future__ import annotations              # line 9
from datetime import datetime                   # line 11
from typing import Optional, Literal            # line 12
from pydantic import BaseModel                  # line 14 — MUST BECOME: BaseModel, Field, model_validator
```

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/put_time_clock_events.py
from __future__ import annotations                                          # line 19
from datetime import datetime, timezone                                     # line 21
from typing import Any, List                                                # line 22
import pandas as pd                                                         # line 24
from parrot_tools.interfaces.workday.handlers.base import WorkdayWriteTypeBase   # line 26
from parrot_tools.interfaces.workday.models.clock_event import ClockEvent, ClockEventResult  # line 27
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/clock_event.py
class ClockEvent(BaseModel):                     # line 34
    employee_id: str                             # line 56
    event_datetime: datetime                     # line 57
    clock_event_type: ClockEventType             # line 58
    time_clock_event_id: Optional[str] = None    # line 59  <-- required when delete=True
    position_id: Optional[str] = None            # line 60
    time_zone: Optional[str] = None              # line 61
    time_entry_code: Optional[str] = None        # line 62
    auto_submit: bool = False                    # line 63
    comment: Optional[str] = None                # line 64
    class Config:
        extra = "allow"

class ReportedTimeBlock(BaseModel):              # line 74  — NOT in scope
class ClockEventResult(BaseModel):               # line 103 — NOT in scope
```

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/put_time_clock_events.py
class PutTimeClockEventsType(WorkdayWriteTypeBase):                              # line 38
    def _operation_name(self) -> str:                                            # line 46
    def build_request(self, events: List[ClockEvent], **kwargs) -> dict:         # line 49  <-- EMIT HERE
    def parse_ack(self, raw: Any) -> pd.DataFrame:                               # line 92
    async def execute(self, events: List[ClockEvent], **kwargs) -> pd.DataFrame: # line 111
```

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/base.py
class WorkdayWriteTypeBase(WorkdayTypeBase):     # line 178
    def build_request(self, **kwargs) -> Dict[str, Any]:  # line 212
    def parse_ack(self, raw: Any) -> Any:                 # line 227
    async def execute(self, **kwargs) -> Any:             # line 243
```

### Reference Source (flowtask — READ ONLY)

- `../flowtask/flowtask/interfaces/workday/models/clock_event.py` (175 lines vs 124 here)
- `../flowtask/flowtask/interfaces/workday/handlers/put_time_clock_events.py` (192 vs 178)

The flowtask emission block reads (adapt, do not blind-copy):
```python
if ev.delete:
    item["Delete_Time_Clock_Event"] = True
if ev.location:
    item["Location"] = ev.location
if ev.cost_center:
    item["Cost_Center"] = ev.cost_center
if ev.override_rate is not None:          # presence-based: 0 IS sent
    item["Override_Rate"] = ev.override_rate
# ev.latitude / ev.longitude intentionally NOT emitted
```

### Does NOT Exist

- ~~`ClockEvent.delete`~~ / ~~`.location`~~ / ~~`.cost_center`~~ / ~~`.latitude`~~ / ~~`.longitude`~~ / ~~`.override_rate`~~ — none exist yet
- ~~`ClockEvent._delete_requires_event_id`~~ — validator to be added
- ~~`Field` / `model_validator` in clock_event.py's current import~~ — only `BaseModel` is imported (line 14)
- ~~an `Override_Location` field on the Workday clock event~~ — there is NO separate override field; `Location` **is** the override
- ~~any geo/GPS field in the Time Tracking WSDL~~ — none exists in any version v27.1→v46.1. Never emit lat/lon.
- ~~a hard-delete operation~~ — `Delete_Time_Clock_Event` is a **soft** delete; the block stays visible with `Is_Deleted=true`

---

## Implementation Notes

### Key Constraints
- `override_rate` is **presence-based**, not truthiness-based: `0` must be sent, `None` must be omitted. `if ev.override_rate:` would be a bug — use `is not None`.
- `delete`, `location`, `cost_center` use truthiness in flowtask (`if ev.delete:`) — preserve that behaviour.
- The validator must raise with a message explaining that a delete needs the `Time_Clock_Event_ID`.
- GPS range validation via `Field(ge=..., le=...)`, but never serialised.
- Keep `class Config: extra = "allow"`.
- Google-style docstrings + strict type hints.

### References in Codebase
- `packages/ai-parrot-tools/tests/workday/test_request_time_off.py` — an existing write-handler test in this repo; follow its shape
- `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/base.py:212` — the `build_request` contract

---

## Acceptance Criteria

- [ ] All six new fields exist on `ClockEvent` with the documented types/bounds
- [ ] `ClockEvent(delete=True)` without `time_clock_event_id` raises with an explicit message
- [ ] `Delete_Time_Clock_Event`, `Location`, `Cost_Center`, `Override_Rate` appear in the payload when set
- [ ] `override_rate=0` IS emitted; `override_rate=None` is omitted
- [ ] `latitude`/`longitude` NEVER appear in the SOAP payload, even when set
- [ ] Out-of-range lat/lon are rejected by validation
- [ ] Existing `ClockEvent` construction (only the pre-existing fields) still works unchanged
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/workday/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/clock_event.py packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/put_time_clock_events.py`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/workday/test_clock_event_write_surface.py
import pytest
from parrot_tools.interfaces.workday.models.clock_event import ClockEvent


class TestClockEventModel:
    def test_delete_requires_event_id(self):
        with pytest.raises(ValueError, match="time_clock_event_id"):
            ClockEvent(employee_id="1", event_datetime=..., clock_event_type="In", delete=True)

    def test_delete_with_event_id_is_valid(self):
        ...

    @pytest.mark.parametrize("lat,lon", [(91.0, 0.0), (0.0, 181.0), (-91.0, 0.0)])
    def test_gps_out_of_range_rejected(self, lat, lon):
        ...

    def test_backwards_compatible_construction(self):
        """Pre-existing fields alone still construct a valid ClockEvent."""


class TestPayloadEmission:
    def test_delete_flag_emitted(self):
        ...

    def test_location_and_cost_center_emitted(self):
        ...

    def test_override_rate_zero_is_sent(self):
        """Presence-based: 0 must be emitted, not skipped as falsy."""

    def test_override_rate_none_is_omitted(self):
        ...

    def test_gps_never_serialised(self):
        """lat/lon set → absent from the payload entirely."""
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/workday-interfaces-homologation.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-2140-workday-clock-event-write-surface.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
