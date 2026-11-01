# TASK-4907: Passkey sign-in on the inline `/autonomous/admin` page

**Feature**: FEAT-772 — Passkey (WebAuthn) sign-in, enrollment and management in the Admin UI
**Spec**: `sdd/specs/passkey-support.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9, G7, AC12, codex S8. `/autonomous/admin` is a self-contained HTML string
(`_ADMIN_LOGIN_HTML`, no bundler) that logs in with BasicAuth and stores the same
`ai_parrot_token` / `ai_parrot_session` keys as the SPA. It gets **sign-in only** (button +
conditional UI), as a near-verbatim port of navigator-auth's own `templates/oauth/login.html`
passkey script (navigator-auth `dev` branch; not shipped in the installed wheel), with the
`/oauth2/authorize` continuation replaced by this page's `saveSession(data)` path. No enrollment;
the signed-in state links to the SPA's `/account/security`. There is no pytest for this page today;
this task adds a marker-level contract test (no browser in CI, so behaviour is checked manually).

---

## Scope

- In `_ADMIN_LOGIN_HTML`: `autocomplete="username webauthn"`; hidden `#passkeyBtn` button + `#alertError` reuse; vanilla passkey `<script>` block; a "Manage passkeys" link in `#quickLinks`.
- Visibility: unhide the button only after a successful probe `POST /api/v1/auth/passkey/login/options` (same rule as the SPA); reuse that probe response for conditional UI.
- Success: `saveSession(data); showAlert('success', 'Login successful! Redirecting…'); showSessionState(data);` then the same `setTimeout` redirect as `handleLogin`.
- Failure: `showAlert('error', 'Passkey sign-in failed. Use your password instead.')`; `NotAllowedError` / `AbortError` silent.
- Create `tests/test_autonomous_admin_page.py`.

**NOT in scope**: enrollment/management here, changes to `handleLogin` / BasicAuth, the orchestrator route registration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/autonomous/admin.py` | MODIFY | Passkey button + vanilla ceremony in `_ADMIN_LOGIN_HTML` |
| `packages/ai-parrot-server/tests/test_autonomous_admin_page.py` | CREATE | Contract test for the served page |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web
from parrot.autonomous.admin import _ADMIN_LOGIN_HTML, admin_login_page   # admin.py:17, :394
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/autonomous/admin.py
_ADMIN_LOGIN_HTML = """\ ... """                                         # :17 (plain string, NOT an f-string — braces are literal)
#   :217-218 <div class="alert error" id="alertError"></div> / alertSuccess
#   :220 <form id="loginForm" onsubmit="handleLogin(event)"> … :224 placeholder="Enter your username" autocomplete="username">
#   :233 <button type="submit" class="btn-login" id="loginBtn">Sign In</button>
#   :243-245 <div class="quick-links" id="quickLinks" style="display:none;"> <a href="/api/whatsapp/dashboard">…</a>
#   JS: saveSession(data) :252 · showAlert(type,msg) :273 · hideAlerts() · showSessionState(session) · handleLogin(event) :308
#       success path :340-346 → saveSession(data); showAlert('success','Login successful! Redirecting…'); showSessionState(data);
#       setTimeout(() => { window.location.href = '/api/whatsapp/dashboard'; }, 1500);
#   :324 'X-Auth-Method': 'BasicAuth'
async def admin_login_page(request: web.Request) -> web.Response   # :394 — text=_ADMIN_LOGIN_HTML, content_type='text/html'
# packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py:338 registers GET /autonomous/admin (not changed)
```
```js
// Upstream reference (navigator-auth templates/oauth/login.html, dev): OPTIONS_URL, LOGIN_URL; b64urlToBuffer,
// bufferToB64url, toRequestOptions (native parseRequestOptionsFromJSON first), credentialToJSON (toJSON first),
// passkeySignIn(username, mediation) with AbortController — conditional stored, explicit click aborts it;
// isConditionalMediationAvailable().then(available → passkeySignIn(undefined, "conditional")).
```

### Does NOT Exist
- ~~a pytest for `/autonomous/admin`~~ — created here.
- ~~enrollment endpoints usable without a session~~ — `register/*` require a session; do not add enrollment here.
- ~~`showError()`~~ in this page — use the existing `showAlert('error', …)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/autonomous/admin.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/test_autonomous_admin_page.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Change the username autocomplete — *why*: conditional UI requires the `webauthn` token.
2. Add the hidden button after `#loginBtn` and the "Manage passkeys" link in `#quickLinks`.
3. Add a second `<script>` block before `</body>` with the passkey code — *why*: keeps the existing script untouched.
4. Write the contract test.

