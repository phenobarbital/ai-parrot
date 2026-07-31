---
type: Wiki Overview
title: 'TASK-1020: HR Convenience Methods (search_employee, search_holidays)'
id: doc:sdd-tasks-completed-task-1020-hr-convenience-methods-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agents need typed convenience methods for HR queries, following the same
  pattern as
---

# TASK-1020: HR Convenience Methods (search_employee, search_holidays)

**Feature**: FEAT-147 — Evaluate Odoo MCP Toolkit
**Spec**: `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1013, TASK-1015
**Assigned-to**: unassigned

---

## Context

Agents need typed convenience methods for HR queries, following the same pattern as
`find_partner`. This task adds `search_employee` and `search_holidays`.

Implements spec §3 Module 7: HR Convenience Methods.

---

## Scope

- Add `search_employee` async method: queries `hr.employee` via `search_read` with
  name ilike filter, returns `list[HrEmployee]`
- Add `search_holidays` async method: queries `hr.leave` by date range and optional
  `employee_id`, returns `list[HrLeave]`
- Define `_HR_EMPLOYEE_DEFAULT_FIELDS` and `_HR_LEAVE_DEFAULT_FIELDS` class-level tuples
- Handle "module not installed" gracefully: catch `OdooRPCError` and return empty list
  with a warning logged
- Decorate both with `@tool_schema`

**NOT in scope**: Other HR models (hr.department, hr.contract), other toolkit methods.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY | Add `search_employee`, `search_holidays`, default field lists |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .models.inputs import SearchEmployeeInput, SearchHolidaysInput  # TASK-1013
from .models.entities import HrEmployee, HrLeave                    # TASK-1013

# Existing pattern to follow (toolkit.py:46-54):
from .models.entities import ResPartner  # already imported
```

### Existing Signatures to Use
```python
# toolkit.py — partner pattern to replicate (line 520-558):
_PARTNER_DEFAULT_FIELDS = [
    "id", "display_name", "name", "is_company", ...
]

async def find_partner(self, name=None, email=None, ...) -> list[ResPartner]:
    domain = []
    if name:
        domain.append(("name", "ilike", name))
    ...
    records = await self._execute("res.partner", "search_read", [domain], {fields, limit})
    return [ResPartner.model_validate(r) for r in records or []]
```

### Does NOT Exist
- ~~`OdooToolkit.search_employee()`~~ — must be created
- ~~`OdooToolkit.search_holidays()`~~ — must be created
- ~~`HrEmployee`~~ — created in TASK-1013
- ~~`HrLeave`~~ — created in TASK-1013

---

## Implementation Notes

### Default Field Lists
```python
_HR_EMPLOYEE_DEFAULT_FIELDS = [
    "id", "display_name", "name", "job_id", "job_title",
    "department_id", "parent_id", "work_email", "work_phone",
    "mobile_phone", "company_id", "active",
]

_HR_LEAVE_DEFAULT_FIELDS = [
    "id", "display_name", "employee_id", "holiday_status_id",
    "date_from", "date_to", "number_of_days", "state", "name",
]
```

### search_employee
```python
@tool_schema(SearchEmployeeInput)
async def search_employee(self, name: str, limit: int = 20) -> list[HrEmployee]:
    domain = [("name", "ilike", name)]
    try:
        records = await self._execute(
            "hr.employee", "search_read", [domain],
            {"fields": self._HR_EMPLOYEE_DEFAULT_FIELDS, "limit": limit},
        )
        return [HrEmployee.model_validate(r) for r in records or []]
    except OdooRPCError as exc:
        self.logger.warning("search_employee failed (HR module may not be installed): %s", exc)
        return []
```

### search_holidays
- Build domain: `[("date_from", ">=", start_date), ("date_to", "<=", end_date)]`
- If `employee_id`: append `("employee_id", "=", employee_id)`
- Query `hr.leave` model
- Same `OdooRPCError` catch pattern

---

## Acceptance Criteria

- [ ] `search_employee(name="Alice")` returns `list[HrEmployee]`
- [ ] `search_holidays(start_date="2026-01-01", end_date="2026-01-31")` filters by dates
- [ ] `search_holidays(..., employee_id=5)` adds employee filter
- [ ] When HR module is not installed, returns empty list (no crash)
- [ ] Both methods have `@tool_schema` decorators

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_search_employee(odoo_toolkit):
    tk._transport.execute_kw = AsyncMock(return_value=[
        {"id": 1, "name": "Alice", "display_name": "Alice"},
    ])
    result = await tk.search_employee(name="Alice")
    assert len(result) == 1
    assert isinstance(result[0], HrEmployee)

@pytest.mark.asyncio
async def test_search_employee_module_not_installed(odoo_toolkit):
    tk._transport.execute_kw = AsyncMock(side_effect=OdooRPCError("model not found"))
    result = await tk.search_employee(name="Alice")
    assert result == []

@pytest.mark.asyncio
async def test_search_holidays_by_date(odoo_toolkit):
    tk._transport.execute_kw = AsyncMock(return_value=[
        {"id": 1, "employee_id": [5, "Alice"], "date_from": "2026-01-05", "date_to": "2026-01-06"},
    ])
    result = await tk.search_holidays(start_date="2026-01-01", end_date="2026-01-31")
    assert len(result) == 1
    assert isinstance(result[0], HrLeave)
```

---

## Completion Note

*(Agent fills this in when done)*
