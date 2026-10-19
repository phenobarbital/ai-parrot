# TASK-4491: Toolkit tools wd_get_worker_event_history and wd_get_worker_job_changes

**Feature**: FEAT-706 — Workday Worker Event History and Job Changes
**Spec**: `sdd/specs/workday-worker-event-history-and-job-changes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4487
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Agents reach Workday through `WorkdayToolkit`. This task adds two thin
`@tool_schema` wrappers that call `fetch_models` on the per-operation composable and return
JSON-ready dicts, mirroring `wd_get_position` (FEAT-591). The tools only need the model classes
(TASK-4487) to be testable: the tests stub `_get_composable`, so they do not wait for the
handlers or their registration (TASK-4488–4490). End-to-end routing is covered by the feature-tier
validation contract once TASK-4490 lands.

---

## Scope

- Add `GetWorkerEventHistoryInput` and `GetWorkerJobChangesInput` above the FEAT-230 input-schema block.
- Add `wd_get_worker_event_history` and `wd_get_worker_job_changes` to `WorkdayToolkit` immediately before `_parse_job_profile`.
- Write `test_worker_history_toolkit.py`: tools exposed, delegation key + params, JSON-serializable output.

**NOT in scope**: handlers, service/config registration, exposing `event_types` on the tool (spec §7: keep the agent surface small).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py` | MODIFY | Two input models + two tool methods |
| `packages/ai-parrot-tools/tests/workday/test_worker_history_toolkit.py` | CREATE | Toolkit tests with a stubbed composable |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in tool.py — add nothing:
from typing import Any, Dict, List, Optional, Type, Union      # tool.py:63
from pydantic import BaseModel, Field                          # tool.py:67
from ..decorators import tool_schema                           # tool.py:71
# tests:
from parrot_tools.workday.tool import WorkdayToolkit           # tool.py:368
from parrot_tools.interfaces.workday.models.worker_event import FieldChange, JobChange, JobSnapshot, WorkerEvent   # TASK-4487
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/workday/tool.py
class GetJobProfileInput(BaseModel): ...                                  # ends right before line 312 (blank) / 313
# Homologated read-tool input schemas (FEAT-230 Module 3)                 # line 313 — insert the two input models ABOVE this comment
class WorkdayToolkit(AbstractToolkit):                                    # line 368
    self._initialized = False                                             # line 453
    async def wd_start(self) -> str                                       # line 465
    async def _get_composable(self, operation_type: str) -> WorkdayComposable   # line 484
    @tool_schema(GetPositionInput) async def wd_get_position(...)         # line 1258 — reference implementation (1258-1314)
    def _parse_job_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:   # line 1359 — insert the two tools ABOVE this

# composable (WorkdayService)
async def fetch_models(self, operation_type: str, **params) -> list       # service.py:359
```

### Does NOT Exist
- ~~`WorkdayToolkit.wd_get_worker_history()`~~ — the names are exactly `wd_get_worker_event_history` and `wd_get_worker_job_changes`.
- ~~`event_types` tool parameter~~ — handler-only.
- ~~`svc.get_worker_event_history()`~~ — call `svc.fetch_models("<key>", ...)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/workday/tool.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/workday/test_worker_history_toolkit.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/workday/tool.py#WorkdayToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/workday/tool.py#WorkdayToolkit._get_composable",
    "sym:packages/ai-parrot-tools/src/parrot_tools/workday/tool.py#WorkdayToolkit.wd_get_position",
    "sym:packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py#WorkdayService.fetch_models"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The docstring of each tool is the LLM-facing description — keep it accurate and concrete.
- Return `[m.model_dump(mode="json") for m in models]` so dates become ISO strings and `json.dumps` accepts the result.
- Let `ValueError` / `LookupError` from the handlers propagate (the toolkit surfaces them to the agent).

---

## Implementation Blueprint

### Steps (in order)
1. Insert the two input models above the FEAT-230 comment — *why*: input schemas live together at module top.
2. Insert the two tools above `_parse_job_profile` — *why*: groups them with the FEAT-591 read tools.
3. Write the tests; run Validation Commands (includes the existing toolkit suites).

### `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py` (MODIFY) — input models
```python
# occurrences: 1 (verified: grep -c '# Homologated read-tool input schemas (FEAT-230 Module 3)' tool.py)
# BEFORE — insert above `# Homologated read-tool input schemas (FEAT-230 Module 3)` (verified: tool.py:313)
class GetWorkerEventHistoryInput(BaseModel):
    """Input for retrieving a worker's Workday event history."""

    worker_id: str = Field(description="Worker WID, Employee ID or Contingent Worker ID")
    worker_id_type: Optional[str] = Field(
        default=None,
        description="WID | Employee_ID | Contingent_Worker_ID; omit to auto-detect "
        "(WID by shape, else Employee_ID then Contingent_Worker_ID)",
    )
    effective_from: Optional[str] = Field(default=None, description="YYYY-MM-DD; requires effective_through")
    effective_through: Optional[str] = Field(default=None, description="YYYY-MM-DD; requires effective_from")
    updated_from: Optional[str] = Field(default=None, description="YYYY-MM-DD; requires updated_through")
    updated_through: Optional[str] = Field(default=None, description="YYYY-MM-DD; requires updated_from")


