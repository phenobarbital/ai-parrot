---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [admin-ui, ai-parrot-server, docs]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [passkey, webauthn, authentication, admin-ui, navigator-auth, login]
---

# Brainstorm: Passkey (WebAuthn) sign-in and enrollment in the Admin UI

**Date**: 2026-10-30
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

navigator-auth ≥ 0.28.x ships a complete passkey (WebAuthn / FIDO2) backend —
`PasskeyAuth`, merged in
[phenobarbital/navigator-auth#607](https://github.com/phenobarbital/navigator-auth/pull/607)
(FEAT-101, merged 2026-10-02). It exposes a public sign-in ceremony
(`POST /api/v1/auth/passkey/login/options` + `POST /api/v1/login` with
`X-Auth-Method: PasskeyAuth`), session-bound enrollment
(`register/options`, `register/verify`) and credential management
(`GET/PATCH/DELETE /api/v1/auth/passkey/credentials`). The installed
`navigator-auth 0.28.9` already contains all of it.

ai-parrot cannot use any of it today:

- The Admin UI login page (`packages/ai-parrot-server/ui/src/pages/Login.svelte`)
  only knows the `BasicAuth` username/password form. Non-external backends
  discovered through `/api/v1/auth/methods` render as a **disabled** button
  ("Not yet supported in this Admin UI"), so even with `PasskeyAuth` enabled a
  user sees a dead button.
- There is no user-level account/security page anywhere in the SPA, so nobody
  can **enroll** a first passkey or manage existing ones.
- `ai-parrot-server` declares no `navigator-auth[passkey]` extra: the shared
  venv has `fido2` but **not** `webauthn` (py_webauthn), so `PasskeyAuth`
  refuses to start (`ConfigError`) on a stock install.
- The inline admin login page (`parrot/autonomous/admin.py`, served at
  `/autonomous/admin`) is BasicAuth-only as well.

**Who is affected**: every operator who wants phishing-resistant, passwordless
login for the agent workspace and admin pages (end users and admins alike);
ops teams who want ABAC policies keyed on `auth_method == "passkey"` /
`mfa == true` (the backend already emits those session keys).

**Why now**: the backend work is done and released; the only missing piece is
the client side that drives the browser ceremonies.

## Constraints & Requirements

- **Scope (Round 1/2 decisions)**: sign-in **and** enrollment **and**
  credential management in the Admin UI; server-side wiring in ai-parrot
  (optional extra + operator docs + example settings); passkey **sign-in only**
  in the inline `/autonomous/admin` page. `parrot-formdesigner` has no login
  form (it redirects to `/admin` when `ai_parrot_token` is missing), so it
  needs no change.
- **Sign-in UX**: explicit "Sign in with a passkey" button (username-first when
  a username is typed, usernameless otherwise) **plus** conditional UI /
  autofill (`autocomplete="username webauthn"` + `mediation: "conditional"`),
  mirroring navigator-auth's own OAuth2 login page.
- **Visibility**: no new build flag. Show passkey UI only when the browser has
  `window.PublicKeyCredential` and the public `login/options` endpoint answers;
  the **same** usernameless `login/options` call is reused as the conditional-UI
  challenge (one request per login-page load).
- **Session model unchanged**: the SPA keeps authenticating with
  `Authorization: Bearer <token>` from `ai_parrot_token`; a passkey login must
  produce the same login envelope (`data.token` + user payload) and store it
  through the existing `AuthStore` so `handle401()`, `logout()`, the Topbar
  identity and `parrot-formdesigner`/`admin.py` interop keep working.
- **Enrollment auth**: Bearer-authenticated requests skip navigator-auth's CSRF
  double-submit check, so the SPA's enrollment/management calls go through the
  existing `apiClient` with no CSRF plumbing. (The inline admin page also uses
  a Bearer token and needs none either.)
- **Relying-party origin**: the backend resolves the RP **only** from the
  browser `Origin` header against `PASSKEY_RELYING_PARTIES` (exact match). The
  SPA is same-origin in production; during `pnpm dev` the Vite origin
  (`http://localhost:5173`) must be listed as an RP or ceremonies 4xx. Docs
  must say so.
- **Browser compatibility**: use the native
  `PublicKeyCredential.parseRequestOptionsFromJSON` /
  `parseCreationOptionsFromJSON` / `credential.toJSON()` when available
  (Chrome 129+, Safari 18+, Firefox 119+) and a hand-written base64url fallback
  otherwise. **No new npm dependency.**
- **Routing**: new user-level section `/account/security`. A new first path
  segment means updating `config.appSections` **and** `SPA_SECTIONS` in
  `parrot/server/ui/serving.py` (and its tests) in lockstep, or the SPA shell
  will 404 / be auth-blocked on a hard reload.
- **Security**: never show a different error for "unknown user" vs "bad
  assertion" (the backend returns a uniform 401; the UI must not undo that);
  treat `NotAllowedError` / `AbortError` as a dismissed prompt, not an error;
  an explicit click must abort a pending conditional-UI request before starting
  a modal one (two concurrent `credentials.get` calls reject).
- **Conventions**: Svelte 5 runes only, `$lib` imports, vendored shadcn
  primitives (`button`, `card`, `input`, `label`, `dialog`, `badge`,
  `skeleton` exist — there is **no** `dropdown-menu`), vitest +
  `@testing-library/svelte` next to the code; Python side `aiohttp` only.
- **Tests**: vitest with a mocked `navigator.credentials` (jsdom has none) and
  mocked `apiClient`/`axios`; pytest for `serving.py` section changes and the
  admin inline page.

---

## Options Explored

### Option A: Native WebAuthn in the SPA + `/account/security` page + server wiring

A small typed WebAuthn helper module in the SPA (JSON ⇄ ArrayBuffer
conversion with native-API-first, hand-written fallback; capability detection;
`AbortController` handling), a `passkey` API module wrapping the six backend
endpoints, an `AuthStore.loginWithPasskey()` method that reuses the Basic
login's token-storage path, a `PasskeySignIn` component dropped into
`Login.svelte` (button + conditional UI; replaces the disabled
`ProviderButtons` entry for the passkey backend), and a new
`pages/account/Security.svelte` page (list / add / rename / delete passkeys)
registered as route `/account/security`, linked from the Sidebar "Workspace"
section (and/or a Topbar link). Server side: `ai-parrot-server[passkey]` extra
(`navigator-auth[passkey]`), `SPA_SECTIONS += "/account"`, operator docs in
`docs/admin-ui.md`, example `AUTHENTICATION_BACKENDS` /
`PASSKEY_RELYING_PARTIES` settings, and the same vanilla-JS passkey block
navigator-auth ships in its OAuth2 login page added to `_ADMIN_LOGIN_HTML`
(sign-in only).

✅ **Pros:**
- Zero new runtime dependencies; the fallback is ~60 lines and already proven
  in navigator-auth's `templates/oauth/login.html`.
- Fully typed and unit-testable with the existing vitest setup (mock
  `navigator.credentials`, `PublicKeyCredential`).
- Reuses every existing seam: `AuthStore` token storage, `apiClient` 401
  interceptor, `router` + `App.svelte` route table, `nav.ts` registry,
  `SPA_SECTIONS`.
- Keeps the SPA's Bearer session model; enrollment needs no CSRF work.
- Gives users a real home for passkeys (`/account/security`) that later account
  features (API keys, sessions) can extend.

❌ **Cons:**
- More hand-written code than a library (`webauthn.ts` helper + its tests).
- A new top-level section touches both the UI config and the Python serving
  module — two places to keep in sync (already the documented rule, but a
  footgun).
- The inline admin page gets a second copy of the vanilla JS (inline HTML
  string, no bundler); it can't share the SPA's TypeScript module.

📊 **Effort:** Medium–High (≈ 8–10 tasks: helper, API module, store method,
sign-in component, security page, routing/nav, serving.py + tests, server
extra + docs/settings, admin.py inline page, docs).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth[passkey]` (≥ 0.28.9) | `PasskeyAuth` backend + `webauthn>=2,<3` (py_webauthn) | New optional extra on `ai-parrot-server`; Redis ≥ 6.2 (GETDEL) |
| Browser WebAuthn Level 3 API | `PublicKeyCredential.parseRequestOptionsFromJSON` / `parseCreationOptionsFromJSON`, `credential.toJSON()`, `isConditionalMediationAvailable()` | Native in Chrome 129+, Safari 18+, Firefox 119+; fallback for older |
| `vitest` ^4 + `@testing-library/svelte` | Unit tests with mocked `navigator.credentials` | Already in `ui/package.json` |
| `pytest` + `aiohttp` test client | `serving.py` section/exclusion tests, admin inline page smoke test | Existing `tests/test_admin_ui_serving.py` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/ui/src/pages/Login.svelte` — host for the passkey button + `autocomplete="username webauthn"` on the username input.
- `packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts` — `login()` token/user persistence path to factor into a shared "store login envelope" step used by `loginWithPasskey()`.
- `packages/ai-parrot-server/ui/src/lib/api/http.ts` — `apiClient` (Bearer + 401 interceptor) for enrollment/management; `extractServerMessage()` for `{reason}` error bodies.
- `packages/ai-parrot-server/ui/src/lib/components/ProviderButtons.svelte` — exclude the passkey backend the same way `isBasicAuth()` excludes BasicAuth.
- `packages/ai-parrot-server/ui/src/App.svelte` route table, `lib/nav.ts` registry, `lib/router.svelte.ts` `isInAppPath()`.
- `packages/ai-parrot-server/src/parrot/server/ui/serving.py` — `SPA_SECTIONS`, `_spa_paths()`, `_auth_exclusion_patterns()`.
- `packages/ai-parrot-server/src/parrot/autonomous/admin.py` — `_ADMIN_LOGIN_HTML` + `saveSession(data)` helper.
- navigator-auth `templates/oauth/login.html` (upstream, not vendored) — reference vanilla-JS ceremony to port into `admin.py`.

---

### Option B: Same architecture, with `@simplewebauthn/browser`

Identical page/route/server plan to Option A, but the SPA uses
`@simplewebauthn/browser` (`startAuthentication`, `startRegistration`,
`browserSupportsWebAuthn`, `browserSupportsWebAuthnAutofill`) instead of a
hand-written helper.

✅ **Pros:**
- Less code to own; the library handles JSON conversion, autofill
  (`useBrowserAutofill: true`) and some browser quirks.
- Widely used, pairs naturally with py_webauthn's option/response JSON shapes.

❌ **Cons:**
- A new runtime npm dependency in a UI that so far deliberately vendors
  primitives and avoids libraries for small concerns (the router itself is
  hand-rolled by design decision).
- Still does not help the inline `admin.py` page (no bundler there), so the
  vanilla fallback has to be written anyway.
- `startAuthentication({ useBrowserAutofill })` takes the request options
  directly; wiring the "single call serves probe + conditional UI, explicit
  click aborts it" rule means fighting the library's own AbortController.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `@simplewebauthn/browser` ^13 | WebAuthn ceremony wrapper | ESM, ~10 KB; version to pin at implementation time |
| `navigator-auth[passkey]` | backend | as Option A |

🔗 **Existing Code to Reuse:** same as Option A.

---

### Option C: Delegate login to navigator-auth's OAuth2 login page

Instead of implementing ceremonies in the SPA, enable navigator-auth's
`Oauth2Provider` backend and register the Admin UI as an OAuth2 client (PKCE).
The SPA's login page redirects to `/oauth2/authorize`; navigator-auth's own
`templates/oauth/login.html` already offers password **and** passkey sign-in;
the SPA exchanges the code for a token at the callback.

✅ **Pros:**
- Passkey sign-in (button + conditional UI) comes for free from upstream and
  stays in sync with future navigator-auth changes.
- Centralises login UX across every navigator-auth-backed app.

❌ **Cons:**
- Replaces the whole login architecture (direct `POST /api/v1/login` →
  authorization-code flow + client registration + PKCE + callback route) for a
  feature that only needs one more auth method. Breaks the simple Bearer
  contract documented in `docs/admin-ui.md` "Auth model".
- Still provides **no enrollment or credential management** — the OAuth2
  login page only signs in; the `/account/security` page is needed anyway.
- Operational burden: OAuth2 client rows, redirect URIs per deployment,
  `templates/oauth/login.html` is not even shipped in the installed wheel
  (templates directory absent in `navigator_auth 0.28.9` site-packages).

📊 **Effort:** High (and mostly unrelated to passkeys)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator_auth.backends.oauth2.Oauth2Provider` | authorization server | requires client registration tables |

🔗 **Existing Code to Reuse:** `AuthStore.handle401()` redirect pattern; little else.

---

### Option D (unconventional): One shared vanilla `passkey.js` served by the backend

Ship a single framework-free `passkey.js` (the ceremony code from
navigator-auth's login page, parameterised by callbacks) as a static asset from
`ai-parrot-server`, and have **both** the Svelte `Login.svelte` (via a
`<script>` tag / dynamic import of a global) and `admin.py`'s inline page load
it. One implementation, two consumers.

✅ **Pros:**
- No duplicated ceremony code between the SPA and the inline page.
- Could later be reused by `parrot-formdesigner` or other server-rendered pages.

❌ **Cons:**
- Mixes an untyped global script into a strict-TypeScript Svelte 5 SPA; no
  vitest coverage of the ceremony from the SPA side; CSP/`nonce` handling for an
  extra script tag.
- The SPA bundle would depend on a runtime asset served by a different package
  path (`/static/...` vs `/ui/assets/...`) — a new coupling the current
  `serving.py` design avoids.
- Enrollment/management UI (the bulk of the work) is Svelte anyway, so the
  sharing gain is limited to ~100 lines of sign-in code.

📊 **Effort:** Medium

📦 **Libraries / Tools:** none new.

🔗 **Existing Code to Reuse:** `serving.py` static mounting (`ASSETS_PREFIX`), `admin.py`.

---

## Recommendation

**Option A** is recommended because:

- It is the only option that delivers the full agreed scope (sign-in **plus**
  enrollment **plus** management) without changing the SPA's Bearer-token auth
  contract or adding a runtime dependency. Options C and D either replace the
  login architecture or trade typing/testability for a small code-sharing win,
  and neither removes the need for the Svelte security page.
- The hand-written helper is the known cost: ~60 lines of base64url fallback
  already battle-tested upstream, plus native-API-first paths that most current
  browsers take. That is cheaper to own than a library whose autofill/abort
  model fights the agreed "one call = probe + conditional UI, click aborts it"
  behaviour (Option B).
- Duplicating the ceremony into `admin.py`'s inline page is accepted: that page
  is a self-contained HTML string by design (no bundler), it only needs
  sign-in, and the duplicated block is the same vanilla JS navigator-auth
  already maintains — the brainstorm records this as a known duplication rather
  than inventing a shared-asset mechanism (Option D).

What we trade off: a second WebAuthn code path (TypeScript module vs inline
vanilla JS) that must stay behaviourally aligned, and one more place
(`/account`) where `config.appSections` and `SPA_SECTIONS` must match.

---

## Feature Description

### User-Facing Behavior

**Login page (`/login`).**
- When the browser supports WebAuthn and the backend answers
  `POST /api/v1/auth/passkey/login/options`, the page shows a
  **"Sign in with a passkey"** button under the password form (where the
  disabled passkey `ProviderButtons` entry used to be) and the username field
  gets `autocomplete="username webauthn"`.
- On supporting browsers the page immediately arms **conditional UI**: focusing
  the username field offers the user's saved passkeys in the browser autofill
  dropdown; picking one signs in without typing anything.
- Clicking the button starts a **modal** ceremony: if a username is typed it is
  sent (username-first; the server returns that user's credential ids or
  deterministic decoys), otherwise a usernameless (discoverable) request is
  made.
- Success: the SPA stores the login envelope exactly as a password login would
  and navigates to `?next=` or `/agents`. Failure: a single inline alert
  "Passkey sign-in failed. Use your password instead." Dismissing the browser
  prompt shows nothing.
- When the backend is not enabled (404/405 on `login/options`) or the browser
  lacks WebAuthn, the page is **byte-identical** to today's.

**Security page (`/account/security`).**
- New "Account › Security" entry in the Sidebar "Workspace" section (user
  level, not admin); requires auth like every non-login route.
- A "Passkeys" card lists the caller's credentials: label (or "Unnamed
  passkey"), device type (`single_device` / `multi_device`), "synced" badge
  when `backed_up`, relying party, created and last-used dates. Empty state
  explains what a passkey is and offers **"Add a passkey"**.
- **Add a passkey**: runs the creation ceremony, then asks for an optional
  label (≤ 128 chars) in a dialog before calling `register/verify`. Errors:
  "This device is already registered" (409), "Your browser does not support
  passkeys", generic failure otherwise.
- **Rename** inline (1–128 chars). **Delete** with a confirmation dialog; a
  409 from the server renders "You can't delete your only way to sign in. Set a
  password or add another passkey first."
- If the current origin is not an allow-listed relying party, `register/options`
  fails (4xx) and the page shows an operator-oriented hint ("This site is not
  configured for passkeys — ask your administrator to add its origin to
  `PASSKEY_RELYING_PARTIES`").

**Inline admin page (`/autonomous/admin`).**
- Same "Sign in with a passkey" button + conditional UI, vanilla JS, same
  visibility rule; success calls the page's existing `saveSession(data)` and
  continues as a password login does. No enrollment here — the page links to
  the SPA's `/account/security` for that.

**Operator.**
- `pip install "ai-parrot-server[passkey]"` pulls `navigator-auth[passkey]`.
- Documented settings: `AUTHENTICATION_BACKENDS=navigator_auth.backends.BasicAuth,navigator_auth.backends.PasskeyAuth`,
  `PASSKEY_RELYING_PARTIES` (one entry per exact origin, incl. the Vite dev
  origin), `PASSKEY_USER_VERIFICATION`, Redis ≥ 6.2 requirement, and the
  fact that `rp_id` must be the origin host or a parent domain.

### Internal Behavior

1. **Capability + availability probe (login page mount).** If
   `window.PublicKeyCredential && navigator.credentials` are absent → passkey
   UI stays hidden. Otherwise `POST login/options` with `{}` (bare `axios`,
   like the existing `/auth/methods` discovery, to stay clear of the 401
   interceptor). A 2xx with `{challenge_id, publicKey}` → mark available;
   anything else → hidden. The response is **kept** and, when
   `isConditionalMediationAvailable()` resolves true, immediately used for
   `navigator.credentials.get({ publicKey, mediation: "conditional", signal })`.
2. **Explicit button.** Abort the pending conditional request (its
   `AbortController`), `POST login/options` with `{username}` or `{}`, convert
   options (native `parseRequestOptionsFromJSON` else fallback), call
   `credentials.get()` (modal), serialise (`toJSON()` else fallback), then
   `AuthStore.loginWithPasskey(challenge_id, credentialJSON)` →
   `POST /api/v1/login` with header `X-Auth-Method: PasskeyAuth` through
   `apiClient`. The store validates `data.token`, writes `ai_parrot_token` /
   `ai_parrot_session`, sets `token`/`user` — the same persistence step
   `login()` uses today, factored into one private helper.
3. **Enrollment.** `apiClient.post(register/options, {})` (Bearer → no CSRF)
   → `parseCreationOptionsFromJSON` (or fallback converting `challenge`,
   `user.id`, `excludeCredentials[].id`) → `credentials.create()` →
   `apiClient.post(register/verify, {credential, label})` → refresh list.
4. **Management.** `apiClient.get(credentials)`, `patch(credentials/{id},
   {label})`, `delete(credentials/{id})`; map 404/409/4xx `{reason}` bodies via
   `extractServerMessage()`.
5. **Routing.** `App.svelte` adds `{ path: "/account/security", requiresAuth:
   true }`; `config.appSections` adds `"account"`; `nav.ts` adds a `user`
   section entry. `serving.py` `SPA_SECTIONS` adds `"/account"` so the shell
   and its auth exclusion cover `/account` and `/account/*`.
6. **Admin inline page.** `_ADMIN_LOGIN_HTML` gains the button, the
   `autocomplete="username webauthn"` attribute and the vanilla ceremony block
   (ported from navigator-auth's `templates/oauth/login.html`, with the
   `/oauth2/authorize` continuation replaced by `saveSession(data)` +
   existing post-login UI).

### Edge Cases & Error Handling

- **Backend disabled** → `login/options` 404 → no passkey UI; no error shown.
- **Rate limited** (`PASSKEY_LOGIN_OPTIONS_RATE`, 429) → treat like
  unavailable at probe time; on explicit click show the generic failure.
- **Dismissed / timed-out prompt** (`NotAllowedError`, `AbortError`) → silent.
- **Conditional UI vs click race** → click aborts the conditional controller
  first; after a failed modal attempt, conditional UI is **not** re-armed (the
  challenge was consumed); the user can click again.
- **Challenge expiry** (`PASSKEY_CHALLENGE_TTL`, default 300 s) → the server's
  uniform 401; UI shows the generic message. The probe challenge used for
  conditional UI can expire while the page sits idle — acceptable (the user
  falls back to the button, which fetches a fresh one).
- **Origin not an RP** → `login/options` 4xx → hidden at login; explicit error
  hint on the security page.
- **Disabled account** → 403 from `/api/v1/login` → show server message.
- **Last login method** → DELETE 409 → specific message; the delete button is
  not pre-disabled client-side (the server is the authority).
- **Duplicate enrollment** → 409 → "already registered".
- **Older browsers without JSON helpers** → fallback conversion; browsers
  without `isConditionalMediationAvailable` → button only.
- **localStorage unavailable** → same behaviour as password login (in-memory
  session for the tab).
- **`?next=` preservation** → unchanged: the probe uses bare `axios`, so a 401
  can never trigger `handle401()`'s redirect rewrite.

---

## Capabilities

### New Capabilities
- `passkey-sign-in`: passkey button + conditional UI on the Admin UI login page; `AuthStore.loginWithPasskey()`.
- `passkey-enrollment-management`: `/account/security` page — list, add, rename, delete passkeys.
- `webauthn-browser-helper`: typed JSON⇄binary conversion, capability detection, abortable ceremonies (no dependency).
- `account-section-routing`: new `/account` SPA section (`appSections`, `SPA_SECTIONS`, nav entry).
- `passkey-server-extra`: `ai-parrot-server[passkey]` optional extra + operator docs + example settings.
- `autonomous-admin-passkey-signin`: vanilla-JS passkey sign-in in `/autonomous/admin`.

### Modified Capabilities
- `ui-server-backend` (FEAT-468, `sdd/specs/ui-server-backend.spec.md`): `SPA_SECTIONS` grows; auth-exclusion patterns and tests change accordingly.
- Admin UI login/auth model documented in `docs/admin-ui.md` "Auth model".

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `ui/src/pages/Login.svelte` | modifies | passkey button, `autocomplete="username webauthn"`, probe + conditional UI |
| `ui/src/lib/components/ProviderButtons.svelte` | modifies | exclude the `PasskeyAuth` backend (handled by the dedicated component) like BasicAuth |
| `ui/src/lib/stores/auth.svelte.ts` | extends | `loginWithPasskey()`; shared envelope-persistence helper |
| `ui/src/lib/api/passkey.ts` (new) | new | wrappers for the six passkey endpoints |
| `ui/src/lib/webauthn.ts` (new) | new | JSON⇄ArrayBuffer, capability detection, abort handling |
| `ui/src/lib/components/auth/PasskeySignIn.svelte` (new) | new | login-page component |
| `ui/src/pages/account/Security.svelte` (new) + components | new | passkey list / add / rename / delete |
| `ui/src/App.svelte`, `ui/src/lib/config.ts`, `ui/src/lib/nav.ts` | modifies | route, `appSections`, nav entry |
| `parrot/server/ui/serving.py` + `tests/test_admin_ui_serving.py` | modifies | `SPA_SECTIONS += "/account"`, exclusion pattern tests |
| `parrot/autonomous/admin.py` | modifies | vanilla passkey sign-in block in `_ADMIN_LOGIN_HTML` |
| `packages/ai-parrot-server/pyproject.toml` | extends | `passkey = ["navigator-auth[passkey]>=0.28.9"]`; include in `all` |
| `docs/admin-ui.md` | modifies | "Auth model" + quick-start settings for passkeys, dev-origin RP note |
| `env/*` example settings (if tracked) / docs | extends | `AUTHENTICATION_BACKENDS`, `PASSKEY_RELYING_PARTIES` examples |
| Redis | depends on | ≥ 6.2 (`GETDEL`) for challenge storage — backend requirement, document only |
| navigator-auth | depends on | `>= 0.28.9` (PasskeyAuth present in installed version); no upstream change needed |

No breaking changes: without `PasskeyAuth` enabled, the UI renders exactly as
today; the `/account` section only adds routes.

---

## Code Context

### User-Provided Code

None pasted. The user supplied the upstream reference:
https://github.com/phenobarbital/navigator-auth/pull/607 (FEAT-101, merged
2026-10-02 into navigator-auth `dev`).

### Verified Codebase References

#### Admin UI (Svelte 5 SPA — `packages/ai-parrot-server/ui/src/`)
```ts
// pages/Login.svelte
import ProviderButtons, { type AuthMethodInfo } from "$lib/components/ProviderButtons.svelte"; // :16
// discovery: bare axios.get(`${config.apiBaseUrl}${config.authMethodsUrl}`) in onMount (bypasses apiClient) // :49-57
const result = await authStore.login(username, password);   // :70
//   <Input id="username" ... autocomplete="username" />      // :105  ← becomes "username webauthn"
//   <ProviderButtons {methods} />                            // :138

// lib/stores/auth.svelte.ts
class AuthStore {
  token = $state<string | null>(...); user = $state<AuthUser | null>(...); loading = $state(false);
  isAuthenticated = $derived(this.token !== null);
  async login(username: string, password: string): Promise<{ success: boolean; error?: string }>  // :62
  //   apiClient.post(config.loginUrl, {username, password}, { headers: { "X-Auth-Method": "BasicAuth" } }) // :68
  //   requires data.token; localStorage.setItem(config.tokenStorageKey / sessionStorageKey)
  async logout(): Promise<void>   // :99
  handle401(): void               // :113
}
export const authStore = new AuthStore();

// lib/config.ts
loginPath: `${basePath}/login`,                 // :56
homePath: `${basePath}/agents`,                 // :58
appSections: ["login", "agents", "admin"],      // :62  ← add "account"
loginUrl: "/api/v1/login",                      // :63
authMethodsUrl: "/api/v1/auth/methods",         // :65
tokenStorageKey: "ai_parrot_token", sessionStorageKey: "ai_parrot_session"

// lib/router.svelte.ts
export interface RouteDefinition { path: string; component: RouteComponentLoader; requiresAuth?: boolean } // :27
function isInAppPath(path: string): boolean     // :69  (first segment ∈ config.appSections)
class Router { ... guard(path: string = this.path): boolean }  // :87, :218
export { Router, isInAppPath }; export const router = new Router();

// App.svelte
router.routes = [ { path: "/login", ... }, { path: "/agents", requiresAuth: true }, ... ]  // :20

// lib/nav.ts
export type NavSection = "user" | "admin";       // :13
export interface NavEntry { path: string; label: string; icon: string; section: NavSection }
export const navEntries: NavEntry[] = [ ... ];   // :29

// lib/components/Sidebar.svelte — renders navEntries grouped by navSections (import at :6)
// lib/components/Topbar.svelte — identity + ThemeSwitcher + "Sign out" Button (:34); no user dropdown menu

// lib/components/ProviderButtons.svelte
export interface AuthMethodInfo { name; uri; description; icon; external: boolean; headers: Record<string,string> } // :20
function isBasicAuth(info: AuthMethodInfo): boolean   // :36  (headers["x-auth-method"] === "basicauth")
// non-external providers render a DISABLED button "Not yet supported in this Admin UI"

// lib/api/http.ts
export class ApiError extends Error { code: "network"|"timeout"|"server"|"auth"|"unknown"; status?; raw? } // :31
export function extractServerMessage(data: unknown, status: number): string  // :80
const apiClient = axios.create({...}); export default apiClient;             // :164, :197 (Bearer + 401 → authStore.handle401())

// lib/api/auth-headers.ts
export function getAuthHeaders(): Record<string, string>   // :16

// pages/Login.test.ts — pattern: vi.spyOn(axios, "get").mockResolvedValue({ data: {} }) (:20), vi.spyOn(apiClient, "post")
// vite.config.ts — envPrefix: ['VITE_', 'PUBLIC_'] (:62); vitest-setup.ts stubs ResizeObserver / Element.animate (no navigator.credentials stub yet)
// lib/ui/internal/shadcn/ui/ — avatar badge button card checkbox command dialog input label progress select separator sheet skeleton slider switch tabs textarea
```

#### Server (`packages/ai-parrot-server/src/parrot/`)
```python
# server/ui/serving.py
SPA_SECTIONS: tuple[str, ...] = ("/login", "/agents")                       # :39  ← add "/account"
def _spa_paths(prefix: str, *, mount_root: bool) -> list[str]               # :124
def _auth_exclusion_patterns(prefix: str, *, mount_root: bool) -> list[str] # :141
def setup_admin_ui(app, prefix=..., mount_root=...)                          # :235

# tests/test_admin_ui_serving.py
#   asserts patterns ("/admin", "/admin/*", "/login", "/agents", "/agents/*", "/ui/assets/*")  # :192
#   parametrized shell paths ["/", "/login", "/agents", "/agents/helpdesk/chat", "/admin/home"]  # :68

# autonomous/admin.py
_ADMIN_LOGIN_HTML = """..."""                                                # :17
#   <input type="text" id="username" ... autocomplete="username">            # :224
#   fetch('/api/v1/login', { headers: { 'X-Auth-Method': 'BasicAuth' } })    # :320-324
#   saveSession(data) → localStorage ai_parrot_token / ai_parrot_session     # :253-254
async def admin_login_page(request: web.Request) -> web.Response            # :394
# autonomous/orchestrator.py — add_route('GET', '/autonomous/admin', admin_login_page, name='autonomous_admin') (:338); appended to exclude_list (:342-343)
```

```toml
# packages/ai-parrot-server/pyproject.toml
[project.optional-dependencies]            # :46
all = ["ai-parrot-server[scheduler,mcp,a2a,autonomous,comm-center]"]   # :97-98  ← add passkey
# packages/ai-parrot/pyproject.toml :116 and root pyproject.toml :198 — "navigator-auth>=0.28.3"
```

```python
# app.py :296 / appauto.py :65
auth = AuthHandler()
auth.setup(self.app)
# docs/admin-ui.md :221 — "- **Login**: set `AUTHENTICATION_BACKENDS=navigator_auth.backends.BasicAuth`"
# packages/parrot-formdesigner/src/parrot_formdesigner/ui/templates.py :129 _auth_script() — reads ai_parrot_token (:155), redirects to /admin when missing; NO login form
```

#### navigator-auth 0.28.9 (installed, `.venv/lib/python3.12/site-packages/navigator_auth/`)
```python
# backends/__init__.py :20   from .passkey import PasskeyAuth   (exported in __all__)
# backends/passkey.py
PASSKEY_PREFIX = "/api/v1/auth/passkey"                                   # :35
class PasskeyAuth(BasicAuth):                                             # :63
    _description = "Passkey (WebAuthn) authentication"; _service_name = "passkey"   # :67-68
    # routes (configure): POST register/options, POST register/verify, POST login/options,
    #   GET credentials, PATCH credentials/{id}, DELETE credentials/{id}  # :76-88
    # app[AUTH_EXCLUDE_LIST_KEY].append(f"{PASSKEY_PREFIX}/login/options")  # :90  (only login/options is public)
    async def get_payload(self, request) -> tuple[str, dict]              # :196  body {challenge_id: str, credential: dict}
    async def register_options(self, request) -> web.Response            # :217  session required; body {} ; returns PublicKeyCredentialCreationOptions JSON
    async def register_verify(self, request) -> web.Response             # :261  body {credential, label?≤128}; 201 {"status":"registered","id"}; 400/401/409
    async def login_options(self, request) -> web.Response               # :335  body {username?}; returns {"challenge_id", "publicKey"}; decoys for unknown users
    async def authenticate(self, request) -> dict                        # :397  POST /api/v1/login + X-Auth-Method: PasskeyAuth → open_session(...) Basic-style envelope
    #   extra = {"auth_method":"passkey","mfa":uv,"amr":[...],"org_id","client_id","passkey_rp_id"}  # :468-475
    async def list_credentials(self, request) -> web.Response            # :510  [{id,label,created_at,last_used_at,device_type,backed_up,rp_id}]
    async def rename_credential(self, request) -> web.Response           # :532  body {label 1..128}; 200 {"status":"renamed"}; 400/404
    async def delete_credential(self, request) -> web.Response           # :549  204; 404; 409 "cannot delete the last login method"
# _json_errors wrapper → JSON {"reason": str} for 4xx (:36-56)
# conf.py
PASSKEY_RELYING_PARTIES: list = []             # :598 (JSON list of {origin, rp_id, rp_name, org_id?, client_id?})
PASSKEY_CHALLENGE_TTL = 300                    # :609
PASSKEY_USER_VERIFICATION = "required"         # :611
PASSKEY_TENANT_ATTRIBUTE = None                # :613
PASSKEY_DECOY_CREDENTIALS = 1                  # :615
PASSKEY_LOGIN_OPTIONS_RATE = 0                 # :617
EXCLUDE_DEFAULTS = ["/static/", "/api/v1/login", "/api/v1/logout", "/api/v1/forgot-password", "/api/v1/reset-password"]  # :63
# passkey/rp.py — RelyingPartyResolver.resolve(request) (:79) reads ONLY Origin (Referer exact fallback); by_origin(origin) (:95)
# auth.py — async def auth_methods(request) (:541) lists backend.get_backend_info() → {name, uri:"/api/v1/login", description, icon, external:false, headers}
# dist-info METADATA — Provides-Extra: passkey ; Requires-Dist: webauthn<3,>=2.0; extra == "passkey"
```

#### Key Attributes & Constants
- `config.appSections` → `string[]` (`ui/src/lib/config.ts:62`) — must mirror `SPA_SECTIONS` (`serving.py:39`).
- `config.tokenStorageKey = "ai_parrot_token"`, `config.sessionStorageKey = "ai_parrot_session"` — shared with `admin.py` and `parrot-formdesigner`.
- Passkey login header value: `X-Auth-Method: PasskeyAuth` (class name, like `BasicAuth`).
- Login-options response: `{ challenge_id: string, publicKey: PublicKeyCredentialRequestOptionsJSON }`; login body: `{ challenge_id, credential: PublicKeyCredentialJSON }`.
- `auth_methods` entry for the passkey backend: `name: "PasskeyAuth"`, `uri: "/api/v1/login"`, `external: false`, `headers: {"x-auth-method": "PasskeyAuth"}` (derived from `backends/abstract.py:126-129`; exact header casing to confirm at implementation).

### Does NOT Exist (Anti-Hallucination)
- ~~`webauthn` (py_webauthn) in the shared venv~~ — only `fido2 2.2.1` is installed; `.venv/.../webauthn/__init__.py` is absent. `PasskeyAuth` raises `ConfigError` at startup without it.
- ~~any `passkey`/`webauthn` code under `packages/ai-parrot-server/ui/src`~~ — nothing exists yet.
- ~~`"account"` in `config.appSections` / `"/account"` in `SPA_SECTIONS`~~ — the section has to be created.
- ~~a user profile / account / settings page in the SPA~~ — `pages/` has only `Agents`, `Dashboard`, `Home`, `Login`, `agents/*`.
- ~~`dropdown-menu` shadcn primitive~~ — not vendored (`dialog`, `badge`, `card`, `button`, `input`, `label`, `skeleton` are).
- ~~a login form in `parrot-formdesigner`~~ — `templates.py` only reads `ai_parrot_token` and redirects to `/admin`; no `X-Auth-Method` anywhere in that package.
- ~~`navigator_auth/templates/oauth/login.html` in the installed wheel~~ — the directory is not shipped in 0.28.9 site-packages; the reference JS must be read from the GitHub repo (`templates/oauth/login.html` on `dev`).
- ~~`AuthStore.loginWithPasskey()`~~, ~~`ui/src/lib/api/passkey.ts`~~, ~~`ui/src/lib/webauthn.ts`~~ — to be created.
- ~~a `navigator.credentials` / `PublicKeyCredential` stub in `vitest-setup.ts`~~ — jsdom provides none; tests must stub them.
- ~~`PUBLIC_PASSKEY_ENABLED` build flag~~ — explicitly rejected (Round 1); availability is probed at runtime.
- ~~`/api/v1/auth/methods` in the default exclude list~~ — anonymous discovery 401s (existing Login.svelte comment); not relied on for passkey visibility.

---

## Parallelism Assessment

- **Internal parallelism**: three largely independent lanes — (1) SPA sign-in
  (`webauthn.ts`, `api/passkey.ts`, `AuthStore.loginWithPasskey`,
  `PasskeySignIn.svelte`, `Login.svelte`); (2) SPA security page + `/account`
  routing (`Security.svelte`, `App.svelte`, `config.ts`, `nav.ts`) which
  depends on lane 1's `webauthn.ts`/`api/passkey.ts` only; (3) Python side
  (`serving.py` + tests, `pyproject.toml` extra, `admin.py` inline page,
  docs). Lane 3 has no file overlap with lanes 1–2.
- **Cross-feature independence**: touches `Login.svelte`, `App.svelte`,
  `config.ts`, `nav.ts`, `serving.py`, `admin.py`, `docs/admin-ui.md`. Check
  in-flight FEAT-468/475/476 follow-ups and any open spec editing the Admin UI
  route table before starting; no known conflict at brainstorm time.
- **Recommended isolation**: `mixed` — one feature worktree, with the Python
  lane (3) eligible for a parallel coder sub-worktree; lanes 1 → 2 sequential
  (shared helper + store).
- **Rationale**: the helper/API module is the common dependency for both UI
  lanes, so they serialise; the server lane shares no files with the UI and
  can proceed concurrently.

---

## Open Questions

- [x] Feature or hotfix, and base branch? — *Owner: Jesus Lara*: feature on `dev`.
- [x] Scope: sign-in only, or also enrollment and management? — *Owner: Jesus Lara*: sign-in + enrollment + management in the Admin UI; server wiring (extra, docs, example settings); sign-in only in `/autonomous/admin`.
- [x] Sign-in UX? — *Owner: Jesus Lara*: explicit button (username-first / usernameless) plus conditional UI autofill.
- [x] How does the UI decide to show passkeys? — *Owner: Jesus Lara*: runtime probe of `POST /api/v1/auth/passkey/login/options` + WebAuthn capability check; no build flag.
- [x] Where does credential management live? — *Owner: Jesus Lara*: new `/account/security` section (adds `account` to `appSections` and `/account` to `SPA_SECTIONS`).
- [x] WebAuthn JSON conversion approach? — *Owner: Jesus Lara*: native Level-3 helpers first, hand-written base64url fallback; no npm dependency.
- [x] Cost of the probe challenge? — *Owner: Jesus Lara*: a single usernameless `login/options` call doubles as probe and conditional-UI challenge.
- [ ] Should the Sidebar "Workspace" entry be "Account" (future-proof) or "Security" (precise), and should the Topbar also link to it? — *Owner: Jesus Lara*
- [ ] After a successful passkey login, should the Topbar surface `auth_method`/`mfa` (e.g. a small "passkey" badge) or is that out of scope? — *Owner: Jesus Lara*
- [ ] Which tracked example settings (if any under `env/` are committed) should carry `AUTHENTICATION_BACKENDS` + `PASSKEY_RELYING_PARTIES`, vs docs-only? `env/` contents are mostly git-ignored. — *Owner: Jesus Lara*
- [ ] Exact `headers["x-auth-method"]` value navigator-auth advertises for `PasskeyAuth` in `/api/v1/auth/methods` (needed to filter it out of `ProviderButtons`) — verify against a running backend at `/sdd-task` time. — *Owner: implementer*
- [ ] Should `ai-parrot-server[passkey]` pin `navigator-auth>=0.28.9` explicitly (first release containing PasskeyAuth in site-packages) or inherit the core `>=0.28.3` floor? — *Owner: Jesus Lara*
