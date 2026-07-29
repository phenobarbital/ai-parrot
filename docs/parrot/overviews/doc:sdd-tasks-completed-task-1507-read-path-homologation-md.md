---
type: Wiki Overview
title: 'TASK-1507: Read-path homologation — 9 agent-facing tools'
id: doc:sdd-tasks-completed-task-1507-read-path-homologation-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 3**. Adds the 9 read/utility homologated methods to
relates_to:
- concept: mod:parrot_tools.workday.tool
  rel: mentions
---

# TASK-1507: Read-path homologation — 9 agent-facing tools

**Feature**: FEAT-230 — Workday Composable Interface + Toolkit Homologation
**Spec**: `sdd/specs/workday-tooling-composable-interface.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1506
**Assigned-to**: unassigned

---

## Context

Implements **Module 3**. Adds the 9 read/utility homologated methods to
`WorkdayToolkit` as public async tools, each delegating to an EXISTING composable
operation (verified to exist in the source). Each becomes a tool automatically via
`AbstractToolkit.get_tools()` (public + coroutine). Identity is always an explicit
`worker_id` parameter (Non-Goal: session-derived identity).

The 9 methods (2 net-new write/eligibility ops are TASK-1508/1509):
`find_employee_id_by_name`, `get_current_user_info`, `get_more_employee_data`,
`get_personal_information`, `get_direct_reports`, `get_time_off_balance`,
`get_current_user_time_off_balance`, `get_current_user_time_off_history`,
`get_today_date_and_day_of_week`.

---

## Scope

- Add the 9 public async methods to `WorkdayToolkit`, each with a clear LLM-facing
  docstring and `@tool_schema(InputModel)` where it takes structured params.
- Delegate to existing composable ops:
  - `find_employee_id_by_name` / `get_current_user_info` / `get_more_employee_data` /
    `get_personal_information` / `get_direct_reports` → `get_workers` (handler `workers.py`).
  - `get_time_off_balance` / `get_current_user_time_off_balance` →
    `get_time_off_balances` (handler `time_off_balances.py`).
  - `get_current_user_time_off_history` → `get_time_requests` (handler `time_requests.py`).
  - `get_today_date_and_day_of_week` → local `datetime` (NO SOAP).
- Return JSON-serializable `dict` / `list[dict]` (`fetch_models()`+`model_dump()`
  preferred; `fetch()`+`to_dict()` fallback).
- Add input schema Pydantic models and `METHOD_TO_SERVICE_MAP` entries for the new
  method names (map to the existing `WorkdayService(str, Enum)` categories).

**NOT in scope**: `request_my_time_off` (TASK-1508), `get_my_time_off_eligibility`
(TASK-1509); refactoring existing `wd_*` (done in TASK-1506).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py` | MODIFY | Add 9 homologated tools + input schemas + METHOD_TO_SERVICE_MAP entries |
| `packages/ai-parrot-tools/tests/workday/test_homologation_read.py` | CREATE | Per-method + get_tools exposure tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ..decorators import tool_schema
from ..interfaces.workday import WorkdayService as WorkdayComposable
from pydantic import BaseModel, Field
```

### Existing Signatures to Use
```python
# Composable (parrot_tools/interfaces/workday/service.py — from TASK-1505):
async def fetch(self, operation_type, **params) -> pd.DataFrame   # line 266
async def fetch_models(self, operation_type, **params) -> list    # line 291

# Verified composable operation_type keys (service.py:218 _type_handlers):
#   "get_workers", "get_time_off_balances", "get_time_requests"  (all EXIST)
# Verified models mapped (service.py:90 _OPERATION_MODEL_MAP):
#   "get_workers"->Worker, "get_time_off_balances"->TimeOffBalance, "get_time_requests"->TimeRequest

# Toolkit hooks:
class WorkdayToolkit(AbstractToolkit):    # tool.py:472
    def _flatten_entries(self, ...): ...  # tool.py:1706
METHOD_TO_SERVICE_MAP: dict               # tool.py:113 (extend with new method names)
class WorkdayService(str, Enum):          # tool.py:99  HUMAN_RESOURCES / ABSENCE_MANAGEMENT

