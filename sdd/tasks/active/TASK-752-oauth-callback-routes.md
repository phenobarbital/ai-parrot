# TASK-752: OAuth Callback HTTP Routes

**Feature**: FEAT-107 — Jira OAuth 2.0 (3LO) Per-User Authentication
**Spec**: `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-751
**Assigned-to**: unassigned

---

## Context

Module 6 of the spec. After the user authorizes on Atlassian's consent page, the browser redirects to our callback URL. This task implements the aiohttp routes that receive the redirect, verify the CSRF state nonce, exchange the authorization code for tokens via `JiraOAuthManager`, and render a success/error HTML page.

---

## Scope

- Create aiohttp route handler for `GET /api/auth/jira/callback`.
- Verify `state` parameter against Redis nonce (via `JiraOAuthManager`).
- Exchange `code` for tokens via `JiraOAuthManager.handle_callback()`.
- Return HTML success page (browser-friendly, not JSON).
- Return HTML error page for invalid state, missing code, or exchange failure.
- Mount routes in `AutonomousOrchestrator.setup_routes()`.
- Write unit tests.

**NOT in scope**: Telegram notification after callback (TASK-754), AgenTalk hot-swap (TASK-755), JiraToolkit integration (TASK-753).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/routes.py` | CREATE | OAuth callback route handler |
| `packages/ai-parrot/src/parrot/autonomous/orchestrator.py` | MODIFY | Mount callback routes in setup_routes() |
| `packages/ai-parrot/tests/unit/test_oauth_callback_routes.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web  # verified: used throughout parrot/handlers/
from parrot.auth.jira_oauth import JiraOAuthManager  # created by TASK-751
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/autonomous/orchestrator.py:112
class AutonomousOrchestrator:
    def setup_routes(self, app):  # line 253
        # Currently mounts webhook_listener and hook_manager routes
        # Also mounts admin login page at /autonomous/admin
        # This task adds OAuth callback routes here

# Existing Telegram OAuth callback pattern to follow:
# packages/ai-parrot/src/parrot/integrations/telegram/oauth2_callback.py
# Uses aiohttp web.Response with HTML content-type
```

### Does NOT Exist
- ~~`parrot.auth.routes`~~ — module does NOT exist yet (this task creates it)
- ~~`/api/auth/jira/callback` route~~ — not mounted yet (this task adds it)

---

## Implementation Notes

### Route Handler
```python
# packages/ai-parrot/src/parrot/auth/routes.py
from aiohttp import web
from navconfig.logging import logging

logger = logging.getLogger(__name__)

_SUCCESS_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Jira Connected</title>
<style>body{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f5f5f5}
.container{text-align:center;padding:2rem}.check{font-size:3rem;color:#36b37e}</style>
</head><body><div class="container">
<div class="check">&#10003;</div>
<h2>Jira Connected</h2>
<p>Hi {display_name}! Your Jira account ({site_url}) is now linked.</p>
<p>You can close this window and return to your chat.</p>
</div></body></html>"""

_ERROR_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Authorization Failed</title>
<style>body{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f5f5f5}
.container{text-align:center;padding:2rem}.x{font-size:3rem;color:#de350b}</style>
</head><body><div class="container">
<div class="x">&#10007;</div>
<h2>Authorization Failed</h2>
<p>{error}</p>
</div></body></html>"""


async def jira_oauth_callback(request: web.Request) -> web.Response:
    code = request.query.get("code")
    state = request.query.get("state")

    if not code or not state:
        return web.Response(
            text=_ERROR_HTML.format(error="Missing code or state parameter."),
            content_type="text/html", status=400,
        )

    manager: JiraOAuthManager = request.app["jira_oauth_manager"]
    try:
        token_set = await manager.handle_callback(code, state)
    except ValueError as e:
        return web.Response(
            text=_ERROR_HTML.format(error=str(e)),
            content_type="text/html", status=400,
        )
    except Exception as e:
        logger.exception("OAuth callback error")
        return web.Response(
            text=_ERROR_HTML.format(error="An unexpected error occurred."),
            content_type="text/html", status=500,
        )

    return web.Response(
        text=_SUCCESS_HTML.format(
            display_name=token_set.display_name,
            site_url=token_set.site_url,
        ),
        content_type="text/html",
    )


def setup_jira_oauth_routes(app: web.Application):
    app.router.add_get("/api/auth/jira/callback", jira_oauth_callback)
```

