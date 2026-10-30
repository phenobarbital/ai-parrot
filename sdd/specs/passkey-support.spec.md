---
type: feature
base_branch: dev
projects: [admin-ui, ai-parrot-server, docs]   # FEAT-576 — carried verbatim from the brainstorm
tags: [passkey, webauthn, authentication, admin-ui, navigator-auth, login]   # FEAT-576 — carried verbatim from the brainstorm
---

# Feature Specification: Passkey (WebAuthn) sign-in, enrollment and management in the Admin UI

**Feature ID**: FEAT-772 (reserved 2026-10-30 by `reserve_ids.py`, commit `ed44ca4fa`)
**Date**: 2026-10-30
**Author**: Jesus Lara (Claude Code, Fable 5.1)
**Status**: approved
**Target version**: ai-parrot-server 1.4.0 (the Admin UI ships inside the server wheel; current server version 1.3.5, core 1.2.6)
**Exploration**: `sdd/proposals/passkey-support.brainstorm.md` (Recommended Option A, all 12 open questions resolved 2026-10-30)
**Upstream dependency**: navigator-auth `PasskeyAuth` backend — [phenobarbital/navigator-auth#607](https://github.com/phenobarbital/navigator-auth/pull/607) (FEAT-101, merged 2026-10-02), present in the installed `navigator-auth 0.28.9`

---

## 1. Motivation & Business Requirements

### Problem Statement

navigator-auth ≥ 0.28.9 ships a complete passkey (WebAuthn / FIDO2) backend, `PasskeyAuth`: a public
sign-in ceremony (`POST /api/v1/auth/passkey/login/options` + `POST /api/v1/login` with
`X-Auth-Method: PasskeyAuth`), session-bound enrollment (`register/options`, `register/verify`) and
credential management (`GET/PATCH/DELETE /api/v1/auth/passkey/credentials`). ai-parrot cannot use any
of it today:

- The Admin UI login page (`packages/ai-parrot-server/ui/src/pages/Login.svelte`) only knows the
  `BasicAuth` form. Any non-external backend discovered through `/api/v1/auth/methods` renders as a
  **disabled** button ("Not yet supported in this Admin UI"), so with `PasskeyAuth` enabled a user sees
  a dead button.
- The SPA has no user-level account/security page, so nobody can **enroll** a first passkey or manage
  existing ones.
- `ai-parrot-server` declares no `navigator-auth[passkey]` extra: the shared venv has `fido2` but
  **not** `webauthn` (py_webauthn), so `PasskeyAuth` refuses to start (`ConfigError`) on a stock
  install.
- The inline admin login page (`parrot/autonomous/admin.py`, served at `/autonomous/admin`) is
  BasicAuth-only as well.

Affected: every operator who wants phishing-resistant, passwordless login for the agent workspace and
admin pages; ops teams who want ABAC policies keyed on `auth_method == "passkey"` / `mfa == true`
(the backend already emits those session keys). The backend work is done and released; only the
client side that drives the browser ceremonies is missing.

### Goals

- G1. Passkey **sign-in** on the Admin UI login page: an explicit "Sign in with a passkey" button
  (username-first when a username is typed, usernameless otherwise) **plus** conditional UI / autofill
  (`autocomplete="username webauthn"`, `mediation: "conditional"`).
- G2. Passkey **enrollment and management** in a new user-level page `/account/security`: list, add
  (with optional label), rename, delete.
- G3. **Zero-config visibility**: passkey UI appears only when the browser supports WebAuthn and the
  public `login/options` endpoint answers; the same usernameless call is the conditional-UI challenge
  (one request per login-page load). No build flag.
- G4. **Session model unchanged**: a passkey login yields the same login envelope (`data.token` + user
  payload) and is persisted by the existing `AuthStore`, so `handle401()`, `logout()`, the Topbar
  identity and the `ai_parrot_token` interop with `admin.py` / `parrot-formdesigner` keep working.
- G5. **No new runtime dependency**: native WebAuthn Level-3 JSON helpers first
  (`PublicKeyCredential.parseRequestOptionsFromJSON` / `parseCreationOptionsFromJSON`,
  `credential.toJSON()`), hand-written base64url fallback otherwise.
- G6. **Server wiring**: `ai-parrot-server[passkey]` optional extra pinning
  `navigator-auth[passkey]>=0.28.9`; `SPA_SECTIONS` grows `/account`; operator docs in
  `docs/admin-ui.md` plus a copy-ready `docs/examples/passkey.settings.example`.
- G7. Passkey **sign-in only** in the inline `/autonomous/admin` page (vanilla JS, same visibility
  rule, no enrollment).
- G8. Navigation: an **"Account"** entry in the Sidebar "Workspace" section and the Topbar identity
  as a link to `/account/security`; a small **"Passkey"** badge in the Topbar when
  `auth_method === "passkey"`; `/account/security` states the current session's method.

### Non-Goals (explicitly out of scope)

- Changing the SPA's Bearer-token auth contract (delegating login to navigator-auth's OAuth2 login
  page was rejected in the brainstorm — Option C) or adding `@simplewebauthn/browser` /
  `@github/webauthn-json` (Option B) or a backend-served shared `passkey.js` (Option D).
- Passkey enrollment or management in `/autonomous/admin`; that page links to `/account/security`.
- Any change to `parrot-formdesigner`: it has no login form (`templates.py` only reads
  `ai_parrot_token` and redirects to `/admin`).
- Any change to navigator-auth itself (relying-party resolution, decoys, rate limiting, CSRF rules
  are consumed as-is).
- A password-change or "set a password" flow (the DELETE 409 message points the user to it, but it
  is not built here).
- Admin-side management of **other** users' passkeys; the backend only exposes the caller's own.
- Fixing the pre-existing behaviour where a `401` from the BasicAuth `POST /api/v1/login` routed
  through `apiClient` trips `authStore.handle401()` (see §7 Known Risks — recorded, not fixed here).

---

## 2. Architectural Design

### Overview

The SPA gains a small typed WebAuthn helper (`$lib/webauthn.ts`: JSON ⇄ ArrayBuffer conversion with
native-API-first and hand-written fallback, capability detection, user-cancel classification), a
`$lib/api/passkey.ts` module wrapping the six backend endpoints, an `AuthStore.loginWithPasskey()`
method that reuses the Basic login's envelope-persistence path, a `PasskeySignIn.svelte` component
dropped into `Login.svelte` (button + conditional UI, replacing the disabled `ProviderButtons` entry
for the passkey backend), and a new `pages/account/Security.svelte` page (list / add / rename /
delete passkeys, current session method) registered as route `/account/security`, linked from the
Sidebar "Workspace" section ("Account") and from the Topbar identity, which also shows a "Passkey"
badge for passkey sessions.

Two transport rules govern every call (resolved from the codebase, §6):

1. **Unauthenticated ceremony calls bypass `apiClient`.** `POST login/options` and
   `POST /api/v1/login` (`X-Auth-Method: PasskeyAuth`) use a bare `axios` call, exactly like the
   existing `/api/v1/auth/methods` discovery in `Login.svelte`: the shared interceptor calls
   `authStore.handle401()` on every non-"policy" 401, and the passkey backend answers **every**
   sign-in failure with the same 401 — routing it through `apiClient` would clear the session and
   rewrite `?next=` on each failed attempt.
2. **Authenticated calls use `apiClient`.** `register/options`, `register/verify`, `credentials`
   (GET/PATCH/DELETE) carry the Bearer token the interceptor injects; navigator-auth's CSRF
   double-submit check applies only to cookie-only sessions, so no CSRF plumbing is needed.

Server side: `ai-parrot-server[passkey]` pins `navigator-auth[passkey]>=0.28.9`; `SPA_SECTIONS`
in `parrot/server/ui/serving.py` grows `"/account"` so the SPA shell and its auth exclusion cover
`/account` and `/account/*`; `docs/admin-ui.md` and a new `docs/examples/passkey.settings.example`
document `AUTHENTICATION_BACKENDS`, `PASSKEY_RELYING_PARTIES` (one exact origin per entry, including
the Vite dev origin), `PASSKEY_USER_VERIFICATION` and the Redis ≥ 6.2 requirement. The inline
`/autonomous/admin` page gets the same vanilla-JS sign-in block navigator-auth ships in its OAuth2
login page, with the continuation replaced by the page's existing `saveSession(data)`.

Without `PasskeyAuth` enabled (`login/options` → 404) or without WebAuthn in the browser, the login
page renders exactly as today.

### Component Diagram

```
Login.svelte ──mounts──▶ PasskeySignIn.svelte ──uses──▶ $lib/api/passkey.ts ──bare axios──▶ POST /api/v1/auth/passkey/login/options
     │  (autocomplete="username webauthn")      │                 │                               POST /api/v1/login (X-Auth-Method: PasskeyAuth)
     │                                          │                 └──▶ $lib/webauthn.ts (toRequestOptions / credentialToJSON / isUserCancelled)
     │                                          └──▶ authStore.loginWithPasskey(challengeId, credentialJSON) ──▶ _storeLoginEnvelope(data)
     └──▶ ProviderButtons.svelte  (filters BasicAuth AND PasskeyAuth)

AppShell ──▶ Sidebar (nav.ts: "Account" → /account/security)
         └─▶ Topbar (identity link → /account/security; <Badge>Passkey</Badge> when authStore.authMethod === "passkey")

App.svelte route "/account/security" ──▶ pages/account/Security.svelte ──▶ PasskeyList.svelte / AddPasskeyDialog.svelte
                                                │                                   │
                                                └──▶ $lib/api/passkey.ts ──apiClient (Bearer)──▶ POST register/options · POST register/verify
                                                                                                 GET/PATCH/DELETE /api/v1/auth/passkey/credentials[/{id}]
config.appSections += "account"  ◀── must mirror ──▶  serving.py SPA_SECTIONS += "/account"

autonomous/admin.py _ADMIN_LOGIN_HTML ──vanilla JS──▶ login/options → credentials.get → POST /api/v1/login → saveSession(data)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ui/src/pages/Login.svelte` | modifies | `autocomplete="username webauthn"`; mounts `PasskeySignIn` below the form; passes `username` + `nextTarget()` |
| `ui/src/lib/components/ProviderButtons.svelte` | modifies | adds `isPasskeyAuth()` filter (header `x-auth-method` lower-cased `=== "passkeyauth"`) next to `isBasicAuth()` |
| `ui/src/lib/stores/auth.svelte.ts` (`AuthStore`) | extends | `loginWithPasskey()`, private `_storeLoginEnvelope()`, `authMethod` derived getter; `login()` refactored to call the shared helper |
| `ui/src/lib/api/http.ts` (`apiClient`, `ApiError`, `extractServerMessage`) | uses | authenticated passkey calls + error-message extraction from `{reason}` bodies |
| `ui/src/lib/config.ts` | extends | `passkeyApiPrefix`, `accountSecurityPath`; `appSections` gains `"account"` |
| `ui/src/lib/router.svelte.ts` (`isInAppPath`, `Router.guard`) | uses | new route is `requiresAuth: true`; `?next=/account/security` round-trips because `account` is an app section |
| `ui/src/App.svelte` route table | extends | `{ path: "/account/security", component: () => import("./pages/account/Security.svelte"), requiresAuth: true }` |
| `ui/src/lib/nav.ts` | extends | `{ path: "/account/security", label: "Account", section: "user" }` |
| `ui/src/lib/components/Topbar.svelte` | modifies | identity `<a href>` to `/account/security` via `router.navigate`; `Badge` "Passkey" |
| vendored shadcn `badge`, `dialog`, `card`, `button`, `input`, `label`, `skeleton` | uses | no new primitives |
| `parrot/server/ui/serving.py` (`SPA_SECTIONS`) | modifies | `("/login", "/agents", "/account")` |
| `tests/test_admin_ui_serving.py` | modifies | pattern and path parametrizations gain `/account` |
| `parrot/autonomous/admin.py` (`_ADMIN_LOGIN_HTML`) | modifies | passkey button + conditional UI + vanilla ceremony block |
| `packages/ai-parrot-server/pyproject.toml` | extends | `passkey = ["navigator-auth[passkey]>=0.28.9"]`; `all` includes `passkey` |
| `docs/admin-ui.md` | modifies | "Auth model" + quick start gain the passkey block; dev-origin RP note |
| `docs/examples/passkey.settings.example` | new | copy-ready settings |
| navigator-auth `PasskeyAuth` (0.28.9) | depends on | consumed as-is; see §6 for the exact routes, bodies and status codes |
| Redis ≥ 6.2 | depends on | challenge store (`GETDEL`) — backend requirement, documented only |

