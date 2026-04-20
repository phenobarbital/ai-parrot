# TASK-783: `login_multi.html` — Unified Auth Chooser Page

**Feature**: FEAT-109 — Telegram Multi-Auth Negotiation
**Spec**: `sdd/specs/FEAT-109-telegram-multi-auth-negotiation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (3-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The Telegram WebApp page that `CompositeAuthStrategy` opens. It is
a stateless chooser — on load it parses the query string and
renders ONE button per auth method it was told about (`auth_url` →
basic, `azure_auth_url` → azure). Clicking a button runs the
method-specific flow inline, ending with
`tg.sendData({auth_method: <name>, ...})` so the wrapper's
composite can dispatch.

Implements **Module 7** of the spec. Parallelizable — pure static
file.

---

## Scope

- Create `static/telegram/login_multi.html`.
- On load:
  1. Parse URL query params: `auth_url`, `azure_auth_url`,
     `next_auth_url`, `next_auth_required`, plus Azure callback
     `token`.
  2. If `token` is present → handle the Azure token-callback
     branch (copy from `azure_login.html:162-188`). Post
     `{auth_method: "azure", token}` via `tg.sendData`.
  3. Otherwise, render one button per non-empty auth URL:
     - `auth_url` → "🔐 Sign in to Navigator" — reveals the
       email/password form (copy from `login.html`).
     - `azure_auth_url` → "🪟 Sign in with Azure" — the redirect
       flow (copy from `azure_login.html:194-218`).
  4. Preserve `next_auth_url` / `next_auth_required` across any
     redirect:
     - Basic path: submit the form with these fields so the
       Navigator login endpoint returns a redirect that carries
       them through (same contract `login.html` already uses for
       `next_auth_url` — verify in that file).
     - Azure path: use the same `preserveParams` pattern as
       `azure_login.html:205-213` and extend the preserved set.
- Every `sendData` payload MUST include `auth_method: "basic"` or
  `auth_method: "azure"` so `CompositeAuthStrategy.handle_callback`
  can dispatch.
- Apply the same visual style (CSS) as `azure_login.html` for
  consistency — the Telegram theme variables (`--tg-theme-*`) are
  the shared language.
- Accessibility: `aria-label` on each button, keyboard-navigable
  form.

**NOT in scope**:
- Replacing / deleting `login.html` or `azure_login.html`.
- Server-side changes to Navigator.
- OAuth2 button (spec non-goal for MVP).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `static/telegram/login_multi.html` | CREATE | Unified auth chooser — dispatch by query params |

---

## Codebase Contract (Anti-Hallucination)

### Reference Files

```
static/telegram/login.html         — BasicAuth form + sendData flow
static/telegram/azure_login.html   — Azure redirect + token callback flow
```

### Verified Patterns

```html
<!-- From azure_login.html:205-213 — parameter preservation across
     the Microsoft round-trip: -->
var preserveParams = new URLSearchParams();
preserveParams.set('azure_auth_url', azureUrl);
var redirectUrl = pageBase + '?' + preserveParams.toString();
var sep = azureUrl.indexOf('?') !== -1 ? '&' : '?';
var fullUrl = azureUrl + sep + 'redirect_url=' + encodeURIComponent(redirectUrl);
window.location.href = fullUrl;
```

```html
<!-- From azure_login.html:162-188 — token callback flow that posts
     sendData({auth_method: "azure", token}) and closes the WebApp. -->
```

```html
<!-- From login.html — BasicAuth form that submits credentials to
     auth_url (POST), receives a JWT, and posts:
     tg.sendData({user_id, token, display_name, email}).
     TASK-777 is adding auth_method: "basic" to this payload in
     login.html; do the same in login_multi.html from the start. -->
