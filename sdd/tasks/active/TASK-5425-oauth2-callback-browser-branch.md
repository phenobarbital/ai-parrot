# TASK-5425: OAuth2 callback — registry-aware browser branch

**Feature**: FEAT-854 — Telegram Auth Open Mode (webview | browser)
**Spec**: `sdd/specs/telegram-auth-open-mode.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5418, TASK-5422, TASK-5423
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 item 1 and decision `browser-return-channel-server-side`. Today
`oauth2_callback_handler` (oauth2_callback.py:138) turns `code`/`state` into an HTML page
that calls `Telegram.WebApp.sendData()`. In browser mode the provider redirects the
system browser here, where `sendData` does not exist; the server must complete the login
itself.

The handler must classify the `state` by the `browser.` prefix **before** any
provider-error / missing-code rendering or legacy HTML:
- `browser.` state → consume the registry entry atomically. Miss (unknown, expired,
  consumed, swept, lost on restart) → **HTTP 410** browser error HTML, no `sendData`,
  no session mutation, no strategy call. Hit + provider `error` or missing `code` →
  **HTTP 400** browser error HTML (attempt consumed). Hit + `code` → resolve the wrapper
  and delegate **exactly once** to `_complete_auth_payload({"auth_method": "oauth2",
  "code": code, "state": state}, telegram_id=entry.telegram_id, chat_id=entry.chat_id,
  browser_entry=entry)`; that call alone consumes PKCE, exchanges the code and fetches
  userinfo (also for composite strategies, which dispatch on `auth_method`).
- Unprefixed state → today's legacy behavior, byte-for-byte.

The prefix is a routing discriminator only; registry membership authenticates the
correlation and the provider authenticates identity.

---

## Scope

- Add the browser branch to `oauth2_callback_handler` and a private
  `_browser_oauth2_callback(request, state)` helper in `oauth2_callback.py`.
- Append the M5 OAuth2 tests and the full-flow integration test to
  `test_oauth2_integration.py`.

**NOT in scope**: route mounting for `/oauth2/callback` (deployments mount it — no in-repo
caller of `setup_oauth2_routes`), the POST endpoint (TASK-5424), any strategy change.
**Do not** call `handle_callback`, `_consume_state`, `exchange_code` or `fetch_userinfo`
from this module.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_callback.py` | MODIFY | Browser branch + helper |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_integration.py` | MODIFY | Append browser-branch tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev @ `0083e04b62` (2026-11-09).

### Verified Imports
```python
import html as html_mod                    # verified: telegram/oauth2_callback.py:8
from aiohttp import web                    # verified: telegram/oauth2_callback.py:10
from navconfig.logging import logging      # verified: telegram/oauth2_callback.py:11
from parrot.integrations.telegram.browser_login import (     # TASK-5418
    BROWSER_LOGIN_APP_KEY, TELEGRAM_WRAPPERS_APP_KEY, BrowserVerificationError,
    BrowserVerifierUnavailableError, is_browser_state, render_browser_error, render_browser_success,
)
```
`browser_login.py` imports nothing from `oauth2_callback.py`, and `combined_callback.py`
imports `_ERROR_HTML_TEMPLATE, _json_escape` from here (combined_callback.py:23-26) — keep
both names unchanged.

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_callback.py
_SUCCESS_HTML_TEMPLATE = """..."""   # line 15 (legacy, contains sendData)
_ERROR_HTML_TEMPLATE = """..."""     # line 82
def _json_escape(value: str) -> str: # line 118
async def oauth2_callback_handler(request: web.Request) -> web.Response:   # line 138 (occurs once)
    #   code = request.query.get("code")     # line 150 (occurs once) — first statement after the docstring
def setup_oauth2_routes(app: web.Application, path: str = "/oauth2/callback") -> None:  # line 195

# TASK-5422: TelegramAgentWrapper._complete_auth_payload(...) -> bool (raises typed errors)
# TASK-5423: wrappers registered in app[TELEGRAM_WRAPPERS_APP_KEY][bot_id]; /login stores the
#            browser state as the OAuth2 PKCE key via build_login_keyboard / build_authorize_url.

# Existing legacy tests that must stay green unchanged:
# tests/integrations/telegram/test_oauth2_integration.py:378-399 (TestOAuth2CallbackEndpoint)
# tests/integrations/telegram/test_oauth2_callback.py
```

