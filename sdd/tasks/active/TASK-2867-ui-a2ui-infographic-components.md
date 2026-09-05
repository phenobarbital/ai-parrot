# TASK-2867: Bundled UI — Svelte 5 A2UI `Infographic` renderer components

**Feature**: FEAT-527 — Infographic → A2UI migration (dual-emit)
**Spec**: `sdd/specs/infographic-a2ui-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2866, TASK-2860, TASK-2863
**Assigned-to**: unassigned

---

## Context

Spec §1 G4, §2 Overview step 5, §2 New Public Interfaces (Svelte), §3 Module 3. This task
builds the display-only renderer for an `Infographic`-rooted A2UI envelope: root dispatcher,
sections-as-tabs, and a node renderer covering the Parrot composites the adapter emits
(`KPICard`, `Chart`, `DataTable`, `InfoCard`, `Timeline`, `HtmlDocument`) and the Basic
primitives it lowers to (`Text`, `Image`, `List`, `CheckBox`, `Divider`, `Tabs`, `Row`, `Column`).
It reuses the existing ECharts-backed `InfographicChartBlock.svelte` instead of adding a second
chart stack, and renders `HtmlDocument` in a sandboxed iframe.

---

## Scope

Create under `ui/src/lib/components/agents/canvas/a2ui/`:

- `A2UISurface.svelte` — props `{ envelope: A2UIEnvelope }`; finds the `root` component
  (`components.find(c => c.id === "root")`, fallback `components[0]`); dispatches to
  `A2UIInfographic` for `Infographic`/`Report`, else to `A2UINode` (widget); shows a
  "Unsupported surface" placeholder when no root.
- `A2UIInfographic.svelte` — props `{ component: WireComponent; dataModel }`; renders `title`,
  optional `subtitle`, then `sections`: one section → stacked; >1 → tabs (use the existing
  `AppTabs` bits-ui wrapper if present in `$lib/components/ui`, else a minimal local tab strip —
  verify with `ls ui/src/lib/components/ui`). Each section: `heading`, `text`, then
  `components[]` via `A2UINode` with descriptor `{component, properties}`; honour
  `properties.layout === "half"` by grouping consecutive halves in a 2-column grid (mirrors
  TASK-2860 backend `Row`).
- `A2UINode.svelte` — props `{ descriptor: SectionDescriptor; dataModel }`; resolves bindings with
  `resolveProps`; dispatch table:
  - `KPICard` → label/value/unit/delta/trend (+ `icon`, `color`, `comparisonPeriod` from TASK-2860)
  - `Chart` → map to `ChartBlockData` (`chart_type ← type`, `labels ← rows[x]`, `series ← y[] → {name, values}`,
    `stacked`, `show_legend ← showLegend`, `color_by_sign ← colorBySign`, `positive_color`, `negative_color`,
    `layout`) and render `InfographicChartBlock` (`{#if features.charts}`); unknown A2UI types
    (`gauge`, `funnel`, `waterfall`, `heatmap`, `treemap`) fall back to `bar` with a caption (the block already does this)
  - `DataTable` → `columns` + resolved rows → existing `InfographicTableBlock.svelte` (`TableBlockData` shape — verify)
  - `InfoCard` → title/subtitle/body/badge/footer card
  - `Timeline` → existing `InfographicTimelineBlock.svelte` (map props — verify `TimelineBlockData`)
  - `Text`, `Image`, `Divider`, `List`(children), `CheckBox`(label + checked, read-only), `Row`/`Column`(children), `Tabs`(tabs[{title, child}])
  - `HtmlDocument` → `<iframe sandbox="allow-scripts" srcdoc={html} | src={srcUrl} title={title}>`
  - anything else (incl. action-bearing `Button`/`TextField`/`FilterBar`/`Map`) → visible placeholder
    `"<component> is not supported in this view"`.
- Tests with `@testing-library/svelte` + vitest: `A2UIInfographic.test.ts`, `A2UINode.test.ts`
  (including the HtmlDocument iframe sandbox attribute and the unsupported placeholder); mock
  `$lib/features` via `vi.hoisted` as `features-gating.test.ts` does; mock heavy chart/table blocks
  where needed.

**NOT in scope**: opening the canvas / tab data plumbing (TASK-2868); editing/export of A2UI
surfaces; actions/`callAgentFunction`; `Map`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte` | CREATE | root dispatcher |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIInfographic.svelte` | CREATE | title/sections/tabs |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte` | CREATE | component dispatch |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-chart-adapter.ts` | CREATE | `Chart` props+rows → `ChartBlockData` (pure, unit-tested) |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/*.test.ts` | CREATE | component + adapter tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import { features } from "$lib/features";                                                       // features.ts (a2ui + charts flags)
import type { A2UIEnvelope, CreateSurface, WireComponent, SectionDescriptor } from "./a2ui-types";   // TASK-2866
import { resolveBinding, resolveProps } from "./a2ui-binding";                                  // TASK-2866
import InfographicChartBlock from "../infographic/blocks/InfographicChartBlock.svelte";        // exists (props = ChartBlockData)
import InfographicTableBlock from "../infographic/blocks/InfographicTableBlock.svelte";        // exists
import InfographicTimelineBlock from "../infographic/blocks/InfographicTimelineBlock.svelte";  // exists
import type { ChartBlockData, ChartType } from "../infographic/infographic-types";              // infographic-types.ts:74-100, :23-35
import { render, screen } from "@testing-library/svelte";                                       // features-gating.test.ts:20
```

### Existing Signatures to Use
```ts
// infographic/blocks/InfographicChartBlock.svelte  (Svelte 5 runes)
let { chart_type, title, description, labels, series, x_axis_label, y_axis_label, stacked, show_legend, color_by_sign, positive_color, negative_color }: ChartBlockData = $props();  // :8-21
// falls back to 'bar' for heatmap/treemap/funnel/gauge/waterfall (comment :25-28) ; gated on features.charts (:2-4)

// infographic/infographic-types.ts
export interface ChartBlockData { chart_type: ChartType; title?; description?; labels: string[]; series: ChartSeriesItem[]; x_axis_label?; y_axis_label?; stacked?; show_legend?; layout?: "full"|"half"; color_by_sign?; ... }  // :74-100
export type ChartType = "bar"|"line"|"pie"|"donut"|"area"|"scatter"|"radar"|"heatmap"|"treemap"|"funnel"|"gauge"|"waterfall"  // :23-35
// TableBlockData / TimelineBlockData — read their interfaces in the same file before mapping

// canvas/InfographicCanvas.svelte:263 — how a block canvas is embedded: <InfographicBlockCanvas infographic={...} onBlocksChange={...} />
// A2UI wire (docs/frontend/agentdashboard-a2ui-reference.md §4): CreateSurface{surfaceId, catalogId, components[{id, component, ...props}], dataModel}
// Infographic props (catalog/parrot/infographic.py:33-63): title, subtitle, theme, sections[{heading, text, components[{component, properties}]}]
// Chart props (camelCase, TASK-2859): type, x, y[], stacked, showLegend, trendline, xAxisMode, palette, colorBySign, positiveColor, negativeColor, layout, data:{path}
// KPICard props: label, value, unit, delta, trend (+ icon, color, comparisonPeriod after TASK-2860)
// DataTable props: columns, data:{path}, explanation, totalRows, truncated (+ style after TASK-2860)
// HtmlDocument props (TASK-2863): title, html | srcUrl, theme
// Adapter data-model layout (adapters/infographic.py:256-264 `_bind_rows("charts", key, rows)`): rows at /charts/<key>/rows-style pointers; each row {label: <x>, <seriesName>: value} with x column name `_X_COLUMN` — read the constant in adapters/infographic.py before writing the chart adapter
```

### Does NOT Exist
- ~~a shadcn `tabs`/`table` directory~~ — doc §11.16: use `AppTabs`/`AppTooltip`/`AppDropdown` (bits-ui wrappers) or `DataTable.svelte`/`SimpleTable` if present; verify with `ls ui/src/lib/components/ui`.
- ~~a second chart library~~ — reuse `InfographicChartBlock` (layerchart/AppChart under `features.charts`).
- ~~`Infographic.sections[].components[].props`~~ — the descriptor key is `properties` (backend `_descriptor(component, properties)`).
- ~~Chart.js in the SPA~~ — not a dependency here (Chart.js is only vendored in the backend interactive-html renderer).

---

## Implementation Notes

### Pattern to Follow
Svelte 5 runes (`$props()`, `$derived`, `{#if}`/`{#each}` with keys), feature gating exactly as
`InfographicCanvas.svelte:5-10` (`if (features.x) await import(...)` + `{#if features.x}` markup).

### Key Constraints
- Every heavy import behind `features.a2ui`/`features.charts`.
- `HtmlDocument` iframe: `sandbox="allow-scripts"` only (no `allow-same-origin`), `referrerpolicy="no-referrer"`.
- Never `{@html}` untrusted strings; A2UI `Text` renders as text.
- Pure adapter `a2ui-chart-adapter.ts` unit-tested separately from components.

### References in Codebase
- `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/InfographicBlockCanvas.svelte` — block dispatch via registry (structure to mirror).
- `packages/ai-parrot-server/ui/src/lib/components/agents/features-gating.test.ts` — Svelte component test + features mock.

---

## Acceptance Criteria

- [ ] `A2UISurface` renders an `Infographic`-rooted envelope: title, subtitle, N sections (tabs when N>1), nested KPICard/Chart/DataTable/InfoCard/Timeline/Text/Image/List/CheckBox/Divider/Row/Column/Tabs
- [ ] `Chart` descriptors render through `InfographicChartBlock` with rows resolved from `dataModel`; adapter unit-tested (bar, donut, colorBySign, half layout)
- [ ] `HtmlDocument` renders a sandboxed iframe (`srcdoc` or `src`)
- [ ] Unknown / action-bearing components render a visible placeholder, never throw
- [ ] `cd packages/ai-parrot-server/ui && pnpm test` green; `pnpm check` (svelte-check) if configured

---

## Test Specification

```ts
// A2UIInfographic.test.ts
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
const { features } = vi.hoisted(() => ({ features: { a2ui: true, charts: false, canvas: true, infographic: true, maps: false, voice: false, avatar: false, datasets: false, richEditor: false } }));
vi.mock("$lib/features", () => ({ features }));
import A2UISurface from "./A2UISurface.svelte";

const envelope = { version: "v1.0", createSurface: { surfaceId: "infographic-abc", components: [
  { id: "root", component: "Infographic", title: "Q1", subtitle: "Fin", sections: [
    { heading: "Hero", components: [{ component: "KPICard", properties: { label: "Revenue", value: "$1.2M", trend: "up" } }] },
    { heading: "Detail", text: "Revenue grew.", components: [{ component: "HtmlDocument", properties: { title: "Doc", srcUrl: "https://x/doc.html" } }] },
  ] } ], dataModel: {} } };

it("renders title, two tabs, a KPI and a sandboxed iframe", async () => {
  render(A2UISurface, { envelope });
  expect(screen.getByText("Q1")).toBeInTheDocument();
  expect(screen.getAllByRole("tab")).toHaveLength(2);
  expect(screen.getByText("Revenue")).toBeInTheDocument();
  const iframe = document.querySelector("iframe")!;
  expect(iframe.getAttribute("sandbox")).toBe("allow-scripts");
});

it("shows a placeholder for unsupported components", () => {
  render(A2UISurface, { envelope: { version: "v1.0", createSurface: { surfaceId: "w", components: [{ id: "root", component: "FilterBar" }] } } });
  expect(screen.getByText(/not supported/i)).toBeInTheDocument();
});
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2866, TASK-2860, TASK-2863 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `infographic-types.ts` (Table/Timeline block data), `adapters/infographic.py` `_X_COLUMN` and `_bind_rows`, and `ls ui/src/lib/components/ui`
4. **Update status** in `sdd/tasks/index/infographic-a2ui-migration.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2867-ui-a2ui-infographic-components.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