### Data Models

```ts
// ui/src/lib/api/passkey.ts — wire shapes, mirrors navigator_auth/backends/passkey.py (§6)
export interface PasskeyLoginOptions {
  challenge_id: string;
  publicKey: PublicKeyCredentialRequestOptionsJSON;   // lib.dom type (TS ≥ 5.4) or local structural alias
}
export interface PasskeyCredentialSummary {           // GET /credentials item — never carries key material
  id: string;                                         // base64url credential id
  label: string | null;
  created_at: string | null;                          // ISO-8601
  last_used_at: string | null;
  device_type: string | null;                         // "single_device" | "multi_device"
  backed_up: boolean;
  rp_id: string;
}
export interface PasskeyRegisterResult { status: "registered"; id: string }  // 201
export type PasskeyLoginBody = { challenge_id: string; credential: PublicKeyCredentialJSON };

// ui/src/lib/webauthn.ts
export type PublicKeyCredentialJSON = ReturnType<PublicKeyCredential["toJSON"]>;  // structural alias when lib.dom lacks it
```

```ts
// ui/src/lib/stores/auth.svelte.ts — the login envelope already stored under ai_parrot_session gains readers only
export interface AuthUser { [key: string]: unknown }                 // unchanged
// authMethod: $derived — (authStore.user?.auth_method as string | undefined) ?? null
```

```python
# docs/examples/passkey.settings.example — documented keys (navigator_auth/conf.py:598-617)
AUTHENTICATION_BACKENDS = "navigator_auth.backends.BasicAuth,navigator_auth.backends.PasskeyAuth"
PASSKEY_RELYING_PARTIES = '[{"origin": "https://parrot.example.com", "rp_id": "parrot.example.com", "rp_name": "AI-Parrot"},
                            {"origin": "http://localhost:5000", "rp_id": "localhost", "rp_name": "AI-Parrot (dev)"},
                            {"origin": "http://localhost:5173", "rp_id": "localhost", "rp_name": "AI-Parrot (vite dev)"}]'
PASSKEY_USER_VERIFICATION = "required"     # or "preferred"
PASSKEY_CHALLENGE_TTL = 300
PASSKEY_DECOY_CREDENTIALS = 1
PASSKEY_LOGIN_OPTIONS_RATE = 0             # leave 0 behind a proxy; rate-limit login/options at the proxy
```

### New Public Interfaces

```ts
// $lib/webauthn.ts
export function isWebAuthnSupported(): boolean;
export function isConditionalMediationAvailable(): Promise<boolean>;
export function toRequestOptions(json: PublicKeyCredentialRequestOptionsJSON): PublicKeyCredentialRequestOptions;
export function toCreationOptions(json: PublicKeyCredentialCreationOptionsJSON): PublicKeyCredentialCreationOptions;
export function credentialToJSON(cred: PublicKeyCredential): PublicKeyCredentialJSON;
export function isUserCancelled(err: unknown): boolean;   // NotAllowedError | AbortError
export function base64UrlToBuffer(value: string): ArrayBuffer;
export function bufferToBase64Url(buffer: ArrayBuffer): string;

// $lib/api/passkey.ts
export async function fetchLoginOptions(username?: string): Promise<PasskeyLoginOptions | null>;  // bare axios; null on any failure
export async function postPasskeyLogin(body: PasskeyLoginBody): Promise<AuthUser>;               // bare axios; throws on non-2xx
export async function fetchRegisterOptions(): Promise<PublicKeyCredentialCreationOptionsJSON>;   // apiClient
export async function verifyRegistration(credential: PublicKeyCredentialJSON, label?: string): Promise<PasskeyRegisterResult>;
export async function listPasskeys(): Promise<PasskeyCredentialSummary[]>;
export async function renamePasskey(id: string, label: string): Promise<void>;
export async function deletePasskey(id: string): Promise<void>;                                   // ApiError status 409 = last login method

// AuthStore (stores/auth.svelte.ts)
async loginWithPasskey(challengeId: string, credential: PublicKeyCredentialJSON): Promise<{ success: boolean; error?: string }>;
get authMethod(): string | null;
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 webauthn-browser-helper | yes | function set and semantics fixed in §2 New Public Interfaces; fallback algorithm = navigator-auth `templates/oauth/login.html` (`b64urlToBuffer`/`bufferToB64url`/`toRequestOptions`/`credentialToJSON`), extended for creation options (`user.id`, `excludeCredentials[].id`) | — |
| M2 passkey-api | yes | URLs from `config.passkeyApiPrefix`; bare-axios vs `apiClient` split fixed in §2; error mapping via `extractServerMessage` | — |
| M3 auth-store-passkey-login | yes | `loginWithPasskey()` signature, `_storeLoginEnvelope()` refactor, `authMethod` getter fixed | — |
| M4 passkey-sign-in-component | yes | props, state machine (probe → conditional → click aborts → modal), copy strings and silent-cancel rule fixed in §3/§7 | — |
| M5 account-security-page | yes | page layout, three components, copy strings and status-code → message table fixed | — |
| M6 account-navigation-and-badge | yes | route object, `appSections`, nav entry, Topbar link + badge fixed | — |
| M7 spa-account-section-serving | yes | one tuple edit + test parametrizations | — |
| M8 server-passkey-extra-and-docs | yes | extra name, pin, `all` membership, doc sections and example file fixed | — |
| M9 autonomous-admin-passkey-signin | yes | vanilla block ported from upstream `login.html`, continuation = `saveSession(data)` + `showAlert` + existing redirect; new pytest smoke test | — |

### Dependency graph

```
M1 ──▶ M2 ──▶ M3 ──▶ M4 ──▶ (Login.svelte)        M7 (serving.py)      M8 (pyproject + docs)      M9 (admin.py)
 │      └────▶ M5 ──▶ M6 (routes/nav/Topbar)      independent of every UI module; M6 and M7 must BOTH land before /account/security
 └──────────────┘                                   survives a hard reload (same PR; no code import between them)
