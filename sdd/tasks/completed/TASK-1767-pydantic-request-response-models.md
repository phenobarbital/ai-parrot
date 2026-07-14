# TASK-1767: Pydantic Request/Response Models

**Feature**: FEAT-306 — AgentCrew Saved Crews (Execution Persistence & Replay)
**Spec**: `sdd/specs/agentcrew-saved-crews.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The REST API for saved executions needs Pydantic models for request parsing and
response serialization. These models are used by the handler (TASK-1773) and
service (TASK-1772). Creating them early with no dependencies allows other tasks
to import them.

Implements spec Module 7.

---

## Scope

- Add the following Pydantic models to the crew handler models file:
  - `ExecutionFilter` — filters for listing (crew_name, method, date_from, date_to)
  - `ExecutionSummary` — summary for list responses (id, crew_name, method, prompt, user_id, tenant, timestamp, status)
  - `ExecutionDetail(ExecutionSummary)` — full record with session_id and payload
  - `ReplayRequest` — empty body for replay (future extension point)
  - `ScheduleRequest` — schedule_type, schedule_config, created_by, created_email, metadata, callbacks
  - `PaginatedResponse` — items, total, limit, offset

**NOT in scope**: Handler or service logic (TASK-1772, TASK-1773).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/crew/models.py` | MODIFY | Add new Pydantic models |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Existing imports in models.py:
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

# Existing models in the file:
from parrot.models.crew_definition import ExecutionMode  # re-exported
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/crew/models.py
class JobStatus(str, Enum): ...  # line 25
class CrewQueryRequest(BaseModel): ...  # line 35
class CrewJob: ...  # line 65 (dataclass)
class CrewListResponse(BaseModel): ...  # line 108
class CrewJobResponse(BaseModel): ...  # line 117
class CrewJobStatusResponse(BaseModel): ...  # line 128
```

### Does NOT Exist
- ~~`ExecutionFilter`~~ — does not exist yet; this task creates it
- ~~`ExecutionSummary`~~ — does not exist yet
- ~~`ExecutionDetail`~~ — does not exist yet
- ~~`ScheduleRequest`~~ — does not exist yet
- ~~`PaginatedResponse`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
Follow the existing model patterns in `models.py` — Pydantic `BaseModel` with
`Field` descriptions. See `CrewQueryRequest` and `CrewJobResponse` for examples.

```python
class ExecutionFilter(BaseModel):
    crew_name: Optional[str] = None
    method: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None

class ExecutionSummary(BaseModel):
    id: str
    crew_name: str
    method: str
    prompt: Optional[str] = None
    user_id: Optional[str] = None
    tenant: str = "global"
    timestamp: datetime
    status: str = "success"

class ExecutionDetail(ExecutionSummary):
    session_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

class ReplayRequest(BaseModel):
    pass

class ScheduleRequest(BaseModel):
    schedule_type: str
    schedule_config: Dict[str, Any]
    created_by: Optional[int] = None
    created_email: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    callbacks: Optional[List[Dict[str, Any]]] = None

class PaginatedResponse(BaseModel):
    items: List[ExecutionSummary]
    total: int
    limit: int
    offset: int
```

### Key Constraints
- Use Google-style docstrings on each model
- Follow existing naming conventions in the file

---

## Acceptance Criteria

- [ ] All six models added to `models.py`
- [ ] Models use proper type hints and Field descriptions
- [ ] `ExecutionDetail` inherits from `ExecutionSummary`
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/crew/models.py`
- [ ] Import works: `from parrot.handlers.crew.models import ExecutionFilter, ExecutionSummary, ScheduleRequest`

---

## Test Specification

```python
# tests/unit/test_execution_models.py
import pytest
from datetime import datetime


class TestExecutionModels:
    def test_execution_filter_defaults(self):
        from parrot.handlers.crew.models import ExecutionFilter
        f = ExecutionFilter()
        assert f.crew_name is None
        assert f.method is None

    def test_execution_summary_required_fields(self):
        from parrot.handlers.crew.models import ExecutionSummary
        s = ExecutionSummary(id="abc", crew_name="test", method="run_sequential", timestamp=datetime.now())
        assert s.tenant == "global"
        assert s.status == "success"

    def test_execution_detail_inherits_summary(self):
        from parrot.handlers.crew.models import ExecutionDetail
        d = ExecutionDetail(id="abc", crew_name="test", method="run", timestamp=datetime.now())
        assert d.payload == {}

    def test_schedule_request_required_fields(self):
        from parrot.handlers.crew.models import ScheduleRequest
        s = ScheduleRequest(schedule_type="DAILY", schedule_config={"hour": 9})
        assert s.schedule_type == "DAILY"

    def test_paginated_response(self):
        from parrot.handlers.crew.models import PaginatedResponse, ExecutionSummary
        p = PaginatedResponse(items=[], total=0, limit=20, offset=0)
        assert p.total == 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm existing models in models.py
4. **Update status** in `sdd/tasks/index/agentcrew-saved-crews.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1767-pydantic-request-response-models.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: Added all six models (`ExecutionFilter`, `ExecutionSummary`,
`ExecutionDetail(ExecutionSummary)`, `ReplayRequest`, `ScheduleRequest`,
`PaginatedResponse`) to `packages/ai-parrot-server/src/parrot/handlers/crew/models.py`,
following the existing `Field(description=...)` + Google-style docstring
convention used by `CrewQueryRequest`/`CrewJobResponse`. Created
`tests/unit/test_execution_models.py` exactly per the task's Test Specification
(5 tests, all passing). `ruff check` clean; all six models import cleanly.

**Deviations from spec**: none