### Does NOT Exist
- ~~Tombstones for consumed states~~ — the prefix alone routes; a miss is always 410.
- ~~`request.app["telegram_wrapper"]`~~ (singular) — the map is `app["telegram_wrappers"][bot_id]`.
- ~~A `provider` query param in browser mode~~ — not needed; the strategy knows its provider.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_callback.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_integration.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_callback.py#oauth2_callback_handler",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_callback.py#setup_oauth2_routes"
  ]
}
```

---

## Implementation Notes

### Response contract (browser states only)
| Case | Status | Page |
|---|---|---|
| entry missing (unknown/expired/consumed/restart-lost) | 410 | `render_browser_error("This sign-in link has expired or was already used. Send /login in Telegram to start again.")` |
| entry hit + `error` param or no `code` | 400 | `render_browser_error("Sign-in was cancelled or failed. Send /login in Telegram to try again.")` |
| no wrapper for `entry.bot_id` | 503 | `render_browser_error("The bot is temporarily unavailable. Please try again later.")` |
| `BrowserVerificationError` or completion `False` | 401 | `render_browser_error("Sign-in could not be verified. Send /login in Telegram to try again.")` |
| `BrowserVerifierUnavailableError` | 503 | as the no-wrapper row |
| success | 200 | `render_browser_success(entry.bot_username, display_name)` |

`display_name`: after success read `wrapper._user_sessions.get(entry.telegram_id)`; use its
`display_name` when it is authenticated, else `""` (staged logins are not promoted yet).
All responses `content_type="text/html"`; never include `code`, `state` or tokens.

---

## Implementation Blueprint

### Steps (in order)
1. Add the import block below `from navconfig.logging import logging` (line 11).
2. Insert `_browser_oauth2_callback` BEFORE `async def oauth2_callback_handler(` (occurs once, line 138).
3. Insert the classification BEFORE `    code = request.query.get("code")` (occurs once, line 150).
4. Append tests.

### `oauth2_callback.py` (MODIFY — helper)
```python
def _browser_html(page: str, status: int) -> web.Response:
    return web.Response(text=page, content_type="text/html", status=status)


async def _browser_oauth2_callback(request: web.Request, state: str) -> web.Response:
    """Complete a browser-mode OAuth2 login server-side (FEAT-854). No sendData involved."""
    registry = request.app.get(BROWSER_LOGIN_APP_KEY)
    entry = registry.consume(state) if registry is not None else None  # atomic, before any await
    if entry is None:
        logger.warning("Browser OAuth2 callback with unknown or expired state %s...", state[:8])
        return _browser_html(render_browser_error(
            "This sign-in link has expired or was already used. Send /login in Telegram to start again."
        ), 410)
    code = request.query.get("code")
    if request.query.get("error") or not code:
        logger.warning("Browser OAuth2 callback without a code (provider error or cancel)")
        return _browser_html(render_browser_error(
            "Sign-in was cancelled or failed. Send /login in Telegram to try again."
        ), 400)
    # FILL IN: wrapper lookup (503), ONE awaited _complete_auth_payload call with
    # {"auth_method": "oauth2", "code": code, "state": state} and the entry's ids +
    # browser_entry=entry, typed-error mapping (401/503), success page — per the response table.
```

### `oauth2_callback.py` (MODIFY — classification)
```python
# occurrences: 1 (verified: grep -c '    code = request.query.get("code")' telegram/oauth2_callback.py) — line 150
# BEFORE — insert above it:
    # FEAT-854: route by the browser-state namespace BEFORE any legacy rendering.
    browser_state = request.query.get("state")
    if is_browser_state(browser_state):
        return await _browser_oauth2_callback(request, browser_state)
```
Also add one sentence to the handler docstring: browser-namespace states complete
server-side; all other states keep the legacy `sendData` page.

### `test_oauth2_integration.py` (MODIFY — append)
```python
# Build an app with setup_oauth2_routes(app), a real OAuth2 browser-mode wrapper
# (_oauth2_config() + auth_open_mode="browser", public_base_url=...; app=the same app), and
# patch OAuth2AuthStrategy.exchange_code / fetch_userinfo with AsyncMocks returning
# MOCK_GOOGLE_TOKEN_RESPONSE / MOCK_GOOGLE_USERINFO (defined at the top of this file).

class TestOAuth2BrowserBranch:
    async def test_oauth2_callback_browser_branch(self):
        # FILL IN: /login (handle_login) -> registered state -> GET /oauth2/callback?code=..&state=..
        # -> 200, no "sendData" in the HTML, contains https://t.me/<bot>; session authenticated.

    async def test_oauth2_callback_legacy_branch_unchanged(self):
        # FILL IN: unknown UNPREFIXED state -> legacy 200 page containing sendData (same as
        # TestOAuth2CallbackEndpoint); legacy provider-error page unchanged.

    async def test_oauth2_browser_replay_expiry_410(self):
        # FILL IN: consumed, expired (created_at - 601), unknown prefixed and "restart-lost"
        # (fresh app, no registry) states -> 410, no sendData, exchange_code not awaited.

    async def test_oauth2_browser_callback_exactly_once(self):
        # FILL IN: single and composite (basic+oauth2 with a basic verifier stub): exchange_code,
        # fetch_userinfo and _consume_state each called once; _persist_principal_link and
        # _initialize_user_context once.

    async def test_oauth2_browser_concurrent_callbacks(self):
        # FILL IN: asyncio.gather two GETs for one state -> one 200 + one 410; exchange_code once.

    async def test_oauth2_browser_error_no_legacy_fallback(self):
        # FILL IN: prefixed state + error=access_denied, and prefixed state without code ->
        # 400 browser page, no sendData, no strategy call; the state is consumed (retry -> 410).

    async def test_browser_mode_full_flow_oauth2(self):
        # FILL IN: /login -> provider redirect simulated -> authenticated TelegramUserSession and a
        # proactive bot.send_message to the chat.
```

### FILL IN checklist
- [ ] `_browser_oauth2_callback` remaining rows — response table
- [ ] Seven tests

---

## Acceptance Criteria

- [ ] Prefixed states never reach legacy rendering; unprefixed states are byte-identical to today (legacy tests unchanged).
- [ ] Miss → 410; provider error/missing code on a hit → 400; both with no `sendData`, strategy call or mutation.
- [ ] Exactly one exchange per successful login; a concurrent duplicate gets 410.
- [ ] No strategy method is called from `oauth2_callback.py`.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_integration.py -q`

---

## Test Specification

See the appended test block (spec §4 rows `test_oauth2_callback_browser_branch`,
`test_oauth2_callback_legacy_branch_unchanged`, `test_oauth2_browser_replay_expiry_410`,
`test_oauth2_browser_callback_exactly_once`, `test_oauth2_browser_concurrent_callbacks`,
`test_oauth2_browser_error_no_legacy_fallback`; integration `test_browser_mode_full_flow_oauth2`).

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
   `PYTHONPATH=packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5425 telegram-auth-open-mode verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