```

### Module 1: webauthn-browser-helper
- **Path**: `packages/ai-parrot-server/ui/src/lib/webauthn.ts` (new) + `webauthn.test.ts` (new)
- **Responsibility**: Framework-free WebAuthn plumbing: capability detection, JSON ⇄ binary conversion with native Level-3 API first and base64url fallback, user-cancel classification.
- **Depends on**: nothing in the repo (browser APIs only).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```ts
  // packages/ai-parrot-server/ui/src/lib/webauthn.ts (new)
  export type PublicKeyCredentialJSON = { id: string; rawId: string; type: string; authenticatorAttachment?: string;
    clientExtensionResults: Record<string, unknown>; response: Record<string, unknown> };
  /** True when `window.PublicKeyCredential` and `navigator.credentials` exist. */
  export function isWebAuthnSupported(): boolean;
  /** Resolves `PublicKeyCredential.isConditionalMediationAvailable()`; false when the static method is missing or throws. */
  export function isConditionalMediationAvailable(): Promise<boolean>;
  /** Native `PublicKeyCredential.parseRequestOptionsFromJSON` when present, else decodes `challenge` and `allowCredentials[].id`. */
  export function toRequestOptions(json: PublicKeyCredentialRequestOptionsJSON): PublicKeyCredentialRequestOptions;
  /** Native `parseCreationOptionsFromJSON` when present, else decodes `challenge`, `user.id`, `excludeCredentials[].id`. */
  export function toCreationOptions(json: PublicKeyCredentialCreationOptionsJSON): PublicKeyCredentialCreationOptions;
  /** `cred.toJSON()` when present, else hand-built object covering assertion AND attestation responses (`transports` via `getTransports?.()`). */
  export function credentialToJSON(cred: PublicKeyCredential): PublicKeyCredentialJSON;
  /** True for `NotAllowedError` / `AbortError` (dismissed prompt, superseded request) — callers show nothing. */
  export function isUserCancelled(err: unknown): boolean;
  export function base64UrlToBuffer(value: string): ArrayBuffer;
  export function bufferToBase64Url(buffer: ArrayBuffer): string;
  ```

### Module 2: passkey-api
- **Path**: `packages/ai-parrot-server/ui/src/lib/api/passkey.ts` (new) + `passkey.test.ts` (new); modifies `ui/src/lib/config.ts`
- **Responsibility**: Typed wrappers for the six `PasskeyAuth` endpoints with the §2 transport split; URL constants in `config`.
- **Depends on**: M1 (`PublicKeyCredentialJSON`), existing `apiClient` / `ApiError` / `extractServerMessage` (`lib/api/http.ts`), `config`.
- **Interface Skeleton**:
  ```ts
  // packages/ai-parrot-server/ui/src/lib/config.ts  (modifies config.ts:65 — after authMethodsUrl)
  passkeyApiPrefix: "/api/v1/auth/passkey",   // navigator_auth/backends/passkey.py:35 PASSKEY_PREFIX
  accountSecurityPath: `${basePath}/account/security`,

  // packages/ai-parrot-server/ui/src/lib/api/passkey.ts (new)
  import axios from "axios";
  import apiClient, { ApiError, extractServerMessage } from "$lib/api/http";   // verified: http.ts:31, :80, :197
  import { config } from "$lib/config";
  import type { PublicKeyCredentialJSON } from "$lib/webauthn";
  export interface PasskeyLoginOptions { challenge_id: string; publicKey: PublicKeyCredentialRequestOptionsJSON }
  export interface PasskeyCredentialSummary { id: string; label: string | null; created_at: string | null;
    last_used_at: string | null; device_type: string | null; backed_up: boolean; rp_id: string }
  /** POST {prefix}/login/options via bare axios (NOT apiClient — §2 rule 1). `{username}` when given, `{}` otherwise.
   *  Returns null on ANY failure (404 = backend disabled, 429 = rate limited, network) — callers treat null as "unavailable". */
  export async function fetchLoginOptions(username?: string): Promise<PasskeyLoginOptions | null>;
  /** POST config.loginUrl with header X-Auth-Method: PasskeyAuth via bare axios; resolves to the login envelope; rejects with the raw axios error. */
  export async function postPasskeyLogin(body: { challenge_id: string; credential: PublicKeyCredentialJSON }): Promise<Record<string, unknown>>;
  /** POST {prefix}/register/options with body {} through apiClient (Bearer). */
  export async function fetchRegisterOptions(): Promise<PublicKeyCredentialCreationOptionsJSON>;
  /** POST {prefix}/register/verify {credential, label?}; 201 → {status, id}; ApiError 409 = already registered, 400 = failed/label too long. */
  export async function verifyRegistration(credential: PublicKeyCredentialJSON, label?: string): Promise<{ status: "registered"; id: string }>;
  export async function listPasskeys(): Promise<PasskeyCredentialSummary[]>;                 // GET {prefix}/credentials
  export async function renamePasskey(id: string, label: string): Promise<void>;             // PATCH {prefix}/credentials/{encodeURIComponent(id)} {label: label.trim()} (1..128 enforced client-side too)
  export async function deletePasskey(id: string): Promise<void>;                            // DELETE {prefix}/credentials/{encodeURIComponent(id)} → 204 with NO body (never parse); ApiError.status 409 = last login method
  /** Human message for a passkey ApiError: prefers the backend's `{reason}` body (extractServerMessage), falls back to err.message. */
  export function passkeyErrorMessage(err: unknown): string;
  ```

### Module 3: auth-store-passkey-login
- **Path**: modifies `packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts` + `auth.test.ts`
- **Responsibility**: Persist a passkey login envelope through the same path as a Basic login; expose the session's auth method.
- **Depends on**: M2 (`postPasskeyLogin`), existing `AuthStore.login()` (`auth.svelte.ts:62`).
- **Interface Skeleton**:
  ```ts
  // packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts (modifies auth.svelte.ts:62 login(), adds below logout():99)
  class AuthStore {
    /** `user.auth_method` from the stored envelope ("passkey" | "basic" | …) or null. Drives the Topbar badge (M6). */
    authMethod = $derived<string | null>(...);
    /** Shared tail of login(): requires data.token, writes ai_parrot_token / ai_parrot_session (try/catch), sets token+user. Throws when token is missing. */
    private _storeLoginEnvelope(data: Record<string, unknown>): void;
    /** POST /api/v1/login with X-Auth-Method: PasskeyAuth (via M2 postPasskeyLogin — bare axios, never apiClient) then _storeLoginEnvelope().
     *  Same result shape as login(); the error string is the server's message when present, else "Passkey sign-in failed". */
    async loginWithPasskey(challengeId: string, credential: PublicKeyCredentialJSON): Promise<{ success: boolean; error?: string }>;
  }
  ```

### Module 4: passkey-sign-in-component
- **Path**: `packages/ai-parrot-server/ui/src/lib/components/auth/PasskeySignIn.svelte` (new) + `PasskeySignIn.test.ts` (new); modifies `ui/src/pages/Login.svelte`, `ui/src/lib/components/ProviderButtons.svelte`, `ui/src/pages/Login.test.ts`
- **Responsibility**: Login-page passkey UX: availability probe, conditional UI, explicit button, error alert, navigation on success.
- **Depends on**: M1, M2, M3.
- **Interface Skeleton**:
  ```svelte
  <!-- packages/ai-parrot-server/ui/src/lib/components/auth/PasskeySignIn.svelte (new) -->
  <script lang="ts">
    interface Props {
      /** Current value of the login form's username input (username-first when non-empty). */
      username: string;
      /** Called with the resolved in-app target after a successful login (Login.svelte passes nextTarget()). */
      onSuccess: (target: string) => void;
      /** Disables the button while the password form is submitting. */
      disabled?: boolean;
    }
    // state: available = $state(false); busy = $state(false); error = $state("");
    // onMount: if (!isWebAuthnSupported()) return; const started = await fetchLoginOptions();
    //   if (!started) return; available = true;
    //   if (await isConditionalMediationAvailable()) void runCeremony(started, "conditional");
    // click: abort pending conditional controller; started = await fetchLoginOptions(username.trim() || undefined); runCeremony(started)
    // runCeremony: navigator.credentials.get({ publicKey: toRequestOptions(started.publicKey), mediation?, signal })
    //   → authStore.loginWithPasskey(started.challenge_id, credentialToJSON(cred)) → onSuccess(target) | error = "Passkey sign-in failed. Use your password instead."
    //   isUserCancelled(err) → silent. After a failed MODAL attempt conditional UI is NOT re-armed.
  </script>
  <!-- renders nothing when !available; else a divider + <Button variant="outline" data-testid="passkey-signin"> + role="alert" error -->
  ```
  ```ts
  // ProviderButtons.svelte (modifies ProviderButtons.svelte:36-44)
  function isPasskeyAuth(info: AuthMethodInfo): boolean;   // headers["x-auth-method"]?.toLowerCase() === "passkeyauth" — verified value: abstract.py:100,130
  // providers filter becomes: !isBasicAuth(info) && !isPasskeyAuth(info)
  // Login.svelte (modifies Login.svelte:105 autocomplete="username" → "username webauthn"; :138 adds <PasskeySignIn {username} disabled={loading} onSuccess={(t) => router.navigate(t, { replace: true })} /> above <ProviderButtons/>)
  ```

### Module 5: account-security-page
- **Path**: `packages/ai-parrot-server/ui/src/pages/account/Security.svelte` (new) + `Security.test.ts` (new); `ui/src/lib/components/account/PasskeyList.svelte` (new); `ui/src/lib/components/account/AddPasskeyDialog.svelte` (new)
- **Responsibility**: List / add / rename / delete the caller's passkeys; show the current session method; operator hint when the origin is not an RP.
- **Depends on**: M1 (`toCreationOptions`, `credentialToJSON`, `isUserCancelled`), M2, M3 (`authStore.authMethod`); vendored `card`, `button`, `input`, `label`, `dialog`, `badge`, `skeleton`.
- **Interface Skeleton**:
  ```svelte
  <!-- pages/account/Security.svelte (new) — route /account/security, requiresAuth -->
  <!-- Card "Session": "Signed in with a passkey" | "Signed in with a password" (authStore.authMethod) -->
  <!-- Card "Passkeys": <PasskeyList> + "Add a passkey" (opens AddPasskeyDialog). Empty state copy explains passkeys.
       After EVERY mutation (add/rename/delete) the page re-fetches listPasskeys() — never removes/updates rows optimistically;
       a 409 on delete is authoritative (row stays). Rows may belong to other relying parties (GET lists ALL RPs) — rp_id is shown, never hidden. -->
  <!-- Error states (from passkeyErrorMessage / ApiError.status):
       register/options 4xx (origin not an RP) → "This site is not configured for passkeys — ask your administrator to add its origin to PASSKEY_RELYING_PARTIES."
       verify 409 → "This device is already registered." · browser unsupported → "Your browser does not support passkeys."
       delete 409 → "You can't delete your only way to sign in. Set a password or add another passkey first." -->

  <!-- lib/components/account/PasskeyList.svelte (new) -->
  <script lang="ts">
    interface Props { items: PasskeyCredentialSummary[]; loading: boolean;
      onRename: (id: string, label: string) => Promise<void>; onDelete: (id: string) => Promise<void> }
    // row: label || "Unnamed passkey" · device_type ("single_device" → "This device only", "multi_device" → "Synced") · <Badge> when backed_up
    //      · rp_id · created_at / last_used_at (toLocaleString) · inline rename (1–128 chars) · Delete → confirmation <Dialog>
  </script>

  <!-- lib/components/account/AddPasskeyDialog.svelte (new) -->
  <script lang="ts">
    interface Props { open: boolean; onClose: () => void; onRegistered: () => void }
    // flow: fetchRegisterOptions() → navigator.credentials.create({ publicKey: toCreationOptions(json) })
    //       → label step (optional, ≤128) → verifyRegistration(credentialToJSON(cred), label || undefined) → onRegistered()
  </script>
  ```

### Module 6: account-navigation-and-badge
- **Path**: modifies `ui/src/App.svelte`, `ui/src/lib/config.ts` (`appSections`), `ui/src/lib/nav.ts`, `ui/src/lib/components/Topbar.svelte`; extends `ui/src/lib/router.test.ts`, `ui/src/App.test.ts`, `ui/src/lib/components/AppShell.test.ts`
- **Responsibility**: Make `/account/security` reachable and visible; Topbar identity link and "Passkey" badge.
- **Depends on**: M5 (page component), M3 (`authStore.authMethod`).
- **Interface Skeleton**:
  ```ts
  // config.ts:62  appSections: ["login", "agents", "admin", "account"],   // MUST mirror serving.py SPA_SECTIONS (M7)
  // App.svelte:20 route table — before the "--- Administration" comment (:32):
  //   { path: "/account/security", component: () => import("./pages/account/Security.svelte"), requiresAuth: true },
  // nav.ts:29 navEntries — after the "/agents" entry (section "user"), i.e. before the "/admin/home" entry at :37:
  //   { path: "/account/security", label: "Account", icon: "<24x24 stroke path>", section: "user" },
  ```
  ```svelte
  <!-- Topbar.svelte (modifies Topbar.svelte:32) -->
  <a href={config.accountSecurityPath} onclick={(e) => { e.preventDefault(); router.navigate(config.accountSecurityPath); }}
     class="text-muted-foreground hover:text-foreground text-sm" data-testid="topbar-identity">{identity}</a>
  {#if authStore.authMethod === "passkey"}<Badge variant="secondary" data-testid="topbar-auth-badge">Passkey</Badge>{/if}
  ```

### Module 7: spa-account-section-serving
- **Path**: modifies `packages/ai-parrot-server/src/parrot/server/ui/serving.py`, `packages/ai-parrot-server/tests/test_admin_ui_serving.py`
- **Responsibility**: Serve the SPA shell (and exclude it from auth) for `/account` and `/account/*`.
- **Depends on**: nothing (Python only); M6 for the end-to-end effect.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/server/ui/serving.py  (modifies serving.py:39)
  SPA_SECTIONS: tuple[str, ...] = ("/login", "/agents", "/account")   # MUST match config.appSections (ui/src/lib/config.ts:62)
  # tests/test_admin_ui_serving.py: parametrize :68 adds "/account/security"; pattern set :192 adds "/account", "/account/*";
  #   lookalike list :86/:198 adds "/accounts" (must NOT be served/excluded)
  ```

### Module 8: server-passkey-extra-and-docs
- **Path**: modifies `packages/ai-parrot-server/pyproject.toml`, `docs/admin-ui.md`; creates `docs/examples/passkey.settings.example`
- **Responsibility**: Make `PasskeyAuth` installable and configurable from ai-parrot alone.
- **Depends on**: none.
- **Interface Skeleton**:
  ```toml
  # packages/ai-parrot-server/pyproject.toml  (modifies pyproject.toml:46 optional-dependencies; :97-98 all)
  passkey = [
      # navigator-auth's PasskeyAuth backend (FEAT-101) + py_webauthn; 0.28.9 is the first release shipping it.
      "navigator-auth[passkey]>=0.28.9",
  ]
  all = [
      "ai-parrot-server[scheduler,mcp,a2a,autonomous,comm-center,passkey]",
  ]
  # root uv.lock — regenerate with `uv lock` (NOT `uv sync` inside a worktree): today it pins navigator-auth 0.28.7
  # (uv.lock:9689-9690) and has NO `webauthn` entry, so a plain `uv sync` would downgrade the venv below PasskeyAuth.
  ```
  ```markdown
  <!-- docs/admin-ui.md — "Auth model" (:44) gains a "Passkeys" paragraph; quick start (:221) gains the
       AUTHENTICATION_BACKENDS + PASSKEY_RELYING_PARTIES block and the Vite-dev-origin note; link to docs/examples/passkey.settings.example.
       Operator section MUST also cover: `pip install "ai-parrot-server[passkey]"`; Redis >= 6.2 (GETDEL); AUTH_SECRET_KEY still mandatory
       (multi-worker tokens); startup failure modes — ConfigError when PASSKEY_RELYING_PARTIES is empty/invalid or `webauthn` is missing;
       `rp_id` must be the origin host or a parent domain; PASSKEY_LOGIN_OPTIONS_RATE=0 behind a proxy. -->
  ```

### Module 9: autonomous-admin-passkey-signin
- **Path**: modifies `packages/ai-parrot-server/src/parrot/autonomous/admin.py`; creates `packages/ai-parrot-server/tests/test_autonomous_admin_page.py`
- **Responsibility**: Passkey sign-in (button + conditional UI) in the inline `/autonomous/admin` page; no enrollment.
- **Depends on**: none (vanilla JS inside `_ADMIN_LOGIN_HTML`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/autonomous/admin.py  (modifies _ADMIN_LOGIN_HTML, admin.py:17)
  #   :224  autocomplete="username"  →  autocomplete="username webauthn"
  #   after the <form> submit button: <button type="button" id="passkeyBtn" hidden>Sign in with a passkey</button>
  #   <script> block ported from navigator-auth templates/oauth/login.html (b64urlToBuffer, bufferToB64url, toRequestOptions,
  #     credentialToJSON, passkeySignIn(username, mediation), conditional-UI arming, click aborts conditional) with:
  #     OPTIONS_URL = '/api/v1/auth/passkey/login/options'; LOGIN_URL = '/api/v1/login';
  #     success → saveSession(data); showAlert('success', 'Login successful! Redirecting…'); showSessionState(data); same setTimeout redirect (:344-346)
  #     failure → showAlert('error', 'Passkey sign-in failed. Use your password instead.'); NotAllowedError/AbortError → silent
  #     button.hidden = false ONLY after a successful probe fetch of OPTIONS_URL (same visibility rule as the SPA)
  #   a "Manage passkeys" link to /account/security in the signed-in state block
  # tests/test_autonomous_admin_page.py (new): GET /autonomous/admin → 200, body contains 'username webauthn',
  #   '/api/v1/auth/passkey/login/options', "'X-Auth-Method': 'PasskeyAuth'" and still "'X-Auth-Method': 'BasicAuth'"
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `webauthn.test.ts::isWebAuthnSupported` | M1 | false without `PublicKeyCredential`; true with stubs |
| `webauthn.test.ts::toRequestOptions fallback` | M1 | without native parser decodes `challenge` and `allowCredentials[].id` to ArrayBuffers; with native parser delegates |
| `webauthn.test.ts::toCreationOptions fallback` | M1 | decodes `challenge`, `user.id`, `excludeCredentials[].id` |
| `webauthn.test.ts::credentialToJSON` | M1 | prefers `toJSON()`; fallback round-trips base64url for assertion and attestation shapes |
| `webauthn.test.ts::base64url round-trip` | M1 | `bufferToBase64Url(base64UrlToBuffer(x)) === x` for padded/unpadded inputs |
| `webauthn.test.ts::isUserCancelled` | M1 | true for `NotAllowedError`/`AbortError` DOMExceptions, false otherwise |
| `passkey.test.ts::fetchLoginOptions` | M2 | uses bare `axios.post`, never `apiClient`; `{username}` vs `{}`; null on 404/429/network |
| `passkey.test.ts::postPasskeyLogin` | M2 | bare axios POST to `config.loginUrl` with `X-Auth-Method: PasskeyAuth` |
| `passkey.test.ts::authenticated calls` | M2 | `fetchRegisterOptions`/`verifyRegistration`/`listPasskeys`/`renamePasskey`/`deletePasskey` go through `apiClient` with the right method/URL/body |
| `passkey.test.ts::passkeyErrorMessage` | M2 | surfaces `{reason}` bodies; falls back to `err.message` |
| `auth.test.ts::loginWithPasskey success` | M3 | stores `ai_parrot_token`/`ai_parrot_session`, sets `token`/`user`, `authMethod === "passkey"` |
| `auth.test.ts::loginWithPasskey failure` | M3 | returns `{success:false, error}` and does NOT call `handle401()` or touch storage |
| `auth.test.ts::login still works` | M3 | existing BasicAuth tests unchanged after the `_storeLoginEnvelope` refactor |
| `PasskeySignIn.test.ts::hidden when unsupported` | M4 | renders nothing when `PublicKeyCredential` is undefined |
| `PasskeySignIn.test.ts::hidden when probe fails` | M4 | `fetchLoginOptions` → null ⇒ no button, no network retry |
| `PasskeySignIn.test.ts::conditional UI armed once` | M4 | probe response reused for `credentials.get({mediation:"conditional"})`; exactly one `login/options` call on mount |
| `PasskeySignIn.test.ts::click aborts conditional and signs in` | M4 | pending controller aborted; username-first body; `loginWithPasskey` called; `onSuccess(target)` |
| `PasskeySignIn.test.ts::cancel is silent, failure shows alert` | M4 | `NotAllowedError` → no alert; 401 → "Passkey sign-in failed. Use your password instead." |
| `Login.test.ts::username autocomplete` | M4 | input has `autocomplete="username webauthn"`; existing Login tests still pass with `axios.post` mocked to reject (probe unavailable) |
| `Login.test.ts::PasskeyAuth excluded from ProviderButtons` | M4 | a `PasskeyAuth` method entry renders no disabled button |
| `Security.test.ts::lists passkeys` | M5 | renders label/device/badge/dates from `listPasskeys` |
| `Security.test.ts::empty state + add` | M5 | empty copy; add flow calls `fetchRegisterOptions` → `credentials.create` → `verifyRegistration(label)` → refresh |
| `Security.test.ts::rename/delete + 409` | M5 | PATCH/DELETE calls; 409 on delete shows the last-login-method message |
| `Security.test.ts::origin not configured` | M5 | 4xx on `register/options` shows the operator hint |
| `router.test.ts::isInAppPath account` | M6 | `/account/security` true; `/accounts` false |
| `App.test.ts::account route` | M6 | `/account/security` resolves inside `AppShell` and requires auth (redirect with `?next=`) |
| `AppShell.test.ts::topbar link + badge` | M6 | identity is a link to `/account/security`; badge present only when `auth_method === "passkey"` |
| `test_admin_ui_serving.py::/account served` | M7 | `/account/security` returns `index.html`; `/accounts` does not; exclusion patterns include `/account` and `/account/*` |
| `test_autonomous_admin_page.py::passkey block present` | M9 | page body carries the webauthn autocomplete, options URL and `PasskeyAuth` header string |

Test doubles: jsdom has no WebAuthn. Each test file stubs `globalThis.PublicKeyCredential` (with/without
`parseRequestOptionsFromJSON` / `isConditionalMediationAvailable`) and `navigator.credentials.get/create`
via `vi.stubGlobal` / `Object.defineProperty`; `vitest-setup.ts` is **not** changed (no global stub —
the "unsupported browser" path must stay testable).

### Integration Tests

| Test | Description |
|---|---|
| `test_admin_ui_serving.py` (aiohttp test client, existing fixtures) | shell served for every `SPA_SECTIONS` entry including `/account`; `/accounts` 404; exclusion list on startup |
| Manual (documented in `docs/admin-ui.md`) | real browser against a running backend with `PasskeyAuth` enabled: enroll on `/account/security`, sign out, sign in via autofill and via button, delete last passkey → 409 |
| Manual — Vite dev origin (documented in `docs/admin-ui.md`) | with `pnpm dev` (`http://localhost:5173`, proxy `changeOrigin: true` rewrites `Host` only — `vite.config.ts:84`) the browser's `Origin` reaches navigator-auth unchanged: enroll + sign in succeed only when `http://localhost:5173` is listed in `PASSKEY_RELYING_PARTIES`; the same credential is NOT offered on `http://localhost:5000` (different RP entry) |

### Validation Contract

> UI tests run through pytest wrappers in `packages/ai-parrot-server/tests/ui/` (`_vitest.run_vitest`), the
> repo convention since FEAT-593 — `check_task_graph` accepts pytest validation commands only. Each wrapper
> runs the vitest files listed in its docstring; a single runner keeps every test running once per tier.

tests:
- packages/ai-parrot-server/tests/test_admin_ui_serving.py
- packages/ai-parrot-server/tests/test_autonomous_admin_page.py
- packages/ai-parrot-server/tests/test_passkey_packaging.py
- packages/ai-parrot-server/tests/test_passkey_settings_example.py
- packages/ai-parrot-server/tests/ui/test_vitest_passkey_webauthn.py
- packages/ai-parrot-server/tests/ui/test_vitest_passkey_api.py
- packages/ai-parrot-server/tests/ui/test_vitest_auth_store.py
- packages/ai-parrot-server/tests/ui/test_vitest_passkey_sign_in.py
- packages/ai-parrot-server/tests/ui/test_vitest_account_security.py
- packages/ai-parrot-server/tests/ui/test_vitest_account_navigation.py
markers: none

### Test Data / Fixtures

```ts
// shared by M1/M4/M5 tests — a minimal WebAuthn stub factory (lives in each test file or src/lib/test-utils/webauthn-stubs.ts)
export function stubWebAuthn(opts: { native?: boolean; conditional?: boolean; get?: () => Promise<unknown>; create?: () => Promise<unknown> }): void;
// get() resolves a fake PublicKeyCredential: { id: "Y3JlZA", rawId: ArrayBuffer, type: "public-key", response: { clientDataJSON, authenticatorData, signature, userHandle: null }, getClientExtensionResults: () => ({}), toJSON? }
export const LOGIN_OPTIONS = { challenge_id: "chal-1", publicKey: { challenge: "Y2hhbGxlbmdl", rpId: "localhost", allowCredentials: [], userVerification: "required", timeout: 60000 } };
export const CREDENTIAL_ROW = { id: "Y3JlZA", label: "Laptop", created_at: "2026-10-30T00:00:00+00:00", last_used_at: null, device_type: "multi_device", backed_up: true, rp_id: "localhost" };
```

```python
# tests/test_autonomous_admin_page.py — aiohttp test client around admin_login_page (admin.py:394); no DB/Redis needed
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC01. With `PasskeyAuth` disabled (`login/options` → 404) or WebAuthn absent, `/login` renders byte-identical markup to today (no passkey button, no network retry) and `/autonomous/admin` shows no passkey button.
- [ ] AC02. With `PasskeyAuth` enabled, `/login` shows "Sign in with a passkey", the username input has `autocomplete="username webauthn"`, and exactly ONE `POST login/options` is issued on mount, reused for `credentials.get({mediation:"conditional"})` when available.
- [ ] AC03. Clicking the button aborts the pending conditional request, sends `{username}` when the field is non-empty (else `{}`), and on success stores the envelope via `AuthStore` and navigates to `?next=` or `/agents` (same as a password login).
- [ ] AC04. Passkey sign-in failures show exactly "Passkey sign-in failed. Use your password instead."; `NotAllowedError`/`AbortError` show nothing; the login page's `?next=` is never rewritten by a failed passkey attempt (no `apiClient` on `login/options` or the passkey `POST /api/v1/login`).
- [ ] AC05. `/account/security` (route `requiresAuth`) lists the caller's passkeys (label, device type, synced badge, RP, created/last used), supports add (with optional label ≤ 128), rename (1–128) and delete with confirmation; a DELETE 409 shows the last-login-method message; a 4xx on `register/options` shows the operator hint naming `PASSKEY_RELYING_PARTIES`.
- [ ] AC06. Enrollment and management calls go through `apiClient` (Bearer) and send no CSRF header; a genuine 401 there still triggers `handle401()`.
- [ ] AC07. Sidebar "Workspace" shows "Account" → `/account/security`; the Topbar identity links there; a "Passkey" badge appears iff the stored envelope has `auth_method === "passkey"`; `/account/security` states the current session method.
- [ ] AC08. `config.appSections` and `serving.py` `SPA_SECTIONS` both contain the `account` section; `/account/security` hard-reloads to the SPA shell pre-login and `/accounts` is neither served nor auth-excluded.
- [ ] AC09. `ProviderButtons` renders no disabled button for the `PasskeyAuth` method entry (`x-auth-method` lower-cased `"passkeyauth"`).
- [ ] AC10. `ai-parrot-server[passkey]` resolves `navigator-auth[passkey]>=0.28.9` and `ai-parrot-server[all]` includes it; the regenerated root `uv.lock` resolves `navigator-auth>=0.28.9` and contains a `webauthn` entry; `import webauthn` succeeds in an env installed with the extra.
- [ ] AC11. `docs/admin-ui.md` documents the passkey setup (backends, RPs incl. `http://localhost:5173` for `pnpm dev`, user verification, Redis ≥ 6.2, `rp_id` rule) and links `docs/examples/passkey.settings.example`, which exists and is tracked.
- [ ] AC12. `/autonomous/admin` performs passkey sign-in (button + conditional UI) ending in `saveSession(data)` and the existing redirect; the page still performs BasicAuth login; no enrollment UI there.
- [ ] AC13. No new entry in `ui/package.json` dependencies; `pnpm build` succeeds; the Validation Contract runners pass (`pytest` files + `vitest` files above).
- [ ] AC14. Every uniform-401 path keeps the server's indistinguishability: the UI never shows a different message for "unknown user" vs "bad assertion" vs "expired challenge".

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Carried from the brainstorm's Code Context and re-verified at `1ee364d41` (dev, 2026-10-30; the
> ledger-only commit `ed44ca4fa` on top touches none of these files). Implementation agents MUST NOT
> reference imports, attributes, or methods not listed here without first verifying they exist.

### Verified Imports

```ts
// Admin UI (packages/ai-parrot-server/ui/src/)
import apiClient, { ApiError, extractServerMessage } from "$lib/api/http";          // http.ts:197 (default), :31, :80
import { config } from "$lib/config";                                                 // config.ts (export const config)
import { authStore, type AuthUser } from "$lib/stores/auth.svelte";                   // auth.svelte.ts (export const authStore; export interface AuthUser)
import { isInAppPath, router, type RouteDefinition } from "$lib/router.svelte";       // router.svelte.ts:27 (RouteDefinition), :69 (isInAppPath), export { Router, isInAppPath }; export const router
import { navEntries, navSections, type NavEntry, type NavSection } from "$lib/nav";   // nav.ts:13, :29
import ProviderButtons, { type AuthMethodInfo } from "$lib/components/ProviderButtons.svelte"; // Login.svelte:16; AuthMethodInfo at ProviderButtons.svelte:20
import { getAuthHeaders } from "$lib/api/auth-headers";                               // auth-headers.ts:16 (fetch-based calls, if any)
import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
import { Card, CardContent, CardHeader, CardTitle } from "$lib/ui/internal/shadcn/ui/card/index.js";
import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";
import { Badge } from "$lib/ui/internal/shadcn/ui/badge/index.js";                   // ui/badge/{badge.svelte,index.ts}
import * as Dialog from "$lib/ui/internal/shadcn/ui/dialog/index.js";                 // ui/dialog/{dialog,dialog-content,dialog-footer,dialog-header,dialog-title,…}.svelte
import { Skeleton } from "$lib/ui/internal/shadcn/ui/skeleton/index.js";
import axios from "axios";                                                            // ui/package.json "axios": "^1.16.1"
```

```python
# Server
from parrot.server.ui.serving import SPA_SECTIONS, setup_admin_ui          # serving.py:39, :235
from parrot.autonomous.admin import admin_login_page, _ADMIN_LOGIN_HTML    # admin.py:394, :17
from navigator_auth.backends import PasskeyAuth                            # navigator_auth/backends/__init__.py:20 (in __all__)
from navigator_auth.backends.passkey import PASSKEY_PREFIX                 # passkey.py:35 == "/api/v1/auth/passkey"
```

### Existing Class Signatures

```ts
// packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts
class AuthStore {
  token = $state<string | null>(readStoredToken());
  user = $state<AuthUser | null>(readStoredUser());
  loading = $state(false);
  isAuthenticated = $derived(this.token !== null);
  async login(username: string, password: string): Promise<{ success: boolean; error?: string }>  // :62 — apiClient.post(config.loginUrl, {username,password}, { headers: { "X-Auth-Method": "BasicAuth" } }) (:68); requires data.token; localStorage.setItem(tokenStorageKey/sessionStorageKey)
  async logout(): Promise<void>        // :99 — GET config.logoutUrl, then clearStorage()
  handle401(): void                    // :113 — clearStorage(); router.navigate(`${config.loginPath}?next=${encodeURIComponent(next)}`)
}
export const authStore = new AuthStore();

// packages/ai-parrot-server/ui/src/lib/config.ts (export const config = { … })
loginPath: `${basePath}/login`,            // :56
homePath: `${basePath}/agents`,            // :58
appSections: ["login", "agents", "admin"], // :62
loginUrl: "/api/v1/login",                 // :63
logoutUrl: "/api/v1/logout",
authMethodsUrl: "/api/v1/auth/methods",    // :65
tokenStorageKey: "ai_parrot_token", sessionStorageKey: "ai_parrot_session",
apiBaseUrl (string, "" by default), apiWithCredentials (boolean)

// packages/ai-parrot-server/ui/src/lib/router.svelte.ts
export interface RouteDefinition { path: string; component: RouteComponentLoader; requiresAuth?: boolean }  // :27
function isInAppPath(path: string): boolean   // :69 — first segment ∈ config.appSections
class Router { path = $state(...); params = $state<Record<string,string>>({}); routes: RouteDefinition[];
  navigate(to: string, options?: { replace?: boolean }): void; match(path?: string): RouteDefinition | undefined;
  guard(path?: string): boolean /* :218 — redirects to loginPath?next= when requiresAuth && !token */ }

