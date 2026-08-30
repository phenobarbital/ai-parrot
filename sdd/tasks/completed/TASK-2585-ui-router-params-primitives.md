# TASK-2585: Router `:param` routes + vendored form primitives + JsonEditor/StringListEditor widgets

**Feature**: FEAT-475 — UI Agent Management — Admin UI Agent CRUD
**Spec**: `sdd/specs/ui-agent-management.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (router extension, vendored primitives), §3 Module 3, §8
Q1 (resolved: JSON editor = validated textarea, no dependency). The
hand-rolled router only matches exact paths; the form needs
`/admin/agents/:name`, an unsaved-changes hook, and UI primitives the
FEAT-468 shell never needed.

---

## Scope

- `ui/src/lib/router.svelte.ts`: support `:param` segments in
  `RouteDefinition.path`; `match()` fills a new `params = $state<Record<string,string>>({})`;
  static routes win over param routes when both match; add
  `beforeNavigate: ((to: string) => boolean | Promise<boolean>) | null`
  consulted by `navigate()` (return false ⇒ navigation cancelled). Existing
  `router.test.ts` cases must keep passing; the `guard()` login redirect
  must bypass `beforeNavigate` (destination `config.loginPath`).
- Vendor shadcn-svelte primitives for bits-ui 2.x: `tabs`, `checkbox`,
  `switch`, `textarea`, `slider` under `ui/src/lib/ui/internal/shadcn/ui/<family>/`
  with `index.ts` barrels, semantic tokens, `cn()` — same style as the
  existing families. Byte-faithful to upstream where possible.
- `ui/src/lib/components/JsonEditor.svelte`: props `value: unknown`
  (object or array), `mode: "object" | "array" | "any"`, `label`, `hint`;
  auto-resizing textarea, live `JSON.parse`, inline error, "Format" button
  (pretty-print), emits parsed value only when valid and reports validity
  (`onvalid`/bindable `valid`).
- `ui/src/lib/components/StringListEditor.svelte`: bindable `items: string[]`;
  add (Enter or button), remove, move up/down; trims and drops blanks;
  optional `suggestions: string[]` (datalist) for tools / KB class paths.
- Vitest suites for router params/hook, JsonEditor, StringListEditor.

**NOT in scope**: the agent form itself, route table entries in `App.svelte`
(TASK-2587), API wrappers (TASK-2586).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/router.svelte.ts` | MODIFY | `:param`, `params`, `beforeNavigate` |
| `packages/ai-parrot-server/ui/src/lib/router.test.ts` | MODIFY | add param/hook cases |
| `packages/ai-parrot-server/ui/src/lib/ui/internal/shadcn/ui/{tabs,checkbox,switch,textarea,slider}/*` | CREATE | vendored primitives |
| `packages/ai-parrot-server/ui/src/lib/components/JsonEditor.svelte` (+ `.test.ts`) | CREATE | validated JSON textarea |
| `packages/ai-parrot-server/ui/src/lib/components/StringListEditor.svelte` (+ `.test.ts`) | CREATE | list-of-strings editor |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (TS)
```ts
import { config } from "$lib/config";                         // config.basePath="/admin", config.loginPath
import { router, Router, isInAppPath, type RouteDefinition } from "$lib/router.svelte";
import { cn } from "$lib/ui/internal/shadcn/utils";           // exists
import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";   // barrel style used by pages
import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";
import { render, fireEvent, waitFor } from "@testing-library/svelte";   // vitest + jsdom setup in vitest.config.ts / vitest-setup.ts
```

### Existing Signatures to Use
```ts
// packages/ai-parrot-server/ui/src/lib/router.svelte.ts (current)
export interface RouteDefinition { path: string; component: RouteComponentLoader; requiresAuth?: boolean }
class Router {
  path = $state(window.location.pathname | config.basePath);
  routes: RouteDefinition[] = [];
  navigate(to: string, { replace = false } = {}): void      // pushState/replaceState + this.path = to
  match(path = this.path): RouteDefinition | undefined      // strips "?query", exact pathname equality  ← extend
  guard(path = this.path): boolean                          // redirects to `${config.loginPath}?next=` via navigate(..., {replace:true})
}
export { Router, isInAppPath }; export const router = new Router();
// router.test.ts existing cases: navigate/popstate/guard/next round-trip/external next rejected — keep green.

// Vendored primitive style (copy from ui/src/lib/ui/internal/shadcn/ui/input/input.svelte and select/*):
//   Svelte 5 runes, `let { class: className, ...restProps } = $props()`, `cn(...)` with semantic token classes,
//   bits-ui imports like `import { Tabs as TabsPrimitive } from "bits-ui";` — bits-ui ^2.18.1 is installed.
// Conventions doc: ui/src/lib/ui/README.md; skill: ui/docs/svelte5-structural/SKILL.md
```

### Does NOT Exist
- ~~`/home/jesuslara/proyectos/navigator-frontend-next`~~ — corporate copy-in source is NOT on disk; take primitives from shadcn-svelte upstream (generator output), not from a local copy.
- ~~`svelte-spa-router`, `tinro`, SvelteKit `$app/navigation`, `beforeNavigate` from SvelteKit~~ — router is hand-rolled; the hook is ours.
- ~~`svelte-jsoneditor`, CodeMirror~~ — not dependencies (spec §8 Q1). Do not add.
- ~~`@lucide/svelte`~~ — not installed; icons are inline SVG paths (see `nav.ts`).
- ~~`Router.params`, `Router.beforeNavigate`~~ — created by this task.