```

### Does NOT Exist

- ~~A pre-existing `login_multi.html`~~ — this task creates it.
- ~~Server-side negotiation endpoint~~ — explicitly non-goal.

---

## Implementation Notes

### File skeleton

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Sign In</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style> /* reuse tg-theme-* vars from azure_login.html */ </style>
</head>
<body>
  <div class="login-card">
    <div class="login-header">
      <div class="icon">&#x1F510;</div>
      <h1>Sign In</h1>
      <p>Choose how you'd like to authenticate</p>
    </div>
    <div id="mainContent"></div>
    <div class="status-msg" id="statusMsg"></div>
  </div>

  <script>
    const tg = window.Telegram.WebApp;
    tg.ready(); tg.expand();

    const params = new URLSearchParams(window.location.search);
    const authUrl = params.get('auth_url') || '';
    const azureAuthUrl = params.get('azure_auth_url') || '';
    const nextAuthUrl = params.get('next_auth_url') || '';
    const nextAuthRequired = params.get('next_auth_required') === 'true';
    const token = params.get('token') || '';

    // --- 1. Azure token-callback branch (copy from azure_login.html) ---
    if (token) {
      handleAzureTokenCallback(token);
      return;
    }

    // --- 2. Render buttons for available methods ---
    const content = document.getElementById('mainContent');
    if (authUrl) content.appendChild(buildBasicButton(authUrl));
    if (azureAuthUrl) content.appendChild(buildAzureButton(azureAuthUrl));
    if (!authUrl && !azureAuthUrl) {
      showError('No authentication methods configured.');
    }

    // --- Helpers ---
    function buildBasicButton(url) { /* reveals form; submit → sendData({auth_method:"basic",...}) */ }
    function buildAzureButton(url) { /* redirects; on return, sendData({auth_method:"azure", token}) */ }
    function handleAzureTokenCallback(t) { /* identical to azure_login.html:162-188 */ }
  </script>
</body>
</html>
```

### Preservation for the redirect chain

Both button handlers must carry `next_auth_url` /
`next_auth_required` through their respective flows:

```js
// Azure button — when composing the redirect_url:
const preserveParams = new URLSearchParams();
preserveParams.set('azure_auth_url', azureAuthUrl);
if (nextAuthUrl) preserveParams.set('next_auth_url', nextAuthUrl);
if (nextAuthRequired) preserveParams.set('next_auth_required', 'true');
const redirectUrl = pageBase + '?' + preserveParams.toString();

// Basic form — pass as hidden fields or query params on the POST
// — whatever login.html currently does; follow its contract
// exactly.
```

### Visual parity

Copy the CSS block verbatim from `azure_login.html` (it's
Telegram-theme-aware) and adjust only button colors if you want to
differentiate basic vs azure. Keep `.btn-azure` class and add
`.btn-basic` sibling so CSS remains cohesive.

---

## Acceptance Criteria

- [ ] `static/telegram/login_multi.html` exists.
- [ ] Opened with `?auth_url=X` only → only the basic button shows.
- [ ] Opened with `?azure_auth_url=Y` only → only the azure button.
- [ ] Opened with both → both buttons shown.
- [ ] Opened with neither → "No authentication methods configured"
      error state.
- [ ] Azure click path preserves `next_auth_url` /
      `next_auth_required` across the MS round-trip.
- [ ] Basic submit path preserves `next_auth_url` /
      `next_auth_required` to Navigator (matches `login.html`'s
      contract).
- [ ] Every `sendData` payload includes
      `auth_method: "basic" | "azure"`.
- [ ] Smoke test: open the file locally with query params in a
      browser and confirm no JS errors in console, buttons render,
      click handlers fire.

---

## Test Specification

Client-side HTML is typically not unit-tested in this repo. Manual
smoke tests are the acceptance path:

1. Open `http://localhost/static/telegram/login_multi.html?auth_url=https://h/api/v1/login&azure_auth_url=https://h/api/v1/auth/azure/`
   in a desktop browser.
2. Verify both buttons render; click each; confirm correct redirect
   target in DevTools Network tab.
3. Open with `?next_auth_url=https://jira.example.com/oauth&next_auth_required=true&auth_url=…`
   and verify the param is preserved in the outbound URL.

A headless test with Playwright is acceptable but optional.

---

## Agent Instructions

1. Read `login.html` and `azure_login.html` in full before writing a
   line — the goal is feature parity with both, not reinvention.
2. Stick to vanilla JS; no build step.
3. Match the Telegram-theme CSS variables.
4. Commit as an SDD-scoped commit.

---

## Completion Note

*(Agent fills this in when done)*