// packages/ai-parrot-server/ui/src/App.svelte  — router.routes = [ { path: "/login", … }, { path: "/agents", requiresAuth: true }, …, // --- Administration --- … ]  (:20)
// packages/ai-parrot-server/ui/src/lib/nav.ts
export type NavSection = "user" | "admin";                                       // :13
export interface NavEntry { path: string; label: string; icon: string; section: NavSection }
export const navSections = [{ id: "user", label: "Workspace" }, { id: "admin", label: "Admin" }];
export const navEntries: NavEntry[] = [ { path: "/agents", label: "Agents", … section: "user" }, { path: "/admin/home", … }, … ];  // :29

// packages/ai-parrot-server/ui/src/lib/components/Topbar.svelte
const identity = $derived.by(() => user?.name || user?.username || user?.user || user?.email || "Signed in");
<span class="text-muted-foreground text-sm" data-testid="topbar-identity">{identity}</span>   // :32
<Button variant="outline" size="sm" onclick={handleLogout}>Sign out</Button>                      // :34

// packages/ai-parrot-server/ui/src/lib/components/ProviderButtons.svelte
export interface AuthMethodInfo { name: string; uri: string; description: string; icon: string; external: boolean; headers: Record<string, string> }  // :20
function isBasicAuth(info: AuthMethodInfo): boolean   // :36 — info.headers?.["x-auth-method"]?.toLowerCase() === "basicauth"
const providers = $derived(methods ? Object.entries(methods).map(…).filter(({ info }) => !isBasicAuth(info)) : []);  // :41-47
// non-external providers render <Button variant="outline" disabled title="Not yet supported in this Admin UI">

