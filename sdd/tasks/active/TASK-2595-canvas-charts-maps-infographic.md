# TASK-2595: Flagged surfaces — canvas, charts, maps, infographic

**Feature**: FEAT-476 — AgentChat Migration
**Spec**: `sdd/specs/agentchat-migration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2594
**Assigned-to**: unassigned

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

- [ ] `features-gating.test.ts`: with charts/maps/canvas off, no dynamic import attempted and buttons absent
- [ ] Build matrix: chunk absent when its flag is off; `dist/` stays flat
- [ ] Placeholder block renders for disabled-feature canvas content
- [ ] `pnpm test` and `pnpm build` green

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

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
