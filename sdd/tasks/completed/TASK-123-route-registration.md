# TASK-123: DatasetManagerHandler Route Registration

**Feature**: DatasetManager Support for AgentTalk Handler
**Spec**: `sdd/specs/dataset-support-agenttalk.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (1h)
**Depends-on**: TASK-122
**Assigned-to**: null

---

## Context

> This task implements Module 5 from the spec: Route Registration.

Register the `DatasetManagerHandler` routes in the application's route configuration.

---

## Scope

- Add `DatasetManagerHandler` import to handlers `__init__.py`
- Register routes at `/api/v1/agents/datasets/{agent_id}`
- Support all HTTP methods: GET, PATCH, PUT, POST, DELETE

**NOT in scope**:
- Handler implementation (that's TASK-122)
- API documentation (P2)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/__init__.py` | MODIFY | Export DatasetManagerHandler |
| Route configuration file | MODIFY | Register handler routes |

---

## Implementation Notes

### Route Pattern
The route should follow the existing pattern for agent-related endpoints:
```
/api/v1/agents/datasets/{agent_id}
```

### Find Existing Route Registration
First, find where routes are currently registered:
```bash
grep -r "AgentTalk" parrot/handlers/ --include="*.py" -l
grep -r "add_route" parrot/ --include="*.py" | head -20
```

### Example Registration (Navigator pattern)
```python
# In handlers/__init__.py or route setup file
from .datasets import DatasetManagerHandler

# Route registration (pattern depends on Navigator framework)
# Option A: Class-based view with automatic method routing
app.router.add_view('/api/v1/agents/datasets/{agent_id}', DatasetManagerHandler)

# Option B: Individual method routes
app.router.add_route('GET', '/api/v1/agents/datasets/{agent_id}', DatasetManagerHandler)
app.router.add_route('PATCH', '/api/v1/agents/datasets/{agent_id}', DatasetManagerHandler)
app.router.add_route('PUT', '/api/v1/agents/datasets/{agent_id}', DatasetManagerHandler)
app.router.add_route('POST', '/api/v1/agents/datasets/{agent_id}', DatasetManagerHandler)
app.router.add_route('DELETE', '/api/v1/agents/datasets/{agent_id}', DatasetManagerHandler)
```

### References in Codebase
- `parrot/handlers/__init__.py` — existing handler exports
- Look for where `AgentTalk` routes are registered

---

## Acceptance Criteria

- [ ] `DatasetManagerHandler` exported from `parrot/handlers/__init__.py`
- [ ] Routes registered at `/api/v1/agents/datasets/{agent_id}`
- [ ] GET method accessible at the route
- [ ] PATCH method accessible at the route
- [ ] PUT method accessible at the route
- [ ] POST method accessible at the route
- [ ] DELETE method accessible at the route
- [ ] Route accessible only with authentication (inherited from decorator)

---

## Test Specification

```python
# tests/handlers/test_dataset_routes.py
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase


class TestDatasetRoutes(AioHTTPTestCase):
    """Test that routes are properly registered."""

    async def get_application(self):
        # Set up test app with routes
        pass

    async def test_get_route_exists(self):
        """GET /api/v1/agents/datasets/{agent_id} is routed."""
        resp = await self.client.request("GET", "/api/v1/agents/datasets/test-agent")
        assert resp.status != 404  # Route exists (may need auth)

    async def test_patch_route_exists(self):
        """PATCH /api/v1/agents/datasets/{agent_id} is routed."""
        resp = await self.client.request("PATCH", "/api/v1/agents/datasets/test-agent")
        assert resp.status != 404

    async def test_put_route_exists(self):
        """PUT /api/v1/agents/datasets/{agent_id} is routed."""
        resp = await self.client.request("PUT", "/api/v1/agents/datasets/test-agent")
        assert resp.status != 404

    async def test_post_route_exists(self):
        """POST /api/v1/agents/datasets/{agent_id} is routed."""
        resp = await self.client.request("POST", "/api/v1/agents/datasets/test-agent")
        assert resp.status != 404

    async def test_delete_route_exists(self):
        """DELETE /api/v1/agents/datasets/{agent_id} is routed."""
        resp = await self.client.request("DELETE", "/api/v1/agents/datasets/test-agent")
        assert resp.status != 404
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-122 is in `tasks/completed/`
3. **Find existing route registration pattern** — look at how AgentTalk is registered
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-123-route-registration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude session
**Date**: 2026-03-03
**Notes**:
- Added `DatasetManagerHandler` import to `parrot/manager/manager.py`
- Registered route at `/api/v1/agents/datasets/{agent_id}` using `router.add_view()`
- Added lazy import export in `parrot/handlers/__init__.py`
- Created 15 route registration tests in `tests/handlers/test_dataset_routes.py`
- All 41 dataset-related tests pass (26 handler + 15 routes)
