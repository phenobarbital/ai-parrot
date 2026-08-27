# TASK-2527: Admin UI core runtime — Router, AuthStore, API client

**Feature**: FEAT-468 — UI Server Backend — Embedded Admin UI Foundation
**Spec**: `sdd/specs/ui-server-backend.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2525
**Assigned-to**: unassigned

---

## Context

Spec §2 New Public Interfaces (TS side) + §3 Module 4 (runtime part). The
three rune-class pillars every page depends on: the hand-rolled history
router, the auth store, and the API client layer adapted from
navigator-frontend-next.

---

## Scope

- `ui/src/lib/router.svelte.ts` — hand-rolled ~100-line history-mode
  `Router` rune class (svelte5-structural): `path = $state(...)`,
  `navigate(to)`, popstate handling, route table with lazy page components,
  `guard()` redirecting to the login route with `?next=<intended>` when
  `AuthStore` has no token. Base-path aware (`/admin`).
- `ui/src/lib/stores/auth.svelte.ts` — `AuthStore` rune class: `token`,
  `user` from `localStorage` keys **`ai_parrot_token`** /
  **`ai_parrot_session`**; `login(username, password)` → `POST
  /api/v1/login` with header `X-Auth-Method: BasicAuth`, stores token +
  user payload; `logout()` → `GET /api/v1/logout` + clear storage;
  `handle401()` → clear + route to login preserving `next`.
- `ui/src/lib/stores/theme.svelte.ts` — `ThemeStore` adapted from the
  corporate one (localStorage-persisted, `.dark` class / `data-theme`).
- `ui/src/lib/api/` — copy + adapt `http.ts` (axios wrapper: `ApiError`,
  `registerInterceptors`, `createApiClient`) and `auth-headers.ts` from
  navigator-frontend-next; wire a 401 interceptor to `AuthStore.handle401`;
  `config.ts` reads `import.meta.env` (no `$env/*`).
- Vitest suites for Router (navigate/guard/back-forward/next-param) and
  AuthStore (login stores token, 401 clears, logout).

**NOT in scope**: Login page and layout components (TASK-2528), pages.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/router.svelte.ts` | CREATE | Router rune class |
| `packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts` | CREATE | AuthStore |
| `packages/ai-parrot-server/ui/src/lib/stores/theme.svelte.ts` | CREATE | ThemeStore (adapted copy) |
| `packages/ai-parrot-server/ui/src/lib/api/{http.ts,auth-headers.ts,config.ts}` | CREATE | adapted copies |
| `packages/ai-parrot-server/ui/src/lib/{router,stores,api}/*.test.ts` | CREATE | vitest suites |

---

## Codebase Contract (Anti-Hallucination)

### Backend API contract (verified)
```text
POST /api/v1/login    — navigator_auth/auth.py:398 (route :602). JSON body,
                        iterates backends; BasicAuth selected via header
                        X-Auth-Method: BasicAuth (precedent:
                        parrot/autonomous/admin.py:394-398 inline page).
                        Returns JSON userdata + sets session cookie.
GET  /api/v1/logout   — auth.py:278 (route :603)
GET/POST /api/v1/auth/methods — auth.py:626-638 (consumed in TASK-2528)
GET  /api/v1/user/session     — auth.py:617 (session introspection)
```

### localStorage contract (verified — must match formdesigner)
```javascript
// packages/parrot-formdesigner/src/parrot_formdesigner/ui/templates.py:151-157,174-178
localStorage.getItem('ai_parrot_token')     // Bearer token
localStorage.getItem('ai_parrot_session')   // user payload
// on 401: remove both, redirect to /admin (the SPA login)
```

### Copy-in sources (verified in /home/jesuslara/proyectos/navigator-frontend-next)
- `src/lib/api/http.ts` — `class ApiError` (codes network|timeout|server|
  auth|unknown), `safeRaw()` strips Authorization before surfacing errors,
  `extractServerMessage()`, `registerInterceptors()`, `createApiClient(baseURL?)`,
  `createApiClientWithToken(token)`; test `http.test.ts`.
- `src/lib/api/auth-headers.ts` — `getAuthHeaders()` reading
  `config.tokenStorageKey` from localStorage.
- `src/lib/config.ts` — env-driven config object; ONLY SvelteKit coupling
  is `$env/dynamic/public` → replace with `import.meta.env`.
- `src/lib/stores/theme.svelte.ts` — `class ThemeStore` →
  `export const themeStore = new ThemeStore()` (96 lines, cleanest rune-class
  exemplar; strip its cookie/SSR sync — SPA is client-only).
- `src/lib/stores/auth.svelte.ts` — corporate rune AuthStore (reference for
  shape; storage keys DIFFER — use `ai_parrot_token`, not the corporate key).
- `src/lib/navauth/storage.ts` (`AuthStorage`), `providers/basic.ts` —
  reference for the login call shape.
- Skill doc copied by TASK-2525 into `ui/docs/svelte5-structural/`.

### Does NOT Exist
- ~~a router library in the project~~ — hand-rolled per resolved decision;
  do NOT add `svelte-spa-router`/`tinro`.
- ~~`$app/navigation`, `$app/environment`, `$env/dynamic/public`~~ — no
  SvelteKit; copied code importing these MUST be adapted.
- ~~an HTML login page on the server~~ — `/api/v1/login` is JSON-only; the
  SPA renders the form (TASK-2528).
- ~~cookie-based API auth from the SPA~~ — navigator-auth sets a session
  cookie, but the SPA MUST use `Authorization: Bearer` (formdesigner
  compatibility); do not rely on the cookie.

---

## Implementation Notes

### Key Constraints
- Router: intercept same-origin `<a>` clicks OR expose `navigate()` only —
  keep it ~100 lines; lazy `import()` per route for code-splitting.
- All three stores are classes with `$state` fields exported as singletons
  (`export const router = new Router(...)`) — the corporate pattern.
- Storage access wrapped in try/catch (private mode).
- `?next=` must be validated as an in-app path (starts with `/admin`) to
  avoid open-redirect.

### References in Codebase
- Spec §2 New Public Interfaces — Router/AuthStore signatures.

---

## Acceptance Criteria

- [ ] Router vitest suite passes: navigate updates `path` + history;
  popstate restores; guard redirects unauthenticated to login with `?next=`;
  next validated in-app.
- [ ] AuthStore vitest suite passes: `login()` POSTs with
  `X-Auth-Method: BasicAuth` (mocked), stores `ai_parrot_token` +
  `ai_parrot_session`; 401 interceptor clears both and routes to login;
  `logout()` clears storage.
- [ ] No `$app/*` / `$env/*` imports; `pnpm test` green; `pnpm build` green.

---

## Test Specification

```typescript
// ui/src/lib/router.test.ts
describe('Router', () => {
  it('navigates and updates history');
  it('restores on popstate');
  it('guard redirects to login with next param');
  it('rejects external next targets');
});
// ui/src/lib/stores/auth.test.ts
describe('AuthStore', () => {
  it('login stores ai_parrot_token and user payload');
  it('handle401 clears storage and preserves intended route');
  it('logout clears storage');
});
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2525 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/ui-server-backend.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (resumed)
**Date**: 2026-08-27
**Notes**:
- `router.svelte.ts` — `Router` rune class (~95 lines): `path = $state(...)`,
  `navigate(to, {replace})`, popstate listener, `match()`, `guard()`.
  `guard()` reads the token directly from `localStorage` (not from
  `AuthStore`) so `router.svelte.ts` has zero dependency on
  `stores/auth.svelte.ts` — this breaks what would otherwise be a 3-way
  `router -> auth -> http -> router` import cycle down to the one
  intentional 2-way `auth <-> http` cycle described below. `isInAppPath()`
  exported for reuse by `AuthStore.handle401()` and tests; an untrusted/
  external `path` passed to `guard()` falls back to `config.basePath`
  instead of being embedded in `?next=`.
- `stores/auth.svelte.ts` — `AuthStore` rune class: `token`/`user` seeded
  from `localStorage` (`ai_parrot_token`/`ai_parrot_session`) at
  construction; `login()` → `POST /api/v1/login` with header
  `X-Auth-Method: BasicAuth` (verified against
  `navigator_auth.auth.AuthHandler.api_login`/`get_auth_backend` and the
  `parrot/autonomous/admin.py` inline admin page), stores `data.token` +
  the full `data` payload; `logout()` → `GET /api/v1/logout` (best-effort;
  storage cleared unconditionally in `finally`); `handle401()` clears
  storage and calls `router.navigate()` preserving `?next=`.
- `stores/theme.svelte.ts` — `ThemeStore` adapted from the source: cookie/
  SSR sync stripped (client-only SPA, per contract), theme set trimmed to
  `["light", "dark"]` (only those two theme CSS files were vendored by
  TASK-2525 — midnight/warm are explicitly optional and absent).
- `api/http.ts` — `ApiError`, `safeRaw`, `extractServerMessage`,
  `registerInterceptors`, `createApiClient` copied from the source with
  the SvelteKit `browser`/`$env` couplings removed (SPA has no SSR) and
  the 401 branch calling `authStore.handle401()` instead of a raw
  `localStorage`/`window.location` redirect, per this task's own Scope.
  `createApiClientWithToken` (embed/iframe token-only client) was
  intentionally NOT copied — no embed/iframe use case exists in the Admin
  UI scope.
- `api/auth-headers.ts` — `getAuthHeaders()` copied with the same
  SvelteKit-coupling removal; simplified to read the token as a raw
  string (matches `admin.py`'s `localStorage.setItem('ai_parrot_token',
  data.token)`) rather than the source's JSON-blob-with-fallback parsing,
  since `http.ts`/`auth.svelte.ts` never store a JSON blob under that key.
- **Circular import, by design**: `http.ts` imports `authStore` from
  `stores/auth.svelte.ts` (used only inside the 401 interceptor
  callback), and `auth.svelte.ts` imports `apiClient` from `http.ts`
  (used only inside `login()`/`logout()` method bodies) — neither module
  touches the other's export at module-evaluation time, so the cycle
  resolves safely under both Vite (`pnpm build`) and Vitest (`pnpm test`,
  including a dedicated `handle401()` test asserting the full
  clear-storage-then-navigate flow through the live circular binding).
- Vitest suites: `router.test.ts` (5 tests — navigate/popstate/guard-
  redirects-with-next/guard-allows-with-token/rejects-external-next),
  `stores/auth.test.ts` (5 tests — login stores token+session, login
  surfaces server error, logout clears storage + calls the endpoint,
  logout clears storage even when the network call fails, handle401
  clears+redirects), `api/http.test.ts` (8 tests — `extractServerMessage`
  adapted verbatim from the source's own `http.test.ts`, logic unchanged).
- `pnpm test` — 19/19 passed (4 files, including the pre-existing
  `App.test.ts`). `pnpm build` (now `pnpm generate && vite build`) green.
  `grep -rn '\$app/\|\$env/' src/` clean (verified twice — once after
  writing the code, once more after rewording explanatory docstring
  comments that had contained the literal strings `$app/environment` /
  `$env/dynamic/public` in prose, which would have false-positived a
  literal grep despite not being real imports).
- Added `axios` (`^1.16.1`, matching the resolved version installed in
  the source repo) as a new `dependencies` entry in `ui/package.json`.

**Deviations from spec**:
- `createApiClientWithToken` from the source `http.ts` was not copied —
  no embed/iframe token-only client use case in the Admin UI's scope; the
  task's Scope only lists `ApiError`, `registerInterceptors`,
  `createApiClient` explicitly.
- `getAuthHeaders()`/token storage simplified to a raw string rather than
  the source's JSON-blob-with-fallback parsing, since this repo's
  `ai_parrot_token` key (per the verified localStorage contract) always
  holds the raw token, never a JSON blob.
- `ThemeStore` limited to `light`/`dark` (source supports `light`/`dark`/
  `midnight`/`warm`) — mechanical consequence of TASK-2525 only vendoring
  those two theme CSS files.

**Post-hoc fixes (FEAT-468 final adversarial review, 2026-08-27)**: two
critical bugs found in this task's files —
1. `Router.match()` did an EXACT string match, including the query
   string, against the route table's bare paths. `guard()`/
   `AuthStore.handle401()` redirect to `${loginPath}?next=<encoded>`,
   which never equalled the route table's bare `/admin/login` entry —
   `App.svelte`'s `resolve()` (TASK-2528) treated it as an unmatched
   route and immediately navigated away again, wiping `?next=` before
   `Login.svelte` (TASK-2528) ever mounted to read it. Fixed by stripping
   the query string before comparing in `match()`. Regression test added
   in `router.test.ts`.
2. `config.ts` defaulted `apiBaseUrl` to the ABSOLUTE
   `"http://localhost:5000"`, baked into the production bundle at
   `pnpm build` time (no `PUBLIC_API_URL` is set anywhere in the release
   pipeline — TASK-2531). Since the Admin UI is served same-origin
   (`setup_admin_ui()` mounts it on the same aiohttp app that serves
   `/api/*`), every API call — including login — went to the wrong
   origin on any real deployment. Fixed by defaulting to a relative/
   same-origin base URL (`""`). Regression test added in
   `config.test.ts`.

See commit `fix(ui-server-backend): address CRITICAL code-review findings
on FEAT-468`.
