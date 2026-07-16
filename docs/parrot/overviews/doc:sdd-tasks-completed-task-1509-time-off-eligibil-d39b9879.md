---
type: Wiki Overview
title: 'TASK-1509: `get_my_time_off_eligibility` handler (NEW operation)'
id: doc:sdd-tasks-completed-task-1509-time-off-eligibility-handler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 5**. No eligibility operation exists in the vendored
  source
relates_to:
- concept: mod:parrot_tools.interfaces.workday.service
  rel: mentions
- concept: mod:parrot_tools.workday.tool
  rel: mentions
---

# TASK-1509: `get_my_time_off_eligibility` handler (NEW operation)

**Feature**: FEAT-230 — Workday Composable Interface + Toolkit Homologation
**Spec**: `sdd/specs/workday-tooling-composable-interface.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1507
**Assigned-to**: unassigned

---

## Context

Implements **Module 5**. No eligibility operation exists in the vendored source
(`Get_Time_Off_Plan_Balances` returns balances, not eligibility — verified). This
task builds a net-new READ handler returning the time-off plans/types a worker may
request, registers it, and exposes the `get_my_time_off_eligibility` tool. Shares
`tool.py` with TASK-1508, so runs sequentially in the same worktree.

---

## Scope

- CREATE `handlers/time_off_eligibility.py` subclassing the paginated read base
  `WorkdayTypeBase` (handlers/base.py:11), following `time_off_balances.py` as a
  reference read handler.
- REGISTER the new operation_type in `WorkdayService.__init__`'s `_type_handlers`
  (service.py:218) and add a `_WSDL_MAP` entry → `WORKDAY_WSDL_ABSENCE_MANAGEMENT`
  (config.py:54). Since it returns typed rows, register a model in
  `_OPERATION_MODEL_MAP` (service.py:90) so `fetch_models()` doesn't return `[]`.
- ADD the `get_my_time_off_eligibility(worker_id)` tool to `WorkdayToolkit`,
  returning JSON-serializable `list[dict]` of eligible time-off types.

**Unresolved (decide here):** the exact Workday op that enumerates requestable
time-off plans/types — verify against the Absence Management WSDL (spec §8).

**NOT in scope**: `request_my_time_off` (TASK-1508).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/time_off_eligibility.py` | CREATE | `WorkdayTypeBase` read handler for eligibility |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/models/time_off_eligibility.py` | CREATE | Pydantic model for an eligible time-off type (if none reusable) |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py` | MODIFY | Register handler in `_type_handlers` + `_OPERATION_MODEL_MAP` |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py` | MODIFY | `_WSDL_MAP` entry → Absence Management |
| `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py` | MODIFY | `get_my_time_off_eligibility` tool |
| `packages/ai-parrot-tools/tests/workday/test_time_off_eligibility.py` | CREATE | Eligibility-returns-types test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .base import WorkdayTypeBase          # handlers/base.py:11
from ..interfaces.workday import WorkdayService as WorkdayComposable   # in tool.py
```

### Existing Signatures to Use
```python
# handlers/base.py — read base (subclass this for a read op):
class WorkdayTypeBase(ABC):                            # line 11
    def __init__(self, service, max_retries=..., retry_delay=...): ...  # line 21
    @abstractmethod
    async def execute(self, **kwargs) -> Any: ...      # line 53
    async def _paginate_soap_operation(self, ...): ... # line 60 (pagination idiom)

# Reference read handler: handlers/time_off_balances.py:13 (Get_Time_Off_Plan_Balances)

# service.py — register here:
self._type_handlers: dict = { ... }                    # line 218 (add new read op key)
_OPERATION_MODEL_MAP: dict[str, type]                  # service.py:90 (add op -> model; else fetch_models returns [])
async def fetch_models(self, operation_type, **params) -> list: ...    # line 291

# config.py:
_WSDL_MAP: dict                                        # line 54 (add op -> WORKDAY_WSDL_ABSENCE_MANAGEMENT)
```

### Does NOT Exist
- ~~a time-off eligibility op/handler in the source~~ — NONE exists; must be built.
- ~~`Get_Time_Off_Plan_Balances` returning eligibility~~ — it returns BALANCES, not eligibility.
- ~~`fetch_models` auto-returning models for an unmapped op~~ — returns `[]` (service.py:308); register the model.

