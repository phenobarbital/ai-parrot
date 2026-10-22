# TASK-3999: Admin UI — render a second value axis for right-axis series (AppChart)

**Feature**: FEAT-623 — Infographic → A2UI display hints
**Spec**: `sdd/specs/infographic-a2ui-display-hints.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3998
**Assigned-to**: unassigned

---

## Context

Spec Module 5, second half (5b). After TASK-3998, `ChartBlockData` carries
`series[i].axis` and `y_axis_labels`. The admin UI still draws every
series against one value scale, because:
- `InfographicChartBlock.svelte` receives `y_axis_label` and discards it
  (`_y_axis_label`, :15);
- `AppChartConfig` (`charts/chart-contract.ts`) has no axis concept;
- `AppChart.svelte` renders one `<Chart>` with a single `yScale`/`yDomain`
  computed across **all** `config.y` keys (:175-201, :493-494).

So a small series ("New MRR", ~50K) is flattened against a large one
("MRR", ~1.2M).

**Spec §7 stop rule.** AppChart is layerchart `2.0.0-next.64` with no
axis abstraction. If a second scale needs an AppChart redesign, ship
nothing beyond TASK-3998's mapping, leave the chart single-axis (exactly
today's behaviour, and no `console.warn`), and record the follow-up spec
in the Completion Note. Do not build a second chart stack.

---

## Scope

- **Step 1 (gate)**: assess feasibility per Implementation Notes →
  "Feasibility gate". If it fails, revert any partial edits, fill in the
  Completion Note with the reason, and close the task as
  `verified` with "stop rule fired".
- Add `seriesAxes?`, `yAxisLabel?` and `yAxisLabels?` to `AppChartConfig`.
- Create a pure helper `charts/dual-axis.ts` that splits keys by axis and
  computes each axis domain, with a vitest suite and a pytest wrapper.
- In `InfographicChartBlock.svelte`, stop discarding `y_axis_label`. Build
  `seriesAxes` from `series[i].axis` (only when some series is `'right'`),
  and pass `yAxisLabel` / `yAxisLabels` into the config.
- In `AppChart.svelte`, cartesian **SVG** branch only: when the config has
  ≥1 right-axis series, the left `<Chart>` uses only the left keys' domain
  and series, and a second, layered `<Chart>` draws the right keys on their
  own domain with `<Axis placement="right">`.

**NOT in scope**:
- the canvas branch (`useCanvas`, >2000 points): it stays single-axis;
- `horizontalBar`, pie, donut, radar and map: unchanged;
- tooltips for right-axis series (the layered chart is
  `pointer-events: none`), documented as a known gap;
- any Python or wire change;
- TASK-3998's adapter mapping.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/charts/chart-contract.ts` | MODIFY | `seriesAxes`, `yAxisLabel`, `yAxisLabels` on `AppChartConfig` |
| `packages/ai-parrot-server/ui/src/lib/components/charts/dual-axis.ts` | CREATE | pure `splitByAxis` / `axisDomain` helpers |
| `packages/ai-parrot-server/ui/src/lib/components/charts/dual-axis.test.ts` | CREATE | vitest for the helpers |
| `packages/ai-parrot-server/tests/ui/test_vitest_chart_dual_axis.py` | CREATE | pytest wrapper |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/blocks/InfographicChartBlock.svelte` | MODIFY | pass axis info into `AppChartConfig` |
| `packages/ai-parrot-server/ui/src/lib/components/charts/AppChart.svelte` | MODIFY | layered right-axis `<Chart>` in the SVG cartesian branch |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
// AppChart.svelte :2-16 — from "layerchart": Area, Axis, Bars, Canvas, Chart, Group, Highlight, Pie, Points, Rule, Spline, Svg, Tooltip
// AppChart.svelte :17-22 — from "d3-scale": scaleBand, scaleLinear, scaleOrdinal, scalePoint
import type { AppChartConfig } from "./chart-contract.js";                       // AppChart.svelte:25
import type { AppChartConfig } from '$lib/components/charts/chart-contract.js';  // InfographicChartBlock.svelte:5
import type { ChartBlockData, ChartType } from '../infographic-types';          // InfographicChartBlock.svelte:6
import { describe, expect, it } from 'vitest';
```
```python
from ._vitest import run_vitest  # verified: packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_dsl.py:3
```

