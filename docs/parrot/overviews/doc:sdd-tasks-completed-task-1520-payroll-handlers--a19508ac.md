---
type: Wiki Overview
title: 'TASK-1520: Payroll handlers in the Workday composable'
id: doc:sdd-tasks-completed-task-1520-payroll-handlers-composable-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1**. The composable has NO payroll handlers today (only
  the
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot_tools.interfaces.workday.config
  rel: mentions
---

# TASK-1520: Payroll handlers in the Workday composable

**Feature**: FEAT-233 — Workday Composable-Only WSDL Routing
**Spec**: `sdd/specs/workday-composable-only-wsdl-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1**. The composable has NO payroll handlers today (only the
`Worker` model carries payroll *fields*). Before the toolkit's payroll methods can
delegate to the composable (TASK-1521) and the legacy SOAP path can be deleted
(TASK-1522), the composable needs 3 read handlers for the Workday Payroll WSDL.

---

## Scope

- CREATE 3 read handlers under `interfaces/workday/handlers/`, each subclassing
  `WorkdayTypeBase` and issuing its Workday Payroll operation via
  `self.service.call_operation(...)`, mirroring `handlers/time_off_balances.py`:
  - `payroll_balances.py` → `get_payroll_balances`
  - `payroll_results.py` → `get_payroll_results`
  - `company_payment_dates.py` → `get_company_payment_dates`
- REGISTER the 3 operation_types in `WorkdayService._type_handlers` (service.py:222,
  alongside the existing entries like `get_time_off_balances` at service.py:237).
- ADD `_WSDL_ROUTING` entries in `config.py:57` mapping the 3 op keys →
  `WORKDAY_WSDL_PAYROLL`.
- If the handlers return typed rows, register models in `_OPERATION_MODEL_MAP`
  (service.py:93) and add Pydantic models under `interfaces/workday/models/`.

**Unresolved (decide here):** exact Workday Payroll operation names + payload shapes
— verify against `env/workday/payroll_v45_2.wsdl` before coding (spec §8).

**NOT in scope:** touching `workday/tool.py` (TASK-1521/1516); deleting legacy code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/payroll_balances.py` | CREATE | `WorkdayTypeBase` read handler |
| `.../interfaces/workday/handlers/payroll_results.py` | CREATE | read handler |
| `.../interfaces/workday/handlers/company_payment_dates.py` | CREATE | read handler |
| `.../interfaces/workday/models/payroll.py` | CREATE (if typed) | Pydantic models for payroll rows |
| `.../interfaces/workday/service.py` | MODIFY | register handlers in `_type_handlers` (+ `_OPERATION_MODEL_MAP`) |
| `.../interfaces/workday/config.py` | MODIFY | `_WSDL_ROUTING` → `WORKDAY_WSDL_PAYROLL` |
| `packages/ai-parrot-tools/tests/workday/test_payroll_handlers.py` | CREATE | handler unit tests (mocked) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .base import WorkdayTypeBase                # handlers/base.py:11
from parrot.conf import WORKDAY_WSDL_PAYROLL      # packages/ai-parrot/src/parrot/conf.py:623
#   WORKDAY_WSDL_PATHS["payroll"] = WORKDAY_WSDL_PAYROLL  # conf.py:655
```

### Existing Signatures to Use
```python
# Reference read handler — interfaces/workday/handlers/time_off_balances.py
class TimeOffBalanceType(WorkdayTypeBase):                 # line 10
    async def execute(self, **kwargs) -> pd.DataFrame: ... # line 27  (calls self.service.call_operation)

# interfaces/workday/service.py
_OPERATION_MODEL_MAP: dict[str, type] = { ... }            # line 93   (add payroll entries if typed)
self._type_handlers: dict[str, Any] = { ... }             # line 222  (register here)
    "get_time_off_balances": TimeOffBalanceType(self),     # line 237  (registration shape to mirror)
async def call_operation(self, operation, **kwargs)         # used by handlers
async def fetch(self, operation_type, **params) -> pd.DataFrame   # line 266
async def fetch_models(self, operation_type, **params) -> list    # line 291

# interfaces/workday/config.py
_WSDL_ROUTING: dict[str, Any] = { ... }                    # line 57   (add get_payroll_* here)
    "get_time_off_balances": WORKDAY_WSDL_ABSENCE_MANAGEMENT,  # line 72  (entry shape)
def get_wsdl_path(operation_type) -> Any: ...              # line 86   (uses _WSDL_ROUTING)
```

### Does NOT Exist
- ~~payroll handlers/operations in the composable~~ — none today; this task creates them.
- ~~a `get_payroll_*` entry in `_WSDL_ROUTING`~~ — must be added.
- ~~`WorkdayWriteTypeBase` for these~~ — payroll ops are READS; subclass `WorkdayTypeBase` (not the write base).

---

## Implementation Notes

### Pattern to Follow
```python
# handlers/payroll_balances.py  (mirror time_off_balances.py)
from .base import WorkdayTypeBase

class PayrollBalancesType(WorkdayTypeBase):
    async def execute(self, *, worker_id: str, **kwargs):
        raw = await self.service.call_operation(
            operation="Get_Payroll_...",   # CONFIRM against payroll_v45_2.wsdl
            **self._build_request(worker_id, **kwargs),
        )
        return self._parse(raw)   # -> DataFrame
```

### Key Constraints
- Read ops → `WorkdayTypeBase` (not the write base).
- Register in `_type_handlers` + `_WSDL_ROUTING` (+ `_OPERATION_MODEL_MAP` if typed).
- Async throughout; unit tests mock `call_operation` (no live tenant).

### References in Codebase
- `interfaces/workday/handlers/time_off_balances.py` — closest read-handler reference.
- `interfaces/workday/handlers/time_requests.py` — another read handler.

---

## Acceptance Criteria

- [ ] 3 payroll handlers exist, subclass `WorkdayTypeBase`, registered in `_type_handlers`.
- [ ] `get_wsdl_path("get_payroll_balances"|"get_payroll_results"|"get_company_payment_dates")` returns `WORKDAY_WSDL_PAYROLL`.
- [ ] Handlers return parsed results (mocked `call_operation`); JSON-serializable at the boundary.
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/workday/test_payroll_handlers.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/interfaces/workday`

---

## Test Specification
```python
# packages/ai-parrot-tools/tests/workday/test_payroll_handlers.py
import pytest
from parrot_tools.interfaces.workday.config import get_wsdl_path
from parrot.conf import WORKDAY_WSDL_PAYROLL


def test_payroll_ops_route_to_payroll_wsdl():
    for op in ("get_payroll_balances", "get_payroll_results", "get_company_payment_dates"):
        assert get_wsdl_path(op) == WORKDAY_WSDL_PAYROLL


@pytest.mark.asyncio
async def test_payroll_balances_handler(monkeypatch):
    """Handler builds payload + parses ack with mocked call_operation."""
    ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 1, §6, §8). 2. **Check deps** — none.
3. **Verify the Codebase Contract** (confirm handler/registry line anchors + WSDL).
4. **Update status** → in-progress. 5. **Implement**. 6. **Verify** criteria.
7. **Move** to `sdd/tasks/completed/`; **update index** → done. 8. **Fill Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <id>
**Date**: YYYY-MM-DD
**Notes**: (record chosen Payroll operation names + payload shapes)

**Deviations from spec**: none | describe if any
