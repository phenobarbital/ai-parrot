---
type: Wiki Overview
title: 'TASK-986: IntegrationsHandler, Route Registration, and Config'
id: doc:sdd-tasks-completed-task-986-handler-routes-config-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Exposes the integrations API via four HTTP endpoints, registers them in the
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.handlers.integrations
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
---

# TASK-986: IntegrationsHandler, Route Registration, and Config

**Feature**: FEAT-144 — Cross-Repository JiraToolkit OAuth2 3LO (Web AgentChat)
**Spec**: `sdd/specs/cross-repository-jiratoolkit-oauth2-3lo.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-985
**Assigned-to**: unassigned

---

## Context

Exposes the integrations API via four HTTP endpoints, registers them in the
application router alongside existing AgentTalk routes, and adds the
`WEB_OAUTH_ALLOWED_ORIGINS` config key. Also registers `JiraOAuth2Provider`
with the global registry at app startup.

Implements spec Modules 6, 10, and 11.

---

## Scope

- Add `WEB_OAUTH_ALLOWED_ORIGINS` to `parrot/conf.py` using `Kardex.get(..., fallback=[])`.
- Create `parrot/handlers/integrations.py` with `IntegrationsHandler(BaseView)`:
  - `GET .../integrations/{agent_id}` → list integrations.
  - `POST .../integrations/{agent_id}/{provider}/connect` → start connect.
  - `POST .../integrations/{agent_id}/{provider}/enable` → confirm enable.
  - `DELETE .../integrations/{agent_id}/{provider}` → disconnect.
  - Stack `@is_authenticated()` + `@user_session()`.
  - Validate origin from `request.headers.get("Origin")` or request body.
- Register the four routes in `parrot/manager/manager.py` (route registration
  block at L985-1080) adjacent to existing AgentTalk routes.
- Register `JiraOAuth2Provider` with the global `OAuth2ProviderRegistry` at
  app startup in the same manager block.
- Write unit tests.

**NOT in scope**: OAuth callback changes (TASK-987), AgentTalk envelope (TASK-988),
frontend (TASK-990).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Add `WEB_OAUTH_ALLOWED_ORIGINS` |
| `packages/ai-parrot/src/parrot/handlers/integrations.py` | CREATE | `IntegrationsHandler` |
| `packages/ai-parrot/src/parrot/manager/manager.py` | MODIFY | Route registration + provider registration |
| `tests/unit/integrations/oauth2/test_handler.py` | CREATE | Handler tests |
| `tests/unit/integrations/oauth2/test_conf.py` | CREATE | Config key test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Handler (new file):
from aiohttp import web
from navigator.views import BaseView  # agent.py:31
from navigator_auth.decorators import is_authenticated, user_session  # agent.py:22
from parrot.integrations.oauth2.service import IntegrationsService  # TASK-985
from parrot.conf import WEB_OAUTH_ALLOWED_ORIGINS  # added by this task

# Manager (existing file to modify):
from parrot.handlers.integrations import IntegrationsHandler  # new import
from parrot.integrations.oauth2.jira_provider import JiraOAuth2Provider  # TASK-984
from parrot.integrations.oauth2.registry import register_oauth2_provider  # TASK-983

# Config:
# parrot/conf.py uses navconfig Kardex pattern:
# JIRA_CLIENT_ID = config.get("JIRA_CLIENT_ID")   # line 608
# NEVER use default= — use fallback= (navconfig convention)
```

### Existing Signatures to Use
```python
# parrot/handlers/agent.py:48-50 — decorator + class pattern
@is_authenticated()
@user_session()
class AgentTalk(BaseView):
    ...

# parrot/manager/manager.py:1001-1005 — route registration pattern
# router.add_view('/api/v1/agents/chat/{agent_id}', AgentTalk)
# router.add_view('/api/v1/agents/chat/{agent_id}/{method_name}', AgentTalk)

# parrot/conf.py:608-610
JIRA_CLIENT_ID = config.get("JIRA_CLIENT_ID")
JIRA_CLIENT_SECRET = config.get("JIRA_CLIENT_SECRET")
JIRA_REDIRECT_URI = config.get("JIRA_REDIRECT_URI")
```

### Does NOT Exist
- ~~`parrot.handlers.integrations`~~ — does not exist yet; this task creates it.
- ~~`WEB_OAUTH_ALLOWED_ORIGINS`~~ — does not exist in `parrot/conf.py` yet; this task adds it.
- ~~`config.get("KEY", default=[])`~~ — WRONG. Use `fallback=[]`, never `default=`.
- ~~`router.add_route`~~ — verify the exact method. `manager.py` uses `router.add_view()`
  for class-based views. If the handler uses different URL patterns per method
  (GET vs POST vs DELETE), may need separate route entries or URL dispatch.

---

## Implementation Notes

### Config Pattern
```python
# parrot/conf.py — add near the JIRA_ block (around line 610):
WEB_OAUTH_ALLOWED_ORIGINS = config.get("WEB_OAUTH_ALLOWED_ORIGINS", fallback=[])
# If the value comes as a comma-separated string from env, parse it:
if isinstance(WEB_OAUTH_ALLOWED_ORIGINS, str):
    WEB_OAUTH_ALLOWED_ORIGINS = [o.strip() for o in WEB_OAUTH_ALLOWED_ORIGINS.split(",") if o.strip()]
```

