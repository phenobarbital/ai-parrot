# TASK-5424: `POST /api/auth/telegram/browser-complete` endpoint + route mounting

**Feature**: FEAT-854 — Telegram Auth Open Mode (webview | browser)
**Spec**: `sdd/specs/telegram-auth-open-mode.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5418, TASK-5422, TASK-5423
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 items 2-3. The page-based login pages (TASK-5421) POST the payload
they used to pass to `sendData()`, plus `state`, to this endpoint. The handler consumes
the browser state (single-use), resolves the bot's wrapper from
`app["telegram_wrappers"][bot_id]` (TASK-5423) and delegates **once** to
`wrapper._complete_auth_payload(..., browser_entry=entry)` (TASK-5422), using only the
entry's Telegram ids. The JSON body is untrusted input, never proof of identity.

Mounting: the route must exist in the same aiohttp app as the wrapper. Both Telegram
startup paths call `attach_telegram_wrapper(app, wrapper, bot)`
(integrations/manager.py:190, called from `IntegrationBotManager._start_telegram_bot`
:414-416 and `TelegramBotManager._start_bot` telegram/manager.py:198-200) during
`on_startup`, when only `on_startup` itself is frozen and `app.router` is still mutable
(integrations/manager.py:869-870). That is the guaranteed mount point. The spec also asks
for the orchestrator mount beside `setup_combined_auth_routes(app)`
(orchestrator.py:369, ImportError degrade) — add it there too; the setup is idempotent.

The endpoint is pre-authentication, so it must be excluded from navigator-auth's
middleware exactly like the combined callback (`combined_callback.py:190-197`).

---

## Scope

- Append `browser_complete_handler(request)` and `setup_browser_auth_routes(app)` to
  `browser_login.py`.
- Mount it from `attach_telegram_wrapper` for browser-mode wrappers and from the
  orchestrator next to the combined-auth routes.
- Append endpoint tests to `test_browser_login.py`.

**NOT in scope**: the OAuth2 GET callback (TASK-5425), page JS (TASK-5421), wrapper logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_login.py` | MODIFY | Handler + idempotent route setup |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | Mount in `attach_telegram_wrapper` |
| `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py` | MODIFY | Mount beside `setup_combined_auth_routes(app)` |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py` | MODIFY | Endpoint tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev @ `0083e04b62` (2026-11-09).

### Verified Imports
```python
from aiohttp import web                    # verified: telegram/oauth2_callback.py:10
from navigator_auth.conf import exclude_list   # verified: telegram/combined_callback.py:192 (inside try/except ImportError)
# browser_login.py names from TASK-5418: BROWSER_LOGIN_APP_KEY, TELEGRAM_WRAPPERS_APP_KEY,
# BROWSER_COMPLETE_PATH, PAGE_AUTH_METHODS, is_browser_state, BrowserVerificationError,
# BrowserVerifierUnavailableError, telegram_deep_link
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/combined_callback.py:176-197 — pattern
def setup_combined_auth_routes(app: web.Application, path: str = COMBINED_CALLBACK_PATH) -> None:
    app.router.add_get(path, combined_auth_callback_handler)
    try:
        from navigator_auth.conf import exclude_list
        if path not in exclude_list:
            exclude_list.append(path)
    except ImportError:
        pass

# packages/ai-parrot-integrations/src/parrot/integrations/manager.py
def attach_telegram_wrapper(app: Any, wrapper: Any, bot: Any) -> None:   # line 190
    ...
    wrapper._attach_login_coordinator()                                     # line 202 (last line; occurs once)

# packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py:359-369
            try:
                from parrot.integrations.telegram.combined_callback import (
                    setup_combined_auth_routes,
                )
            except ImportError as exc:
                self.logger.warning(...)
            else:
                setup_combined_auth_routes(app)                             # line 369 (occurs once)

