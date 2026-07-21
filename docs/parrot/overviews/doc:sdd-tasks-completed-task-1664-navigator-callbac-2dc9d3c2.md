---
type: Wiki Overview
title: 'TASK-1664: Navigator Callback Route'
id: doc:sdd-tasks-completed-task-1664-navigator-callback-route-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Adds an MCP-specific OAuth2 callback handler to Navigator at
relates_to:
- concept: mod:parrot.auth.oauth2_routes
  rel: mentions
---

# TASK-1664: Navigator Callback Route

**Feature**: FEAT-262 — MCP Server OAuth2 Support
**Spec**: `sdd/specs/mcp-server-oauth2-support.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1660, TASK-1663
**Assigned-to**: unassigned

---

## Context

Adds an MCP-specific OAuth2 callback handler to Navigator at
`/api/auth/oauth2/mcp/callback`. When the user completes the browser-based
authorization, this route receives the authorization code and dispatches it
to the correct `OAuthContext` (identified by the `state` parameter) so the
transport can complete the token exchange. Implements spec Module 6.

---

## Scope

- Extend `setup_oauth2_routes()` in `parrot/auth/oauth2_routes.py` to register
  the MCP callback route at `/api/auth/oauth2/mcp/callback`
- The callback handler must:
  - Extract `code` and `state` from query params
  - Look up the pending OAuth2 context by `state` (via a module-level registry
    or shared dict that TASK-1663 populates)
  - Signal the `callback_handler` in `OAuthContext` with `(code, state)`
  - Return an HTML response: "Authentication complete. You can close this window."
  - Handle errors: missing code, invalid state, expired context
- Write unit tests

**NOT in scope**: The OAuth2 flow itself (TASK-1663), provider registration
(TASK-1661), or OAuthManager removal (TASK-1665).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2_routes.py` | MODIFY | Add MCP callback route |
| `tests/auth/test_mcp_oauth2_callback.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Existing OAuth2 routes (verified: parrot/auth/oauth2_routes.py)
from parrot.auth.oauth2_routes import setup_oauth2_routes  # line 199

# aiohttp web framework
from aiohttp import web
```

### Existing Signatures to Use
```python
# parrot/auth/oauth2_routes.py:199
def setup_oauth2_routes(
    app: web.Application,
    ...
) -> None:
    # Mounts callback routes on the Navigator app

# parrot/auth/oauth2_routes.py:74
async def _handle_web_callback(
    request: web.Request,
    provider_id: str,
    ...
) -> web.Response:
    # Pattern to follow for the MCP callback
```

### Does NOT Exist
- ~~`/api/auth/oauth2/mcp/callback` route~~ — does not exist yet (being added)
- ~~`parrot.auth.oauth2_routes.mcp_callback_handler`~~ — does not exist yet

---

## Implementation Notes

### Coordination with TASK-1663
The transport (TASK-1663) creates a `callback_handler` that awaits an `asyncio.Event`.
This callback route must signal that event. The coordination mechanism is a module-level
dict mapping `state` → `(asyncio.Event, result_dict)`:

```python
# Shared between transport and callback route
_pending_mcp_callbacks: dict[str, tuple[asyncio.Event, dict]] = {}

async def handle_mcp_oauth2_callback(request: web.Request) -> web.Response:
    state = request.query.get("state")
    code = request.query.get("code")
    error = request.query.get("error")

    if error:
        return web.Response(status=400, text=f"OAuth2 error: {error}")
    if not state or state not in _pending_mcp_callbacks:
        return web.Response(status=400, text="Invalid or expired OAuth2 state")
    if not code:
        return web.Response(status=400, text="Missing authorization code")

    event, result = _pending_mcp_callbacks.pop(state)
    result["code"] = code
    result["state"] = state
    event.set()

    return web.Response(
        content_type="text/html",
        text="<html><body><h3>Authentication complete. You can close this window.</h3></body></html>"
    )
```

### Key Constraints
- Route path: `/api/auth/oauth2/mcp/callback` (consistent with existing OAuth2 routes)
- Must handle error responses from OAuth2 server (`error` query param)
- State lookup must be timing-safe (pop from dict to prevent replay)
- The shared `_pending_mcp_callbacks` dict should be in a place both the transport
  and callback route can import (e.g., `parrot/mcp/oauth2_storage.py` or a new
  `parrot/mcp/oauth2_state.py`)

---

## Acceptance Criteria

- [ ] Route registered at `/api/auth/oauth2/mcp/callback`
- [ ] Valid callback with `code` and `state` signals the pending context
- [ ] Invalid/missing state returns 400
- [ ] Missing code returns 400
- [ ] OAuth2 error parameter handled gracefully
- [ ] HTML response rendered on success
- [ ] All tests pass: `pytest tests/auth/test_mcp_oauth2_callback.py -v`

---

## Test Specification

```python
# tests/auth/test_mcp_oauth2_callback.py
import pytest
import asyncio
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop


class TestMCPOAuth2Callback:
    @pytest.mark.asyncio
    async def test_valid_callback(self):
        """Valid code + state signals the pending event."""
        ...

    @pytest.mark.asyncio
    async def test_invalid_state(self):
        """Unknown state returns 400."""
        ...

    @pytest.mark.asyncio
    async def test_missing_code(self):
        """Missing code returns 400."""
        ...

    @pytest.mark.asyncio
    async def test_error_response(self):
        """OAuth2 error param returns 400 with error message."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1660 and TASK-1663 are completed
3. **Verify the Codebase Contract** — READ `parrot/auth/oauth2_routes.py`
4. **Coordinate** with TASK-1663's callback mechanism
5. **Implement** the callback route
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-26
**Notes**: Added handle_mcp_oauth2_callback() and setup_mcp_oauth2_callback()
to parrot/auth/oauth2_routes.py. Uses oauth2_state.py for shared state coordination.
Handles error params, missing state, missing code, replay prevention (pop from dict).
All 10 tests pass.

**Deviations from spec**: Idempotency check uses app.router.resources() instead of
app.router.routes() to avoid double-counting GET+HEAD route pairs.
