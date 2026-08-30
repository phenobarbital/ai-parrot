# TASK-2595: Flagged surfaces — canvas, charts, maps, infographic

**Feature**: FEAT-476 — AgentChat Migration
**Spec**: `sdd/specs/agentchat-migration.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2594
**Assigned-to**: sdd-worker

---

## Context

Spec §3 Module 5. The heavy visual surfaces behind `features.canvas`,
`features.charts`, `features.maps`, `features.infographic`. TASK-2594
already routes to these files through gated dynamic imports; this task
makes them exist and verifies the chunks vanish when flags are off.

---

## Scope

- Copy from navigator: `components/agents/canvas/**` (`CanvasPanel.svelte`,
  `canvas-block-exporter.ts`, `canvas-block-types.ts`,
  `canvas-tab-manager.svelte.js`, `infographic/infographic-types.ts`),
  `components/agents/{DataChart,DataMap,StructuredMap,ChartConfigPanel}.svelte`,
  `structured-map-colors.ts`, `components/charts/{AppChart,AppChartGeo}.svelte`,
  `charts/chart-contract.ts`, `components/visualizations/ECharts.svelte`,
  `config/regeneration-models.ts`.
- Inside these files, gate cross-surface imports: `CanvasPanel` loads
  charts/maps/rich editor only under their flags; `AppChartGeo`/`DataMap`
  load `leaflet`/`world-atlas`/`topojson-client`/`d3-geo` under
  `features.maps`.
- A saved canvas block whose feature is off renders a "feature disabled
  in this build" placeholder block.
- Leaflet static assets (marker images/CSS) must land hashed under
  `dist/assets/` (Vite import of `leaflet/dist/leaflet.css` + inlined
  images) — never a nested directory (package-data globs are
  non-recursive).
- Tests: `features-gating.test.ts`; build-matrix check script or test
  that inspects `dist/assets` names for `echarts`/`leaflet`/`layerchart`
  chunks per flag.

**NOT in scope**: voice/avatar/datasets (TASK-2596).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `ui/src/lib/components/agents/canvas/**` | CREATE (vendored) | |
| `ui/src/lib/components/agents/{DataChart,DataMap,StructuredMap,ChartConfigPanel}.svelte`, `structured-map-colors.ts` | CREATE (vendored) | |
| `ui/src/lib/components/charts/**`, `visualizations/ECharts.svelte`, `config/regeneration-models.ts` | CREATE (vendored) | |
| `ui/src/lib/components/agents/features-gating.test.ts` | CREATE | vitest |
| `ui/src/lib/components/agents/canvas/{AudioCanvas,BlockCanvas,ChartCanvas,InfographicCanvas,InfographicEditor,InteractiveArtifactCanvas,MarkdownCanvas,SpreadsheetCanvas,canvas-persistence.svelte,canvas-registry}.{svelte,ts}`, `canvas/blocks/*.svelte` (14), `canvas/infographic/{InfographicBlockCanvas,InfographicInsertHandle,InfographicToolbar}.svelte`, `canvas/infographic/{demo-financial-variance,infographic-html-export,infographic-registry}.ts`, `canvas/infographic/blocks/*.svelte` (10) | CREATE (vendored) | full `canvas/**` closure `CanvasPanel.svelte`/`canvas-registry.ts` pull in eagerly — not listed individually in the original Scope bullet but covered by its `canvas/**` glob |
| `ui/src/lib/components/charts/overlays.ts` | CREATE (vendored) | unlisted `AppChart.svelte` dependency, discovered while wiring |
| `ui/src/lib/components/grid/{ResultGrid.svelte,formulas,grid-state.svelte,cell-format}.ts`, `ui/src/lib/styles/revogrid-theme.css` | CREATE (vendored) | unlisted `SpreadsheetCanvas.svelte` dependency, discovered while wiring |
| `ui/package.json` | MODIFY | add `@revolist/svelte-datagrid`, `@tiptap/extension-{link,underline}`, `exceljs`, `@iconify-json/lucide` — all real transitive deps of the `canvas/**` closure not enumerated in TASK-2591's original dependency list |
| `ui/src/lib/icons.ts` | MODIFY | register the `lucide` icon prefix (`ResultGrid.svelte` uses `icon="lucide:…"`) |
| `ui/src/lib/components/agents/ChartConfigPanel.svelte` | MODIFY (import fix) | `Badge`/`Separator` aren't re-exported from `$lib/ui/components` (TASK-2593 trimmed that barrel) — import from `$lib/ui/internal/shadcn/ui/{badge,separator}` directly instead |
| `ui/src/lib/components/agents/canvas/blocks/{ChartBlock,MapBlock}.svelte`, `ui/src/lib/components/agents/canvas/infographic/blocks/InfographicChartBlock.svelte`, `ui/src/lib/components/agents/canvas/InfographicCanvas.svelte`, `ui/src/lib/components/charts/AppChart.svelte` | MODIFY (gating) | converted the static/always-mounted `DataChart`/`DataMap`/`AppChart`/`InfographicEditor`/`AppChartGeo` cross-surface imports to `{#if features.x}{#await import(...)}`-gated, with a "feature disabled in this build" placeholder fallback |
| `ui/src/lib/components/agents/{avatar/AvatarViewer,avatar/VoiceNativeAvatarViewer,DataManagementModal,DatasetConfigModal,VoiceNotePlayer}.svelte` | FIX (unrelated bug, found while verifying) | TASK-2594's placeholder-generation heredoc let `$props()` get shell-expanded to `()` in these 5 files (`$props` = unset shell var); real build/test suites never caught it because Vite only parses a resolved dynamic-import target when the module is actually reachable in a full dependency-graph walk (e.g. a production build with the importing component wired into an entry point) — see Completion Note |

> **Pre-existing state, added by TASK-2594 — read before starting:**
> - `ui/src/lib/components/agents/canvas/canvas-block-types.ts`,
>   `canvas/canvas-tab-manager.svelte.ts`, and
>   `canvas/infographic/infographic-types.ts` **already exist**, ported
>   verbatim from navigator (byte-identical, `diff` clean) — TASK-2594
>   needed them unconditionally (`AgentChat.svelte`'s core message
>   handling creates/updates canvas tabs even before the visual
>   `CanvasPanel` is gated in) and pulled them forward. Nothing left to
>   do for these three files — do not recreate/overwrite.
> - `ui/src/lib/config/regeneration-models.ts` **already exists** (real,
>   complete implementation, not a placeholder) — `ChatBubble.svelte`
>   needed it unconditionally. Nothing left to do here either.
> - `ui/src/lib/components/agents/canvas/CanvasPanel.svelte`,
>   `{DataChart,DataMap,StructuredMap,ChartConfigPanel}.svelte`,
>   `ui/src/lib/components/charts/AppChart.svelte`, and
>   `ui/src/lib/components/visualizations/ECharts.svelte` **already
>   exist but only as TEMPORARY build-resolution placeholders**
>   (empty template + a header comment saying so) — TASK-2594 added
>   these because Vite/Rollup resolve a literal dynamic-import specifier
>   at transform/build time regardless of the `features.x` runtime
>   guard (`@vite-ignore` does not suppress resolution for a literal
>   string, only the warning for a non-analyzable one — verified against
>   vite@5.4.21/rollup@4.63.0). **Replace these wholesale with the real
>   vendored component** — do not diff/extend/`git mv` them, there is no
>   real implementation to preserve.
> - `structured-map-colors.ts` and `ui/src/lib/components/charts/
>   chart-contract.ts`/`AppChartGeo.svelte` genuinely do NOT exist yet —
>   normal CREATE, nothing pre-empted for those.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import { features } from "$lib/features";                     // TASK-2591
import { createBlock, isCanvasBlockArray } from "$lib/components/agents/canvas/canvas-block-types";  // navigator import in AgentChat.svelte (spec §6)
import * as canvasTabManager from "$lib/components/agents/canvas/canvas-tab-manager.svelte.js";     // navigator import in AgentChat.svelte
import type { AppChartConfig } from "$lib/components/charts/chart-contract";                       // navigator chart-contract.ts (31 lines)
```

### Existing Signatures to Use
```ts
// navigator src/lib/components/charts/AppChart.svelte:16 — `} from "layerchart";` (unconditional; layerchart 2.0.0-next.64 pinned) ; :23 browser from $app/environment
// navigator AppChartGeo.svelte (139 lines) — d3-geo/topojson/world-atlas; :16 browser
// navigator DataMap.svelte (224), StructuredMap.svelte (566), structured-map-colors.ts (235) — leaflet
// navigator visualizations/ECharts.svelte (300) — echarts
// navigator canvas/CanvasPanel.svelte (434), canvas-block-exporter.ts (392; :363 browser), canvas-block-types.ts (212), infographic/infographic-types.ts (256)
// Backend infographic routes: /api/v1/agents/infographic/{resource:templates|themes|render}[…] and /api/v1/agents/infographic/{agent_id} (manager.py:2091-2120)
// pyproject.toml:111 — "parrot.server.ui" = ["dist/*", "dist/assets/*"] (non-recursive)
```

### Does NOT Exist
- ~~`chart.js`~~ — never a dependency.
- ~~nested `dist/assets/<subdir>/`~~ — must not be produced; inline or hash-flatten.
- ~~`__AGENTCHAT_*__` being runtime-mutable~~ — they are compile-time defines; tests must use `vi.mock("$lib/features")`.

---

## Implementation Notes

### Key Constraints
- Only imports/gating edits; logic untouched.
- Verify with three builds: all-on, `CHARTS=false`, `MAPS=false` — grep `dist/assets` for `echarts|layerchart|leaflet`.

---

## Acceptance Criteria

- [x] `features-gating.test.ts`: with charts/maps off, `ChartBlock`/`MapBlock`/`InfographicChartBlock` render the "feature disabled in this build" placeholder instead of the real (dynamically-imported) component
- [x] Build matrix — CORRECTED during implementation: "chunk absent when flag is off" is not achievable with the current `$lib/features` design (see Completion Note for the verified root cause and what's true instead: correct per-feature code-splitting into separate chunk files that are never fetched at runtime when the flag is off, verified against the real build's `dist/assets` output for a repro entry importing `AgentChat.svelte`)
- [x] Placeholder block renders for disabled-feature canvas content — `ChartBlock`, `MapBlock`, `InfographicChartBlock` (charts/maps); `InfographicCanvas`'s rich-text editor falls back to the existing plain `<textarea>` HTML-source view when `features.richEditor` is off
- [x] `pnpm test` (34 files / 210 tests) and `pnpm build` green

---

## Test Specification

```ts
// ui/src/lib/components/agents/features-gating.test.ts
import { vi, it, expect } from "vitest";
vi.mock("$lib/features", () => ({ features: { voice: true, avatar: true, maps: false, charts: false, canvas: false, infographic: false, datasets: true, richEditor: true } }));
const imp = vi.fn(); vi.stubGlobal("__importSpy", imp);
import { render, screen } from "@testing-library/svelte";
import AgentChat from "./AgentChat.svelte";
it("hides canvas/chart/map affordances when flags are off", () => {
  render(AgentChat, { agentId: "bot" });
  expect(screen.queryByRole("button", { name: /canvas/i })).toBeNull();
});
```

---

## Agent Instructions

1. Read spec §3 Module 5, §7 Known Risks. 2. Confirm TASK-2594 completed. 3. Verify contract. 4. Index → `in-progress`. 5. Implement. 6. Verify (build matrix). 7. Move to `completed/`. 8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-30
**Notes**:
Ported the full `canvas/**` closure (CanvasPanel.svelte + canvas-registry.ts
statically pull in every canvas type — BlockCanvas, InfographicCanvas,
AudioCanvas, SpreadsheetCanvas, InteractiveArtifactCanvas — plus all 14
block components and the 10 infographic block variants), DataChart/DataMap/
StructuredMap/ChartConfigPanel, AppChart/AppChartGeo/chart-contract/
overlays, and ECharts. Gated the cross-surface heavy imports discovered
while wiring (ChartBlock→DataChart, MapBlock→DataMap, InfographicChartBlock
→AppChart, InfographicCanvas→InfographicEditor, AppChart→AppChartGeo)
behind their respective `features.X` flags with placeholder fallbacks,
per Scope. 34 files / 210 tests green; `pnpm build` verified (both via
the real project build and a standalone repro entry importing
`AgentChat.svelte` directly across an all-on / `CHARTS=false` /
`MAPS=false` matrix).

**Deviations from spec**:
1. **Real bug found and fixed**: TASK-2594's placeholder-generation
   heredoc script used unquoted `<<EOF`, so `$props()` got shell-expanded
   to `()` in 5 placeholder files (`avatar/{AvatarViewer,
   VoiceNativeAvatarViewer}.svelte`, `DataManagementModal.svelte`,
   `DatasetConfigModal.svelte`, `VoiceNotePlayer.svelte`) — a Svelte
   parse error. Neither `pnpm test` nor a `pnpm build` where the
   importing component isn't wired into an entry point catches this,
   because Vite only parses a *resolved* dynamic-import target when the
   module is actually walked as part of a real dependency graph (a
   production build with the component reachable from an entry, or the
   file being genuinely imported/rendered at runtime) — TASK-2594's own
   verification never did that. Fixed all 5 (`let _props = $props();`).
2. **`features.X` + dynamic `import()` does NOT achieve "chunk absent
   when flag is off"** (this task's own stated AC) — verified with an
   isolated Vite/Rollup repro: a plain top-level `const` re-exported
   from another module DOES get cross-module dead-code-eliminated
   together with its guarded `import()` when the guarding `if` reads a
   `define`-compiled-constant. But `$lib/features`'s shape
   (`export const features = Object.freeze({ charts: __AGENTCHAT_CHARTS__,
   ... })`, from TASK-2591) reads the flag via an **object property**
   (`features.charts`), and esbuild/Rollup do not propagate a constant
   value through an object literal across module boundaries — so
   `if (features.charts) { import(...) }` never gets eliminated, and the
   chunk is always emitted into `dist/assets`, in every flag
   configuration. What IS true and verified: each gated surface still
   gets its own separate chunk (confirmed AppChart/ECharts/DataMap/
   StructuredMap/leaflet/CanvasPanel/InfographicEditor/exceljs all land
   as distinct files), and that chunk is never *fetched* by the browser
   unless the runtime `if (features.x)` branch actually executes — which
   is the practically-important property for bundle-size/perf purposes.
   Fixing the "chunk absent from disk" property for real would require
   reshaping `$lib/features` to export flat `const` bindings instead of
   an object (a change to TASK-2591's already-merged deliverable,
   touching every `features.x` call site across TASK-2594/2595/2596) —
   out of this task's scope; flagging as a follow-up for a dedicated
   spec/task if the byte-for-byte "chunk absent" guarantee is ever
   actually required (e.g. for an air-gapped/minimal-footprint deploy
   profile). `features-gating.test.ts` asserts the real, verified
   behavior (placeholder renders, real component doesn't) rather than
   the aspirational one.
3. Discovered and ported unlisted transitive dependencies while wiring
   the `canvas/**` closure: `charts/overlays.ts` (AppChart), the whole
   `components/grid/**` + `styles/revogrid-theme.css` (SpreadsheetCanvas
   → ResultGrid), and added `@revolist/svelte-datagrid`,
   `@tiptap/extension-{link,underline}`, `exceljs`, `@iconify-json/lucide`
   to `package.json` (none were in TASK-2591's original dependency list).
4. `ChartConfigPanel.svelte`'s `Badge`/`Separator` imports pointed at
   `$lib/ui/components`, which TASK-2593 deliberately trimmed to just the
   `App*` wrappers — redirected to `$lib/ui/internal/shadcn/ui/{badge,
   separator}` directly, matching the established convention documented
   in that barrel's own header comment.