### Handler Pattern
```python
@is_authenticated()
@user_session()
class IntegrationsHandler(BaseView):
    async def get(self) -> web.Response:
        """GET /api/v1/agents/integrations/{agent_id} — list integrations."""
        agent_id = self.request.match_info["agent_id"]
        user_id = self.request.get("user_id")  # or however user_session exposes it
        svc = IntegrationsService()
        descriptors = await svc.list_for_user(user_id, agent_id)
        return web.json_response([d.model_dump() for d in descriptors])

    async def post(self) -> web.Response:
        """Dispatched by URL: .../connect or .../enable."""
        # Check URL suffix to determine action
        ...

    async def delete(self) -> web.Response:
        """DELETE /api/v1/agents/integrations/{agent_id}/{provider}."""
        ...
```

### Route Registration
```python
# In parrot/manager/manager.py, after the AgentTalk route block (~L1005):
router.add_view(
    '/api/v1/agents/integrations/{agent_id}',
    IntegrationsHandler
)
router.add_view(
    '/api/v1/agents/integrations/{agent_id}/{provider}/connect',
    IntegrationsHandler
)
router.add_view(
    '/api/v1/agents/integrations/{agent_id}/{provider}/enable',
    IntegrationsHandler
)
router.add_view(
    '/api/v1/agents/integrations/{agent_id}/{provider}',
    IntegrationsHandler
)

# Provider registration at startup:
register_oauth2_provider(JiraOAuth2Provider())
```

### Key Constraints
- Origin validation: read from `request.headers.get("Origin")` if not in request body.
  If neither present, return HTTP 400.
- The handler should **not** contain business logic — delegate to `IntegrationsService`.
- HTTP status codes: 200 for success, 400 for bad request, 409 for conflict (enable
  without credential), 500 for server errors.

---

## Acceptance Criteria

- [ ] `WEB_OAUTH_ALLOWED_ORIGINS` defaults to `[]` when env var unset.
- [ ] `WEB_OAUTH_ALLOWED_ORIGINS` parses comma-separated string into list.
- [ ] `GET /api/v1/agents/integrations/{agent_id}` returns JSON list of descriptors.
- [ ] `POST .../jira/connect` returns `{auth_url, state, scopes, expires_in}`.
- [ ] `POST .../jira/enable` returns descriptor with `connected=true, enabled_on_agent=true`.
- [ ] `DELETE .../jira` returns `{provider: "jira", disconnected: true}`.
- [ ] Handler reads `Origin` header when `return_origin` not in body.
- [ ] Missing origin returns HTTP 400.
- [ ] All four routes appear in `app.router.routes()` after manager startup.
- [ ] `JiraOAuth2Provider` is registered at app startup.
- [ ] All tests pass: `pytest tests/unit/integrations/oauth2/test_handler.py tests/unit/integrations/oauth2/test_conf.py -v`
- [ ] No lint errors.

---

## Test Specification

```python
# tests/unit/integrations/oauth2/test_handler.py
import pytest
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop


class TestIntegrationsHandler:
    @pytest.mark.asyncio
    async def test_get_returns_descriptors(self):
        """GET .../integrations/{agent_id} returns a JSON list."""
        ...

    @pytest.mark.asyncio
    async def test_connect_init_origin_from_header(self):
        """If return_origin not in body, handler reads Origin header."""
        ...

    @pytest.mark.asyncio
    async def test_connect_init_missing_origin_returns_400(self):
        """Neither body nor header has origin → 400."""
        ...


# tests/unit/integrations/oauth2/test_conf.py
import pytest


class TestWebOAuthAllowedOrigins:
    def test_default_empty_list(self, monkeypatch):
        monkeypatch.delenv("WEB_OAUTH_ALLOWED_ORIGINS", raising=False)
        # Re-import or reload to test
        from parrot.conf import WEB_OAUTH_ALLOWED_ORIGINS
        assert WEB_OAUTH_ALLOWED_ORIGINS == [] or isinstance(WEB_OAUTH_ALLOWED_ORIGINS, list)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2-3 (Modules 6, 10, 11)
2. **Check dependencies** — verify TASK-985 is complete
3. **Verify**: how `user_session` decorator exposes `user_id` on the request.
   Check `AgentTalk._get_user_session` at agent.py:874 for the pattern.
4. **Verify**: how `router.add_view` is used in manager.py — confirm the exact
   API for registering class-based views with URL parameters.
5. **Update status** → `"in-progress"`
6. **Implement** handler, routes, config
7. **Verify** all acceptance criteria
8. **Move to completed**, update index

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-05-05
**Notes**: Implemented exactly as specified. WEB_OAUTH_ALLOWED_ORIGINS added to
conf.py as comma-separated env var parsed to list. IntegrationsHandler created
as BaseView with @is_authenticated/@user_session decorators, dispatching
GET/POST/DELETE to service layer. Four routes registered in manager.py plus
_register_oauth2_providers on_startup callback. Unit tests bypass auth decorators
via `request["authenticated"] = True` and patching `navigator_auth.decorators.get_session`.
All 4 handler tests and 63 oauth2 unit tests pass. Lint clean on modified files.

**Deviations from spec**: none