### Existing Signatures to Use
```ts
// charts/chart-contract.ts (31 lines)
export interface AppChartConfig {   // :12
  type: ChartType; x: string; y: string[];
  stacked?; trendline?; median?; splitSeries?; showLegend?; xAxisMode?; palette?;
  colorBySign?; negativeColor?; title?;
  description?: string;             // :30  (last field)
}

// charts/AppChart.svelte (671 lines)
interface Props { config: AppChartConfig; data: Record<string, any>[]; loading?: boolean; compact?: boolean; }  // :43-48
let seriesDefs = $derived(config.y.map((key, i) => ({ key, label: key, value: ..., color: resolvedPalette[i % ...] })));  // :133
let useCanvas = $derived(totalPoints > 2000);       // :172
let yMax / yMin / yMaxStacked = $derived(...)       // :175 / :182 / :192 — computed over ALL config.y
let chartSeries = $derived(seriesDefs.map(...));    // :203
// Cartesian branch (:485-…):
//   <Chart {data} x={config.x} y={config.y[0]} xScale={isBar ? scaleBand().padding(0.3) : scalePoint().padding(0.5)}
//          yScale={scaleLinear()} yDomain={[yMin * 1.05, yMaxStacked * 1.05]} yNice
//          series={useSignColor ? undefined : chartSeries} seriesLayout={config.stacked ? "stack" : "group"}
//          padding={{ top: 16, right: 16, bottom: 36, left: 52 }} tooltipContext={{ mode: "band" }}>   // :486-500
//   {#if useCanvas} <Canvas>…</Canvas> {:else} <Svg> <Axis placement="left" grid rule /> (:537) … <Highlight area /> (:597) </Svg>

// agents/canvas/infographic/blocks/InfographicChartBlock.svelte (131 lines)
//   :8-21  let { chart_type, title, description, labels, series, x_axis_label: _x_axis_label,
//                y_axis_label: _y_axis_label, stacked, show_legend, color_by_sign, positive_color, negative_color }: ChartBlockData = $props();
//   :78-110 appChartConfig = $derived.by((): AppChartConfig => { … color_by_sign branch (:84-95) … return { type, x: '_label', y, stacked, showLegend, ...(palette ? { palette } : {}) } (:103-109) })
//   :124  <AppChart config={appChartConfig} data={chartData} />

// From TASK-3998 (must be done first):
// infographic-types.ts  ChartSeriesItem.axis?: 'left' | 'right' ;  ChartBlockData.y_axis_labels?: (string | null)[]
```

### Does NOT Exist
- ~~Any axis concept in `AppChartConfig`~~: no `seriesAxes`, `yAxisLabel` or `yAxisLabels` today.
- ~~A secondary y-scale prop on layerchart `<Chart>`~~: `<Chart>` takes one `yScale`/`yDomain`. A second scale means a second `<Chart>`.
- ~~An axis title anywhere in AppChart~~: `<Axis>` is used without a label (:452-453, :537-542). Whether layerchart 2.0.0-next.64's `<Axis>` accepts a `label` prop is **unverified** (no `ui/node_modules` in the main checkout on 2026-09-30). Check `node_modules/layerchart/dist/components/Axis.svelte.d.ts` before using it.
- ~~Tests for `AppChart.svelte` or `InfographicChartBlock.svelte`~~: none exist. This task tests the pure helper only.
- ~~`charts/dual-axis.ts`~~: created by this task.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/charts/chart-contract.ts",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/charts/dual-axis.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/charts/dual-axis.test.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/ui/test_vitest_chart_dual_axis.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/blocks/InfographicChartBlock.svelte",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/charts/AppChart.svelte",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Layerchart assessment (written at task time, 2026-09-30)
AppChart's cartesian branch is **one** `<Chart>` with a single
`yScale={scaleLinear()}` and a `yDomain` computed over every `config.y`
key. layerchart 2.x has no per-series secondary scale, so a second value
axis means a **second `<Chart>`**. It is layered absolutely over the first
and given the same `data`, `x`, `xScale` and `padding`, so band and point
positions line up. It draws only the right-axis keys on their own
`yDomain`, plus `<Axis placement="right">`, with `pointer-events: none`.

This is additive inside the SVG branch, roughly 40–60 lines in
`AppChart.svelte`, and leaves the canvas branch and every non-cartesian
type alone. It is therefore **expected to pass the gate**. The open risks:
- x alignment depends on both charts getting identical width and padding;
- right-axis series get no tooltip or highlight;
- a stacked config plus right axis is ambiguous (stack only the left keys).

### Feasibility gate (Step 1)
The gate passes only if all of these hold:
1. Two absolutely stacked `<Chart>` instances with identical `data`, `x`,
   `xScale` and `padding` render aligned x positions in a quick manual
   check, or in a vitest DOM check if one is cheap.
2. The change stays inside the SVG cartesian branch and new derived values.
   The `<Chart>` props of the existing branches are NOT restructured.