// packages/ai-parrot-server/ui/src/pages/Login.svelte
let username = $state(""); let password = $state(""); let loading = $state(false); let error = $state(""); let methods = $state<Record<string, AuthMethodInfo> | null>(null);
function nextTarget(): string                      // :28 — ?next= guarded by isInAppPath, else config.homePath
onMount: axios.get(`${config.apiBaseUrl}${config.authMethodsUrl}`, { withCredentials: config.apiWithCredentials })  // :49-57 — DELIBERATELY bare axios (comment :34-48)
const result = await authStore.login(username, password);   // :70
<Input id="username" … autocomplete="username" />           // :105
<ProviderButtons {methods} />                               // :138

// packages/ai-parrot-server/ui/src/lib/api/http.ts
export class ApiError extends Error { constructor(message, public readonly code: "network"|"timeout"|"server"|"auth"|"unknown", public readonly status?: number, public readonly raw?: unknown) }  // :31
export function extractServerMessage(data: unknown, status: number): string   // :80 — checks {error}, {message}, {message:{message}}, {detail}; NOTE: does NOT read {reason} → passkeyErrorMessage must check `reason` first
function registerInterceptors(instance): request adds `Authorization: Bearer <ai_parrot_token>` (:114-123); response 401 → authStore.handle401() unless /policy/i in body/statusText (:129-141); 403/404/other → ApiError
const apiClient = axios.create({ baseURL: config.apiBaseUrl, timeout: 300000, withCredentials: config.apiWithCredentials, headers: {"Content-Type": "application/json"} });  // :164
export default apiClient;   // :197
```

```python
# packages/ai-parrot-server/src/parrot/server/ui/serving.py
SPA_SECTIONS: tuple[str, ...] = ("/login", "/agents")                        # :39 — "MUST match config.appSections"
def _spa_paths(prefix: str, *, mount_root: bool) -> list[str]                # :124 — [section, f"{section}/{{tail:.*}}"] per section + prefix
def _auth_exclusion_patterns(prefix: str, *, mount_root: bool) -> list[str]  # :141 — [section, f"{section}/*"] per section + prefix + assets
def setup_admin_ui(app: web.Application, prefix: str = DEFAULT_PREFIX, mount_root: bool | None = None) -> bool   # :235