---

## Implementation Notes

### Pattern to Follow
```python
# handlers/time_off_eligibility.py  (read op — mirror time_off_balances.py)
from .base import WorkdayTypeBase

class TimeOffEligibilityType(WorkdayTypeBase):
    async def execute(self, *, worker_id, **kwargs):
        raw = await self.service.call_operation(
            operation="Get_Eligible_Absence_Types",  # CONFIRM against Absence Mgmt WSDL
            **self._build_request(worker_id),
        )
        return self._parse(raw)   # -> DataFrame of eligible types
```

### Key Constraints
- Read op → subclass `WorkdayTypeBase` (not the write base).
- Register in `_type_handlers`, `_OPERATION_MODEL_MAP`, and `_WSDL_MAP`.
- Tool returns JSON-serializable `list[dict]` (no DataFrame).
- Identity via explicit `worker_id`.

### References in Codebase
- `handlers/time_off_balances.py:13` — closest read-handler reference.
- `service.py:90` / `service.py:218` — registries to extend.

---

## Acceptance Criteria

- [ ] `handlers/time_off_eligibility.py` subclasses `WorkdayTypeBase`.
- [ ] New op registered in `_type_handlers`, `_OPERATION_MODEL_MAP`, and `_WSDL_MAP`.
- [ ] `get_my_time_off_eligibility` tool present, public, async, returns `list[dict]`.
- [ ] Returns eligible time-off types (mocked) — JSON-serializable, never a DataFrame.
- [ ] `get_tools()` now exposes all 11 homologated methods (with TASK-1507/1508).
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/workday/test_time_off_eligibility.py -v`
- [ ] No linting errors.

---

## Test Specification
```python
# packages/ai-parrot-tools/tests/workday/test_time_off_eligibility.py
import json
import pytest
from parrot_tools.workday.tool import WorkdayToolkit


@pytest.mark.asyncio
async def test_get_my_time_off_eligibility(monkeypatch):
    """Returns eligible time-off types as JSON-serializable list[dict]."""
    async def fake_call_operation(self, operation, **kwargs):
        return {"eligible": [{"type": "PTO"}]}
    monkeypatch.setattr(
        "parrot_tools.interfaces.workday.service.WorkdayService.call_operation",
        fake_call_operation,
    )
    res = await WorkdayToolkit().get_my_time_off_eligibility(worker_id="123")
    assert isinstance(res, list)
    json.dumps(res)


def test_get_tools_exposes_eleven():
    names = {t.name for t in WorkdayToolkit().get_tools()}
    assert "get_my_time_off_eligibility" in names
```

---

## Agent Instructions

1. **Read the spec** (esp. §3 Module 5, §6, §8 unresolved op name).
2. **Check dependencies** — TASK-1507 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm read-base + registry anchors.
4. **Update status** → `"in-progress"`.
5. **Implement** the eligibility handler + tool.
6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`; **update index** → `"done"`.
8. **Fill in the Completion Note** (record the chosen Workday op name).

---

## Completion Note

**Completed by**: Claude Sonnet 4.6
**Date**: 2026-06-08
**SOAP op used**: `Get_Time_Off_Types` (Absence Management WSDL)
**Notes**: Created models/time_off_eligibility.py (TimeOffEligibility Pydantic model:
time_off_type_id, name, description, unit). Created handlers/time_off_eligibility.py
(TimeOffEligibilityType subclassing WorkdayTypeBase) — calls Get_Time_Off_Types with
Employee_Reference filter, parses Response_Data.Time_Off_Type into rows. Registered in
handlers/__init__.py, service.py (_type_handlers + _OPERATION_MODEL_MAP → TimeOffEligibility),
config.py (_WSDL_ROUTING → WORKDAY_WSDL_ABSENCE_MANAGEMENT). Added
get_my_time_off_eligibility tool to WorkdayToolkit. All 11 homologated tools confirmed
present in get_tools(). 10/10 tests pass; ruff clean.

**Deviations from spec**: none | describe if any