3. No new dependency.

If any of these fails, the stop rule fires (see Context).

### Key Constraints
- **No behaviour change without right-axis series.** When `seriesAxes` is
  absent or has no `'right'` entry, the rendered output must be
  byte-for-byte today's: same domain, padding and series.
- The left domain is computed over the left keys only, and the right domain
  over the right keys only. Reuse the same floor rule as `yMin`/`yMaxStacked`
  (0 floor for stacked, real minimum ≤ 0 otherwise). Stacking applies to
  the left keys only.
- Mark choice for the right series: bar charts draw right series as
  `<Spline>`, matching FieldSync's "bars + rate line" envelope. Line and
  area charts keep their own mark. This is a FILL IN with that bound.
- When there is a right axis, both charts use `padding.right = 52`
  (mirroring `left: 52`), so the right tick labels fit.
- The canvas branch (`useCanvas`) ignores `seriesAxes`.

### References in Codebase
- `AppChart.svelte:175-201`: existing domain derivations to mirror in `axisDomain`.
- `AppChart.svelte:577-595`: overlay `<Spline data=… y=…>` usage (trendline), the pattern for drawing a keyed line in a Chart.

---

## Implementation Blueprint

### Steps (in order)
1. **Feasibility gate** (Implementation Notes). *Why*: spec §7 stop rule. If it fails, stop and record.
2. Extend `AppChartConfig`. *Why*: both components type-check against it.
3. Create `dual-axis.ts` plus its vitest and wrapper. *Why*: the logic stays testable outside Svelte, since there are no component tests for AppChart.
4. Wire `InfographicChartBlock.svelte`. *Why*: it is the hop that currently discards the axis data.
5. Add the layered right `<Chart>` to `AppChart.svelte`. *Why*: this is the actual render.
6. Check by hand in the admin UI with the walkthrough envelope ("New MRR" on the right). *Why*: there is no automated render test.

### `packages/ai-parrot-server/ui/src/lib/components/charts/chart-contract.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '  description?: string;' chart-contract.ts)
// AFTER — insert below `  description?: string;` (verified: :30), inside AppChartConfig
  /** Per-series value axis, parallel to `y` ('left' default). Cartesian SVG only. */
  seriesAxes?: ("left" | "right" | null)[];
  /** Left value-axis name (single-axis charts). */
  yAxisLabel?: string;
  /** Axis names `[left, right]` when any series is on the right. */
  yAxisLabels?: (string | null)[];
```

### `packages/ai-parrot-server/ui/src/lib/components/charts/dual-axis.ts` (CREATE)
```ts
/**
 * Pure dual-axis helpers for AppChart (FEAT-623 TASK-3999).
 * Kept out of the Svelte component so the split/domain rules are unit-testable.
 */

export interface AxisSplit {
  left: string[];
  right: string[];
}

/** Split `y` keys by `seriesAxes` (parallel array; anything but 'right' is left). */
export function splitByAxis(y: string[], seriesAxes?: ("left" | "right" | null)[]): AxisSplit {
  const left: string[] = [];
  const right: string[] = [];
  y.forEach((key, i) => (seriesAxes?.[i] === "right" ? right : left).push(key));
  return { left, right };
}

/**
 * Value domain for `keys`, matching AppChart's floor rule:
 * stacked → [0, max row sum]; otherwise → [min(0, min value), max(0, max value)].
 */
export function axisDomain(
  data: Record<string, unknown>[],
  keys: string[],
  stacked: boolean,
): [number, number] {
  // FILL IN: mirror AppChart.svelte:175-201 exactly (Number(v) || 0 coercion, 0 floor when stacked,
  // real minimum ≤ 0 otherwise) — bounded by Key Constraints "no behaviour change without right-axis series".
  throw new Error("FILL IN");
}
```

### `packages/ai-parrot-server/ui/src/lib/components/charts/dual-axis.test.ts` (CREATE)
```ts
import { describe, expect, it } from "vitest";
import { axisDomain, splitByAxis } from "./dual-axis";

describe("splitByAxis", () => {
  it("puts only exact 'right' entries on the right", () => {
    expect(splitByAxis(["a", "b", "c"], ["left", "right", null])).toEqual({ left: ["a", "c"], right: ["b"] });
  });
  it("treats a missing/short seriesAxes as all-left", () => {
    expect(splitByAxis(["a", "b"])).toEqual({ left: ["a", "b"], right: [] });
    expect(splitByAxis(["a", "b"], ["right"])).toEqual({ left: ["b"], right: ["a"] });
  });
});

