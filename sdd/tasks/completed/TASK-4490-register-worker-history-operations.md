# TASK-4490: Register the two operations in config, handlers and service

**Feature**: FEAT-706 — Workday Worker Event History and Job Changes
**Spec**: `sdd/specs/workday-worker-event-history-and-job-changes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4488, TASK-4489
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. The handlers from TASK-4488/4489 are unreachable until both operation keys
are routed to the Human Resources WSDL, exported from `handlers/__init__.py`, and registered in
`WorkdayService._type_handlers` and `_OPERATION_MODEL_MAP`. An unregistered key silently routes
to the Staffing WSDL, which has no `Get_Worker_Event_History` (spec §7 "WSDL fallback trap").

---

## Scope

- Route `get_worker_event_history` and `get_worker_job_changes` to `WORKDAY_WSDL_HUMAN_RESOURCES` in `config._WSDL_ROUTING`.
- Export `WorkerEventHistoryType` and `WorkerJobChangesType` from `handlers/__init__.py`.
- In `service.py`: import both handlers and `WorkerEvent` / `JobChange`; add both keys to `_OPERATION_MODEL_MAP` and `self._type_handlers`.
- Write `test_worker_history_registry.py`: routing, registry, and the `fetch_models` round-trip of a nested `JobChange`.

**NOT in scope**: handler logic, toolkit tools (TASK-4491), docs (TASK-4492), changes to `_record_to_model_kwargs`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py` | MODIFY | Two `_WSDL_ROUTING` rows |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/__init__.py` | MODIFY | Import + `__all__` for both handlers |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py` | MODIFY | Imports, model map, handler registry |
| `packages/ai-parrot-tools/tests/workday/test_worker_history_registry.py` | CREATE | Routing / registry / round-trip tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.conf import WORKDAY_WSDL_HUMAN_RESOURCES, WORKDAY_WSDL_STAFFING        # used by test_position_job_profile.py:7
from parrot_tools.interfaces.workday.config import WorkdayConfig, get_wsdl_path    # config.py:103; WorkdayConfig kwargs pattern: test_rest_client.py:13-20
from parrot_tools.interfaces.workday import service as service_mod                 # pattern: test_fetch_models_rehydrate.py:10
from parrot_tools.interfaces.workday.service import WorkdayService                 # service.py:170
from parrot_tools.interfaces.workday.handlers.worker_event_history import WorkerEventHistoryType   # TASK-4488
from parrot_tools.interfaces.workday.handlers.worker_job_changes import WorkerJobChangesType       # TASK-4489
from parrot_tools.interfaces.workday.models.worker_event import FieldChange, JobChange, JobSnapshot, WorkerEvent   # TASK-4487
```

### Existing Signatures to Use
```python
# config.py
_WSDL_ROUTING: dict[str, Any]          # line 67; last row "get_job_profiles": WORKDAY_WSDL_HUMAN_RESOURCES (line 99), closes line 100
def get_wsdl_path(operation_type) -> Any   # line 103 — falls back to WORKDAY_WSDL_PATH (Staffing)

# service.py
from parrot_tools.interfaces.workday.handlers import ( ... TimeRequestType, WorkerType, )   # alphabetical block; "    WorkerType," at line 69
from parrot_tools.interfaces.workday.models.worker import Worker                           # line 96 (last model import)
_OPERATION_MODEL_MAP: dict[str, type] = { ... "get_references": WorkdayReference, }        # line 102, last entry line 117
self._type_handlers: dict[str, Any] = { ... "get_time_off_eligibility": TimeOffEligibilityType(self), }   # line 279, last entry line 310
async def fetch_models(self, operation_type: str, **params) -> list                         # line 359 — rebuilds rows via _record_to_model_kwargs (line 136)

