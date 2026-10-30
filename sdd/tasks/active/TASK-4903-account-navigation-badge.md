# TASK-4903: `/account/security` route, "Account" nav entry, Topbar link and Passkey badge

**Feature**: FEAT-772 — Passkey (WebAuthn) sign-in, enrollment and management in the Admin UI
**Spec**: `sdd/specs/passkey-support.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4899, TASK-4900, TASK-4902
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6, G8, AC07/AC08. Makes the page from TASK-4902 reachable: a route in
`App.svelte` (`requiresAuth: true`), `"account"` in `config.appSections` (the router's first-segment
whitelist — `isInAppPath()` drops any `?next=` outside it), an **"Account"** entry in the Sidebar
"Workspace" section, the Topbar identity turned into a link, and a small **"Passkey"** badge when the
stored envelope has `auth_method === "passkey"` (decided in the brainstorm, §8 resolved). The Python
side (`SPA_SECTIONS`) is TASK-4904; both must merge before `/account/security` survives a hard reload.

---

## Scope

- `config.ts`: `appSections` gains `"account"`.
- `App.svelte`: route `{ path: "/account/security", component: () => import("./pages/account/Security.svelte"), requiresAuth: true }`.
- `nav.ts`: `{ path: "/account/security", label: "Account", icon: <24x24 stroke path>, section: "user" }` after `/agents`.
- `Topbar.svelte`: identity `<span>` → `<a>` navigating via `router.navigate(config.accountSecurityPath)`; `Badge` "Passkey".
- Tests: `router.test.ts`, `App.test.ts`, `AppShell.test.ts`.

**NOT in scope**: the page itself (TASK-4902), `serving.py` (TASK-4904), any Topbar user menu.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/ui/test_vitest_account_navigation.py` | CREATE | pytest wrapper running the vitest file(s) (validation contract accepts pytest only) |
| `packages/ai-parrot-server/ui/src/lib/config.ts` | MODIFY | `appSections` += `"account"` |
| `packages/ai-parrot-server/ui/src/App.svelte` | MODIFY | Register `/account/security` |
| `packages/ai-parrot-server/ui/src/lib/nav.ts` | MODIFY | "Account" entry (section `user`) |
| `packages/ai-parrot-server/ui/src/lib/components/Topbar.svelte` | MODIFY | Identity link + Passkey badge |
| `packages/ai-parrot-server/ui/src/lib/router.test.ts` | MODIFY | `isInAppPath` accepts `/account/security`, rejects `/accounts` |
| `packages/ai-parrot-server/ui/src/App.test.ts` | MODIFY | Guarded `/account/security` redirects with `?next=` |
| `packages/ai-parrot-server/ui/src/lib/components/AppShell.test.ts` | MODIFY | Identity link + badge |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ._vitest import run_vitest   # packages/ai-parrot-server/tests/ui/_vitest.py (run_vitest(*files) → pnpm exec vitest run, cwd ui/)
```
```ts
// Topbar.svelte already imports: config ($lib/config), router ($lib/router.svelte), Button, authStore, ThemeSwitcher
import { Badge } from "$lib/ui/internal/shadcn/ui/badge/index.js";   // badge/index.ts
// tests already import: render/fireEvent (@testing-library/svelte), vitest, apiClient, navEntries, router, authStore
```

### Existing Signatures to Use
```ts
// packages/ai-parrot-server/ui/src/lib/config.ts:62  appSections: ["login", "agents", "admin"],
// config.accountSecurityPath — added by TASK-4899 (`${basePath}/account/security`)
// packages/ai-parrot-server/ui/src/App.svelte:20  router.routes = [ ... ];  :32  "    // --- Administration ---…" comment
// packages/ai-parrot-server/ui/src/lib/nav.ts:29  export const navEntries: NavEntry[] = [ {path:"/agents",…,section:"user"}, {path:"/admin/home" (:37) …} ]
// packages/ai-parrot-server/ui/src/lib/components/Topbar.svelte:32
//   <span class="text-muted-foreground text-sm" data-testid="topbar-identity">{identity}</span>
// authStore.authMethod: string | null — TASK-4900
// router.test.ts:183 describe("isInAppPath") — two its: accepts [...] / rejects [...]
// AppShell.test.ts — beforeEach sets authStore.user = { username: "alice" }; renders AppShellHarness; "renders every nav entry" iterates navEntries
// App.test.ts:42 — "visiting a guarded route while unauthenticated preserves ?next=…" (pattern: pushState + router.path = …)
```

### Does NOT Exist
- ~~`"account"` in `appSections`~~ / ~~`/account/security` route~~ / ~~"Account" nav entry~~ — added here.
- ~~a Topbar dropdown/user menu~~ and ~~`dropdown-menu` primitive~~ — use a plain link.
- ~~`NavSection` value `"account"`~~ — sections are only `"user" | "admin"` (nav.ts:13); use `"user"`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_account_navigation.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/config.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/App.svelte", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/nav.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/Topbar.svelte", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/router.test.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/App.test.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/AppShell.test.ts", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/ui/src/lib/config.ts#config",
    "sym:packages/ai-parrot-server/ui/src/lib/nav.ts#navEntries",
    "sym:packages/ai-parrot-server/ui/src/lib/router.svelte.ts#isInAppPath",
    "sym:packages/ai-parrot-server/ui/src/lib/router.svelte.ts#Router.guard"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Edit `config.ts` `appSections` — *why*: without it `isInAppPath("/account/security")` is false and `?next=` is dropped.
2. Register the route in `App.svelte` — *why*: lazy import keeps the page out of the login bundle.
3. Add the nav entry — *why*: Sidebar is driven by the registry only.
4. Change the Topbar — *why*: G8 / AC07.
5. Extend the three tests.

### `packages/ai-parrot-server/ui/src/lib/config.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '  appSections: ["login", "agents", "admin"],' config.ts)
// REPLACE (verified: config.ts:62) with:
  appSections: ["login", "agents", "admin", "account"],
