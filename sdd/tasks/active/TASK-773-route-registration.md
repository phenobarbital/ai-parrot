# TASK-773: Route Registration — Wire MCPHelperHandler into App Routes

**Feature**: FEAT-110 — MCP Mixin Helper Handler
**Spec**: `sdd/specs/mcp-mixin-helper-handler.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-771
**Assigned-to**: unassigned

---

## Context

This is the final wiring task. The `MCPHelperHandler` and its
`setup_mcp_helper_routes` function exist (created by TASK-771), but the routes
are not yet registered in the application. This task adds the registration call
to `BotManager.setup_routes()` so the endpoints are live.

Implements spec Section 3, Module 5.

---

## Scope

- Import `setup_mcp_helper_routes` in `parrot/manager/manager.py`.
- Call `setup_mcp_helper_routes(self.app)` in the route setup method, adjacent to the
  existing `setup_credentials_routes(self.app)` call.
- Verify the routes are reachable (import test).

**NOT in scope**: Handler implementation (TASK-771), persistence (TASK-770), registry (TASK-769).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/manager/manager.py` | MODIFY | Import and call `setup_mcp_helper_routes` |
| `tests/unit/test_mcp_route_registration.py` | CREATE | Verify routes are registered |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot/manager/manager.py — existing import pattern (line 62)
from ..handlers.credentials import setup_credentials_routes  # verified: manager.py:62

# New import to add:
from ..handlers.mcp_helper import setup_mcp_helper_routes  # created by TASK-771
```

### Existing Signatures to Use
```python
# parrot/manager/manager.py — route registration location (line 862)
# Inside the setup method, after:
setup_credentials_routes(self.app)  # line 862
# Add:
setup_mcp_helper_routes(self.app)  # NEW

# parrot/handlers/mcp_helper.py (created by TASK-771)
def setup_mcp_helper_routes(app: web.Application) -> None: ...

# parrot/handlers/credentials.py — reference pattern (line 506-523)
def setup_credentials_routes(app: web.Application) -> None:
    app.router.add_route("*", "/api/v1/users/credentials", CredentialsHandler)
    app.router.add_route("*", "/api/v1/users/credentials/{name}", CredentialsHandler)
```

### Does NOT Exist
- ~~`setup_mcp_helper_routes` in `parrot/handlers/__init__.py`~~ — function lives in `mcp_helper.py`, not `__init__.py`
- ~~`self.setup_mcp_routes()`~~ — no such method on BotManager; it's a standalone function
- ~~`app.include_router()`~~ — this is Flask/FastAPI; aiohttp uses `app.router.add_route()`

---

## Implementation Notes

### Exact Insertion Point
```python
# parrot/manager/manager.py, around line 862:

        # User credential management routes
        setup_credentials_routes(self.app)
        # MCP helper routes (discovery, activation, management)
        setup_mcp_helper_routes(self.app)  # <-- ADD THIS LINE
        if self.enable_swagger_api:
```

### Key Constraints
- Import goes at the top of the file with other handler imports (near line 62)
- Call goes immediately after `setup_credentials_routes` (line 862)
- No conditional logic needed — routes should always be available when the app starts
- Keep the same comment style as existing route registrations

### References in Codebase
- `parrot/manager/manager.py:62` — import pattern
- `parrot/manager/manager.py:862` — call site

---

## Acceptance Criteria

- [ ] `setup_mcp_helper_routes` imported in `manager.py`
- [ ] `setup_mcp_helper_routes(self.app)` called after `setup_credentials_routes`
- [ ] Routes `/api/v1/agents/chat/{agent_id}/mcp-servers` etc. are registered
- [ ] Application starts without import errors
- [ ] All tests pass: `pytest tests/unit/test_mcp_route_registration.py -v`

---

## Test Specification

```python
# tests/unit/test_mcp_route_registration.py
import pytest


class TestMCPRouteRegistration:
    def test_setup_mcp_helper_routes_importable(self):
        """Verify setup function can be imported."""
        from parrot.handlers.mcp_helper import setup_mcp_helper_routes
        assert callable(setup_mcp_helper_routes)

    def test_routes_registered(self):
        """Verify routes are added to app router."""
        from aiohttp import web
        from parrot.handlers.mcp_helper import setup_mcp_helper_routes

        app = web.Application()
        setup_mcp_helper_routes(app)

        routes = [r.resource.canonical for r in app.router.routes() if hasattr(r, 'resource')]
        assert any("mcp-servers" in r for r in routes)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-771 is in `tasks/completed/`
3. **Verify the Codebase Contract** — read `manager.py` lines 60-65 and 860-865 to confirm structure
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — this is a small wiring task; two lines of code plus a test
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-773-route-registration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