# TASK-5422: TelegramAgentWrapper._complete_auth_payload(data, *, telegram_id, chat_id,
#            notify=True, browser_entry=None) -> bool   (raises the two typed errors)
```

### Does NOT Exist
- ~~A GET variant of the completion route~~ — POST only.
- ~~`setup_oauth2_routes` mounted by the server for Telegram~~ — `telegram/oauth2_callback.py:195` has no in-repo caller; not this task's concern.
- ~~aiohttp de-duplication of identical routes~~ — adding the same POST twice raises; idempotency must check `app.router.resources()`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_login.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/manager.py#attach_telegram_wrapper",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/combined_callback.py#setup_combined_auth_routes"
  ]
}
```

---

## Implementation Notes

### Response contract (spec M5)
| Case | Status | Body |
|---|---|---|
| body not JSON / not an object / `state` not a non-empty string | 400 | `{"ok": false, "error": "bad_request"}` |
| `state` not in the `browser.` namespace, unknown, expired or replayed | 410 | `{"ok": false, "error": "expired"}` |
| `auth_method` present and not in `PAGE_AUTH_METHODS` | 401 | `{"ok": false, "error": "rejected"}` (state already consumed) |
| no wrapper for `entry.bot_id` | 503 | `{"ok": false, "error": "unavailable"}` |
| `BrowserVerificationError` or `_complete_auth_payload` → `False` | 401 | `{"ok": false, "error": "rejected"}` |
| `BrowserVerifierUnavailableError` | 503 | `{"ok": false, "error": "unavailable"}` |
| success | 200 | `{"ok": true, "redirect_url": telegram_deep_link(entry.bot_username)}` |

- Strip browser-controlled correlation keys before delegating: `state`, `browser_entry`,
  `bot_id`, `chat_id`, `telegram_id`, `verified`.
- Never echo tokens or the request body; log the state's first 8 chars at most.
- Consume the state before any `await` (the registry already guarantees atomicity).

---

## Implementation Blueprint

### Steps (in order)
1. Append the handler + setup to `browser_login.py` (add `from aiohttp import web` to its imports).
2. Mount in `attach_telegram_wrapper`.
3. Mount in the orchestrator.
4. Append tests.

### `browser_login.py` (MODIFY — append at end of file)
```python
_RESERVED_PAYLOAD_KEYS = frozenset({"state", "browser_entry", "bot_id", "chat_id", "telegram_id", "verified"})


def _json(status: int, **body: Any) -> web.Response:
    return web.json_response(body, status=status)


async def browser_complete_handler(request: web.Request) -> web.Response:
    """Consume a browser-mode login payload POSTed by a login page.

    400 on malformed JSON / missing state; 410 on unknown or expired state;
    401 on rejected credentials/identity mismatch; 503 on verifier unavailability;
    200 {ok: true, redirect_url: "https://t.me/<bot>"} on success.
    Never echoes tokens back in the response body.
    """
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return _json(400, ok=False, error="bad_request")
    if not isinstance(body, dict):
        return _json(400, ok=False, error="bad_request")
    state = body.get("state")
    if not isinstance(state, str) or not state:
        return _json(400, ok=False, error="bad_request")
    if not is_browser_state(state):
        return _json(410, ok=False, error="expired")
    registry = request.app.get(BROWSER_LOGIN_APP_KEY)
    entry = registry.consume(state) if registry is not None else None
    if entry is None:
        return _json(410, ok=False, error="expired")
    # FILL IN: the remaining rows of the response contract — auth_method gate, wrapper lookup in
    # request.app.get(TELEGRAM_WRAPPERS_APP_KEY), payload stripping, ONE awaited call to
    # wrapper._complete_auth_payload(data, telegram_id=entry.telegram_id, chat_id=entry.chat_id,
    # browser_entry=entry), typed-error mapping, success body.


def setup_browser_auth_routes(app: web.Application) -> None:
    """Register BROWSER_COMPLETE_PATH on the aiohttp app (idempotent) and exclude it from auth."""
    already = any(
        getattr(resource, "canonical", None) == BROWSER_COMPLETE_PATH for resource in app.router.resources()
    )
    if not already:
        app.router.add_post(BROWSER_COMPLETE_PATH, browser_complete_handler)
        logger.info("Registered Telegram browser-login completion endpoint at %s", BROWSER_COMPLETE_PATH)
    try:  # pragma: no cover - navigator_auth is optional in tests
        from navigator_auth.conf import exclude_list  # type: ignore

        if BROWSER_COMPLETE_PATH not in exclude_list:
            exclude_list.append(BROWSER_COMPLETE_PATH)
    except ImportError:
        pass
```
**Why**: Spec M5 skeleton signatures and docstring verbatim. The handler duck-types the
wrapper (no import of `wrapper.py` — see TASK-5418 import rule).