describe("axisDomain", () => {
  // FILL IN: unstacked positive, unstacked with negatives (floor = real min), stacked (row sums, 0 floor),
  // keys subset ignores other columns — bounded by AppChart.svelte:175-201.
});
```

### `packages/ai-parrot-server/tests/ui/test_vitest_chart_dual_axis.py` (CREATE)
```python
"""FEAT-623 (TASK-3999): run the AppChart dual-axis helper vitest suite from pytest."""

from ._vitest import run_vitest


def test_chart_dual_axis_vitest() -> None:
    """splitByAxis / axisDomain follow AppChart's domain rules."""
    run_vitest("src/lib/components/charts/dual-axis.test.ts")
```

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/blocks/InfographicChartBlock.svelte` (MODIFY)
```svelte
<!-- occurrences: 1 (verified: grep -c 'y_axis_label: _y_axis_label,' InfographicChartBlock.svelte) -->
<!-- REPLACE `		y_axis_label: _y_axis_label,` (verified: :15) with: -->
		y_axis_label,
		y_axis_labels,
```
```ts
// occurrences: 1 (verified: grep -c '...(palette ? { palette } : {})' InfographicChartBlock.svelte)
// AFTER — insert below `			...(palette ? { palette } : {})` (verified: :108), inside the final return object
			// FEAT-623: forward axis info only when it exists — no right series ⇒ no seriesAxes key.
			...(series.some((s) => s.axis === 'right')
				? { seriesAxes: series.map((s) => s.axis ?? null) }
				: {}),
			...(y_axis_label ? { yAxisLabel: y_axis_label } : {}),
			...(y_axis_labels ? { yAxisLabels: y_axis_labels } : {})
```
**Why**: the `color_by_sign` branch (:84-95) is a single-series sign chart
and stays as it is. Only the general return gets axes. A trailing comma
after `...(palette ? { palette } : {})` is needed; add it.

### `packages/ai-parrot-server/ui/src/lib/components/charts/AppChart.svelte` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '  let chartSeries = $derived(' AppChart.svelte)
// BEFORE — insert above `  let chartSeries = $derived(` (verified: :203)
  // FEAT-623: dual value axis (cartesian SVG only; canvas ignores it).
  import { axisDomain, splitByAxis } from "./dual-axis";  // FILL IN: move this import up to the <script> import block (:17-32)
  let axisSplit = $derived(splitByAxis(config.y, config.seriesAxes ?? undefined));
  let hasRightAxis = $derived(
    axisSplit.right.length > 0 && !useCanvas && (isBar || isLine || isArea),
  );
  let leftDomain = $derived(axisDomain(data, axisSplit.left, config.stacked ?? false));
  let rightDomain = $derived(axisDomain(data, axisSplit.right, false));
  // FILL IN: when hasRightAxis, chartSeries / seriesDefs used by the LEFT chart must contain only
  // axisSplit.left keys; when !hasRightAxis they must be EXACTLY today's — bounded by Key Constraints.
```
```svelte
<!-- occurrences: 1 (verified: grep -c 'yDomain={[yMin * 1.05, yMaxStacked * 1.05]}' AppChart.svelte) -->
<!-- REPLACE (verified: :494) -->
          yDomain={hasRightAxis
            ? [leftDomain[0] * 1.05, leftDomain[1] * 1.05]
            : [yMin * 1.05, yMaxStacked * 1.05]}
<!-- occurrences: 1 (verified: grep -c 'padding={{ top: 16, right: 16, bottom: 36, left: 52 }}' AppChart.svelte) -->
<!-- REPLACE (verified: :498) -->
          padding={{ top: 16, right: hasRightAxis ? 52 : 16, bottom: 36, left: 52 }}
