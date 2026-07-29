---
type: Wiki Overview
title: 'TASK-1041: Route registration'
id: doc:sdd-tasks-completed-task-1041-route-registration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.handlers.agents.ephemeral import EphemeralUserAgentHandler #
  TASK-1040 creates this'
relates_to:
- concept: mod:parrot.handlers.agents.ephemeral
  rel: mentions
- concept: mod:parrot.handlers.tools_catalog
  rel: mentions
---

# TASK-1041: Route registration

**Feature**: FEAT-149 — Ephemeral User Agents
**Spec**: `sdd/specs/ephemeral-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1040, TASK-1039
**Assigned-to**: unassigned

---

## Context

> All new HTTP routes must be registered on the aiohttp app (spec §3 Module 5). The
> registration happens in `BotManager` around line 1042 where `/api/v1/user_agents` routes
> are currently added. This task wires the four ephemeral routes and the tools catalog route.

---

## Scope

- Register the following routes in `BotManager`'s route setup method:
  - `POST /api/v1/agents/user/` → `EphemeralUserAgentHandler`
  - `GET /api/v1/agents/user/{chatbot_id}/status` → `EphemeralUserAgentHandler`
  - `PUT /api/v1/agents/user/{chatbot_id}` → `EphemeralUserAgentHandler`
  - `DELETE /api/v1/agents/user/{chatbot_id}` → `EphemeralUserAgentHandler`
  - `GET /api/v1/tools/catalog` → `ToolCatalogHandler`
- Ensure the ephemeral routes do NOT conflict with existing `/api/v1/user_agents` routes.
- Write a smoke test verifying the routes are registered and reachable.

**NOT in scope**: Handler implementation (TASK-1040), tool catalog implementation (TASK-1039).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/manager/manager.py` | MODIFY | Add route registrations (~line 1042) |
| `tests/unit/test_ephemeral_routes.py` | CREATE | Smoke tests for route registration |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.agents.ephemeral import EphemeralUserAgentHandler  # TASK-1040 creates this
from parrot.handlers.tools_catalog import ToolCatalogHandler             # TASK-1039 creates this
```

### Existing Signatures to Use
```python
# parrot/manager/manager.py — route registration pattern (~line 1040-1048):
router = self.app.router
router.add_view('/api/v1/user_agents', UserAgentHandler)             # line 1042
router.add_view('/api/v1/user_agents/{chatbot_id}', UserAgentHandler) # line 1046
```

### Does NOT Exist
- ~~`/api/v1/agents/user/`~~ — does not exist yet; this task registers it.
- ~~`/api/v1/tools/catalog`~~ — does not exist yet; this task registers it.

---

## Implementation Notes

### Pattern to Follow
```python
# Add after the existing user_agents routes (~line 1048):
# Ephemeral user agents (FEAT-149)
router.add_view(
    '/api/v1/agents/user',
    EphemeralUserAgentHandler,
)
router.add_view(
    '/api/v1/agents/user/{chatbot_id}',
    EphemeralUserAgentHandler,
)
router.add_view(
    '/api/v1/agents/user/{chatbot_id}/status',
    EphemeralUserAgentHandler,
)
# Tool catalog (FEAT-149)
router.add_view(
    '/api/v1/tools/catalog',
    ToolCatalogHandler,
)
```

### Key Constraints
- The `{chatbot_id}/status` route MUST be registered as a separate view path so aiohttp routes GET to the status method correctly. If using class-based views, the handler must dispatch based on the path match.
- Do NOT modify existing `/api/v1/user_agents` routes.
- Import the new handler classes at the top of the route-setup section (or use lazy imports consistent with the existing pattern).

### References in Codebase
- `parrot/manager/manager.py:1040-1048` — existing route registration for `UserAgentHandler`

---

## Acceptance Criteria

- [ ] All five routes are registered and reachable (200/201/204 for valid requests).
- [ ] Existing `/api/v1/user_agents` routes still work (no conflict).
- [ ] `GET /api/v1/agents/user/{id}/status` routes correctly (doesn't match `PUT /api/v1/agents/user/{id}`).
- [ ] All tests pass: `pytest tests/unit/test_ephemeral_routes.py -v`
- [ ] No linting errors: `ruff check parrot/manager/manager.py`

---

## Test Specification

```python
# tests/unit/test_ephemeral_routes.py
import pytest


class TestEphemeralRouteRegistration:
    async def test_post_agents_user_route_exists(self, aiohttp_client):
        resp = await client.post("/api/v1/agents/user/", json={})
        assert resp.status != 404  # Route exists (may be 401/400)

    async def test_get_status_route_exists(self, aiohttp_client):
        resp = await client.get("/api/v1/agents/user/fake-id/status")
        assert resp.status != 404

    async def test_put_promote_route_exists(self, aiohttp_client):
        resp = await client.put("/api/v1/agents/user/fake-id")
        assert resp.status != 404

    async def test_delete_route_exists(self, aiohttp_client):
        resp = await client.delete("/api/v1/agents/user/fake-id")
        assert resp.status != 404

    async def test_tools_catalog_route_exists(self, aiohttp_client):
        resp = await client.get("/api/v1/tools/catalog")
        assert resp.status != 404

    async def test_existing_user_agents_routes_unaffected(self, aiohttp_client):
        # Existing routes still resolve
        resp = await client.get("/api/v1/user_agents")
        assert resp.status != 404
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/ephemeral-agents.spec.md` §3 Module 5.
2. **Check dependencies** — TASK-1040 and TASK-1039 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — read `manager.py` around line 1040 for the route pattern.
4. **Update status** in `sdd/tasks/index/ephemeral-agents.json` → `"in-progress"`
5. **Implement** route registrations.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-05-07
**Notes**: Added `EphemeralUserAgentHandler` and `ToolCatalogHandler` imports to manager.py.
Registered 4 ephemeral routes + 1 tool catalog route. The `{chatbot_id}/status`
sub-route is placed before the bare `{chatbot_id}` route to avoid shadowing.
All 6 smoke tests pass.

**Deviations from spec**: none
