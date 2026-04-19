# TASK-759: Combined Callback Endpoint

**Feature**: FEAT-108 — Jira OAuth2 3LO Authentication from Telegram WebApp
**Spec**: `sdd/specs/FEAT-108-jiratoolkit-auth-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-756
**Assigned-to**: unassigned

---

## Context

This task creates the aiohttp route that Jira's OAuth2 consent page redirects to
after the user authorizes. Unlike the existing `jira_oauth_callback` (which renders
a standalone browser page), this endpoint returns HTML that sends the combined
BasicAuth + Jira auth data back to Telegram via `WebApp.sendData()` and then
closes the WebApp.

The BasicAuth data was stashed in Redis (as part of the Jira nonce's `extra_state`)
before the login page redirected to Jira. This callback retrieves it and packages
everything together.

Implements Spec Module 4.

---

## Scope

- Create `parrot/integrations/telegram/combined_callback.py`.
- Implement `combined_auth_callback_handler(request)` aiohttp handler at
  `GET /api/auth/telegram/combined-callback`:
  1. Extract `code` and `state` from query parameters.
  2. Retrieve the state payload from Redis via `JiraOAuthManager` nonce lookup
     (but do NOT consume the nonce — leave that for `handle_callback` later).
     Actually: just pass code+state through — the wrapper will call `handle_callback`.
  3. Return HTML that calls `Telegram.WebApp.sendData(JSON.stringify({jira: {code, state}}))`
     then `Telegram.WebApp.close()`.
  4. Handle error cases (missing code/state, OAuth error from provider).
- Implement `setup_combined_auth_routes(app)` to register the route.
- Follow XSS-safe patterns from existing `oauth2_callback.py` (`_json_escape`).
- Write unit tests for the handler.

**NOT in scope**: Consuming the nonce or exchanging the code (wrapper does that in
TASK-763), identity mapping, vault storage.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/combined_callback.py` | CREATE | Combined callback handler |
| `packages/ai-parrot/tests/unit/test_combined_callback.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web  # standard aiohttp
from parrot.integrations.telegram.oauth2_callback import _json_escape  # oauth2_callback.py:113
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/integrations/telegram/oauth2_callback.py
# Pattern to replicate:
_SUCCESS_HTML_TEMPLATE = """..."""  # line 15 — HTML with {provider_json}, {code_json}, {state_json}
_ERROR_HTML_TEMPLATE = """..."""    # line 77 — error HTML with {error_message}

def _json_escape(value: str) -> str:  # line 113
    # Escapes string for safe JS template embedding
    # Returns JSON-safe quoted string with XSS protections

async def oauth2_callback_handler(request: web.Request) -> web.Response:  # line 133
    # Reference pattern: extracts code/state, returns HTML with sendData

def setup_oauth2_routes(app: web.Application, path: str = "/oauth2/callback") -> None:  # line 188
    # Reference pattern for route registration
```

### Does NOT Exist
- ~~`parrot.integrations.telegram.combined_callback`~~ — does not exist yet (this task creates it)
- ~~A combined callback route at `/api/auth/telegram/combined-callback`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
The combined callback follows the exact same pattern as `oauth2_callback.py:133-185`:
1. Extract query params
2. Validate presence
3. Return HTML with `WebApp.sendData()` + `WebApp.close()`

The key difference: the payload sent via `sendData` contains a `jira` key (not
a generic OAuth provider key), signaling to the wrapper that this is a combined
auth flow.

```python
# The HTML JS should do:
# Telegram.WebApp.sendData(JSON.stringify({jira: {code: "...", state: "..."}}))
# setTimeout(function() { Telegram.WebApp.close(); }, 500);
```

### Key Constraints
- Use `_json_escape` from `oauth2_callback.py` for XSS protection
- The route path must NOT conflict with `/api/auth/jira/callback` (existing standalone)
- Must exclude the route from navigator-auth middleware (same pattern as `routes.py:151-156`)
- The handler does NOT exchange the code — it just passes it through to Telegram

### References in Codebase
- `packages/ai-parrot/src/parrot/integrations/telegram/oauth2_callback.py:15-75` — HTML template pattern
- `packages/ai-parrot/src/parrot/integrations/telegram/oauth2_callback.py:113-130` — `_json_escape`
- `packages/ai-parrot/src/parrot/auth/routes.py:139-157` — route registration + auth exclusion

---

## Acceptance Criteria

- [ ] Handler at `GET /api/auth/telegram/combined-callback` returns HTML with `WebApp.sendData`
- [ ] Missing `code` or `state` returns error HTML
- [ ] OAuth error param (`?error=access_denied`) returns error HTML
- [ ] HTML uses `_json_escape` for all interpolated values (XSS safe)
- [ ] Route excluded from auth middleware
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_combined_callback.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_combined_callback.py
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.integrations.telegram.combined_callback import combined_auth_callback_handler


class TestCombinedCallback:
    async def test_success_returns_html_with_senddata(self):
        request = make_mocked_request("GET", "/api/auth/telegram/combined-callback",
                                       match_info={},
                                       headers={})
        request._rel_url = request._rel_url.with_query({"code": "abc123", "state": "nonce456"})
        response = await combined_auth_callback_handler(request)
        assert response.status == 200
        assert "sendData" in response.text
        assert "abc123" in response.text
        assert "nonce456" in response.text

    async def test_missing_code_returns_error(self):
        request = make_mocked_request("GET", "/api/auth/telegram/combined-callback")
        request._rel_url = request._rel_url.with_query({"state": "nonce456"})
        response = await combined_auth_callback_handler(request)
        assert response.status == 400

    async def test_oauth_error_returns_error_html(self):
        request = make_mocked_request("GET", "/api/auth/telegram/combined-callback")
        request._rel_url = request._rel_url.with_query({"error": "access_denied"})
        response = await combined_auth_callback_handler(request)
        assert response.status == 200
        assert "access_denied" in response.text
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context
2. **Check dependencies** — verify TASK-756 is completed
3. **Read `oauth2_callback.py`** thoroughly — this task mirrors its patterns
4. **Read `routes.py:139-157`** for auth middleware exclusion pattern
5. **Implement** the combined callback handler
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
