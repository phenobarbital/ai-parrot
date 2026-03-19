# TASK-246: OAuth2 Callback aiohttp Endpoint

**Feature**: Telegram Integration OAuth2 Auth (FEAT-036)
**Spec**: `sdd/specs/telegram-integrations-auth.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-244
**Assigned-to**: claude-session

---

## Context

> Expose an aiohttp endpoint that handles the OAuth2 redirect callback. After the user authenticates with Google, the provider redirects to this endpoint with `?code=...&state=...`. The endpoint exchanges the code for tokens, then returns an HTML page that calls `Telegram.WebApp.sendData()` to pass the result back to the Telegram chat.
> Implements spec Module 6. Answer to Open Question 1: "Expose as an aiohttp endpoint."

---

## Scope

### Callback Endpoint
- Create `parrot/integrations/telegram/oauth2_callback.py`
- Define an aiohttp request handler:
  ```python
  async def oauth2_callback_handler(request: web.Request) -> web.Response:
      """Handle OAuth2 provider redirect with authorization code."""
  ```
- Extract `code` and `state` from query params
- Return an HTML page that:
  - Includes Telegram WebApp JS SDK
  - Calls `Telegram.WebApp.sendData(JSON.stringify({provider, code, state}))`
  - Shows a "Authentication complete, returning to Telegram..." message
  - Auto-closes the WebApp

### Endpoint Registration
- Create a helper function to register the route:
  ```python
  def setup_oauth2_routes(app: web.Application, path: str = "/oauth2/callback") -> None:
      app.router.add_get(path, oauth2_callback_handler)
  ```
- The `TelegramAgentWrapper` or `IntegrationBotManager` calls this during setup

### HTML Response Template
```html
<!DOCTYPE html>
<html>
<head><script src="https://telegram.org/js/telegram-web-app.js"></script></head>
<body>
  <p>Authentication complete. Returning to Telegram...</p>
  <script>
    const params = new URLSearchParams(window.location.search);
    const data = {
      provider: params.get('provider') || 'google',
      code: params.get('code'),
      state: params.get('state')
    };
    Telegram.WebApp.sendData(JSON.stringify(data));
    Telegram.WebApp.close();
  </script>
</body>
</html>
```

**NOT in scope**: Token exchange logic (handled in TASK-244 via `handle_callback`), wrapper integration (TASK-245).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/oauth2_callback.py` | CREATE | aiohttp callback handler + route setup |

---

## Implementation Notes

- The callback endpoint is stateless — it just captures the code/state and passes them to Telegram WebApp
- The actual token exchange happens in `OAuth2AuthStrategy.handle_callback()` when Telegram delivers the `web_app_data`
- The `provider` param can be passed via the OAuth2 `state` or as a separate query param
- Must validate that `code` and `state` are present; return error HTML if missing
- Use inline HTML (no template engine needed) — keep it minimal

---

## Acceptance Criteria

- [ ] `oauth2_callback_handler` extracts `code` and `state` from query params
- [ ] Returns HTML that loads Telegram WebApp JS and calls `sendData()`
- [ ] Returns error HTML if `code` is missing
- [ ] `setup_oauth2_routes()` registers GET route on the aiohttp app
- [ ] HTML auto-closes the WebApp after sending data
- [ ] Unit test: mock request with code/state → verify HTML contains sendData call
- [ ] Unit test: mock request without code → verify error response

---

## Agent Instructions

When you pick up this task:

1. **Read** existing handler patterns in `parrot/handlers/` for aiohttp route style
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Create** `parrot/integrations/telegram/oauth2_callback.py`
4. **Write tests** in `tests/integrations/telegram/test_oauth2_callback.py`
5. **Run** `pytest tests/integrations/telegram/test_oauth2_callback.py -v`
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-09

Created `parrot/integrations/telegram/oauth2_callback.py` with:
- `oauth2_callback_handler(request)` — extracts `code`/`state` from query params, returns HTML with `Telegram.WebApp.sendData()` integration
- `setup_oauth2_routes(app, path)` — registers GET route on aiohttp app
- `_json_escape(value)` — JSON-escapes strings with HTML entity protection (`<`, `>`, `&`) to prevent XSS
- Error handling for missing code/state (400) and OAuth2 provider errors (200 with error message)
- Success HTML with spinner animation, sendData call, and WebApp.close() after 500ms
- Error HTML with auto-close after 3 seconds

13 tests pass in `tests/integrations/telegram/test_oauth2_callback.py` covering:
success paths, provider selection, missing params, error responses, content type,
WebApp.close() presence, and XSS prevention. No lint errors.