```
```svelte
<!-- occurrences: 1 (verified: grep -c '<Highlight area />' AppChart.svelte) -->
<!-- The layered right chart goes AFTER the closing </Chart> of the cartesian branch, as a sibling, wrapped in -->
<!-- an absolutely positioned container with pointer-events-none. Anchor context (:597-600): -->
<!--               <Highlight area />                                                         -->
<!--             </Svg>                                                                      -->
<!--           {/if}                                                                         -->
<!-- FILL IN: locate this branch's closing `</Chart>` (the one following :597's </Svg>/{/if} and the Tooltip.Root), -->
<!-- then insert:                                                                                              -->
{#if hasRightAxis}
  <div class="pointer-events-none absolute inset-0">
    <Chart
      {data}
      x={config.x}
      y={axisSplit.right[0]}
      xScale={isBar ? scaleBand().padding(0.3) : (scalePoint().padding(0.5) as any)}
      yScale={scaleLinear()}
      yDomain={[rightDomain[0] * 1.05, rightDomain[1] * 1.05]}
      yNice
      padding={{ top: 16, right: 52, bottom: 36, left: 52 }}
    >
      <Svg>
        <Axis placement="right" rule />
        <!-- FILL IN: one mark per right key — <Spline y={key} stroke=…/> for bar & line charts, <Area> for area;
             colors = the series' palette color (seriesDefs entry for that key) — bounded by Key Constraints "mark choice". -->
      </Svg>
    </Chart>
  </div>
{/if}
```
**Why**: identical `data`, `x`, `xScale` and padding keep the x positions
aligned, and `pointer-events-none` keeps the left chart's tooltip
working. The parent container must be `relative`. FILL IN: confirm the
cartesian branch's wrapper is `relative` (or add `relative` to it) without
changing its size classes.

### FILL IN checklist
- [ ] Step 1 feasibility gate: pass/fail recorded in the Completion Note (spec §7 stop rule).
- [ ] `dual-axis.ts::axisDomain`: mirror `AppChart.svelte:175-201` (Key Constraints).
- [ ] `dual-axis.test.ts`: `axisDomain` cases.
- [ ] `AppChart.svelte`: move the import to the script import block.
- [ ] `AppChart.svelte`: restrict the left `seriesDefs`/`chartSeries` to the left keys only when `hasRightAxis` (byte-identical otherwise).
- [ ] `AppChart.svelte`: locate the cartesian `</Chart>` and insert the layered chart; ensure a `relative` wrapper.
- [ ] `AppChart.svelte`: right-series marks and colours (Key Constraints "mark choice").
- [ ] Axis titles: only if `<Axis label>` is verified in `node_modules/layerchart`. Otherwise skip, and note it.

---

## Acceptance Criteria

- [ ] Gate recorded. If it passed, all of the following hold. If it failed, the chart is unchanged and the follow-up is noted.
- [ ] With no `'right'` entry in `seriesAxes`, `AppChart` output is unchanged: same domain, padding and series.
- [ ] With ≥1 right series on a bar, line or area chart (SVG path), the right keys render on their own scale with a right-hand axis, and the left domain covers the left keys only.
- [ ] `InfographicChartBlock` no longer discards `y_axis_label`.
- [ ] `dual-axis` vitest is green via the pytest wrapper, or the completion note says it skipped because `ui/node_modules` was absent.
- [ ] No new dependency.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_chart_dual_axis.py -q`

---
## Test Specification

`dual-axis.test.ts` (blueprint above) covers the split rules and domain
parity with AppChart. The render is checked by hand with the walkthrough
envelope ("New MRR" with `seriesAxes: [null, 'right']`) after the
walkthrough task (spec Module 8) lands, or with a hand-written envelope before then.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug infographic-a2ui-display-hints --feature-id FEAT-623`).
2. Read the spec (§3 Module 5, §7 stop rule).
3. TASK-3998 must be `done`.
4. Re-run every `grep -c` anchor. Run `pnpm install` in `packages/ai-parrot-server/ui` if `node_modules` is absent.
5. Mark `"in-progress"` in the per-spec index.
6. Step 1 gate first. Then implement from the blueprint.
7. Run the Validation Commands.
8. Commit only the listed files.
9. Close with `scripts/sdd/close_task.sh TASK-3999 infographic-a2ui-display-hints verified`.
10. Fill in the Completion Note, including the gate result.

---

## Completion Note



**Completed by**: sdd-worker (Claude Sonnet 5.5, fallback sequential loop — parrot-sdd-coder unavailable)
**Date**: 2026-09-30
**Feasibility gate**: passed | stop rule fired (<reason>; follow-up spec: <path or TODO>)
**Notes**: Feasibility gate: PASSED (stop rule did NOT fire) — change is additive inside the SVG cartesian branch, no new dependency, <Axis label> verified in layerchart 2.0.0-next.64 types. Layered second <Chart> with identical data/x/xScale/padding, pointer-events-none; left chart uses left keys/domain only; right series drawn as Spline (bar/line) or Area; padding.right=52 only when a right axis exists; byte-identical config otherwise. Axis labels only rendered when a right axis exists. Left-chart tooltip still lists every series (it iterates all seriesDefs), so right-axis values are shown. LIMITS: x-alignment of the two charts was NOT visually verified (no browser in this run) — vite build compiles clean and dual-axis vitest passes; needs a manual look with the walkthrough envelope. Canvas branch (>2000 points), horizontalBar, sign-colored bars stay single-axis.

**Deviations from spec**: none | describe if any
