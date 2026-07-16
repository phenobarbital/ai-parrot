---
type: Wiki Overview
title: 'TASK-987: OAuth Callback Web-Channel Branch and Templates'
id: doc:sdd-tasks-completed-task-987-oauth-callback-web-branch-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The existing `jira_oauth_callback` in `parrot/auth/routes.py` handles only
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
---

# TASK-987: OAuth Callback Web-Channel Branch and Templates

**Feature**: FEAT-144 — Cross-Repository JiraToolkit OAuth2 3LO (Web AgentChat)
**Spec**: `sdd/specs/cross-repository-jiratoolkit-oauth2-3lo.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-985
**Assigned-to**: unassigned

---

## Context

The existing `jira_oauth_callback` in `parrot/auth/routes.py` handles only
Telegram callbacks. This task extends it with a `channel == "web"` branch that:
1. Calls `IntegrationsService.persist_credential()` to upsert the DocumentDB row.
2. Renders an HTML page that posts a message to `window.opener` and self-closes.

The Telegram path remains byte-for-byte unchanged.

Implements spec Module 7.

---

## Scope

- Extend `jira_oauth_callback` (routes.py:83) with a `channel == "web"` branch
  after `handle_callback()` succeeds.
- In the web branch:
  1. Read `extra_state["return_origin"]` and validate against
     `WEB_OAUTH_ALLOWED_ORIGINS`.
  2. Call `IntegrationsService().persist_credential(user_id, "jira", token_set)`.
  3. Render `web_oauth_success.html` template with `target_origin` and payload.
- On error (invalid origin, callback failure), render `web_oauth_error.html`.
- Create the two HTML template files.
- If `extra_state["channel"]` is `"telegram"` or absent, the existing flow
  executes unchanged.
- Write unit tests including a Telegram regression guard.

**NOT in scope**: IntegrationsHandler endpoints (TASK-986), AgentTalk envelope
(TASK-988), frontend popup helper (TASK-990).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/routes.py` | MODIFY | Add web-channel branch in `jira_oauth_callback` |
| `packages/ai-parrot/src/parrot/auth/templates/web_oauth_success.html` | CREATE | Success page with postMessage |
| `packages/ai-parrot/src/parrot/auth/templates/web_oauth_error.html` | CREATE | Error page with postMessage |
| `tests/unit/integrations/oauth2/test_callback_web.py` | CREATE | Callback web-branch tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot/auth/routes.py — existing imports (verify before modifying):
from aiohttp import web  # existing
# The callback function at line 83:
# async def jira_oauth_callback(request: web.Request) -> web.Response:
#     manager: JiraOAuthManager = request.app["jira_oauth_manager"]  # verify key name
#     ...
#     token_set, extra_state = await manager.handle_callback(code, state)
#     ...

# From TASK-985:
from parrot.integrations.oauth2.service import IntegrationsService

# Config (from TASK-986):
from parrot.conf import WEB_OAUTH_ALLOWED_ORIGINS
```

### Existing Signatures to Use
```python
# parrot/auth/routes.py:83
async def jira_oauth_callback(request: web.Request) -> web.Response:
    # Existing flow:
    # 1. Extracts code, state from query params
    # 2. manager = request.app["jira_oauth_manager"]  (verify key)
    # 3. token_set, extra_state = await manager.handle_callback(code, state)
    # 4. Telegram-specific: session stamper (~line 121), chat notification (~line 139)
    # 5. Returns redirect or success response

# parrot/auth/routes.py:156
def setup_jira_oauth_routes(app: web.Application) -> None: ...

# parrot/auth/jira_oauth.py:304
class JiraOAuthManager:
    async def handle_callback(self, code: str, state: str) -> Tuple[JiraTokenSet, Dict[str, Any]]: ...

# parrot/auth/jira_oauth.py:59
class JiraTokenSet(BaseModel):
    account_id: str
    display_name: str
    email: Optional[str]
    scopes: List[str]
    cloud_id: str
    site_url: str
    ...
