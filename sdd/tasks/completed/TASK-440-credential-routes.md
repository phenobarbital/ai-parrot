# TASK-440: Route Registration & Collection Setup

**Feature**: user-based-credentials
**Spec**: `sdd/specs/user-based-credentials.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-439
**Assigned-to**: unassigned

---

## Context

> This task wires up the CredentialsHandler to the application router and ensures
> the DocumentDB collection has proper indexes. Implements Module 4 from the spec (Section 3).

---

## Scope

- Register routes for `CredentialsHandler`:
  - `/api/v1/users/credentials` — GET (all), POST (create)
  - `/api/v1/users/credentials/{name}` — GET (single), PUT (update), DELETE (remove)
- Add a `setup_credentials_routes(app)` function that registers both routes
- Ensure the `user_credentials` DocumentDB collection has a compound unique index on `(user_id, name)`
- Integrate `setup_credentials_routes` into the application startup (find where other handlers are registered and add this one)

**NOT in scope**: handler implementation (TASK-439), data models (TASK-437)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/credentials.py` | MODIFY | Add `setup_credentials_routes(app)` function at bottom |
| Application setup file (find where handlers are registered) | MODIFY | Add call to `setup_credentials_routes(app)` |
| `tests/handlers/test_credential_routes.py` | CREATE | Test that routes are registered correctly |

---

## Implementation Notes

### Pattern to Follow
```python
# At the bottom of credentials.py
def setup_credentials_routes(app: web.Application) -> None:
    """Register credential management routes."""
    # List all + Create
    app.router.add_route("*", "/api/v1/users/credentials", CredentialsHandler)
    # Single credential by name
    app.router.add_route("*", "/api/v1/users/credentials/{name}", CredentialsHandler)
```

### Key Constraints
- Use `app.router.add_route("*", path, ViewClass)` for class-based views (BaseView handles method dispatch)
- Alternatively, if other handlers use individual method registration, follow that pattern
- The `{name}` path parameter must match what `self.request.match_info.get('name')` expects in the handler
- Find the application startup/setup location by searching for where other handler routes are registered (e.g., `ChatHandler`, `AgentTalk`)
- Collection index creation can be done as an async startup hook or documented as a manual step

### References in Codebase
- `parrot/a2a/server.py` — route registration pattern with `app.router.add_*`
- `parrot/handlers/chat.py` — how ChatHandler routes are registered
- Application entry point — where handlers are wired up

---

## Acceptance Criteria

- [ ] `/api/v1/users/credentials` route responds to GET and POST
- [ ] `/api/v1/users/credentials/{name}` route responds to GET, PUT, and DELETE
- [ ] Routes are registered during application startup
- [ ] `user_credentials` collection has compound unique index on `(user_id, name)` (or documented setup step)
- [ ] Tests verify routes are registered: `pytest tests/handlers/test_credential_routes.py -v`

---

## Test Specification

```python
# tests/handlers/test_credential_routes.py
import pytest
from aiohttp import web
from parrot.handlers.credentials import setup_credentials_routes


class TestCredentialRoutes:
    def test_routes_registered(self):
        """Verify all credential routes are registered on the app."""
        app = web.Application()
        setup_credentials_routes(app)
        routes = [r.resource.canonical for r in app.router.routes() if hasattr(r, 'resource')]
        assert "/api/v1/users/credentials" in routes
        assert "/api/v1/users/credentials/{name}" in routes
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/user-based-credentials.spec.md` for full context
2. **Check dependencies** — verify TASK-439 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Find** where other handler routes are registered in the app startup
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-440-credential-routes.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-03-25
**Notes**: Added `setup_credentials_routes` to `parrot/manager/manager.py` imports and call site. Added `setup_credentials_routes()` call before swagger setup. All 5 route registration tests pass. Collection index setup is documented as a manual step (requires live DocumentDB).

**Deviations from spec**: `user_credentials` collection compound unique index on `(user_id, name)` is not created programmatically at startup. This is a DocumentDB admin step documented here. Implementation uses DocumentDB's natural uniqueness via query-before-write in POST.