# AbstractToolkit.get_tools (parrot/tools/toolkit.py:337): a method becomes a tool iff
# public (no '_') AND inspect.iscoroutinefunction; name + docstring drive the LLM spec.
```

### Operation → method mapping (verified in source handlers)
| Tool | operation_type | Source handler | Status |
|---|---|---|---|
| `find_employee_id_by_name` | `get_workers` (name criteria) | handlers/workers.py | exists |
| `get_current_user_info` | `get_workers` | handlers/workers.py | exists |
| `get_more_employee_data` | `get_workers` (extended groups) | handlers/workers.py | exists |
| `get_personal_information` | `get_workers` (`Include_Personal_Information: True`, workers.py:74) | handlers/workers.py | exists |
| `get_direct_reports` | `get_workers` (manager filter) | handlers/workers.py | exists |
| `get_time_off_balance` | `get_time_off_balances` | handlers/time_off_balances.py:13 | exists |
| `get_current_user_time_off_balance` | `get_time_off_balances` | handlers/time_off_balances.py:13 | exists |
| `get_current_user_time_off_history` | `get_time_requests` | handlers/time_requests.py:12 | exists |
| `get_today_date_and_day_of_week` | — (local `datetime`) | — | trivial |

### Does NOT Exist
- ~~`get_my_time_off_eligibility`, `request_my_time_off`~~ as read ops here — NOT in this task (TASK-1508/1509).
- ~~a `get_workers` variant that filters by manager as a separate op~~ — same `get_workers` op with a manager filter param.
- ~~session/`UserInfo`-derived current user~~ — identity is an explicit `worker_id` param.

---

## Implementation Notes

### Pattern to Follow
```python
class GetWorkerByNameInput(BaseModel):
    name: str = Field(..., description="Full or partial worker name to search")

class WorkdayToolkit(AbstractToolkit):
    @tool_schema(GetWorkerByNameInput)
    async def find_employee_id_by_name(self, name: str) -> list[dict]:
        """Find Workday employee IDs matching a worker name. Returns id+name rows."""
        svc = WorkdayComposable(operation_type="get_workers")
        await svc.start()
        models = await svc.fetch_models("get_workers", name=name)
        return [m.model_dump() for m in models]

    async def get_today_date_and_day_of_week(self) -> dict:
        """Return today's ISO date and weekday name (no Workday call)."""
        from datetime import date
        d = date.today()
        return {"date": d.isoformat(), "day_of_week": d.strftime("%A")}
```

### Key Constraints
- Every method: public, async, non-empty docstring (drives the LLM tool spec).
- `get_today_date_and_day_of_week` must NOT make a SOAP call.
- All returns JSON-serializable.

### References in Codebase
- `flowtask/interfaces/workday/handlers/workers.py:74` — personal-information flag.
- `parrot_tools/workday/tool.py:1706` — `_flatten_entries`.

---

## Acceptance Criteria

- [ ] All 9 methods present, public, async, with non-empty docstrings.
- [ ] `WorkdayToolkit().get_tools()` includes all 9 method names (plus TASK-1508/1509 → 11 total once those land).
- [ ] `find_employee_id_by_name` returns a name→id list (mocked `get_workers`).
- [ ] `get_today_date_and_day_of_week` returns date+weekday with NO SOAP call.
- [ ] Every return is JSON-serializable (`json.dumps` succeeds); never a DataFrame.
- [ ] `METHOD_TO_SERVICE_MAP` extended for the new method names.
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/workday/test_homologation_read.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/workday/tool.py`

---

## Test Specification
```python
# packages/ai-parrot-tools/tests/workday/test_homologation_read.py
import json
import pytest
from parrot_tools.workday.tool import WorkdayToolkit


def test_get_tools_exposes_read_methods():
    names = {t.name for t in WorkdayToolkit().get_tools()}
    for m in ["find_employee_id_by_name", "get_current_user_info",
              "get_more_employee_data", "get_personal_information",
              "get_direct_reports", "get_time_off_balance",
              "get_current_user_time_off_balance",
              "get_current_user_time_off_history",
              "get_today_date_and_day_of_week"]:
        assert m in names


@pytest.mark.asyncio
async def test_get_today_date_and_day_of_week_no_soap():
    res = await WorkdayToolkit().get_today_date_and_day_of_week()
    assert "date" in res and "day_of_week" in res
    json.dumps(res)


@pytest.mark.asyncio
async def test_find_employee_id_by_name(monkeypatch):
    """name -> worker id list with mocked get_workers."""
    ...
```

---

## Agent Instructions

1. **Read the spec** (esp. §2 return-shape, §3 Module 3, §6 mapping table).
2. **Check dependencies** — TASK-1506 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm operation_type keys + model map.
4. **Update status** → `"in-progress"`.
5. **Implement** the 9 methods.
6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`; **update index** → `"done"`.
8. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6
**Date**: 2026-06-08
**Notes**: Added 9 public async tools + 4 input schemas + 8 METHOD_TO_SERVICE_MAP
entries. find_employee_id_by_name uses call_operation with Legal_Name criteria;
get_current_user_info / get_more_employee_data / get_personal_information / get_direct_reports
delegate to get_workers composable; get_time_off_balance / get_current_user_time_off_balance
delegate to get_time_off_balances; get_current_user_time_off_history delegates to
get_time_requests; get_today_date_and_day_of_week uses local datetime. All returns
JSON-serializable via model_dump(mode='json'). 14/14 tests pass.
**Notes**:

**Deviations from spec**: none | describe if any
