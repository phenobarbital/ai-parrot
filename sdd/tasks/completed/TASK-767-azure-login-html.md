# TASK-767: Create Azure Login HTML Page

**Feature**: FEAT-109 — Telegram Integration Azure SSO via Navigator
**Spec**: `sdd/specs/telegram-integration-basicauth.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Implements Module 4 from the spec. This is the static HTML page that the
> Telegram WebApp loads when the user taps "Sign in with Azure". The page
> serves dual purpose:
> 1. Without `?token=`: shows a "Sign in with Azure" button that redirects
>    to Navigator's Azure endpoint
> 2. With `?token=jwt`: captures the token and sends it back to Telegram
>    via `WebApp.sendData()`

---

## Scope

- Create `static/telegram/azure_login.html` with:
  - Telegram WebApp JS SDK integration (`telegram-web-app.js`)
  - Query param parsing for `azure_auth_url` and `token`
  - Token detection and auto-submit to Telegram on page load
  - "Sign in with Azure" button that redirects to Navigator's Azure endpoint
  - Matching visual style with existing `login.html` (dark theme, Telegram CSS vars)
  - Error handling for missing `azure_auth_url`
  - Success/loading spinner after token capture

**NOT in scope**: Config model (TASK-764), auth strategy (TASK-765), wrapper changes (TASK-766)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `static/telegram/azure_login.html` | CREATE | Azure SSO login page for Telegram WebApp |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
N/A — this is a standalone HTML file.

### Existing Signatures to Use
```javascript
// Telegram WebApp API (from telegram-web-app.js):
window.Telegram.WebApp.ready()      // Signal readiness
window.Telegram.WebApp.expand()     // Expand to full height
window.Telegram.WebApp.sendData(jsonString)  // Send data back to bot
window.Telegram.WebApp.close()      // Close WebApp

// Verified usage in existing login.html:
// Line 174: const tg = window.Telegram.WebApp;
// Line 175: tg.ready();
// Line 176: tg.expand();
// Line 235: tg.sendData(payload);
```

### Reference: Existing login.html Structure
```html
<!-- static/telegram/login.html — follow same visual patterns -->
<!-- Uses Telegram CSS variables for theming:
  --tg-theme-bg-color        (background)
  --tg-theme-secondary-bg-color  (card background)
  --tg-theme-text-color      (text)
  --tg-theme-hint-color      (secondary text)
  --tg-theme-button-color    (button background)
  --tg-theme-button-text-color (button text)
-->
```

### Callback Data Format
```json
{
  "auth_method": "azure",
  "token": "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiMTIzIn0.sig"
}
```
This is what `AzureAuthStrategy.handle_callback()` (TASK-765) expects.

### Does NOT Exist
- ~~`static/telegram/azure_login.html`~~ — does not exist yet; this task creates it
- ~~`Telegram.WebApp.authenticate()`~~ — not a real API method
- ~~`Telegram.WebApp.getToken()`~~ — not a real API method

---

## Implementation Notes

### Page Flow
```
Page Load:
  1. Initialize Telegram WebApp (ready, expand)
  2. Parse URL query params
  3. Check: does ?token= exist?
     YES → Token redirect-back flow:
       a. Build payload: {"auth_method": "azure", "token": tokenValue}
       b. Show "Authentication complete" + spinner
       c. Call tg.sendData(JSON.stringify(payload))
       d. Close WebApp after 500ms delay
     NO → Login button flow:
       a. Check: does ?azure_auth_url= exist?
          YES → Show "Sign in with Azure" button
          NO  → Show error "Azure auth not configured"
       b. On button click:
          - Build redirect URL: azure_auth_url + ?redirect_url=currentPageURL
          - NOTE: redirect_url must include ALL current query params
            so that azure_auth_url is preserved across the redirect
          - window.location.href = redirectURL
```

### Visual Style
Follow `login.html` exactly:
- Dark theme with Telegram CSS variables
- Centered card layout (`.login-card`)
- Same font stack (`-apple-system, BlinkMacSystemFont, ...`)
- Same spinner animation
- Replace username/password form with single Azure button
- Button text: "Sign in with Azure" with Microsoft icon or lock icon
- Same border-radius, padding, shadow

### Redirect URL Construction
```javascript
// CRITICAL: preserve the azure_auth_url param in the redirect_url
// so the page knows what to do on redirect-back
const currentUrl = window.location.href.split('?')[0];
const preserveParams = new URLSearchParams();
preserveParams.set('azure_auth_url', azureAuthUrl);
const redirectUrl = currentUrl + '?' + preserveParams.toString();

const fullUrl = azureAuthUrl +
    (azureAuthUrl.includes('?') ? '&' : '?') +
    'redirect_url=' + encodeURIComponent(redirectUrl);
window.location.href = fullUrl;
```

### Security Notes
- Token value must NOT be logged or stored in localStorage
- Use `encodeURIComponent()` for all URL parameter values
- No XSS vectors: token is only passed to `sendData()`, never injected into DOM

### References in Codebase
- `static/telegram/login.html` — existing BasicAuth page (copy visual structure)
- `packages/ai-parrot/src/parrot/integrations/telegram/oauth2_callback.py` — similar pattern of capturing data and calling `sendData()`

---

## Acceptance Criteria

- [ ] `static/telegram/azure_login.html` exists and is valid HTML5
- [ ] Page shows "Sign in with Azure" button when loaded with `?azure_auth_url=...`
- [ ] Button redirects to `{azure_auth_url}?redirect_url={current_page_with_params}`
- [ ] Page detects `?token=jwt` on load and sends `{"auth_method": "azure", "token": jwt}` to Telegram
- [ ] Page shows error message when `azure_auth_url` is missing
- [ ] Page uses Telegram CSS variables for theming (matches login.html)
- [ ] Telegram.WebApp.sendData() is called with correct JSON format
- [ ] WebApp closes after successful token transmission
- [ ] No XSS vulnerabilities (token not injected into DOM HTML)

---

## Test Specification

This is a static HTML file — no pytest tests. Manual verification checklist:

1. Open `azure_login.html?azure_auth_url=https://example.com/api/v1/auth/azure/` in browser
   - [ ] "Sign in with Azure" button is visible
   - [ ] Button click would redirect to `https://example.com/api/v1/auth/azure/?redirect_url=...`

2. Open `azure_login.html?azure_auth_url=https://x.com&token=eyJhbGciOiJIUzI1NiJ9.eyJ0ZXN0IjoxfQ.sig` in browser
   - [ ] Page shows "Authentication complete" with spinner
   - [ ] (In Telegram WebApp context) sendData would be called

3. Open `azure_login.html` without params
   - [ ] Error message shown: "Azure authentication is not configured"

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/telegram-integration-basicauth.spec.md` Section 2 "Azure Login Page Flow"
2. **Check dependencies** — none; this task is independent of the Python tasks
3. **Read** `static/telegram/login.html` — use as visual reference
4. **Read** `packages/ai-parrot/src/parrot/integrations/telegram/oauth2_callback.py` — sendData pattern
5. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
6. **Create** `static/telegram/azure_login.html`
7. **Verify** by opening in a browser and checking the three scenarios above
8. **Move this file** to `sdd/tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-04-19
**Notes**: Created azure_login.html with token redirect-back flow and Azure sign-in button flow. Uses Telegram CSS variables for theming matching login.html. File needed force-add (-f) because static/* is gitignored.

**Deviations from spec**: none