---

## Implementation Notes

- Param matching: split on `/`, equal length, segment equality or
  `:name` capture; iterate static routes first (or sort by absence of `:`).
- `navigate()` becoming async (to await `beforeNavigate`) would ripple into
  `App.svelte`'s `resolve()`; keep `navigate` sync and let the hook be
  sync-or-promise: if a promise is returned, defer the push until it
  resolves true. Document the choice in a comment.
- jsdom caveat (FEAT-468 lesson): bits-ui floating primitives are awkward
  in jsdom; Tabs/Checkbox/Switch/Slider are non-floating and fine. Keep
  tests to rendering + interaction, no positioning assertions.
- Do NOT bump vite/svelte pins.

---

## Acceptance Criteria

- [ ] `/admin/agents/:name` matches `/admin/agents/helpdesk` with `router.params.name === "helpdesk"`; `/admin/agents/new` (static) wins over the param route
- [ ] `beforeNavigate` returning `false` cancels navigation; guard's login redirect is never blocked
- [ ] All previous `router.test.ts` cases pass unchanged
- [ ] Five primitive families importable via `$lib/ui/internal/shadcn/ui/<family>/index.js`
- [ ] `JsonEditor`: malformed → inline error + invalid; valid → parsed value emitted; Format pretty-prints; mode enforces object/array
- [ ] `StringListEditor`: add/remove/reorder; blanks dropped; suggestions rendered
- [ ] `pnpm test` green; `pnpm build` succeeds

---

## Test Specification

```ts
// router.test.ts (add)
it("matches :param routes and exposes params", ...)
it("prefers a static route over a param route", ...)
it("beforeNavigate=false cancels navigation", ...)
it("guard redirect bypasses beforeNavigate", ...)
// JsonEditor.test.ts / StringListEditor.test.ts per scope bullets
```

---

## Agent Instructions

1. Read spec §2 Overview, §3 Module 3, §6 (TS block), §7, §8 Q1.
2. Verify the router file before editing; keep existing tests green.
3. Implement + tests (`cd packages/ai-parrot-server/ui && pnpm install --frozen-lockfile && pnpm test`).
4. Move to `sdd/tasks/completed/`, update index → `done`, fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-30
**Notes**: Extended `router.svelte.ts` with `:param` segment matching
(`matchRoute()`/`segments()` helpers), `params = $state<Record<string,
string>>({})` populated by `match()`, and a `beforeNavigate` hook consulted
by `navigate()` (sync-or-promise return; `navigate()` itself stays sync —
a promise defers the history push until it resolves `true`, a rejection
cancels). `match()` checks static routes before param routes so
`/admin/agents/new` always wins over `/admin/agents/:name`. `guard()`'s
login redirect now calls a new private `_commit()` directly, bypassing
`beforeNavigate` entirely, so the unsaved-changes hook can never block a
forced auth redirect. Added 8 new `router.test.ts` cases (params captured,
static-over-param precedence, segment-count mismatch, URI-decoding,
beforeNavigate true/false, async beforeNavigate, guard-bypasses-hook); all
6 pre-existing cases still pass unchanged.

Vendored `tabs`, `checkbox`, `switch`, `textarea`, `slider` under
`ui/src/lib/ui/internal/shadcn/ui/<family>/` from the shadcn-svelte/bits-ui
2.x generator pattern (verified against the installed `bits-ui@2.19.0`
type declarations in `node_modules`, since the corporate copy-in source is
not on disk) — same `cn()`/`data-slot`/`WithElementRef`/
`WithoutChildrenOrChild` style as the existing `input`/`switch`/`dialog`
families. `slider.svelte` required an explicit `type = "single"` default
(bits-ui 2.x's Slider is a discriminated union on `type: "single" |
"multiple"`; without it the primitive assumed array-valued `value` and
crashed) — not in the task's contract, discovered while building the
smoke test. Added `vendored-primitives.test.ts` (5 tests, one per family,
including a `TabsHarness.test.svelte` for the compound Tabs
Root/List/Trigger/Content) with a locally-scoped `ResizeObserver` stub
(jsdom lacks one; bits-ui's Slider needs it) — the stub is local to this
test file, not added to the shared `vitest-setup.ts`.

Added `JsonEditor.svelte` (validated textarea; `value` bindable and only
updated on valid JSON matching `mode`; `valid` bindable + `onvalid`
callback; Format button pretty-prints) and `StringListEditor.svelte`
(bindable `items: string[]`; add via button or Enter; remove/reorder;
blanks trimmed/dropped; optional `suggestions` datalist) with 7 tests
each — object/array/any mode enforcement, malformed-JSON error state,
Format button, add/remove/reorder, blank-trimming, suggestions rendering.

Full UI suite (`pnpm test`): 16 files, 86 tests passed (59 pre-existing +
27 new), 0 failures. `pnpm build` succeeds (772 modules, no type/compile
errors).

Fixed a state-tracking bug from the two prior tasks in this feature while
verifying `git status` before this commit: TASK-2583's and TASK-2584's
"move to completed/" steps staged the new `sdd/tasks/completed/*.md` path
but never staged the deletion at the old `sdd/tasks/active/*.md` path
(`git add <new-path>` does not implicitly stage an absent old path) — both
task files were tracked in two places simultaneously. Fixed in a separate
commit (`sdd: fix stale active/ task file entries for TASK-2583/TASK-2584`)
before this task's own commit.

**Deviations from spec**: none — the `type="single"` Slider default is an
implementation necessity for a working component, not a deviation from
the described props/behavior.