# packages/ai-parrot-server/tests/test_admin_ui_serving.py
@pytest.mark.parametrize("path", ["/", "/login", "/agents", "/agents/helpdesk/chat", "/admin/home"])   # :68
for path in ("/not-a-ui-page", "/agentsfoo", "/api/v1/missing"):                                         # :86 (must NOT serve)
for pattern in ("/admin", "/admin/*", "/login", "/agents", "/agents/*", "/ui/assets/*"):                 # :192 (exclusion list)
for path in ("/administer", "/agentsfoo", "/api/v1/bots", "/api/v1/login"):                              # :198 (must NOT be excluded)

# packages/ai-parrot-server/src/parrot/autonomous/admin.py
_ADMIN_LOGIN_HTML = """…"""                                                    # :17
<input type="text" id="username" name="user" required placeholder="Enter your username" autocomplete="username">   # :224
function saveSession(data) { localStorage.setItem('ai_parrot_token', data.token); localStorage.setItem('ai_parrot_session', JSON.stringify(data)); }  # :252-254
function showAlert(type, msg)                                                  # :273
async function handleLogin(event)                                              # :308 — fetch('/api/v1/login', { headers: { 'Content-Type': 'application/json', 'X-Auth-Method': 'BasicAuth' } }) (:320-324); saveSession(data); showAlert('success', …); showSessionState(data); setTimeout(() => window.location.href = '/api/whatsapp/dashboard', 1500) (:340-346)
async def admin_login_page(request: web.Request) -> web.Response               # :394
# packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py:338 — add_route('GET', '/autonomous/admin', admin_login_page, name='autonomous_admin'); :342-343 appended to exclude_list

# packages/ai-parrot-server/pyproject.toml
[project.optional-dependencies]                                                # :46
all = [ "ai-parrot-server[scheduler,mcp,a2a,autonomous,comm-center]", ]       # :97-98
# packages/ai-parrot/pyproject.toml:116 and root pyproject.toml:198 — "navigator-auth>=0.28.3"
# app.py:296 / appauto.py:65 — auth = AuthHandler(); auth.setup(self.app)   (backends come from the AUTHENTICATION_BACKENDS env, navigator_auth/conf.py:190)
# docs/admin-ui.md:44 "- Login: `POST /api/v1/login` with a `BasicAuth` username/password form." · :221 "- **Login**: set `AUTHENTICATION_BACKENDS=navigator_auth.backends.BasicAuth`"
```

```python
# navigator-auth 0.28.9 — .venv/lib/python3.12/site-packages/navigator_auth/
# backends/passkey.py
PASSKEY_PREFIX = "/api/v1/auth/passkey"                                        # :35
class PasskeyAuth(BasicAuth):                                                  # :63
    _description = "Passkey (WebAuthn) authentication"; _service_name = "passkey"   # :67-68
    # configure(): POST register/options · POST register/verify · POST login/options · GET credentials · PATCH credentials/{id} · DELETE credentials/{id}  (:76-88)
    # app[AUTH_EXCLUDE_LIST_KEY].append(f"{PASSKEY_PREFIX}/login/options")  (:90) — ONLY login/options is public; /api/v1/login is public by EXCLUDE_DEFAULTS (conf.py:63)
    async def get_payload(self, request) -> tuple[str, dict]                   # :196 — JSON body {challenge_id: str, credential: dict}; InvalidAuth 401 otherwise
    async def register_options(self, request) -> web.Response                 # :217 — session required (request["authenticated"]); body ignored; returns PublicKeyCredentialCreationOptions JSON (attestation none, residentKey required)
    async def register_verify(self, request) -> web.Response                  # :261 — body {credential: dict, label?: str ≤128}; 201 {"status":"registered","id"}; 400 invalid/failed/label; 401 state mismatch; 409 duplicate
    async def login_options(self, request) -> web.Response                    # :335 — body {username?: str}; rate-limited (PASSKEY_LOGIN_OPTIONS_RATE); returns {"challenge_id", "publicKey"}; decoys for unknown users
    async def authenticate(self, request) -> dict                             # :397 — POST /api/v1/login + X-Auth-Method: PasskeyAuth; uniform InvalidAuth 401 on every failure (_fail, :327-333); 403 disabled account; open_session(extra={"auth_method":"passkey","mfa":uv,"amr":[…],"org_id","client_id","passkey_rp_id"}) (:468-476)
    async def list_credentials(self, request) -> web.Response                 # :510 — [{id,label,created_at,last_used_at,device_type,backed_up,rp_id}]
    async def rename_credential(self, request) -> web.Response                # :532 — body {label: 1..128}; 200 {"status":"renamed"}; 400; 404
    async def delete_credential(self, request) -> web.Response                # :549 — 204; 404; 409 "Passkey: cannot delete the last login method"
# _json_errors (:36-56) → 4xx bodies are JSON {"reason": "<message>"}; 5xx → {"reason": "Passkey: internal error"}
# backends/abstract.py:100  self._service = self.__class__.__name__ ; :130  self._info.headers = {"x-auth-method": self._service}  → "PasskeyAuth"
# auth.py:541 async def auth_methods(request) → {<name>: backend.get_backend_info()} ; routes GET/POST /api/v1/auth/methods (:702, :708) — NOT in EXCLUDE_DEFAULTS (anonymous → 401)
# conf.py  PASSKEY_RELYING_PARTIES: list = [] (:598) · PASSKEY_CHALLENGE_TTL=300 (:609) · PASSKEY_USER_VERIFICATION="required" (:611) · PASSKEY_TENANT_ATTRIBUTE=None (:613) · PASSKEY_DECOY_CREDENTIALS=1 (:615) · PASSKEY_LOGIN_OPTIONS_RATE=0 (:617)
# conf.py:63 EXCLUDE_DEFAULTS = ["/static/", "/api/v1/login", "/api/v1/logout", "/api/v1/forgot-password", "/api/v1/reset-password"]
# passkey/rp.py  RelyingPartyResolver.resolve(request) (:79) — reads ONLY the Origin header (Referer exact fallback); by_origin(origin) (:95)
# passkey/types.py  RelyingParty{origin, rp_id, rp_name="Navigator", org_id?, client_id?} · StoredCredential · ChallengeState
# middlewares/csrf.py:3-8 — CSRF check applies only when the SOLE credential is the session cookie; Bearer skips it
# dist-info METADATA — Provides-Extra: passkey ; Requires-Dist: webauthn<3,>=2.0; extra == "passkey"
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `fetchLoginOptions` / `postPasskeyLogin` (M2) | `axios.post` (bare) | same pattern as Login.svelte discovery | `Login.svelte:49-57` |
| `fetchRegisterOptions` … `deletePasskey` (M2) | `apiClient.post/get/patch/delete` | Bearer injected by interceptor | `http.ts:114-123` |
| `passkeyErrorMessage` (M2) | `extractServerMessage()` + `{reason}` | backend 4xx body shape | `http.ts:80`, `passkey.py:36-56` |
| `AuthStore.loginWithPasskey` (M3) | `_storeLoginEnvelope` (refactored from `login()`) | same localStorage keys | `auth.svelte.ts:62-93` |
| `PasskeySignIn` (M4) | `authStore.loginWithPasskey`, `router.navigate` | `onSuccess(nextTarget())` | `Login.svelte:28,70-76` |
| `ProviderButtons.isPasskeyAuth` (M4) | `AuthMethodInfo.headers["x-auth-method"]` | `"PasskeyAuth"` | `abstract.py:100,130` |
| `Security.svelte` route (M6) | `router.routes` / `Router.guard` | `requiresAuth: true` | `App.svelte:20`, `router.svelte.ts:218` |
| `config.appSections` ↔ `SPA_SECTIONS` (M6/M7) | `isInAppPath`, `_spa_paths`, `_auth_exclusion_patterns` | string lists must match | `config.ts:62`, `serving.py:39,124,141` |
| Topbar badge (M6) | `authStore.user.auth_method` | envelope extra from `open_session(extra=…)` | `passkey.py:468-476` |
| `admin.py` passkey block (M9) | `saveSession(data)`, `showAlert`, `showSessionState` | existing inline functions | `admin.py:252,273,340-346` |
| `ai-parrot-server[passkey]` (M8) | `navigator-auth[passkey]` extra | `webauthn<3,>=2.0` | navigator_auth dist-info METADATA |

### Does NOT Exist (Anti-Hallucination)

- ~~`webauthn` (py_webauthn) in the shared venv~~ — only `fido2 2.2.1`; `.venv/lib/python3.12/site-packages/webauthn/__init__.py` is absent → `PasskeyAuth` raises `ConfigError` at startup today.
- ~~any `passkey` / `webauthn` code under `packages/ai-parrot-server/ui/src`~~; ~~`$lib/webauthn.ts`~~, ~~`$lib/api/passkey.ts`~~, ~~`components/auth/`~~, ~~`components/account/`~~, ~~`pages/account/`~~ — all created by this feature.
- ~~`AuthStore.loginWithPasskey()`~~, ~~`AuthStore.authMethod`~~, ~~`AuthStore._storeLoginEnvelope()`~~ — to be created (M3).
- ~~`"account"` in `config.appSections`~~ / ~~`"/account"` in `SPA_SECTIONS`~~ / ~~`config.passkeyApiPrefix`~~ / ~~`config.accountSecurityPath`~~ — to be created.
- ~~a user profile / account / settings page~~ — `pages/` has only `Agents`, `Dashboard`, `Home`, `Login`, `agents/*`.
- ~~`dropdown-menu` shadcn primitive~~ — not vendored; `badge`, `dialog`, `card`, `button`, `input`, `label`, `skeleton`, `separator`, `switch`, `tabs` are.
- ~~a Topbar user menu~~ — `Topbar.svelte` is identity `<span>` + `ThemeSwitcher` + "Sign out".
- ~~a `navigator.credentials` / `PublicKeyCredential` stub in `vitest-setup.ts`~~ — jsdom has none; each test file stubs them.
- ~~`extractServerMessage` reading a `reason` key~~ — it reads `error`/`message`/`detail` only (`http.ts:80-106`); passkey errors must check `reason` explicitly.
- ~~a login form in `parrot-formdesigner`~~ — `templates.py:129 _auth_script()` only reads `ai_parrot_token` and redirects to `/admin`; no `X-Auth-Method` in that package.
- ~~`navigator_auth/templates/oauth/login.html` in the installed wheel~~ — not shipped in 0.28.9 site-packages; the vanilla reference is `templates/oauth/login.html` on the navigator-auth `dev` branch (GitHub).
- ~~a pytest covering `/autonomous/admin`~~ — none in `packages/ai-parrot-server/tests` (M9 adds one).
- ~~a tracked `settings/settings.py` or `env/*`~~ — `/settings/` is git-ignored (`.gitignore:271`); ~~`docs/examples/`~~ does not exist yet (M8 creates it).
- ~~`PUBLIC_PASSKEY_ENABLED` build flag~~ — rejected in the brainstorm; availability is probed at runtime.
- ~~`/api/v1/auth/methods` in `EXCLUDE_DEFAULTS`~~ — anonymous discovery 401s; not used for passkey visibility.
- ~~`@simplewebauthn/browser`, `@github/webauthn-json`~~ — not in `ui/package.json` and must not be added.

