# TASK-2527: Admin UI core runtime — Router, AuthStore, API client

**Feature**: FEAT-468 — UI Server Backend — Embedded Admin UI Foundation
**Spec**: `sdd/specs/ui-server-backend.spec.md`
**Status**: pending
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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
