# TASK-1773: CrewExecutionHistoryHandler

**Feature**: FEAT-306 — AgentCrew Saved Crews (Execution Persistence & Replay)
**Spec**: `sdd/specs/agentcrew-saved-crews.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1772, TASK-1767
**Assigned-to**: unassigned

---

## Context

This is the HTTP layer that exposes saved execution operations via REST. It wires
aiohttp routes to `SavedExecutionService` methods and handles request parsing,
response serialization, and error-to-HTTP-status mapping.

Implements spec Module 9.

---

## Scope

- Create `CrewExecutionHistoryHandler(BaseView)` at path `/api/v1/crew/executions`:
  - `GET /api/v1/crew/executions` — list executions with query params
    (crew_name, method, date_from, date_to, limit, offset)
  - `GET /api/v1/crew/executions/{execution_id}` — get execution detail
  - `POST /api/v1/crew/executions/{execution_id}/replay` — replay execution
  - `POST /api/v1/crew/executions/{execution_id}/schedule` — schedule execution
  - `DELETE /api/v1/crew/executions/{execution_id}` — delete execution
- Extract tenant and user_id from request context (follow existing handler patterns)
- Convert service exceptions to appropriate HTTP responses (404, 400, 500)
- Update `packages/ai-parrot-server/src/parrot/handlers/crew/__init__.py` to export
  the new handler
- Write unit/integration tests

**NOT in scope**: Service logic (TASK-1772), storage logic (previous tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/crew/execution_history_handler.py` | CREATE | HTTP handler |
| `packages/ai-parrot-server/src/parrot/handlers/crew/__init__.py` | MODIFY | Add export |
| `tests/unit/test_execution_history_handler.py` | CREATE | Handler tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Handler base class:
from navigator.views import BaseView  # used by CrewExecutionHandler
from navigator.types import WebApp  # used by CrewExecutionHandler

# Logging:
from navconfig.logging import logging

# Service (created in TASK-1772):
# from parrot.handlers.crew.saved_execution_service import SavedExecutionService

# Models (created in TASK-1767):
# from parrot.handlers.crew.models import (
#     ExecutionFilter, ExecutionSummary, ExecutionDetail,
#     ScheduleRequest, PaginatedResponse,
# )
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/crew/execution_handler.py:15
class CrewExecutionHandler(BaseView):
    path: str = '/api/v1/crews'  # line 27
    app: WebApp = None
    _active_crews: dict = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger('Parrot.CrewExecutionHandler')
        self._bot_manager = None
        self.job_manager = self.app['job_manager'] if 'job_manager' in self.app else JobManager()

    @property
    def bot_manager(self):
        if not self._bot_manager:
            app = self.request.app
            self._bot_manager = app['bot_manager'] if 'bot_manager' in app else None
        return self._bot_manager

# __init__.py exports:
from .handler import CrewHandler
from .execution_handler import CrewExecutionHandler
from .tool_catalog import CrewToolCatalogHandler
__all__ = ('CrewHandler', 'CrewExecutionHandler', 'CrewToolCatalogHandler')
```

### Does NOT Exist
- ~~`CrewExecutionHistoryHandler`~~ — does not exist yet; this task creates it
- ~~`/api/v1/crew/executions` route~~ — not registered yet

---

## Implementation Notes

### Pattern to Follow
Follow `CrewExecutionHandler` patterns for handler structure:

```python
from navigator.views import BaseView
from navigator.types import WebApp
from navconfig.logging import logging


class CrewExecutionHistoryHandler(BaseView):
    path: str = '/api/v1/crew/executions'
    app: WebApp = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger('Parrot.CrewExecutionHistoryHandler')
        self._service = None

    @property
    def service(self):
        if self._service is None:
            # Initialize with storage from app config, bot_manager, scheduler
            ...
        return self._service

    async def get(self):
        """List executions or get detail."""
        execution_id = self.request.match_info.get('execution_id')
        if execution_id:
            return await self._get_detail(execution_id)
        return await self._list()

    async def post(self):
        """Replay or schedule an execution."""
        execution_id = self.request.match_info.get('execution_id')
        action = self.request.match_info.get('action')  # 'replay' or 'schedule'
        ...

    async def delete(self):
        """Delete an execution."""
        ...
```

### Key Constraints
- Route patterns need sub-routes for `{execution_id}` and `{execution_id}/{action}`
- Tenant extraction: check how other handlers get tenant from request (likely from
  auth context or query param)
- User ID extraction: from auth token or request context
- Response format: JSON with appropriate content-type headers
- Error mapping: ValueError → 400, not found → 404, other → 500

---

## Acceptance Criteria

- [ ] Handler registered at `/api/v1/crew/executions`
- [ ] `GET` without ID returns paginated list
- [ ] `GET` with ID returns execution detail
- [ ] `POST .../replay` triggers replay via service
- [ ] `POST .../schedule` creates schedule via service
- [ ] `DELETE` removes execution via service
- [ ] 404 returned when execution/crew not found
- [ ] 400 returned when prompt missing for replay
- [ ] Handler exported from `__init__.py`
- [ ] Tests pass
- [ ] No linting errors

---

## Test Specification

```python
# tests/unit/test_execution_history_handler.py
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestCrewExecutionHistoryHandler:
    async def test_list_executions(self):
        """GET / returns paginated list."""

    async def test_get_execution_detail(self):
        """GET /{id} returns full execution."""

    async def test_get_not_found(self):
        """GET /{id} returns 404 for missing execution."""

    async def test_replay_success(self):
        """POST /{id}/replay triggers replay."""

    async def test_replay_crew_not_found(self):
        """POST /{id}/replay returns 404 for deleted crew."""

    async def test_replay_no_prompt(self):
        """POST /{id}/replay returns 400 for missing prompt."""

    async def test_schedule_success(self):
        """POST /{id}/schedule creates APScheduler job."""

    async def test_delete_success(self):
        """DELETE /{id} removes execution."""

    async def test_delete_not_found(self):
        """DELETE /{id} returns 404 for missing execution."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1772 and TASK-1767 must be completed
3. **Verify the Codebase Contract** — study CrewExecutionHandler for patterns
4. **Update status** in `sdd/tasks/index/agentcrew-saved-crews.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1773-execution-history-handler.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
