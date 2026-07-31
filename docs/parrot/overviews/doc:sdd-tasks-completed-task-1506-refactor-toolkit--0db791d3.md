---
type: Wiki Overview
title: 'TASK-1506: Refactor WorkdayToolkit to delegate to the composable'
id: doc:sdd-tasks-completed-task-1506-refactor-toolkit-delegate-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2**. Today `WorkdayToolkit` (`parrot_tools/workday/tool.py`,
relates_to:
- concept: mod:parrot.tools.decorators
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.interfaces.workday.service
  rel: mentions
- concept: mod:parrot_tools.workday.tool
  rel: mentions
---

# TASK-1506: Refactor WorkdayToolkit to delegate to the composable

**Feature**: FEAT-230 — Workday Composable Interface + Toolkit Homologation
**Spec**: `sdd/specs/workday-tooling-composable-interface.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1505
**Assigned-to**: unassigned

---

## Context

Implements **Module 2**. Today `WorkdayToolkit` (`parrot_tools/workday/tool.py`,
1775 LOC) builds Workday SOAP envelopes in-line via its own
`WorkdaySOAPClient`. This task rebases each `wd_*` method so it delegates to the
vendored composable `WorkdayService` (`fetch()` / `fetch_models()` /
`call_operation()`) and converts results to JSON at the tool boundary. The
in-line `WorkdaySOAPClient` SOAP builders are retired (or reduced to a thin shim).

---

## Scope

- Import the vendored composable under an alias to avoid the name collision:
  `from ..interfaces.workday import WorkdayService as WorkdayComposable`.
- Replace each `wd_*` method body that builds SOAP in-line with a delegation to a
  `WorkdayComposable` instance (built per service/WSDL via the existing routing).
- Add a JSON-conversion boundary: prefer `fetch_models()` + `model.model_dump()`;
  fallback `fetch()` + `DataFrame.to_dict(orient="records")` (reuse
  `WorkdayToolkit._flatten_entries`, `tool.py:1706`). No raw `DataFrame` returns.
- Retire `WorkdaySOAPClient`'s SOAP-building helpers (`_build_worker_reference`,
  `_build_request_criteria`, `_parse_worker_response`) or reduce to a thin shim.
- Keep `__init__`, credentials, and `wd_start()` behavior backward-compatible.

**NOT in scope**: renaming the existing `WorkdayService(str, Enum)` (tool.py:99) or
`METHOD_TO_SERVICE_MAP` (tool.py:113) — leave them intact; adding the 11
homologated methods (Module 3 / TASK-1507); new write/eligibility ops (Modules 4/5).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py` | MODIFY | Delegate `wd_*` to composable; alias import; JSON boundary; retire in-line SOAP |
| `packages/ai-parrot-tools/tests/workday/test_toolkit_delegates.py` | CREATE | Delegation + JSON-serializable + unbroken-API tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Within parrot_tools/workday/tool.py use relative forms:
from ..toolkit import AbstractToolkit          # re-export -> parrot.tools.toolkit
from ..decorators import tool_schema           # re-export -> parrot.tools.decorators
from ..interfaces.workday import WorkdayService as WorkdayComposable   # NEW (TASK-1505 package)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/workday/tool.py  (CURRENT — to refactor)
class WorkdayService(str, Enum):                       # line 99   (WSDL-category ENUM — DO NOT TOUCH)
    HUMAN_RESOURCES = "human_resources"                # line 101
    ABSENCE_MANAGEMENT = "absence_management"           # line 102
METHOD_TO_SERVICE_MAP: dict                            # line 113  (consumes the enum — keep intact)
class WorkdaySOAPClient(SOAPClient):                   # line 350  (in-line SOAP builders — RETIRE)
    def _build_worker_reference(self, worker_id, id_type="Employee_ID"): ...   # line 368
    def _build_request_criteria(self, **filters): ...  # line 388
    def _parse_worker_response(self, response): ...     # line 413
class WorkdayToolkit(AbstractToolkit):                 # line 472
    def __init__(self, tenant_name=None, credentials=None, wsdl_paths=None,    # line 492
                 redis_url=None, redis_key="workday:access_token", timeout=30, **kwargs): ...
    async def wd_start(self) -> str: ...               # line 600
    async def wd_get_worker(self, ...): ...            # line 708  @tool_schema(GetWorkerInput)
    async def wd_get_time_off_balance(self, ...): ...  # line 1034 @tool_schema(GetTimeOffBalanceInput)
    def _flatten_entries(self, ...): ...               # line 1706 (reuse for DataFrame->dict)

# Composable delegation surface (parrot_tools/interfaces/workday/service.py — from TASK-1505):
class WorkdayService(SOAPClient):                      # line 111  (the COMPOSABLE — import as WorkdayComposable)
    async def call_operation(self, operation, **kwargs): ...   # line 251
    async def fetch(self, operation_type, **params) -> pd.DataFrame: ...  # line 266
    async def fetch_models(self, operation_type, **params) -> list: ...   # line 291  ([] if no model mapped)
```

### Does NOT Exist
- ~~importing the composable as bare `WorkdayService` into tool.py~~ — collides with the enum at `tool.py:99`. Use the `WorkdayComposable` alias.
- ~~`fetch_models()` returning models for unmapped operation_types~~ — returns `[]` (service.py:308); ensure the op has an `_OPERATION_MODEL_MAP` entry or use `fetch()`+`to_dict`.

---

## Implementation Notes

### Pattern to Follow
```python
# Before (in-line):  build envelope -> self.run(operation) -> parse
# After (delegate):
svc = WorkdayComposable(operation_type="get_workers")
await svc.start()
models = await svc.fetch_models("get_workers", **criteria)   # typed path
return [m.model_dump() for m in models]                        # JSON-serializable
# fallback when no model is mapped:
df = await svc.fetch("get_workers", **criteria)
return self._flatten_entries(df.to_dict(orient="records"))
```

### Key Constraints
- Async throughout; reuse the lazy client cache pattern already in the toolkit.
- Every refactored `wd_*` method must still return the same shape its callers expect.
- `json.dumps(result)` must succeed for every return.

### References in Codebase
- `parrot_tools/workday/tool.py:1706` — `_flatten_entries` (DataFrame→dict).
- `parrot_tools/interfaces/workday/service.py` — delegation target.

---

## Acceptance Criteria

- [ ] `wd_*` methods delegate to `WorkdayComposable.fetch/fetch_models/call_operation`.
- [ ] `WorkdaySOAPClient` SOAP-building helpers removed or reduced to a thin shim.
- [ ] No raw `pandas.DataFrame` returned by any tool (`json.dumps(result)` succeeds).
- [ ] Existing `wd_get_worker` / `wd_get_time_off_balance` return unchanged shapes.
- [ ] The existing `WorkdayService(str, Enum)` and `METHOD_TO_SERVICE_MAP` are untouched.
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/workday/test_toolkit_delegates.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/workday/tool.py`

---

## Test Specification
```python
# packages/ai-parrot-tools/tests/workday/test_toolkit_delegates.py
import json
import pytest

from parrot_tools.workday.tool import WorkdayToolkit, WorkdayService as WorkdayServiceEnum


def test_enum_untouched():
    """The WSDL-category enum still exists and is distinct from the composable."""
    assert WorkdayServiceEnum.HUMAN_RESOURCES == "human_resources"


@pytest.mark.asyncio
async def test_toolkit_delegates_to_service(monkeypatch):
    """A wd_* method calls the composable, not an in-line envelope builder."""
    calls = {}

    async def fake_fetch_models(self, operation_type, **params):
        calls["op"] = operation_type
        return []

    monkeypatch.setattr(
        "parrot_tools.interfaces.workday.service.WorkdayService.fetch_models",
        fake_fetch_models,
    )
    tk = WorkdayToolkit()
    # ... call a refactored wd_* method with mocked start(); assert calls["op"] set


@pytest.mark.asyncio
async def test_tool_returns_json_serializable(monkeypatch):
    """Refactored tools never return a DataFrame."""
    # ... mock service; assert json.dumps(result) succeeds
```

---

## Agent Instructions

1. **Read the spec** (esp. §2 name-collision note, §3 Module 2, §6).
2. **Check dependencies** — TASK-1505 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm tool.py line anchors are still accurate.
4. **Update status** → `"in-progress"`.
5. **Implement** the delegation refactor.
6. **Verify** acceptance criteria.
7. **Move** this file to `sdd/tasks/completed/`; **update index** → `"done"`.
8. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6
**Date**: 2026-06-08
**Notes**: Added `_composables: Dict[str, WorkdayComposable]` cache and
`_get_composable(operation_type)` factory to `WorkdayToolkit`. `wd_close()`
now also closes composables. `wd_get_worker` and `wd_get_time_off_balance`
delegate via `fetch_models()`. All other `wd_*` HR/Absence methods delegate
via `svc.call_operation()`. Payroll methods keep `WorkdaySOAPClient` (no
composable handler). Five `WorkdaySOAPClient` helpers removed
(`_build_worker_reference`, `_build_request_criteria`, `_parse_worker_response`,
`_build_organization_reference`, `_build_field_criteria`) — all inlined.
8/8 new tests pass, 4/4 TASK-1505 tests still green.

**Deviations from spec**: Payroll methods (`wd_get_payroll_balances`,
`wd_get_payroll_results`, `wd_get_company_payment_dates`) kept on
`WorkdaySOAPClient` because no composable handler exists for payroll operations.
