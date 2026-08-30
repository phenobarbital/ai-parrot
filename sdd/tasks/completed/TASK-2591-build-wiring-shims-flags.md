# TASK-2591: Build wiring — deps, SvelteKit shims, feature flags, config, WS stub, offline icons

**Feature**: FEAT-476 — AgentChat Migration
**Spec**: `sdd/specs/agentchat-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none *(FEAT-475 must already be merged into `dev` — spec Worktree Strategy)*
**Assigned-to**: unassigned

---

## Context

Spec §2 "Shims", "Feature flags", "Icons"; §3 Module 1. The Admin UI is
a plain Vite + Svelte 5 SPA (FEAT-468). Navigator's chat tree imports
`$app/environment`, `$app/navigation`, `$env/dynamic/public` (21 sites)
and `wsService` (`/ws/userinfo`, which does not exist in
`ai-parrot-server`). This task lays every foundation the vendored code
will rely on so later tasks are pure copy-in.

---

## Scope

- `ui/package.json`: add runtime deps from spec §7 (`marked`,
  `dompurify`, `highlight.js`, `uuid`, `dexie`, `@iconify/svelte`,
  `echarts`, `layerchart` pinned `2.0.0-next.64`, `d3-scale`, `d3-geo`,
  `topojson-client`, `world-atlas`, `leaflet`, `@types/geojson`,
  `livekit-client`, `@tiptap/core`, `@tiptap/starter-kit`,
  `@tiptap/extension-text-align`, `@tiptap/extension-text-style`,
  `@tiptap/extension-typography`) and placeholder `@iconify-json/*`
  entries (the definitive prefix list is finalized in TASK-2593);
  `pnpm install` updates the lockfile.
- `ui/src/lib/shims/environment.ts` (`export const browser = true`),
  `ui/src/lib/shims/navigation.ts` (`goto(path, {replaceState}) →
  router.navigate(path, {replace})`), `ui/src/lib/shims/env-public.ts`
  (`export const env = import.meta.env`).
- `ui/vite.config.ts`: `resolve.alias` for `$app/environment`,
  `$app/navigation`, `$env/dynamic/public` → the shims; `loadEnv` +
  `define` for `__AGENTCHAT_VOICE__`, `__AGENTCHAT_AVATAR__`,
  `__AGENTCHAT_MAPS__`, `__AGENTCHAT_CHARTS__`, `__AGENTCHAT_CANVAS__`,
  `__AGENTCHAT_INFOGRAPHIC__`, `__AGENTCHAT_DATASETS__`,
  `__AGENTCHAT_RICH_EDITOR__` from `PUBLIC_AGENTCHAT_*` (default
  `true`; `"false"`/`"0"` → false). Mirror the defines in
  `vitest.config.ts` and declare them in `src/vite-env.d.ts` (or
  `app.d.ts`).
- `ui/src/lib/features.ts`: `export const features = Object.freeze({
  voice, avatar, maps, charts, canvas, infographic, datasets,
  richEditor })` read from the defines.
- `ui/src/lib/config.ts`: add the agent fields navigator's ported code
  reads (`agentsChatPath: "/api/v1/agents/chat"`, `agentsVoicePath`,
  `agentsAvatarPath`, `chatInteractionsPath`) — keep existing keys.
- `ui/src/lib/services/websocket-service.ts`: no-op stub with
  navigator's surface (`WSMessage`, `subscribe`, `unsubscribe`,
  `onMessage → () => void`, `send`, `disconnect`, `wsService`
  singleton). Never constructs `WebSocket`.
- `ui/src/lib/icons.ts`: registers bundled collections with
  `addCollection` from `@iconify/svelte`; disable the runtime API
  (`disableCache`/no fetch). Import once from `ui/src/main.ts` before
  mount.
- Tests: `shims/environment.test.ts`, `shims/navigation.test.ts`,
  `features.test.ts`, `services/websocket-service.test.ts`.

**NOT in scope**: copying any navigator component/api/service file
(TASK-2592+); the final `@iconify-json` prefix list (TASK-2593).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/package.json`, `pnpm-lock.yaml` | MODIFY | runtime deps |
| `packages/ai-parrot-server/ui/vite.config.ts`, `vitest.config.ts` | MODIFY | aliases + defines |
| `packages/ai-parrot-server/ui/src/vite-env.d.ts` | CREATE/MODIFY | `declare const __AGENTCHAT_*__: boolean` |
| `packages/ai-parrot-server/ui/src/lib/shims/{environment,navigation,env-public}.ts` | CREATE | SvelteKit shims |
| `packages/ai-parrot-server/ui/src/lib/features.ts` | CREATE | typed flags |
| `packages/ai-parrot-server/ui/src/lib/config.ts` | MODIFY | agent fields |
| `packages/ai-parrot-server/ui/src/lib/services/websocket-service.ts` | CREATE | no-op stub |
| `packages/ai-parrot-server/ui/src/lib/icons.ts`, `src/main.ts` | CREATE/MODIFY | offline icon registration |
| `…/shims/*.test.ts`, `…/features.test.ts`, `…/services/websocket-service.test.ts` | CREATE | vitest |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import { router } from "$lib/router.svelte";      // ui/src/lib/router.svelte.ts:109 — navigate(to, {replace}) at :59
import { config } from "$lib/config";             // ui/src/lib/config.ts — object literal with apiBaseUrl, basePath "/admin", loginPath, tokenStorageKey "ai_parrot_token", sessionStorageKey
import { addCollection, disableCache } from "@iconify/svelte";  // (unverified — check the installed @iconify/svelte ^5 exports before use)
```

### Existing Signatures to Use
```ts
// ui/vite.config.ts (whole file, ~50 lines): defineConfig(({ mode }) => { const env = loadEnv(mode, __dirname, '');
//   base: '/admin/'; envPrefix: ['VITE_', 'PUBLIC_']; plugins: [tailwindcss(), svelte()];
//   resolve.alias: { $lib: path.resolve(__dirname, 'src/lib') }; build.outDir '../src/parrot/server/ui/dist'; assetsDir 'assets';
//   server.proxy '/api' → env.PUBLIC_API_URL || 'http://localhost:5000' })
// ui/vitest.config.ts — exists (jsdom + @testing-library/svelte); keep its shape, add the same alias/define entries
// ui/src/lib/config.ts — const env = import.meta.env; rawBaseUrl = env.PUBLIC_API_URL ?? ""; parseEnvBoolean helper; export const config = {…}
// ui/src/lib/router.svelte.ts:59 — navigate(to: string, { replace = false }: { replace?: boolean } = {}): void
// navigator src/lib/services/websocket-service.ts (surface to mirror): export interface WSMessage (5); private url = "/ws/userinfo" (19);
//   subscribe(channel: string): void (124); unsubscribe(channel: string): void (131); onMessage(type: string, handler): () => void (138);
//   send(data: any): void (156); disconnect(): void (164); export const wsService = new WebSocketService() (173)
// navigator src/lib/config.ts:1 — import { env } from "$env/dynamic/public"  (shape the env-public shim must satisfy: env.PUBLIC_*)
// ui/package.json deps today: axios, bits-ui, clsx, tailwind-merge, tailwind-variants, tw-animate-css; devDeps include vite ^5.4, svelte ^5.55, vitest ^3.2, json-schema-to-typescript
```

### Does NOT Exist
- ~~`$app/environment`, `$app/navigation`, `$env/dynamic/public`~~ — not resolvable until this task's aliases exist.
- ~~`/ws/userinfo`~~ in `ai-parrot-server` (only `/ws/voice`, `manager.py:1812-1834`). The stub must never connect.
- ~~`ui/src/lib/features.ts`, `ui/src/lib/shims/`, `ui/src/lib/icons.ts`~~ — created here.
- ~~`@iconify/svelte`, `dexie`, `echarts`, … in `ui/package.json` on `dev`~~ — added here.
- ~~`chart.js`~~ — not a dependency anywhere; do not add.
- ~~`config.agentsChatPath` etc. on `dev`~~ — added here.

---

## Implementation Notes

### Pattern to Follow
```ts
// ui/vite.config.ts — extend, don't replace:
resolve: { alias: {
  $lib: path.resolve(__dirname, 'src/lib'),
  '$app/environment': path.resolve(__dirname, 'src/lib/shims/environment.ts'),
  '$app/navigation':  path.resolve(__dirname, 'src/lib/shims/navigation.ts'),
  '$env/dynamic/public': path.resolve(__dirname, 'src/lib/shims/env-public.ts'),
}},
define: { __AGENTCHAT_VOICE__: flag(env.PUBLIC_AGENTCHAT_VOICE), /* … ×8 */ },
```

### Key Constraints
- Defaults are `true`; only the strings `"false"`/`"0"` (case-insensitive) disable.
- `features` must be a frozen object of plain booleans (no getters) so `{#if features.x}` is statically analysable.
- The WS stub returns a working unsubscribe function from `onMessage` and logs at `debug` level once.
- No SvelteKit packages added.

### References in Codebase
- `ui/src/lib/config.ts` header comment — env handling doctrine (FEAT-468 TASK-2527)
- `ui/docs/svelte5-structural/SKILL.md` — store/rune conventions
- `docs/admin-ui.md` §"Developer view" (line 87)

---

## Acceptance Criteria

- [ ] `pnpm install && pnpm build` succeeds with the new deps and aliases (no `$app`/`$env` resolution errors once TASK-2592 lands; for this task a smoke import of each shim in a test suffices)
- [ ] `pnpm test` passes: `browser === true`; `goto` maps to `router.navigate` with `replace`; all eight flags `true` by default and `false` when the define is `false`; WS stub never constructs `WebSocket`
- [ ] `ui/src/lib/icons.ts` is imported from `main.ts` before mount
- [ ] Existing FEAT-468/475 UI tests still pass

---

## Test Specification

```ts
// ui/src/lib/features.test.ts
import { describe, it, expect } from "vitest";
import { features } from "./features";
describe("features", () => {
  it("defaults every flag to true", () => {
    expect(Object.values(features).every(Boolean)).toBe(true);
    expect(Object.isFrozen(features)).toBe(true);
  });
});

// ui/src/lib/services/websocket-service.test.ts
import { vi, it, expect } from "vitest";
import { wsService } from "./websocket-service";
it("never opens a socket", () => {
  const spy = vi.spyOn(globalThis, "WebSocket" as any);
  wsService.subscribe("c"); wsService.send({ a: 1 });
  const off = wsService.onMessage("t", () => {}); off(); wsService.disconnect();
  expect(spy).not.toHaveBeenCalled();
});

// ui/src/lib/shims/navigation.test.ts
import { vi, it, expect } from "vitest";
vi.mock("$lib/router.svelte", () => ({ router: { navigate: vi.fn() } }));
import { router } from "$lib/router.svelte";
import { goto } from "./navigation";
it("delegates to router.navigate", async () => {
  await goto("/admin/agents/x/chat", { replaceState: true });
  expect(router.navigate).toHaveBeenCalledWith("/admin/agents/x/chat", { replace: true });
});
```

---

## Agent Instructions

1. **Read the spec** §2 Overview and §3 Module 1
2. **Check dependencies** — confirm `git log --oneline dev | grep -i "FEAT-475"` shows the merge before starting
3. **Verify the Codebase Contract** — read `ui/vite.config.ts`, `ui/vitest.config.ts`, `ui/src/lib/config.ts` first
4. **Update status** in `sdd/tasks/index/agentchat-migration.json` → `"in-progress"`
5. **Implement**; 6. **Verify**; 7. **Move this file** to `sdd/tasks/completed/`; 8. **Update index** → `"done"`; 9. **Completion Note**

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-08-30
**Notes**: Added runtime deps to `package.json` (marked, dompurify,
highlight.js, uuid, dexie, @iconify/svelte + 4 @iconify-json/* placeholder
collections — mdi/ph/svg-spinners/tabler, enumerated by grepping
navigator's vendored tree, per TASK-2593 to finalize; echarts, layerchart
pinned 2.0.0-next.64, d3-scale, d3-geo/topojson-client/world-atlas/leaflet/
@types/geojson, livekit-client, @tiptap/*). Created the three SvelteKit
shims, `features.ts` (frozen, 8 flags), `websocket-service.ts` stub (never
constructs `WebSocket`), `icons.ts` (registers the 4 bundled collections
via `addCollection`, imported once from `main.ts` before mount — verified
`@iconify/svelte` v5's `dist/index.d.ts` exports no `disableCache`, so
offline-ness is achieved purely by only ever resolving locally-registered
prefixes). Extended `vite.config.ts`/`vitest.config.ts` with the
`$app/*`/`$env/*` aliases and `__AGENTCHAT_*__` defines (default true,
"false"/"0" disable), declared in `vite-env.d.ts`. Added the agent-related
`config.ts` fields the task scope specifies (`agentsChatPath`,
`agentsVoicePath`, `agentsAvatarPath`, `chatInteractionsPath`) — note
navigator's own vendored `api/agent.ts` hardcodes its own path constants
rather than reading `config`, so these fields are provisioned for
TASK-2592's import re-pointing rather than consumed today.
`pnpm install && pnpm build` succeed (9.4MB main chunk — icon collections
are statically bundled; code-splitting/flag-gating lands with TASK-2595+).
`pnpm test`: 176/176 pass (6 new + all existing FEAT-468/475 tests green).

**Deviations from spec**: none
