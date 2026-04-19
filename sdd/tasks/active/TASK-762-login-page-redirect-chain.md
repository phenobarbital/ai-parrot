# TASK-762: Login Page JS Redirect Chain

**Feature**: FEAT-108 — Jira OAuth2 3LO Authentication from Telegram WebApp
**Spec**: `sdd/specs/FEAT-108-jiratoolkit-auth-telegram.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-759
**Assigned-to**: unassigned

---

## Context

This task modifies the static login page HTML/JS (served to the Telegram WebApp)
to support a redirect chain. After BasicAuth succeeds, the login page checks for
a `next_auth_url` query parameter. If present, it redirects the browser to that
URL (Jira's OAuth2 authorization page) instead of immediately calling
`WebApp.sendData()`. This keeps the user within a single WebApp interaction
for both auth flows.

Implements Spec Module 7.

**IMPORTANT**: The exact file path of the login page is listed as an Open Question
in the spec. The implementing agent must locate it first.

---

## Scope

- Locate the static login page HTML/JS file (search for the file that handles
  BasicAuth form submission and calls `WebApp.sendData()`).
- Modify the JS to:
  1. On page load, parse `next_auth_url` and `next_auth_required` from URL params.
  2. After BasicAuth succeeds (existing flow):
     - If `next_auth_url` is present: redirect to `next_auth_url` instead of
       calling `WebApp.sendData()`.
     - If `next_auth_url` is absent: call `WebApp.sendData()` as before
       (backward compatible).
  3. If `next_auth_required` is `"false"` and the redirect fails or user returns
     without completing Jira auth, fall back to sending just the BasicAuth data.
- Ensure no regression for the existing BasicAuth-only flow.

**NOT in scope**: The combined callback endpoint (TASK-759, already done),
server-side wrapper logic (TASK-763), or any Python code changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| (login page HTML/JS — path TBD) | MODIFY | Add redirect chain logic after BasicAuth success |

---

## Codebase Contract (Anti-Hallucination)

### Verified References
```javascript
// The existing login page JS calls:
// Telegram.WebApp.sendData(JSON.stringify({
//   user_id: "...",
//   token: "...",
//   display_name: "...",
//   email: "..."
// }));
// This is the BasicAuth result data structure that the wrapper expects.

// The combined callback endpoint (TASK-759) at:
// GET /api/auth/telegram/combined-callback?code=...&state=...
// returns HTML that calls WebApp.sendData with jira data.
```

### Existing Patterns
```python
# BasicAuthStrategy builds the login keyboard URL at auth.py:284:
full_url = f"{page_url}?{urlencode({'auth_url': self.auth_url})}"
# After TASK-763, this will also include next_auth_url and next_auth_required params
```

### Does NOT Exist
- ~~A `next_auth_url` parameter in the login page~~ — does not exist yet (this task adds it)
- ~~Any redirect logic in the login page~~ — currently sends data directly via WebApp.sendData

---

## Implementation Notes

### JS Modification Pattern
```javascript
// After BasicAuth succeeds:
const urlParams = new URLSearchParams(window.location.search);
const nextAuthUrl = urlParams.get('next_auth_url');
const nextAuthRequired = urlParams.get('next_auth_required') !== 'false';

if (nextAuthUrl) {
    // Redirect to secondary auth (e.g., Jira OAuth2)
    window.location.href = nextAuthUrl;
} else {
    // Original behavior: send BasicAuth data back to Telegram
    Telegram.WebApp.sendData(JSON.stringify(authResult));
}
```

### Key Constraints
- The login page must remain backward compatible — no `next_auth_url` = original behavior
- BasicAuth data does NOT need to be passed to the redirect URL — it's stashed server-side
  in Redis as part of the Jira state nonce (see TASK-758's `extra_state`)
- The redirect is a simple `window.location.href` assignment — the browser navigates
  to Jira's consent page within the same WebApp
- XSS considerations: `next_auth_url` should be validated (starts with `https://`)

### References in Codebase
- `packages/ai-parrot/src/parrot/integrations/telegram/auth.py:284` — where the login page URL is constructed
- `packages/ai-parrot/src/parrot/integrations/telegram/oauth2_callback.py:58-67` — JS pattern for WebApp interaction

---

## Acceptance Criteria

- [ ] Login page detects `next_auth_url` query param
- [ ] When `next_auth_url` present: redirects to it after BasicAuth success
- [ ] When `next_auth_url` absent: sends BasicAuth data via `WebApp.sendData()` (unchanged)
- [ ] URL validation: only redirects to `https://` URLs
- [ ] No regression in the existing BasicAuth-only flow
- [ ] Manual test: login page loads, BasicAuth works, redirect to Jira consent page works

---

## Test Specification

This task primarily involves client-side JavaScript modifications. Testing approach:
- **Manual testing** in a browser with Telegram WebApp context
- **Visual verification** that the redirect chain works
- Optionally: unit test the JS logic if a test framework is available

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context
2. **Check dependencies** — verify TASK-759 is completed
3. **FIRST: Locate the login page file** — search for HTML files that reference
   `Telegram.WebApp.sendData` or `auth_url` parameter. Try:
   - `grep -r "WebApp.sendData" --include="*.html" --include="*.js"`
   - `grep -r "auth_url" --include="*.html" --include="*.js"`
   - Check if it's served by navigator-auth (external) rather than ai-parrot
4. **If the login page is external** (navigator-auth), document this and propose
   how to modify it. The implementing agent should communicate this finding.
5. **Modify** the login page JS
6. **Test manually** if possible
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