# handlers/__init__.py
from .payroll import ( PayrollBalancesType, PayrollResultsType, CompanyPaymentDatesType, )  # "    CompanyPaymentDatesType," at line 30
__all__ = [ ... "CompanyPaymentDatesType", ]                                                # line 62 (last entry)
```

### Does NOT Exist
- ~~`WORKDAY_WSDL_PATH` routing for these keys~~ — the default is the Staffing WSDL; route explicitly.
- ~~`WorkdayService.get_worker_event_history()`~~ — no per-operation methods; everything goes through `fetch` / `fetch_models`.
- ~~`WorkdayService.register_handler()`~~ — the registry is the literal dict in `__init__`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/workday/test_worker_history_registry.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py#get_wsdl_path",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py#WorkdayService",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py#WorkdayService.fetch_models"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep the handlers import block in `service.py` alphabetical: `WorkerEventHistoryType`, `WorkerJobChangesType` go immediately before `WorkerType`.
- If the `fetch_models` round-trip loses nested `before`/`after` (spec §7 gotcha), do NOT change `_record_to_model_kwargs`; report it in the Completion Note and fix the handler's DataFrame instead (TASK-4489 owns it — mark this task `done-with-issues`).

---

## Implementation Blueprint

### Steps (in order)
1. Edit `config.py` — *why*: routing is what makes `_get_composable` load the right WSDL.
2. Edit `handlers/__init__.py` — *why*: `service.py` imports handlers from the package.
3. Edit `service.py` (four sites) — *why*: `fetch` / `fetch_models` dispatch.
4. Write the tests, run Validation Commands (includes the existing position and delegate suites).

### `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "get_job_profiles": WORKDAY_WSDL_HUMAN_RESOURCES,' config.py)
# AFTER — insert below `    "get_job_profiles": WORKDAY_WSDL_HUMAN_RESOURCES,` (verified: config.py:99)
    # FEAT-706: worker event history + job changes — Get_Worker_Event_History is HR-only
    "get_worker_event_history": WORKDAY_WSDL_HUMAN_RESOURCES,
    "get_worker_job_changes": WORKDAY_WSDL_HUMAN_RESOURCES,
```

### `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/handlers/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    CompanyPaymentDatesType,' handlers/__init__.py)
# The anchor is followed by `)` on line 31. Insert AFTER that closing `)` (line 31):
# FEAT-706: worker event history + job changes (HR WSDL)
from .worker_event_history import WorkerEventHistoryType
from .worker_job_changes import WorkerJobChangesType

# occurrences: 1 (verified: grep -c '    "CompanyPaymentDatesType",' handlers/__init__.py)
# AFTER — insert below `    "CompanyPaymentDatesType",` (verified: handlers/__init__.py:62)
    # FEAT-706
    "WorkerEventHistoryType",
    "WorkerJobChangesType",
```

### `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    WorkerType,' service.py)
# BEFORE — insert above `    WorkerType,` (verified: service.py:69)
    WorkerEventHistoryType,
    WorkerJobChangesType,

# occurrences: 1 (verified: grep -c 'from parrot_tools.interfaces.workday.models.worker import Worker' service.py)
# AFTER — insert below `from parrot_tools.interfaces.workday.models.worker import Worker` (verified: service.py:96)
from parrot_tools.interfaces.workday.models.worker_event import JobChange, WorkerEvent

# occurrences: 1 (verified: grep -c '    "get_references": WorkdayReference,' service.py)
# AFTER — insert below `    "get_references": WorkdayReference,` (verified: service.py:117)
    "get_worker_event_history": WorkerEvent,
    "get_worker_job_changes": JobChange,

# occurrences: 1 (verified: grep -c '            "get_time_off_eligibility": TimeOffEligibilityType(self),' service.py)
# AFTER — insert below `            "get_time_off_eligibility": TimeOffEligibilityType(self),` (verified: service.py:310)
            # FEAT-706: worker event history + job changes (HR WSDL)
            "get_worker_event_history": WorkerEventHistoryType(self),
            "get_worker_job_changes": WorkerJobChangesType(self),
```
**Why**: the four sites are the only registration points (spec §6 Edit Sites); the model map makes
`fetch_models` return typed `WorkerEvent` / `JobChange` instances.

### `packages/ai-parrot-tools/tests/workday/test_worker_history_registry.py` (CREATE)
```python
"""FEAT-706 — routing, registry and fetch_models round-trip for the worker-history operations."""
from datetime import date

import pandas as pd
import pytest