### `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    wrapper._attach_login_coordinator()' integrations/manager.py) — line 202
# AFTER — insert below it (still inside attach_telegram_wrapper):
    # FEAT-854: browser-mode bots need the completion endpoint in this same app.
    if getattr(getattr(wrapper, "config", None), "auth_open_mode", "webview") == "browser":
        from parrot.integrations.telegram.browser_login import setup_browser_auth_routes

        setup_browser_auth_routes(app)
```

### `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '                setup_combined_auth_routes(app)' autonomous/orchestrator.py) — line 369
# AFTER — insert below it, same indentation (inside the same `else:` branch):
                # FEAT-854: browser-mode completion endpoint (idempotent; the
                # Telegram startup path also mounts it via attach_telegram_wrapper).
                try:
                    from parrot.integrations.telegram.browser_login import (
                        setup_browser_auth_routes,
                    )
                except ImportError as exc:
                    self.logger.warning("Telegram browser-auth route not mounted: %s", exc)
                else:
                    setup_browser_auth_routes(app)
```

### `test_browser_login.py` (MODIFY — append)
```python
# Use aiohttp TestClient/TestServer like test_oauth2_integration.py:378-399. Register a fake
# wrapper object (AsyncMock _complete_auth_payload) under app[TELEGRAM_WRAPPERS_APP_KEY]["7001"]
# and entries via get_or_create_browser_login_registry(app).register(...).

async def test_browser_complete_handler_unknown_state_410():
    # FILL IN: unknown browser state, unprefixed state, expired entry -> 410; wrapper not called.

async def test_browser_complete_handler_success():
    # FILL IN: valid entry -> 200 {ok: true, redirect_url: "https://t.me/parrot_test_bot"};
    # _complete_auth_payload awaited once with the entry's telegram_id/chat_id and
    # browser_entry=entry; "state"/"chat_id" stripped from data; second POST -> 410 (replay).

async def test_browser_complete_handler_error_mapping():
    # FILL IN: 400 (non-JSON, list body, missing state); 401 (BrowserVerificationError, False,
    # auth_method "oauth2"); 503 (BrowserVerifierUnavailableError, no wrapper); bodies never
    # contain the submitted token.

async def test_setup_browser_auth_routes_idempotent():
    # FILL IN: calling twice registers one POST route.

async def test_browser_mode_full_flow_basic():
    # FILL IN: real wrapper (browser basic config, app=web.Application(), host verifier stub
    # returning user_id "42") -> handle_login registers the state -> POST {auth_method: "basic",
    # token, state} -> 200; wrapper._user_sessions[tg_id].authenticated; bot.send_message awaited.
```

### FILL IN checklist
- [ ] `browser_complete_handler` remaining rows — response contract table
- [ ] Five tests

---

## Acceptance Criteria

- [ ] Response contract table holds; replay/expiry → 410 with no session mutation.
- [ ] `_complete_auth_payload` invoked exactly once per consumed state, with entry-owned ids only.
- [ ] Route mounted by `attach_telegram_wrapper` for browser-mode wrappers and beside the combined routes in the orchestrator; double setup is harmless.
- [ ] Path added to navigator-auth `exclude_list`.
- [ ] `ruff check` clean on all three source files.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py -q`

---

## Test Specification

See the appended test block (spec §4 rows `test_browser_complete_handler_unknown_state_410`,
`test_browser_complete_handler_success`; integration row `test_browser_mode_full_flow_basic`).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug telegram-auth-open-mode --feature-id FEAT-854`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/telegram-auth-open-mode.json`
4. **Verify the Codebase Contract** before writing any code; fix stale entries first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src` (add `packages/ai-parrot-server/src` for the orchestrator import check)
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5424 telegram-auth-open-mode verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