```
**Why**: the comment above it says it MUST match `serving.py` `SPA_SECTIONS` — TASK-4904 adds `/account` there.

### `packages/ai-parrot-server/ui/src/App.svelte` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '    // --- Administration -------------------------------------------------' App.svelte)
// BEFORE — insert above that comment (verified: App.svelte:32)
    // FEAT-772: user-level account pages (passkey management).
    {
      path: "/account/security",
      component: () => import("./pages/account/Security.svelte"),
      requiresAuth: true,
    },
```

### `packages/ai-parrot-server/ui/src/lib/nav.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '    path: "/admin/home",' nav.ts)
// The "/admin/home" object opens with `  {` at nav.ts:36 (its path line is :37). Insert this object right before that `  {`:
  {
    path: "/account/security",
    label: "Account",
    // FILL IN: a 24x24 stroke icon path (e.g. a shield or key) — bounded by the NavEntry.icon contract (single `d` string)
    icon: "M12 3l7 4v5c0 4.4-3 8.3-7 9-4-0.7-7-4.6-7-9V7l7-4z",
    section: "user",
  },
```

### `packages/ai-parrot-server/ui/src/lib/components/Topbar.svelte` (MODIFY)
```svelte
<!-- add to <script>: import { Badge } from "$lib/ui/internal/shadcn/ui/badge/index.js"; -->
<!-- occurrences: 1 (verified: grep -c '    <span class="text-muted-foreground text-sm" data-testid="topbar-identity">{identity}</span>' Topbar.svelte) -->
<!-- REPLACE that line (verified: Topbar.svelte:32) with: -->
    <a
      href={config.accountSecurityPath}
      class="text-muted-foreground hover:text-foreground text-sm"
      data-testid="topbar-identity"
      onclick={(event) => {
        event.preventDefault();
        router.navigate(config.accountSecurityPath);
      }}
    >
      {identity}
    </a>
    {#if authStore.authMethod === "passkey"}
      <Badge variant="secondary" data-testid="topbar-auth-badge">Passkey</Badge>
    {/if}
```
**Why**: same SPA-navigation pattern as `Sidebar.svelte` (preventDefault + `router.navigate`).

### Tests (MODIFY)
```ts
// router.test.ts — occurrences: 1 (verified: grep -c '  describe("isInAppPath", () => {' router.test.ts; :183)
//   add "/account/security" to the accepted list and "/accounts" to the rejected list.
// AppShell.test.ts — append:
  it("links the identity to /account/security and shows the Passkey badge for passkey sessions", async () => {
    authStore.user = { username: "alice", auth_method: "passkey" };
    const { getByTestId } = render(AppShellHarness);
    expect(getByTestId("topbar-identity").getAttribute("href")).toBe("/account/security");
    expect(getByTestId("topbar-auth-badge").textContent).toContain("Passkey");
  });
  // FILL IN: no badge for a BasicAuth session (beforeEach user has no auth_method)
// App.test.ts — FILL IN: unauthenticated visit to /account/security lands on /login?next=%2Faccount%2Fsecurity
//   (copy the pushState + router.path pattern from the ?next= test at App.test.ts:42)
```

### `packages/ai-parrot-server/tests/ui/test_vitest_account_navigation.py` (CREATE)
```python
"""FEAT-772 (TASK-4903): run the vitest file(s) from pytest (validation contract)."""

from ._vitest import run_vitest


def test_account_navigation_vitest() -> None:
    """/account/security route, isInAppPath, Topbar link and Passkey badge."""
    run_vitest("src/lib/router.test.ts", "src/App.test.ts", "src/lib/components/AppShell.test.ts")
```
**Why**: `check_task_graph` accepts pytest validation commands only; this is the established wrapper
pattern (`tests/ui/_vitest.py::run_vitest`, e.g. `test_vitest_suggestion_chips.py`). It skips when
`pnpm`/`node_modules` is absent.

### FILL IN checklist
- [ ] `nav.ts` icon path; bounded by NavEntry.icon (24x24 stroke)
- [ ] `AppShell.test.ts` no-badge case; `App.test.ts` guarded redirect; bounded by AC07/AC08

---

## Acceptance Criteria

- [ ] `isInAppPath("/account/security")` true, `isInAppPath("/accounts")` false (AC08)
- [ ] Unauthenticated `/account/security` → `/login?next=%2Faccount%2Fsecurity`; authenticated renders inside AppShell
- [ ] Sidebar shows "Account" in Workspace; Topbar identity links to `/account/security`; badge iff `auth_method === "passkey"` (AC07)

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_account_navigation.py -q`

---

## Test Specification

See the Tests blueprint block above (spec §4 rows for Module 6).

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
   `feat(passkey-support): TASK-4903 — <title>`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4903 passkey-support verified`
   — never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