from parrot.conf import WORKDAY_WSDL_HUMAN_RESOURCES
from parrot_tools.interfaces.workday import service as service_mod
from parrot_tools.interfaces.workday.config import WorkdayConfig, get_wsdl_path
from parrot_tools.interfaces.workday.handlers import WorkerEventHistoryType, WorkerJobChangesType
from parrot_tools.interfaces.workday.models.worker_event import FieldChange, JobChange, JobSnapshot, WorkerEvent
from parrot_tools.interfaces.workday.service import WorkdayService

KEYS = ("get_worker_event_history", "get_worker_job_changes")


def test_routing_to_hr_wsdl():
    for key in KEYS:
        assert get_wsdl_path(key) == WORKDAY_WSDL_HUMAN_RESOURCES


def test_model_map():
    assert service_mod._OPERATION_MODEL_MAP["get_worker_event_history"] is WorkerEvent
    assert service_mod._OPERATION_MODEL_MAP["get_worker_job_changes"] is JobChange


def test_type_handlers_registered():
    # FILL IN: WorkdayService(config=WorkdayConfig(client_id="cid", client_secret="secret",
    #   token_url="https://example.invalid/token", refresh_token="r", tenant="t",
    #   workday_url="https://example.invalid"), operation_type="get_worker_event_history");
    #   assert isinstance(svc._type_handlers[KEYS[0]], WorkerEventHistoryType) and [KEYS[1]] → WorkerJobChangesType.
    #   Do not call start() (it loads the WSDL).
    ...


@pytest.mark.asyncio
async def test_fetch_models_roundtrip(monkeypatch):
    # FILL IN: svc = WorkdayService.__new__(WorkdayService); set svc._logger (pattern test_fetch_models_rehydrate.py:58-59);
    #   build a JobChange(kind="change", before=JobSnapshot(...), after=JobSnapshot(...), changes=[FieldChange(...)]);
    #   fake fetch returns pd.DataFrame([jc.model_dump()]); models = await svc.fetch_models("get_worker_job_changes");
    #   assert models == [jc] (nested before/after/changes intact).
    ...
```

### FILL IN checklist
- [ ] `test_type_handlers_registered` body; bounded by "no WSDL load".
- [ ] `test_fetch_models_roundtrip` body; bounded by AC "nested before/after intact".

---

## Acceptance Criteria

- [ ] `get_wsdl_path()` returns `WORKDAY_WSDL_HUMAN_RESOURCES` for both keys.
- [ ] `WorkdayService._type_handlers` contains both keys; `_OPERATION_MODEL_MAP` maps them to `WorkerEvent` / `JobChange`; `fetch_models` returns typed instances with nested `before`/`after` intact.
- [ ] Existing suites `test_position_job_profile.py`, `test_toolkit_delegates.py` and `test_worker_id_type_fallback.py` still pass unchanged.
- [ ] `ruff check` passes on the touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/workday/test_worker_history_registry.py -q`
- `pytest packages/ai-parrot-tools/tests/workday/test_position_job_profile.py -q`
- `pytest packages/ai-parrot-tools/tests/workday/test_toolkit_delegates.py -q`
- `pytest packages/ai-parrot-tools/tests/workday/test_worker_id_type_fallback.py -q`

---

## Test Specification

See the test block in the Implementation Blueprint and spec §4 (M4 rows).

---

## Agent Instructions

1. Work in the feature worktree; TASK-4488 and TASK-4489 must be `done`.
2. Re-run `grep -c` on every anchor before editing.
3. Mark `in-progress`, implement from the blueprint, complete every `FILL IN`.
4. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`.
5. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4490 workday-worker-event-history-and-job-changes verified`.

---

## Completion Note


- Task: TASK-4490
- Feature: workday-worker-event-history-and-job-changes
- Implementation SHA: 25cb61b082ea22111a860a34a7b16670b62378eb
- Closed at (UTC): 2026-10-19T20:53:26+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: qwen · Backend: nova · Model: qwen.qwen3-coder-480b-a35b-instruct · Attempts: 1 · Duration: 86.9s · Tokens: 748093/6349 |
