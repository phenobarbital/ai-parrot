# TASK-2528: Admin UI shell — login page and app layout

**Feature**: FEAT-468 — UI Server Backend — Embedded Admin UI Foundation
**Spec**: `sdd/specs/ui-server-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2527
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (UI half, user-facing) + §3 Module 4 (shell part). The
visible foundation: the login page (BasicAuth + discovered SSO providers)
and the persistent authenticated layout (sidebar, topbar, theme switcher,
logout) that every module renders inside.

---

## Scope

- `Login.svelte` page (route `/admin/login`, theme-aware, ShadCN tokens):
  - Username/password form → `AuthStore.login()`; inline error from the
    JSON error of `/api/v1/login`; loading state; show-password toggle.
  - Provider buttons rendered dynamically from `GET /api/v1/auth/methods`
    (adapt `ProviderButtons.svelte` + `providers/registry.ts` shapes from
    navauth); BasicAuth form always visible even if discovery fails.
  - Honors `?next=` (validated in-app) after successful login.
- App shell (`AppShell.svelte` + parts):
  - Sidebar navigation driven by a **navigation registry** module
    (`ui/src/lib/nav.ts`: array of `{path, label, icon}`) so future module
    specs append entries — Home, Dashboard, Agents for now.
  - Topbar: user identity (name/email from stored session payload), theme
    switcher (ThemeStore), logout button (`AuthStore.logout()` → login).
  - Renders the routed page in the content area; guard applied — all
    non-login routes require auth.
- Session-expiry UX: 401 during any page fetch lands back on login with
  `?next=` (already wired in TASK-2527 — verify end-to-end here).
- Placeholder routed pages for Home/Dashboard/Agents (replaced by
  TASK-2529/2530) so the shell is navigable.
- Vitest component tests for Login (submit, error, providers) and shell
  (nav renders registry, logout clears).

**NOT in scope**: real Home/Dashboard content (TASK-2529), agents module
(TASK-2530).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/pages/Login.svelte` | CREATE | login page |
| `packages/ai-parrot-server/ui/src/lib/components/ProviderButtons.svelte` | CREATE | adapted from navauth |
| `packages/ai-parrot-server/ui/src/lib/components/{AppShell,Sidebar,Topbar,ThemeSwitcher}.svelte` | CREATE | layout |
| `packages/ai-parrot-server/ui/src/lib/nav.ts` | CREATE | navigation registry |
| `packages/ai-parrot-server/ui/src/pages/{Home,Dashboard,Agents}.svelte` | CREATE | placeholders |
| `packages/ai-parrot-server/ui/src/App.svelte` | MODIFY | wire router + shell + login route |
| corresponding `*.test.ts` | CREATE | vitest |

---

## Codebase Contract (Anti-Hallucination)

### Backend API contract (verified)
```text
GET/POST /api/v1/auth/methods — navigator_auth/auth.py:626-638 — lists
    enabled auth backends (shape: inspect at runtime/test with mock; do not
    hardcode provider ids beyond BasicAuth).
POST /api/v1/login — auth.py:398 — JSON error body on failure (surface its
    message via ApiError.extractServerMessage from http.ts).
GET /api/v1/logout — auth.py:278.
```

### Copy-in sources (verified in /home/jesuslara/proyectos/navigator-frontend-next)
- `src/lib/navauth/components/LoginForm.svelte`, `ProviderButtons.svelte`,
  `AuthGuard.svelte` — adapt (SvelteKit imports must go; corporate SSO
  popup flow via `src/lib/oauth/popup.ts` may be copied if a provider needs
  it, else render provider buttons as plain links/disabled with a tooltip).
- `src/routes/login/+page.svelte` (~455 lines) — visual/UX reference
  ($state username/password/error/loading/showPassword).
- `src/components/{LoadingSpinner,ThemeSwitcher}.svelte` — small standalone
  copies.
- Vendored primitives available after TASK-2525: button, card, input,
  label, badge, separator, skeleton, select, dialog, avatar + `cn()`.
- Conventions: `src/lib/ui/README.md` (copied in TASK-2525) — semantic
  tokens in primitives, scale tokens in pages/wrappers.

### Runtime contract from prior tasks (verify before use)
```typescript
// TASK-2527 deliverables — confirm exact exports before importing:
import { router } from '$lib/router.svelte';        // Router singleton
import { authStore } from '$lib/stores/auth.svelte'; // AuthStore singleton
import { themeStore } from '$lib/stores/theme.svelte';
```

### Does NOT Exist
- ~~a server-rendered login page~~ — the SPA owns login entirely.
- ~~guaranteed SSO providers~~ — discovery may return only BasicAuth (or
  fail); the form must stand alone.
- ~~corporate `SessionExpiredModal` in this project~~ — expiry lands on the
  login page with `?next=`; do not build a modal in this task.
- ~~`$app/*`, `$env/*`~~ — no SvelteKit.

---

## Implementation Notes

### Key Constraints
- svelte5-structural: structural composition (base components + snippets),
  no deep prop drilling; state in the singleton stores.
- All strings user-visible in English (framework OSS surface).
- Theme: `.dark` class strategy from the copied token chain
  (`@custom-variant dark (&:where(.dark, .dark *))`).
- Keep the nav registry data-only (no components in it) so future specs
  append entries without touching the shell.

### References in Codebase
- Spec §2 Overview "UI half" — behavior source of truth.
- `sdd/proposals/ui-agent-management.brainstorm.md` — sticky-actions and
  error-indicator UX conventions (apply where natural, full use in next spec).

---

## Acceptance Criteria

- [ ] Unauthenticated visit to any route renders Login; successful login
  (mocked) lands on `?next=` target or Home.
- [ ] Login failure shows the server's JSON error message inline.
- [ ] Provider buttons render from mocked `/api/v1/auth/methods`; discovery
  failure still shows the BasicAuth form.
- [ ] Shell shows sidebar (from nav registry), topbar with user identity,
  working theme switcher, logout → login.
- [ ] `pnpm test` green (Login + shell suites); `pnpm build` green.

---

## Test Specification

```typescript
// ui/src/pages/Login.test.ts
describe('Login', () => {
  it('submits credentials and navigates to next');
  it('renders server error message on failure');
  it('renders discovered providers; falls back to form alone');
});
// ui/src/lib/components/AppShell.test.ts
describe('AppShell', () => {
  it('renders nav entries from registry');
  it('logout clears auth and shows login');
});
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2527 in `sdd/tasks/completed/`
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
