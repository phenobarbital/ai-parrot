# TASK-5421: Dual-mode login pages (webview `sendData` | browser POST) + executable round-trip test

**Feature**: FEAT-854 — Telegram Auth Open Mode (webview | browser)
**Spec**: `sdd/specs/telegram-auth-open-mode.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5418
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. In browser mode the login page runs in the system browser, where
`Telegram.WebApp.sendData()` does not exist. When the page URL carries
`return_mode=browser&state=<s>&complete_url=<u>` (added by TASK-5419), the page must
POST `{...payload, state}` to the validated `complete_url` (endpoint built by
TASK-5424) instead of calling `sendData`. Azure/Google SSO must carry those three
params through the Navigator round trip. Missing or broken browser context must
**fail closed**: show an error, never fall back to `sendData`. Pages opened without
browser params (old servers, old links, the Telegram webview) keep the legacy path
unchanged.

Facts verified at `/sdd-task` time (paths under
`packages/ai-parrot-integrations/src/parrot/integrations/telegram/static/`):
- The pages call `tg.sendData(...)`, not `Telegram.WebApp.sendData(...)`:
  `login.html:164`, `azure_login.html:219`, `login_multi.html:293`.
- `login.html` `tg` is null-safe (`:115`); `azure_login.html:140` and
  `login_multi.html:240` dereference `window.Telegram.WebApp` unguarded.
- Redirect allowlists: `azure_login.html:248-257` (`preserveParams`, redirect built at
  `:257`, sent as `redirect_uri` at `:260-263`); `login_multi.html:552-570` in
  `buildSSOButton` (Google `:352-358` and Azure `:365-371` both use it).
- Return leg: `azure_login.html:278-287` → `handleTokenCallback(tokenValue)` (`:183`);
  `login_multi.html:332-335` → `handleTokenCallback` (`:612`, method from
  sessionStorage `tg_pending_auth_method`, `:313-325`).
- These pages are **not served by ai-parrot** (no `add_static` for this folder);
  deployments host them at `login_page_url`. The page therefore cannot assume the parrot
  origin — see the completion-destination rule below.

**Cross-repo caveat (record in the Completion Note, do not fix here):** navigator-auth's
Google backend does not keep the caller's `redirect_uri` (`navigator_auth/backends/google.py:99-167`
stores only nonce + callback URI; `external.py:315-346` `home_redirect` then lands on
`AUTH_OAUTH2_REDIRECT_URL`/`AUTH_REDIRECT_URI`). Real Google browser-mode SSO needs a
navigator-auth fix; the page side is still implemented and tested here with a
simulated Navigator return. Azure keeps it (`azure.py:229-254`, gated by
`AUTH_TRUSTED_DOMAINS`).

---

## Scope

- Add one shared JS snippet (identical text in all three pages) providing
  `readBrowserContext()`, `validateBrowserContext(ctx)`, `appendBrowserParams(params)`,
  `completeLogin(payload, legacySend)` and `showBrowserResult(ok, message, redirectUrl)`.
- `login.html`: route `sendBasicAuthAndClose(payload)` through `completeLogin`.
- `azure_login.html`: make `tg` null-safe; build the payload as an object; route
  `handleTokenCallback` through `completeLogin`; call `appendBrowserParams(preserveParams)`
  before `redirectUrl` is built.
- `login_multi.html`: make `tg` null-safe; route `sendAndClose(payload)` through
  `completeLogin`; call `appendBrowserParams(preserveParams)` in `buildSSOButton`.
- Create the executable Playwright test `test_login_pages_browser_mode.py`.

**NOT in scope**: the server endpoint (TASK-5424), the OAuth2 button in
`login_multi.html` (it navigates to the provider; the server callback handles browser
mode — TASK-5425), `combined_callback.py`'s legacy `sendData` page (unreachable from
`/login`: `handle_login` never passes `next_auth_url`), navigator-auth changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/static/login.html` | MODIFY | Shared snippet + browser completion for basic |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/static/azure_login.html` | MODIFY | Snippet, SSO param continuity, browser completion |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/static/login_multi.html` | MODIFY | Snippet, SSO param continuity (Azure + Google), browser completion |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_login_pages_browser_mode.py` | CREATE | Playwright round-trip tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev @ `0083e04b62` (2026-11-09).

### Verified Imports (test)
```python
async_playwright = pytest.importorskip("playwright.async_api", reason="...").async_playwright
#   pattern: packages/ai-parrot-integrations/tests/voice/test_voice_demo_broadcast_browser.py:44-46
#   launch pattern: same file :242-249 (chromium.launch(headless=True), add_init_script, goto)
from parrot.integrations.telegram.browser_login import BROWSER_COMPLETE_PATH, new_browser_state  # TASK-5418
```
playwright 1.52.0 + cached Chromium are installed in the shared venv; it is NOT declared
by ai-parrot-integrations (only `ai-parrot[agents]`, `ai-parrot-tools[scraping]`), so the
test must `importorskip` — and the Completion Note must show a non-skipped run.
`asyncio_mode = "auto"` (ai-parrot-integrations/pyproject.toml:148).

### Existing anchors (exact lines)
```
login.html:162        function sendBasicAuthAndClose(payload) {
login.html:164              tg.sendData(JSON.stringify(payload));
login.html:69         </head>
azure_login.html:140  var tg = window.Telegram.WebApp;            (unguarded)
azure_login.html:183  function handleTokenCallback(tokenValue) {
azure_login.html:205-208  payload = JSON.stringify({auth_method:'azure', token: tokenValue})
azure_login.html:219                      tg.sendData(payload);
azure_login.html:257  var redirectUrl = pageBase + '?' + preserveParams.toString();
azure_login.html:122  </head>
login_multi.html:240  tg assignment (unguarded)
login_multi.html:291  function sendAndClose(payload) {
login_multi.html:293                  tg.sendData(JSON.stringify(payload));
login_multi.html:559  if (azureAuthUrl) preserveParams.set('azure_auth_url', azureAuthUrl);
login_multi.html:570  redirectUrl built
login_multi.html:612  function handleTokenCallback(
login_multi.html:194  </head>
```
Counts: `tg.sendData(` = 1 per page; `preserveParams.set(` = 3 in azure_login.html.

### Does NOT Exist
- ~~A server-side template for these pages~~ — they are static files; config must live in the HTML (`<meta>`).
- ~~`Telegram.WebApp.sendData` in a system browser~~ — absent outside Telegram.
- ~~jsdom navigation~~ — jsdom cannot follow `location.href` redirects, which is why the SSO leg is tested with Playwright.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/static/login.html", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/static/azure_login.html", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/static/login_multi.html", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_login_pages_browser_mode.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Decided rules
- **Browser context is present** when any of: `return_mode` param, a `state` starting with
  `browser.`, a `complete_url` param, or the sessionStorage marker `tg_browser_login_ctx`.
- **Present ⇒ must be valid, else error (never `sendData`)**: `return_mode === 'browser'`;
  `state` matches `/^browser\.[A-Za-z0-9_-]{43}$/`; marker state (if any) equals `state`;
  `complete_url` parses, has no query/hash, `pathname === '/api/auth/telegram/browser-complete'`,
  protocol `https:` (or `http:` only when same-origin), and its **origin is allowed**.
- **Allowed completion origins** ("server-provided", not query-provided): the page's own
  `location.origin`, plus the space-separated origins in
  `<meta name="parrot-browser-complete-origins" content="...">` which the deployer sets
  in the hosted copy of the page (shipped with `content=""`).
- POST: `fetch(complete_url, {method: 'POST', credentials: 'omit', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(Object.assign({}, payload, {state}))})`.
  On `200` + `{ok: true}` show success with a link to `redirect_url` **only if** it starts
  with `https://t.me/`; other statuses show an error (410: "link expired, send /login again";
  401: "sign-in rejected"; 503: "server temporarily unavailable"). Clear the marker after the attempt.
- SSO continuity: `appendBrowserParams(params)` copies `return_mode`, `state` and
  `complete_url` from the current URL into the redirect allowlist **and** stores the marker
  `{state}` in sessionStorage — but only when the context validates; otherwise show the error
  and do not redirect.
- Legacy: when no browser context is present, run the existing code path unchanged.

---

## Implementation Blueprint

### Steps (in order)
1. Add the meta tag before `</head>` in each page (`</head>` occurs once per page).
2. Paste the shared snippet into each page's inline script, before the first use.
3. Wire each page (blocks below).
4. Write the Playwright tests; run them and record the output (no skips).

### Shared snippet (identical in all three pages)
```javascript
  // FEAT-854 browser-mode completion — keep this block identical in all login pages.
  var BROWSER_COMPLETE_PATH = '/api/auth/telegram/browser-complete';
  var BROWSER_STATE_RE = /^browser\.[A-Za-z0-9_-]{43}$/;
  var BROWSER_CTX_KEY = 'tg_browser_login_ctx';

  function readBrowserContext() {
    var q = new URLSearchParams(window.location.search);
    var marker = null;
    try { marker = JSON.parse(window.sessionStorage.getItem(BROWSER_CTX_KEY) || 'null'); } catch (e) { marker = null; }
    var ctx = { mode: q.get('return_mode'), state: q.get('state'), completeUrl: q.get('complete_url'), marker: marker };
    ctx.present = !!(ctx.mode || ctx.completeUrl || marker ||
                     (ctx.state && ctx.state.indexOf('browser.') === 0));
    return ctx;
  }

  function allowedCompletionOrigins() {
    var meta = document.querySelector('meta[name="parrot-browser-complete-origins"]');
    var extra = meta ? (meta.getAttribute('content') || '').split(/\s+/).filter(Boolean) : [];
    return [window.location.origin].concat(extra);
  }

  function validateBrowserContext(ctx) {
    // FILL IN: return null when valid, else a user-facing error string — every rule in
    // "Decided rules" above (mode, state regex, marker match, URL parse, no query/hash,
    // exact path, protocol, allowed origin). Bounded by spec M6 "never POST credentials to
    // an arbitrary query-supplied URL".
  }

  function appendBrowserParams(params) {
    var ctx = readBrowserContext();
    if (!ctx.present) { return true; }
    var err = validateBrowserContext(ctx);
    if (err) { showBrowserResult(false, err); return false; }
    params.set('return_mode', 'browser');
    params.set('state', ctx.state);
    params.set('complete_url', ctx.completeUrl);
    try { window.sessionStorage.setItem(BROWSER_CTX_KEY, JSON.stringify({ state: ctx.state })); } catch (e) { /* storage blocked */ }
    return true;
  }

  function completeLogin(payload, legacySend) {
    var ctx = readBrowserContext();
    if (!ctx.present) { legacySend(); return; }
    var err = validateBrowserContext(ctx);
    if (err) { showBrowserResult(false, err); return; }
    // FILL IN: fetch POST per "Decided rules"; map status -> message; clear the marker;
    // call showBrowserResult(ok, message, redirectUrl). Never log or render the token.
  }

  function showBrowserResult(ok, message, redirectUrl) {
    // FILL IN: replace the page body content with a success/error panel; render the
    // link only when redirectUrl starts with 'https://t.me/'; set textContent (never innerHTML
    // with server/user strings).
  }
```

### `static/login.html` (MODIFY)
```javascript
// occurrences: 1 (verified: grep -c 'function sendBasicAuthAndClose(payload) {' static/login.html) — line 162
// Wrap the existing body: the original statements move unchanged into legacySend.
  function sendBasicAuthAndClose(payload) {
    completeLogin(payload, function legacySend() {
      // FILL IN: the original lines 163-171 of this function, unchanged.
    });
  }
// meta — BEFORE `</head>` (occurs once, line 69):
  <meta name="parrot-browser-complete-origins" content="">
```

### `static/azure_login.html` (MODIFY)
```javascript
// line 140 (occurs once): var tg = window.Telegram.WebApp;  ->
var tg = (window.Telegram && window.Telegram.WebApp) || null;
// FILL IN: guard every later `tg.` use with `if (tg)` — inside Telegram behavior is identical.

// handleTokenCallback (line 183, occurs once): build `var payloadObj = {auth_method: 'azure', token: tokenValue};`
// keep `var payload = JSON.stringify(payloadObj);` for the legacy path, and wrap the existing
// setTimeout/sendData block (lines ~216-222) as:
//   completeLogin(payloadObj, function legacySend() { /* original block, unchanged */ });

// occurrences: 1 (verified: grep -c "var redirectUrl = pageBase + '?' + preserveParams.toString();" static/azure_login.html) — line 257
// BEFORE it insert:
        if (!appendBrowserParams(preserveParams)) { return; }
```

### `static/login_multi.html` (MODIFY)
```javascript
// tg assignment (line 240): make null-safe as in azure_login.html; guard later uses.
// sendAndClose(payload) (line 291, occurs once): wrap the existing body in
//   completeLogin(payload, function legacySend() { /* original lines 292-297 */ });
// handleTokenCallback (line 612) already calls sendAndClose -> no extra change.
// occurrences: 1 (verified: grep -c "if (azureAuthUrl) preserveParams.set('azure_auth_url', azureAuthUrl);" static/login_multi.html) — line 559
// FILL IN: after the next_auth_* lines (564-569) and BEFORE redirectUrl is built (line 570) insert
//   if (!appendBrowserParams(preserveParams)) { return; }
// inside the click handler, so both Google and Azure buttons carry the browser params.
```

### `packages/ai-parrot-integrations/tests/integrations/telegram/test_login_pages_browser_mode.py` (CREATE)
```python
"""FEAT-854 M6: executable round-trip checks for the dual-mode Telegram login pages."""
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from parrot.integrations.telegram.browser_login import BROWSER_COMPLETE_PATH, new_browser_state

async_playwright = pytest.importorskip(
    "playwright.async_api", reason="playwright is required for login-page browser tests"
).async_playwright

STATIC = Path(__file__).resolve().parents[3] / "src/parrot/integrations/telegram/static"
PAGE_ORIGIN = "https://login.example.test"
PARROT_ORIGIN = "https://parrot.example.test"
NAV_ORIGIN = "https://nav.example.test"
INIT_SCRIPT = """
window.__sendData = [];
window.Telegram = { WebApp: { ready(){}, expand(){}, close(){},
  sendData(d){ window.__sendData.push(d); }, initData: '' } };
"""


@pytest.fixture
async def browser_page():
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium unavailable: {exc}")
        page = await browser.new_page()
        await page.add_init_script(INIT_SCRIPT)
        # FILL IN: page.route(f"{PAGE_ORIGIN}/static/*") -> fulfill from STATIC/<name>
        # (optionally injecting a meta content); route "https://telegram.org/**" -> fulfill "";
        # record POSTs to *{BROWSER_COMPLETE_PATH} (url + post_data) on page.complete_posts.
        yield page
        await browser.close()


async def test_basic_browser_mode_posts_payload_not_senddata(browser_page):
    # FILL IN: open login.html?auth_url=<NAV>/api/v1/login&return_mode=browser&state=<s>
    # &complete_url=<PAGE_ORIGIN><BROWSER_COMPLETE_PATH> (same-origin); stub the login POST;
    # submit; assert one completion POST carrying state + auth_method=basic + token,
    # success panel with the t.me link, and window.__sendData == [].


async def test_basic_legacy_mode_uses_senddata(browser_page):
    # FILL IN: no browser params -> exactly one sendData, zero completion POSTs.


async def test_browser_mode_sso_redirect_round_trip(browser_page):
    # FILL IN: azure_login.html and login_multi.html (Azure AND Google buttons): click ->
    # capture the Navigator request, parse redirect_uri, assert return_mode/state/complete_url
    # preserved exactly; fulfill a 302 to redirect_uri + "&token=<jwt>"; assert one POST, zero sendData.
    # Cross-origin complete_url (PARROT_ORIGIN) must work only with the meta allowlist injected.


async def test_browser_mode_sso_context_failure(browser_page):
    # FILL IN: (a) browser state but no return_mode; (b) complete_url on a non-allowed origin;
    # (c) wrong path; (d) return leg with the marker set but params stripped -> error shown,
    # zero POSTs, zero sendData in every case.
```

### FILL IN checklist
- [ ] `validateBrowserContext`, `completeLogin`, `showBrowserResult` — decided rules; spec M6
- [ ] Page wiring in all three pages; `tg` null-safe in azure_login/login_multi
- [ ] Playwright tests (four scenarios above); record the run output in the Completion Note

---

## Acceptance Criteria

- [ ] Pages without browser params behave exactly as before (legacy `sendData` test passes).
- [ ] Browser mode: one POST `{...payload, state}` to the validated `complete_url`, zero `sendData`.
- [ ] Azure and multi-login (Azure + Google) preserve `return_mode`, `state`, `complete_url` in `redirect_uri`.
- [ ] Missing/corrupt context, disallowed origin or wrong path → error, no POST, no `sendData`.
- [ ] Shared snippet text identical in the three pages.
- [ ] Completion Note shows `pytest ... -rs` output with **0 skipped**, and records the navigator-auth Google `redirect_uri` caveat.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_login_pages_browser_mode.py -q -rs`

---

## Test Specification

See the test block above (spec §4 integration rows `test_browser_mode_sso_redirect_round_trip`,
`test_browser_mode_sso_context_failure`).

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
9. **Close the task** with `parrot sdd task close TASK-5421 telegram-auth-open-mode verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
