# TASK-2593: Port shared UI pieces (pruned) and finalize offline icon collections

**Feature**: FEAT-476 — AgentChat Migration
**Spec**: `sdd/specs/agentchat-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2591
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. Navigator's chat tree imports a handful of `ui/components`
wrappers (`AppTooltip`, `AppDialog`, `AppTabs`, `AppTextEditor(.Lite)`,
…) and `@iconify/svelte` at 28 sites. This task vendors only what the
chat tree needs, drops the tangential files listed in the spec, and
pins the exact `@iconify-json/*` collections so icons work offline.

---

## Scope

- Copy `ui/src/lib/ui/components/{AppTooltip,AppDialog,AppDropdown,
  AppDropdownItem,AppSheet,AppTabs,AppTabItem,AppToggle,AppCommand,
  SimpleTable,LlmModelPicker,AppTextEditor,AppTextEditorLite}.svelte`
  and a **trimmed** `ui/components/index.ts` exporting only those.
- Copy `components/common/SessionExpiredModal.svelte`, re-pointed at
  `authStore`/`router`.
- Vendor shadcn `progress`, `separator`, `skeleton` from navigator
  `ui/internal/shadcn/ui/*` **only if absent** after FEAT-475 (check
  `ui/src/lib/ui/internal/shadcn/ui/`).
- `AppTextEditor`/`AppTextEditorLite`: wrap the `@tiptap/*` imports in
  `if (features.richEditor) await import(...)`; render a plain
  `<textarea>` fallback when off.
- **Drop list (do not port)**: `data/manual-data.ts`, `ui/components/
  {AppDatePicker,ToolCatalogPicker,SchemaFormField}`,
  `types/{agentsflow,scraping,hierarchy,crew}.ts`, `api/crew.ts`,
  `navauth/**`, `oauth/popup.ts`, navigator `stores/{auth,theme}`.
- Icons: `grep -rhoE 'icon="[a-z0-9-]+:' ` over the vendored tree
  (after TASK-2592 and this task) → list of prefixes; add
  `@iconify-json/<prefix>` for each; register in `ui/src/lib/icons.ts`
  (TASK-2591 created it); add a vitest that scans `ui/src` for icon
  names and fails on an unregistered prefix.

**NOT in scope**: `components/agents/**` (TASK-2594+).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `ui/src/lib/ui/components/*.svelte`, `index.ts` | CREATE (vendored, trimmed) | |
| `ui/src/lib/ui/internal/shadcn/ui/{progress,separator,skeleton}/` | CREATE (only if missing) | |
| `ui/src/lib/components/common/SessionExpiredModal.svelte` | CREATE (vendored) | |
| `ui/src/lib/icons.ts`, `ui/package.json` | MODIFY | final `@iconify-json/*` set |
| `ui/src/lib/icons.test.ts` | CREATE | unregistered-prefix guard |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import { features } from "$lib/features";                       // TASK-2591
import { authStore } from "$lib/stores/auth.svelte";            // ui/src/lib/stores/auth.svelte.ts:127
import { router } from "$lib/router.svelte";                    // ui/src/lib/router.svelte.ts:109
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "$lib/ui/internal/shadcn/ui/dialog/index.js";  // used by ui/src/pages/agents/AgentDetail.svelte:15-21
import { Badge } from "$lib/ui/internal/shadcn/ui/badge/index.js";   // AgentDetail.svelte:14
import { Skeleton } from "$lib/ui/internal/shadcn/ui/skeleton/index.js";  // AgentsList.svelte:31 — skeleton ALREADY exists on dev
import { Separator } from "$lib/ui/internal/shadcn/ui/separator/index.js"; // AgentDetail.svelte:22 — separator ALREADY exists on dev
```

### Existing Signatures to Use
```ts
// Admin UI shadcn set on dev: avatar, badge, button, card, dialog, input, label, select, separator, skeleton (+ FEAT-475: tabs, checkbox, switch, textarea, slider)
// navigator src/lib/ui/components/index.ts (139 lines) — exports the App* wrappers; trim to the chat subset
// navigator shadcn internals used by the chat closure: checkbox, input, label, progress, separator, skeleton, slider, textarea (spec §6 closure)
// @iconify/svelte usage in navigator: `import Icon from "@iconify/svelte"` then <Icon icon="<prefix>:<name>" />
```

### Does NOT Exist
- ~~`ui/src/lib/data/manual-data.ts`, `AppDatePicker`, `ToolCatalogPicker`, `SchemaFormField`~~ — deliberately not ported; delete imports.
- ~~`$lib/navauth/*`, `$lib/oauth/popup`~~ — not ported.
- ~~`@internationalized/date`, `@xyflow/svelte`, `@azure/msal-browser`~~ — must NOT be added; they are reached only through dropped files.
- ~~Runtime icon fetch from `api.iconify.design`~~ — forbidden (spec §5).

---

## Implementation Notes

### Key Constraints
- Prefer reuse of existing Admin UI primitives over a second copy.
- Header comment `// ai-parrot: …` on every edited vendored file.
- Keep `AppTextEditor` API identical; only the loader changes.

---

## Acceptance Criteria

- [ ] Trimmed `ui/components/index.ts` compiles; no dropped file exists under `ui/src/lib`
- [ ] `ui/src/lib/icons.test.ts` passes and `pnpm test` shows zero requests to `api.iconify.design` (spy on `fetch`)
- [ ] `pnpm build` passes; with `PUBLIC_AGENTCHAT_RICH_EDITOR=false pnpm build`, no `tiptap` chunk exists in `dist/assets`

---

## Test Specification

```ts
// ui/src/lib/icons.test.ts
import { it, expect } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { REGISTERED_PREFIXES } from "./icons";
function* walk(d: string): Generator<string> { for (const f of readdirSync(d)) { const p = join(d, f); statSync(p).isDirectory() ? yield* walk(p) : p.endsWith(".svelte") && (yield p); } }
it("every icon prefix is bundled", () => {
  const used = new Set<string>();
  for (const f of walk("src")) for (const m of readFileSync(f, "utf8").matchAll(/icon=["']([a-z0-9-]+):/g)) used.add(m[1]);
  for (const p of used) expect(REGISTERED_PREFIXES, `prefix ${p}`).toContain(p);
});
```

---

## Agent Instructions

1. Read spec §3 Module 3. 2. Confirm TASK-2591 done (and TASK-2592 if you want the prefix scan to be final; otherwise re-run the scan in TASK-2594). 3. Verify contract. 4. Index → `in-progress`. 5. Implement. 6. Verify. 7. Move to `completed/`. 8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-08-30
**Notes**: Ported 13 App* wrapper components + trimmed index.ts,
SessionExpiredModal, and the sheet/command/progress shadcn primitives
(sheet+command needed by AppSheet/AppCommand, not covered by the task's
"progress/separator/skeleton only if absent" note — separator/skeleton
already existed, sheet/command did not and had to be vendored as a
necessary dependency). Gated @tiptap/* behind features.richEditor with a
plain-textarea fallback in both editor components. Finalized
REGISTERED_PREFIXES by grepping the full navigator closure directly.
pnpm build/test (189/189)/svelte-check all clean (0 new errors).

**Deviations from spec**:
1. Vendored `ui/internal/shadcn/ui/{sheet,command}/*` (not explicitly
   named in the task's "only if absent: progress/separator/skeleton"
   line) — required because AppSheet/AppCommand (both in this task's
   explicit file list) import them and they didn't exist after FEAT-475.
   Standard shadcn-svelte primitives, no cross-cutting dependencies.
2. `ui/components/index.ts` re-exports only the 13 App* wrappers, not
   navigator's full shadcn re-export surface (139 lines) — the Admin UI's
   own shadcn primitives are imported directly from
   `$lib/ui/internal/shadcn/ui/*` by vendored code, avoiding a duplicate
   export surface (reuse-over-duplication, spec §7).
3. `svelte-check` (not `tsc`) used to verify these `.svelte` files
   actually compile, since `pnpm build`'s Vite/Rollup graph doesn't
   reach unimported files yet (nothing mounts these components until
   TASK-2594+) — confirms 0 new errors, 2 new non-blocking `$state`
   closure-capture warnings in the two editor files' plain-textarea
   fallback state (harmless: that state only matters while the flag is
   off, a build-time constant).