### Mounting in Orchestrator
Add to `AutonomousOrchestrator.setup_routes()` after existing route setup:

```python
# Mount OAuth callback routes
if "jira_oauth_manager" in app:
    from parrot.auth.routes import setup_jira_oauth_routes
    setup_jira_oauth_routes(app)
```

### Key Constraints
- The route must be excluded from auth middleware (it's the auth endpoint itself).
- HTML responses, not JSON — the browser will render this page.
- Use `html.escape()` on any user-supplied content rendered in HTML to prevent XSS.
- The `JiraOAuthManager` instance must be stored on `app["jira_oauth_manager"]` at application startup (this task should document the requirement; actual initialization is at app startup).

---

## Acceptance Criteria

- [ ] `GET /api/auth/jira/callback?code=X&state=Y` returns success HTML on valid flow
- [ ] Missing code or state returns 400 with error HTML
- [ ] Invalid/expired state nonce returns 400
- [ ] Route is mounted via `setup_jira_oauth_routes(app)`
- [ ] `AutonomousOrchestrator.setup_routes()` conditionally mounts the routes
- [ ] No XSS in HTML templates (user content escaped)
- [ ] Tests pass: `pytest packages/ai-parrot/tests/unit/test_oauth_callback_routes.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_oauth_callback_routes.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop


class TestJiraOAuthCallback:
    @pytest.mark.asyncio
    async def test_missing_code_returns_400(self, aiohttp_client):
        from parrot.auth.routes import setup_jira_oauth_routes
        app = web.Application()
        app["jira_oauth_manager"] = MagicMock()
        setup_jira_oauth_routes(app)
        client = await aiohttp_client(app)
        resp = await client.get("/api/auth/jira/callback?state=abc")
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_missing_state_returns_400(self, aiohttp_client):
        from parrot.auth.routes import setup_jira_oauth_routes
        app = web.Application()
        app["jira_oauth_manager"] = MagicMock()
        setup_jira_oauth_routes(app)
        client = await aiohttp_client(app)
        resp = await client.get("/api/auth/jira/callback?code=abc")
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_valid_callback(self, aiohttp_client):
        from parrot.auth.routes import setup_jira_oauth_routes
        from parrot.auth.jira_oauth import JiraTokenSet

        mock_manager = MagicMock()
        token = JiraTokenSet(
            access_token="at", refresh_token="rt", expires_at=9999999999,
            cloud_id="c", site_url="https://test.atlassian.net",
            account_id="a", display_name="Test User",
        )
        mock_manager.handle_callback = AsyncMock(return_value=token)

        app = web.Application()
        app["jira_oauth_manager"] = mock_manager
        setup_jira_oauth_routes(app)
        client = await aiohttp_client(app)
        resp = await client.get("/api/auth/jira/callback?code=x&state=y")
        assert resp.status == 200
        text = await resp.text()
        assert "Test User" in text

    @pytest.mark.asyncio
    async def test_invalid_state_returns_400(self, aiohttp_client):
        from parrot.auth.routes import setup_jira_oauth_routes

        mock_manager = MagicMock()
        mock_manager.handle_callback = AsyncMock(side_effect=ValueError("Invalid nonce"))

        app = web.Application()
        app["jira_oauth_manager"] = mock_manager
        setup_jira_oauth_routes(app)
        client = await aiohttp_client(app)
        resp = await client.get("/api/auth/jira/callback?code=x&state=bad")
        assert resp.status == 400
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md` Sections 2, 3
2. **Check dependencies** — verify TASK-751 is in `tasks/completed/`
3. **Verify the Codebase Contract** — check `orchestrator.py:setup_routes()` at line 253
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-752-oauth-callback-routes.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