### Edit Sites (Blueprint Anchors)

Verified against: `1ee364d41` (dev, 2026-10-30; HEAD `ed44ca4fa` differs only by `sdd/tasks/.id_ledger.json`). `/sdd-task` MUST re-run `grep -c` for every row it uses.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/webauthn.ts` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/webauthn.test.ts` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/api/passkey.ts` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/api/passkey.test.ts` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/config.ts` | MODIFY (M2) | `  authMethodsUrl: "/api/v1/auth/methods",` | `config.ts:65` | 1 |
| `packages/ai-parrot-server/ui/src/lib/config.ts` | MODIFY (M6) | `  appSections: ["login", "agents", "admin"],` | `config.ts:62` | 1 |
| `packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts` | MODIFY | `  async login(username: string, password: string): Promise<{ success: boolean; error?: string }> {` | `auth.svelte.ts:62` | 1 |
| `packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts` | MODIFY | `  async logout(): Promise<void> {` | `auth.svelte.ts:99` | 1 |
| `packages/ai-parrot-server/ui/src/lib/stores/auth.test.ts` | MODIFY | `  it("login() surfaces the server error message on failure", async () => {` | `auth.test.ts:37` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/auth/PasskeySignIn.svelte` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/components/auth/PasskeySignIn.test.ts` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/pages/Login.svelte` | MODIFY | `  import ProviderButtons, { type AuthMethodInfo } from "$lib/components/ProviderButtons.svelte";` | `Login.svelte:16` | 1 |
| `packages/ai-parrot-server/ui/src/pages/Login.svelte` | MODIFY | `            autocomplete="username"` | `Login.svelte:105` | 1 |
| `packages/ai-parrot-server/ui/src/pages/Login.svelte` | MODIFY | `      <ProviderButtons {methods} />` | `Login.svelte:138` | 1 |
| `packages/ai-parrot-server/ui/src/pages/Login.test.ts` | MODIFY | `    vi.spyOn(axios, "get").mockResolvedValue({ data: {} });` | `Login.test.ts:20` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/ProviderButtons.svelte` | MODIFY | `  function isBasicAuth(info: AuthMethodInfo): boolean {` | `ProviderButtons.svelte:36` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/ProviderButtons.svelte` | MODIFY | `          .filter(({ info }) => !isBasicAuth(info))` | `ProviderButtons.svelte:45` | 1 |
| `packages/ai-parrot-server/ui/src/pages/account/Security.svelte` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/pages/account/Security.test.ts` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/components/account/PasskeyList.svelte` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/components/account/AddPasskeyDialog.svelte` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/App.svelte` | MODIFY | `    // --- Administration -------------------------------------------------` | `App.svelte:32` | 1 |
| `packages/ai-parrot-server/ui/src/lib/nav.ts` | MODIFY | `    path: "/admin/home",` | `nav.ts:37` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/Topbar.svelte` | MODIFY | `    <span class="text-muted-foreground text-sm" data-testid="topbar-identity">{identity}</span>` | `Topbar.svelte:32` | 1 |
| `packages/ai-parrot-server/ui/src/lib/router.test.ts` | MODIFY | `  describe("isInAppPath", () => {` | `router.test.ts:183` | 1 |
| `packages/ai-parrot-server/src/parrot/server/ui/serving.py` | MODIFY | `SPA_SECTIONS: tuple[str, ...] = ("/login", "/agents")` | `serving.py:39` | 1 |
| `packages/ai-parrot-server/tests/test_admin_ui_serving.py` | MODIFY | `        "path", ["/", "/login", "/agents", "/agents/helpdesk/chat", "/admin/home"]` | `test_admin_ui_serving.py:68` | 1 |
| `packages/ai-parrot-server/tests/test_admin_ui_serving.py` | MODIFY | `        for pattern in ("/admin", "/admin/*", "/login", "/agents", "/agents/*", "/ui/assets/*"):` | `test_admin_ui_serving.py:192` | 1 |
| `packages/ai-parrot-server/pyproject.toml` | MODIFY | `    "ai-parrot-server[scheduler,mcp,a2a,autonomous,comm-center]",` | `pyproject.toml:98` | 1 |
| `packages/ai-parrot-server/pyproject.toml` | MODIFY | `all = [` | `pyproject.toml:97` | 1 |
| `uv.lock` (root) | MODIFY (regenerate with `uv lock`) | `name = "navigator-auth"` | `uv.lock:9689` | 1 |
| `docs/admin-ui.md` | MODIFY | ``- Login: `POST /api/v1/login` with a `BasicAuth` username/password form.`` | `admin-ui.md:44` | 1 |
| `docs/admin-ui.md` | MODIFY | ``- **Login**: set `AUTHENTICATION_BACKENDS=navigator_auth.backends.BasicAuth` `` | `admin-ui.md:221` | 1 |
| `docs/examples/passkey.settings.example` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/autonomous/admin.py` | MODIFY | `                       placeholder="Enter your username" autocomplete="username">` | `admin.py:224` | 1 |
| `packages/ai-parrot-server/src/parrot/autonomous/admin.py` | MODIFY | `                        'X-Auth-Method': 'BasicAuth'` | `admin.py:324` | 1 |
| `packages/ai-parrot-server/tests/test_autonomous_admin_page.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/test_passkey_packaging.py` | CREATE (added at /sdd-task, TASK-4905) | — | — | — |
| `packages/ai-parrot-server/tests/test_passkey_settings_example.py` | CREATE (added at /sdd-task, TASK-4906) | — | — | — |
| `packages/ai-parrot-server/tests/ui/test_vitest_passkey_webauthn.py` | CREATE (added at /sdd-task, TASK-4898) | — | — | — |
| `packages/ai-parrot-server/tests/ui/test_vitest_passkey_api.py` | CREATE (added at /sdd-task, TASK-4899) | — | — | — |
| `packages/ai-parrot-server/tests/ui/test_vitest_auth_store.py` | CREATE (added at /sdd-task, TASK-4900) | — | — | — |
| `packages/ai-parrot-server/tests/ui/test_vitest_passkey_sign_in.py` | CREATE (added at /sdd-task, TASK-4901) | — | — | — |
| `packages/ai-parrot-server/tests/ui/test_vitest_account_security.py` | CREATE (added at /sdd-task, TASK-4902) | — | — | — |
| `packages/ai-parrot-server/tests/ui/test_vitest_account_navigation.py` | CREATE (added at /sdd-task, TASK-4903) | — | — | — |

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated implementation may only express a
> decision already recorded here and in the TASK's implementation blocks.

### Patterns to Follow

- **Svelte 5 runes only** (`$state`, `$derived`, `$props`, `$effect`); `$lib` imports; vendored shadcn
  primitives; Tailwind 4 utilities; `data-testid` on interactive elements the tests assert on
  (`passkey-signin`, `topbar-identity`, `topbar-auth-badge`, `passkey-list`, `passkey-add`).
- **Transport split (§2)**: bare `axios` for `login/options` and the passkey `POST /api/v1/login`
  (mirror `Login.svelte:34-57`'s comment and pattern, including `withCredentials:
  config.apiWithCredentials` and `${config.apiBaseUrl}` prefixing); `apiClient` for everything that
  needs the Bearer token.
- **One probe, one challenge**: `PasskeySignIn` keeps the mount-time `login/options` response and
  uses it for the conditional ceremony; the explicit button always fetches a fresh one (the previous
  challenge was consumed or is being aborted).
- **AbortController discipline**: exactly one pending `credentials.get()` at a time; a click aborts
  the conditional controller before starting the modal request; the component aborts any pending
  controller in `onDestroy`.
- **Silent cancel**: `isUserCancelled(err)` (`NotAllowedError`, `AbortError`) → no alert; every other
  failure → the single generic message. Never branch the message on the server's reason for sign-in
  (AC14); management endpoints (enrollment, delete) DO surface `{reason}` messages, which the backend
  intends to be user-visible.
- **Envelope persistence** stays in one private helper (`_storeLoginEnvelope`) so `login()` and
  `loginWithPasskey()` cannot drift (same keys `ai_parrot_token` / `ai_parrot_session`, same
  try/catch around `localStorage`).
- **Native-first conversion**: check `typeof PublicKeyCredential.parseRequestOptionsFromJSON ===
  "function"` / `parseCreationOptionsFromJSON` / `typeof cred.toJSON === "function"` at call time
  (not module load) so tests can stub either path.
- **Python side**: aiohttp only; no new runtime import of `webauthn` in ai-parrot code (the extra
  exists for navigator-auth); `ruff`/`black` 120 cols; tests with `pytest-asyncio` + aiohttp test
  client as in `test_admin_ui_serving.py`.
- **Docs**: edit `docs/admin-ui.md` in place (Auth model + Quick start); the example file is plain
  `KEY=value`-style text matching how `navconfig` reads env (JSON string for `PASSKEY_RELYING_PARTIES`).

### Known Risks / Gotchas

- **Uniform 401 vs `apiClient` interceptor** — any passkey sign-in failure through `apiClient` would
  call `authStore.handle401()`, clear storage and rewrite `/login?next=` with the login page itself.
  Mitigation: §2 rule 1 (bare axios), AC04, M2 tests assert `apiClient` is never used for those two
  calls. *Pre-existing, out of scope*: the BasicAuth `login()` already routes through `apiClient`, so
  a `401` on a wrong password has the same latent effect today; filed as ledger `issue:ea1e3a3f2488`,
  not changed by this feature.
- **`appSections` ↔ `SPA_SECTIONS` drift** — a mismatch 404s `/account/security` on hard reload or
  lets `?next=` drop it. Mitigation: M6 and M7 land in the same PR; AC08; both files' comments already
  say "MUST match".
- **Relying party is the browser `Origin`** — `pnpm dev` (`http://localhost:5173`) and the backend
  origin (`http://localhost:5000`) are different RPs; credentials enrolled on one are invisible on the
  other. Mitigation: documented example lists both dev origins with `rp_id: "localhost"`; the
  security page's operator hint names `PASSKEY_RELYING_PARTIES`.
- **Probe challenge expiry** — the mount-time challenge expires after `PASSKEY_CHALLENGE_TTL` (300 s);
  an autofill pick after that yields the uniform 401 → generic message; the button path fetches a
  fresh challenge. Accepted; documented in the component comment.
- **Rate limit (`PASSKEY_LOGIN_OPTIONS_RATE`)** — each login-page load spends one `login/options`
  call. With the limiter on, the probe may 429 → UI hides passkeys for that address. Documented;
  operators are told to leave it 0 behind a proxy (upstream guidance).
- **`extractServerMessage` ignores `{reason}`** — passkey 4xx bodies use `reason`; `passkeyErrorMessage`
  must read it first or every error degrades to `HTTP 4xx`.
- **Browser matrix** — `parseRequestOptionsFromJSON`/`toJSON` are native in Chrome 129+, Safari 18+,
  Firefox 119+; older browsers take the fallback. `isConditionalMediationAvailable` missing ⇒ button
  only. `credentials.create()` fallback must also convert `user.id` and `excludeCredentials[].id`.
- **Two concurrent WebAuthn requests reject** — the explicit click must abort the conditional request
  first (upstream `login.html` does the same); covered by M4 tests.
- **jsdom has no WebAuthn** — tests must stub `PublicKeyCredential`/`navigator.credentials` per file;
  do not add a global stub to `vitest-setup.ts` or the "unsupported browser" branch becomes untestable.
- **Inline admin page duplicates the vanilla ceremony** — accepted (no bundler there); keep the block
  a verbatim port of upstream `login.html` so behaviour stays aligned; the pytest smoke test guards
  its presence, not its behaviour (no browser in CI).
- **`uv.lock` is behind the installed venv** — the lock pins `navigator-auth==0.28.7` with no `webauthn`
  entry while the venv has 0.28.9 (installed ad hoc). A `uv sync` would silently remove `PasskeyAuth`;
  until M8 regenerates the lock and the extra is installed, enabling `PasskeyAuth` in
  `AUTHENTICATION_BACKENDS` stops the server at startup with `ConfigError` (also raised when
  `PASSKEY_RELYING_PARTIES` is empty). Both failure modes are documented in `docs/admin-ui.md` (S1, S12).
- **Redis ≥ 6.2 (`GETDEL`)** — backend requirement for the challenge store; documented only.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-auth[passkey]` | `>=0.28.9` | `PasskeyAuth` backend (FEAT-101) + py_webauthn (`webauthn<3,>=2.0`); new `ai-parrot-server[passkey]` extra |
| Browser WebAuthn Level 3 | native (Chrome 129+, Safari 18+, Firefox 119+) | JSON helpers; hand-written fallback for older browsers — **no npm dependency** |
| `axios` | `^1.16.1` (already in `ui/package.json`) | bare calls for the public ceremony endpoints |
| `vitest` ^4 + `@testing-library/svelte` | already present | unit tests with stubbed WebAuthn |
| Redis | `>=6.2` | navigator-auth challenge store (`GETDEL`) — documented requirement |

---

## 8. Open Questions

### Resolved (carried from the brainstorm, 2026-10-30)

- [x] Feature or hotfix, and base branch? — *Resolved in brainstorm*: feature on `dev`.
- [x] Scope: sign-in only, or also enrollment and management? — *Resolved in brainstorm*: sign-in + enrollment + management in the Admin UI; server wiring (extra, docs, example settings); sign-in only in `/autonomous/admin`. → §1 Goals G1/G2/G6/G7, M1–M9.
- [x] Sign-in UX? — *Resolved in brainstorm*: explicit button (username-first / usernameless) plus conditional UI autofill. → M4, AC02/AC03.
- [x] How does the UI decide to show passkeys? — *Resolved in brainstorm*: runtime probe of `POST /api/v1/auth/passkey/login/options` + WebAuthn capability check; no build flag. → §2, M4, AC01/AC02.
- [x] Where does credential management live? — *Resolved in brainstorm*: new `/account/security` section (adds `account` to `appSections` and `/account` to `SPA_SECTIONS`). → M5/M6/M7, AC08.
- [x] WebAuthn JSON conversion approach? — *Resolved in brainstorm*: native Level-3 helpers first, hand-written base64url fallback; no npm dependency. → M1, AC13.
- [x] Cost of the probe challenge? — *Resolved in brainstorm*: a single usernameless `login/options` call doubles as probe and conditional-UI challenge. → M4, AC02, §7.
- [x] Sidebar entry name and Topbar link? — *Resolved in brainstorm*: "Account" in the Sidebar (opens `/account/security`), and the Topbar identity links to the same page. → M6, AC07.
- [x] Surface `auth_method`/`mfa` after a passkey login? — *Resolved in brainstorm*: yes — a small "Passkey" badge (shadcn `badge`) in the Topbar when `auth_method === "passkey"`; `/account/security` also states the current session method. → M3 `authMethod`, M5, M6, AC07.
- [x] Where do example settings live? — *Resolved in brainstorm*: docs block in `docs/admin-ui.md` plus a new tracked `docs/examples/passkey.settings.example` (a commented block in `settings/settings.py` was rejected because `/settings/` is git-ignored). → M8, AC11.
- [x] Exact `headers["x-auth-method"]` value for `PasskeyAuth`? — *Resolved in brainstorm*: `"PasskeyAuth"` — the class name (`backends/abstract.py:100`, `:130`); compare lower-cased like `isBasicAuth()`. → M4, AC09.
- [x] Pin for the extra? — *Resolved in brainstorm*: `navigator-auth[passkey]>=0.28.9` explicitly. → M8, AC10.

### Unresolved

- [x] Q1. Should the pre-existing BasicAuth `login()` → `apiClient` → `handle401()` path (§7 first risk) be filed as a ledger issue for a separate fix? — *Owner: Jesus Lara*: Yes — filed as ledger `issue:ea1e3a3f2488` (bug/minor, discovered-from `spec:FEAT-772`); fixed outside this feature.

<!-- §9 ESCALATE rows, if any, are appended here as Q2… -->

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the exploration document (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.164.0) · Status: completed · Transcript: `sdd/state/FEAT-772/design_research/`
> Every cited path passed containment + existence checks (27 paths). The two factual claims that change the design were re-verified in source: `uv.lock:9689-9690` pins `navigator-auth 0.28.7` with no `webauthn` entry (S1); `vite.config.ts:84` sets `changeOrigin: true` (S10).
> Note: the brainstorm's status was `exploration` with every question resolved on 2026-10-30; the seat was run because `/sdd-spec` was invoked on it, which is the acceptance act (same precedent as FEAT-746).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Pin and lock the passkey-capable navigator-auth version (risk) | CONFIRM | Verified: `uv.lock` resolves 0.28.7 and has no `webauthn`; a `uv sync` would drop `PasskeyAuth`. M8 regenerates the lock (exclusive resource) besides the extra + pin already decided | §3 M8, AC10, §7, Worktree Strategy |
| S2 | Separate public passkey calls from the generic 401 interceptor (risk) | CONFIRM | Independently derived from `http.ts:129-141`; bare axios for `login/options` + passkey `POST /api/v1/login`, `apiClient` for Bearer calls | §2 Overview rules 1–2, AC04, M2 |
| S3 | Specify the challenge state machine for conditional vs username-first login (architecture) | CONFIRM | Backend only scopes `allowCredentials` when a username is sent; the cached usernameless challenge serves conditional UI only, a click aborts it and fetches a username-scoped one; abort on teardown | §3 M4, §7 Patterns, AC02/AC03 |
| S4 | Model the actual endpoint statuses and payloads explicitly (api) | CONFIRM | `encodeURIComponent` on credential ids, 204 without body on DELETE, trimmed 1–128 labels, `{reason}` preserved | §3 M2, §6 |
| S5 | Make cross-RP management and last-login protection visible (risk) | CONFIRM | GET lists every RP; UI shows `rp_id`, refreshes after each mutation (no optimistic removal), treats 409 as authoritative | §3 M5, AC05 |
| S6 | Exclude PasskeyAuth from generic provider rendering (testing) | CONFIRM | Already planned (`isPasskeyAuth`, lower-cased header); discovery test added | §3 M4, AC09, §4 |
| S7 | Separate explicit-support and conditional-support capability checks (architecture) | CONFIRM (substance) | `isWebAuthnSupported` vs `isConditionalMediationAvailable` are independent; test matrix covers native/fallback/no-conditional/cancel. The cited `vitest-setup.ts` / `package.json` are deliberately NOT changed (per-file stubs, no npm dep) | §3 M1/M4, §4, §7 |
| S8 | Create a contract test for the duplicated inline ceremony (risk) | CONFIRM (partial) | A pytest contract test asserting the page's passkey markers lands (M9); abort/persistence/redirect behaviour of inline JS cannot run without a browser in CI — covered by the manual check and by keeping the block a verbatim upstream port | §3 M9, §4, §7 |
| S9 | Test the new route across both SPA and aiohttp contracts (testing) | CONFIRM | `/account/security` + `/accounts` lookalike in `router.test.ts`, `App.test.ts` and `test_admin_ui_serving.py` | §3 M6/M7, §4, AC08 |
| S10 | Verify exact Origin behavior through the Vite proxy (testing) | CONFIRM (manual) | Verified `changeOrigin: true` (`vite.config.ts:84`) rewrites `Host`, not `Origin`; no browser in CI, so a documented manual integration check + both dev origins in the example settings | §4 Integration Tests, §3 M8, §7 |
| S11 | Factor one session-envelope persistence path (api) | CONFIRM | `_storeLoginEnvelope()` shared by `login()` and `loginWithPasskey()`, tested against the same storage contract | §3 M3, §4, AC03 |
| S12 | Document startup and infrastructure prerequisites (risk) | CONFIRM | Operator section covers extra install, Redis ≥ 6.2, `AUTH_SECRET_KEY`, RP JSON for prod + Vite dev, and the `ConfigError` startup failure modes | §3 M8, AC11, §7 |

Summary: **12** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for this spec (`feat-FEAT-772-passkey-support`, created from `origin/dev` by the implementing lane); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edges = imports; modules without an edge run concurrently):
  - M2 → M1 (`PublicKeyCredentialJSON` type) · M3 → M2 (`postPasskeyLogin`) · M4 → M1, M2, M3 · M5 → M1, M2, M3 (`authStore.authMethod`) · M6 → M5 (route lazy-imports `pages/account/Security.svelte`), M3 (badge).
  - Independent from day one: M1, M7, M8, M9 (no code edge to any UI module). M7 and M6 must both be merged before `/account/security` survives a hard reload — same PR, no import edge.
- **Shared files** (their tasks are serialized): `ui/src/lib/config.ts` (M2 adds `passkeyApiPrefix`/`accountSecurityPath`; M6 adds `"account"` to `appSections`); `ui/src/lib/stores/auth.svelte.ts` + `auth.test.ts` (M3 only); `ui/src/pages/Login.svelte` + `Login.test.ts` (M4 only); `docs/admin-ui.md` (M8 only); `packages/ai-parrot-server/pyproject.toml` (M8 only).
- **Exclusive resources** (`parallel: false`): M8's `uv lock` regeneration of the root `uv.lock` (lockfile mutation; run in the feature worktree, never `uv sync` there — see `worktree-management.md`). No migration or compiled-extension step. (`ui/package.json` is NOT touched; `pnpm build` runs in the merge tier only.)
- **Cross-feature dependencies**: none known. Check for in-flight specs editing `App.svelte`'s route table, `nav.ts`, `Topbar.svelte` or `serving.py` before `/sdd-task` (FEAT-468/475/476 follow-ups are merged).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.2 | 2026-10-30 | Jesus Lara / Claude (Opus 5.5) | Approved; Q1 resolved (ledger `issue:ea1e3a3f2488`). /sdd-task: M8 split into packaging (TASK-4905, exclusive) and docs (TASK-4906); two guard tests added to the Validation Contract (`test_passkey_packaging.py`, `test_passkey_settings_example.py`); vitest files wrapped in pytest (`tests/ui/test_vitest_*.py`, FEAT-593 convention) |
| 0.1 | 2026-10-30 | Jesus Lara / Claude (Fable 5.1) | Initial draft from the brainstorm (Option A, 12 resolved questions carried); transport split (bare axios vs apiClient) derived from `http.ts` interceptor; codex design research folded (12 confirm / 0 reject / 0 escalate — `uv.lock` regeneration and Vite-origin manual check added) |