class GetWorkerJobChangesInput(BaseModel):
    """Input for detecting a worker's job position / profile / organization changes."""

    worker_id: str = Field(description="Worker WID, Employee ID or Contingent Worker ID")
    worker_id_type: Optional[str] = Field(
        default=None,
        description="WID | Employee_ID | Contingent_Worker_ID; omit to auto-detect "
        "(WID by shape, else Employee_ID then Contingent_Worker_ID)",
    )
    effective_from: Optional[str] = Field(default=None, description="YYYY-MM-DD; requires effective_through")
    effective_through: Optional[str] = Field(default=None, description="YYYY-MM-DD; requires effective_from")
    include_unchanged: bool = Field(default=False, description="Also return job events whose snapshots are identical")
    include_compensation: bool = Field(
        default=False,
        description="Also snapshot and diff compensation (wage, currency, frequency, package/grade/profile) "
        "and include compensation-change events",
    )


```

### `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py` (MODIFY) — tools
```python
# occurrences: 1 (verified: grep -c '    def _parse_job_profile(self, profile: Dict\[str, Any\]) -> Dict\[str, Any\]:' tool.py)
# BEFORE — insert above `    def _parse_job_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:` (verified: tool.py:1359)
    @tool_schema(GetWorkerEventHistoryInput)
    async def wd_get_worker_event_history(
        self,
        worker_id: str,
        worker_id_type: Optional[str] = None,
        effective_from: Optional[str] = None,
        effective_through: Optional[str] = None,
        updated_from: Optional[str] = None,
        updated_through: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get the Workday event history of a worker (hire, change job, organization
        assignment, time entry, time off, benefits, ...).

        Returns one dict per event with event_id, event_type, description,
        effective_date and completed_at, sorted by effective date. Events are
        references only: use wd_get_worker_job_changes to see what a job change changed.
        """
        if not self._initialized:
            await self.wd_start()
        svc = await self._get_composable("get_worker_event_history")
        # FILL IN: models = await svc.fetch_models("get_worker_event_history", worker_id=..., <all params>);
        #   return [m.model_dump(mode="json") for m in models] — bounded by AC "json.dumps accepts".

    @tool_schema(GetWorkerJobChangesInput)
    async def wd_get_worker_job_changes(
        self,
        worker_id: str,
        worker_id_type: Optional[str] = None,
        effective_from: Optional[str] = None,
        effective_through: Optional[str] = None,
        include_unchanged: bool = False,
        include_compensation: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Get a worker's job changes over time: position, job profile, business title,
        location, supervisory organization, cost center, company, pay group and manager,
        and optionally compensation (include_compensation=True).

        Returns one dict per effective date with kind ("hire" | "change" | "no_change"),
        the triggering events, the before/after job snapshots and the list of changed fields.
        """
        if not self._initialized:
            await self.wd_start()
        svc = await self._get_composable("get_worker_job_changes")
        # FILL IN: same delegation for "get_worker_job_changes" with all six params.

```
**Why**: identical shape to `wd_get_position`, so the composable cache, lazy start and error surface
stay uniform across the toolkit.

### `packages/ai-parrot-tools/tests/workday/test_worker_history_toolkit.py` (CREATE)
```python
"""FEAT-706 — worker-history toolkit tools (stubbed composable)."""
import json
from datetime import date, datetime

import pytest

from parrot_tools.interfaces.workday.models.worker_event import FieldChange, JobChange, JobSnapshot, WorkerEvent
from parrot_tools.workday.tool import WorkdayToolkit


class _FakeComposable:
    def __init__(self, models):
        self.models = models
        self.calls = []
        self.requested_ops = []

    async def fetch_models(self, operation_type, **params):
        self.calls.append((operation_type, params))
        return self.models


def _toolkit(monkeypatch, fake):  # pattern: test_position_job_profile.py:152-161
    tk = WorkdayToolkit()
    tk._initialized = True

    async def fake_get_composable(self, operation_type):
        fake.requested_ops.append(operation_type)
        return fake

    monkeypatch.setattr(WorkdayToolkit, "_get_composable", fake_get_composable)
    return tk


def test_tools_are_exposed():
    names = {t.name for t in WorkdayToolkit().get_tools()}
    assert {"wd_get_worker_event_history", "wd_get_worker_job_changes"} <= names


# FILL IN: test_wd_get_worker_event_history_delegates — requested_ops == ["get_worker_event_history"],
#   every param forwarded, result list[dict] with ISO date strings, json.dumps(result) works.
# FILL IN: test_wd_get_worker_job_changes_delegates — same for "get_worker_job_changes" with a nested JobChange,
#   include_compensation / include_unchanged forwarded.
```

### FILL IN checklist
- [ ] Both tool bodies — delegation + `model_dump(mode="json")`.
- [ ] The two delegate tests.

---

## Acceptance Criteria

- [ ] `WorkdayToolkit.get_tools()` exposes `wd_get_worker_event_history` and `wd_get_worker_job_changes`.
- [ ] Each tool calls `_get_composable` with its own key and forwards every parameter to `fetch_models`.
- [ ] Both return `list[dict]` that `json.dumps` accepts.
- [ ] Existing toolkit tests still pass.
- [ ] `ruff check` passes on `tool.py`.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/workday/test_worker_history_toolkit.py -q`
- `pytest packages/ai-parrot-tools/tests/workday/test_toolkit_delegates.py -q`
- `pytest packages/ai-parrot-tools/tests/workday/test_position_job_profile.py -q`

---

## Test Specification

See the test block in the Implementation Blueprint and spec §4 (M5 rows).

---

## Agent Instructions

1. Work in the feature worktree; TASK-4487 must be `done`.
2. Re-run `grep -c` on both anchors before editing (`tool.py` is large; insert, do not reformat).
3. Mark `in-progress`, implement from the blueprint, complete every `FILL IN`.
4. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`.
5. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4491 workday-worker-event-history-and-job-changes verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