### `packages/ai-parrot-server/src/parrot/autonomous/admin.py` (MODIFY)
```html
<!-- occurrences: 1 (verified: grep -c 'placeholder="Enter your username" autocomplete="username">' admin.py; :224) -->
<!-- REPLACE `autocomplete="username">` on that line with: -->
autocomplete="username webauthn">

<!-- occurrences: 1 (verified: grep -c '<button type="submit" class="btn-login" id="loginBtn">Sign In</button>' admin.py; :233) -->
<!-- AFTER that line (still inside the form), insert: -->
            <button type="button" class="btn-login" id="passkeyBtn" hidden>Sign in with a passkey</button>

<!-- inside #quickLinks, after the WhatsApp link, insert: -->
            <a href="/account/security">🔑 Manage passkeys</a>

<!-- BEFORE `</body>` (the last one in the string), insert a NEW <script> block: -->
    <script>
    (function () {
        var OPTIONS_URL = '/api/v1/auth/passkey/login/options';
        var LOGIN_URL = '/api/v1/login';
        if (!window.PublicKeyCredential || !navigator.credentials) { return; }
        var button = document.getElementById('passkeyBtn');
        var pending = null;

        // FILL IN: b64urlToBuffer, bufferToB64url, toRequestOptions, credentialToJSON — verbatim port of upstream login.html

        async function fetchOptions(username) {
            var resp = await fetch(OPTIONS_URL, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(username ? { username: username } : {})
            });
            return resp.ok ? resp.json() : null;
        }

        async function run(started, mediation) {
            // FILL IN: AbortController ownership (conditional stored in `pending`, explicit run aborts it first);
            //   cred = await navigator.credentials.get({publicKey: toRequestOptions(started.publicKey), signal, mediation?});
            //   resp = await fetch(LOGIN_URL, {method:'POST', credentials:'same-origin',
            //     headers:{'Content-Type':'application/json','X-Auth-Method':'PasskeyAuth'},
            //     body: JSON.stringify({challenge_id: started.challenge_id, credential: credentialToJSON(cred)})});
            //   !resp.ok → throw; data = await resp.json(); !data.token → throw;
            //   saveSession(data); showAlert('success', 'Login successful! Redirecting…'); showSessionState(data);
            //   setTimeout(function () { window.location.href = '/api/whatsapp/dashboard'; }, 1500);
            //   catch: NotAllowedError/AbortError → silent; else showAlert('error', 'Passkey sign-in failed. Use your password instead.')
        }

        button.addEventListener('click', async function () {
            hideAlerts();
            if (pending) { pending.abort(); pending = null; }
            var typed = document.getElementById('username').value.trim();
            var started = await fetchOptions(typed || undefined);
            if (!started) { showAlert('error', 'Passkey sign-in failed. Use your password instead.'); return; }
            run(started);
        });

        fetchOptions().then(async function (started) {
            if (!started) { return; }           // backend disabled / origin not an RP → page unchanged
            button.hidden = false;
            if (PublicKeyCredential.isConditionalMediationAvailable &&
                await PublicKeyCredential.isConditionalMediationAvailable()) {
                run(started, 'conditional');
            }
        });
    })();
    </script>
```
**Why**: the module string is a plain triple-quoted string (not an f-string), so JS braces need no escaping.
Do not touch `handleLogin` — BasicAuth must keep working (AC12).

### `packages/ai-parrot-server/tests/test_autonomous_admin_page.py` (CREATE)
```python
"""FEAT-772 contract test for the inline /autonomous/admin login page (passkey sign-in markers)."""
from __future__ import annotations

from aiohttp import web
from parrot.autonomous.admin import admin_login_page


async def _page(aiohttp_client) -> str:
    app = web.Application()
    app.router.add_get("/autonomous/admin", admin_login_page)
    client = await aiohttp_client(app)
    resp = await client.get("/autonomous/admin")
    assert resp.status == 200
    assert resp.content_type == "text/html"
    return await resp.text()


async def test_page_keeps_basic_auth_login(aiohttp_client) -> None:
    body = await _page(aiohttp_client)
    assert "'X-Auth-Method': 'BasicAuth'" in body


async def test_page_offers_passkey_sign_in(aiohttp_client) -> None:
    body = await _page(aiohttp_client)
    assert 'autocomplete="username webauthn"' in body
    assert "/api/v1/auth/passkey/login/options" in body
    assert "'X-Auth-Method':'PasskeyAuth'" in body.replace(" ", "")
    assert 'id="passkeyBtn" hidden' in body
    # FILL IN: assert the generic failure copy, the 'conditional' mediation string, and the /account/security link
```

### FILL IN checklist
- [ ] Ported helper functions (verbatim upstream); bounded by spec §7 "keep the block a verbatim port"
- [ ] `run()` body; bounded by AC12 and the silent-cancel rule
- [ ] Remaining test assertions

---

## Acceptance Criteria

- [ ] Passkey button hidden unless the probe succeeds; conditional UI armed from the probe response (AC12)
- [ ] Success ends in `saveSession(data)` + existing redirect; BasicAuth login unchanged (AC12)
- [ ] No enrollment UI on this page; "Manage passkeys" links to `/account/security`
- [ ] `ruff check packages/ai-parrot-server/src/parrot/autonomous/admin.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/test_autonomous_admin_page.py -q`

---

## Test Specification

See the test blueprint block above. Manual browser check (spec §4 Integration Tests): sign in on
`/autonomous/admin` via autofill and via the button against a backend with `PasskeyAuth` enabled.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug passkey-support --feature-id FEAT-772`)
2. **Read the spec** at `sdd/specs/passkey-support.spec.md` (§2 transport rules, §6 contract, §7 risks)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/passkey-support.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Re-run `grep -c` for every MODIFY anchor in the blueprint; a count that differs means the anchor moved — re-locate it; a count of `0` means drift — stop and report
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/passkey-support.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `FILL IN` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria — run the Validation Commands. Vitest commands run from
   `packages/ai-parrot-server/ui` (`pnpm exec vitest run <file>`); pytest commands from the worktree
   root with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`):
   `feat(passkey-support): TASK-4907 — <title>`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4907 passkey-support verified`
   — never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note


- Task: TASK-4907
- Feature: passkey-support
- Implementation SHA: ab6398d536ae8ff39dffb4fa4256fd3063fd85cd
- Closed at (UTC): 2026-10-30T15:42:32+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: qwen · Backend: nova · Model: qwen.qwen3-coder-480b-a35b-instruct · Attempts: 1 · Duration: 93s · Tokens: n/a |