```

### Does NOT Exist
- ~~`web_oauth_success.html`~~ — does not exist yet; this task creates it.
- ~~`web_oauth_error.html`~~ — does not exist yet; this task creates it.
- ~~`parrot/auth/templates/` directory~~ — may not exist; create if needed.
- ~~`extra_state["channel"]` in current callbacks~~ — currently no callback passes
  a `channel` key in `extra_state`. The web branch adds this. Telegram's existing
  `extra_state` (if any) does NOT include `"channel"`.
- ~~`aiohttp_jinja2` template rendering~~ — verify whether the project uses it.
  If not, use inline string templates (`web.Response(text=html, content_type="text/html")`).

---

## Implementation Notes

### Web Branch Logic
```python
async def jira_oauth_callback(request: web.Request) -> web.Response:
    # ... existing: extract code/state, call handle_callback ...
    token_set, extra_state = await manager.handle_callback(code, state)

    channel = extra_state.get("channel", "telegram")  # backward compat

    if channel == "web":
        return await _handle_web_callback(request, token_set, extra_state)

    # ... existing Telegram flow unchanged ...
```

### Success Template (web_oauth_success.html)
```html
<!DOCTYPE html>
<html>
<head><title>Authorization Successful</title></head>
<body>
<p>Authorization successful. This window will close automatically.</p>
<script>
  if (window.opener) {
    window.opener.postMessage({
      type: "ai-parrot-oauth-callback",
      provider: "{{ provider }}",
      success: true,
      account_id: "{{ account_id }}",
      display_name: "{{ display_name }}"
    }, "{{ target_origin }}");
  }
  window.close();
</script>
</body>
</html>
```

### Error Template (web_oauth_error.html)
```html
<!DOCTYPE html>
<html>
<head><title>Authorization Failed</title></head>
<body>
<p>Authorization failed: {{ error }}. You may close this window.</p>
<script>
  if (window.opener) {
    window.opener.postMessage({
      type: "ai-parrot-oauth-callback",
      provider: "{{ provider }}",
      success: false,
      error: "{{ error }}"
    }, "{{ target_origin }}");
  }
  window.close();
</script>
</body>
</html>
```

### Key Constraints
- `target_origin` MUST be validated against `WEB_OAUTH_ALLOWED_ORIGINS` before
  being embedded in the HTML. An invalid origin renders the error template with
  `error: "invalid_origin"`.
- Template substitution: use Python `str.format()` or `string.Template` — NOT
  f-strings with user data (XSS risk). Escape `account_id` and `display_name`
  with `html.escape()`. The `target_origin` has already been validated against
  the allowlist but should still be escaped.
- The Telegram path must not be touched. Use the `channel` check to branch.
- If `extra_state` has no `"channel"` key, assume `"telegram"` for backward compat.

---

## Acceptance Criteria

- [ ] `channel == "web"` callback renders `web_oauth_success.html` with postMessage.
- [ ] Rendered HTML posts `{type: "ai-parrot-oauth-callback", provider: "jira", success: true, ...}` to `target_origin`.
- [ ] `persist_credential` is called for web-channel callbacks.
- [ ] Invalid `return_origin` renders error template with `success: false, error: "invalid_origin"`.
- [ ] Telegram callback path (`channel == "telegram"` or absent) is unchanged (regression test).
- [ ] No `users_integrations` write for `channel="telegram"` callbacks.
- [ ] HTML template properly escapes user data (no XSS).
- [ ] All tests pass: `pytest tests/unit/integrations/oauth2/test_callback_web.py -v`
- [ ] No lint errors.

---

## Test Specification

```python
# tests/unit/integrations/oauth2/test_callback_web.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestWebCallbackBranch:
    @pytest.mark.asyncio
    async def test_web_branch_renders_postmessage_html(self):
        """When extra_state["channel"] == "web", callback renders HTML with postMessage."""
        ...

    @pytest.mark.asyncio
    async def test_web_branch_calls_persist_credential(self):
        """persist_credential is called with user_id, provider, token_set."""
        ...

    @pytest.mark.asyncio
    async def test_invalid_return_origin_renders_error_template(self):
        """return_origin not in WEB_OAUTH_ALLOWED_ORIGINS → error template."""
        ...

    @pytest.mark.asyncio
    async def test_telegram_branch_unchanged(self):
        """Telegram branch path executes existing flow exactly (regression guard)."""
        ...

    @pytest.mark.asyncio
    async def test_missing_channel_defaults_to_telegram(self):
        """When extra_state has no 'channel' key, Telegram flow runs."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read** `parrot/auth/routes.py` in full — understand the current callback flow.
2. **Check** how `extra_state` is structured in existing Telegram callbacks.
3. **Verify** whether `aiohttp_jinja2` is used elsewhere; if not, use inline templates.
4. **Check dependencies** — verify TASK-985 is complete.
5. **Be extra careful** not to modify the Telegram path.
6. **Implement** and run the regression test for Telegram first.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
