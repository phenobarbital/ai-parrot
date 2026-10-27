# TASK-4792: `A2UIGraph.svelte` projected boundary frames + rendered browser gate

**Feature**: FEAT-754 — C4 architecture diagrams as a `Graph` kind
**Spec**: `sdd/specs/a2ui-c4-diagrams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4790, TASK-4791
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6, "Chart-instance lifecycle" bullets 2–4. Frames from `computeBoundaryFrames`
(TASK-4791) are abstract layout coordinates; they must be projected through the live graph viewport
using the `onChartReady` hook (TASK-4790) and refreshed on render/resize/roam without a render loop.

---

## Scope

- In `A2UIGraph.svelte` `<script lang="ts">`: pass `onChartReady` to `<ECharts>`; subscribe to `rendered`
  and `graphRoam`; one initial update + coalesced `requestAnimationFrame` updates.
- Each update reads the latest properties, projects both corners of each frame via
  `chart.convertToPixel({seriesIndex: 0}, [x, y])`, writes `silent: true`, unfilled, behind-graph rect + text
  graphics with stable C4-prefixed ids; skip non-finite coords.
- Only `setOption({graphic})` when geometry/labels differ or owned ids went missing after a base-option
  replacement; remove stale owned ids with `$action: 'remove'`; never touch unrelated graphics.
- Cleanup unregisters both events and cancels the pending frame.
- Append the 4 lifecycle vitest cases; record rendered browser evidence (two container sizes, pan, zoom,
  same-geometry option replacement, switch to non-C4, remount) in `artifacts/logs/feat-754-c4-frames-browser.md`.

**NOT in scope**: changes to `ECharts.svelte` (TASK-4790) or to the pure helpers (TASK-4791) beyond bug fixes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte` | MODIFY | lifecycle projection |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.test.ts` | MODIFY | 4 lifecycle cases |
| `artifacts/logs/feat-754-c4-frames-browser.md` | CREATE | rendered evidence (`git add -f`) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import ECharts from '$lib/components/visualizations/ECharts.svelte';   // verified: A2UIGraph.svelte:198
import { browser } from '$app/environment';                              // verified: A2UIGraph.svelte:197
// computeBoundaryFrames, BoundaryFrame — from this module's <script module> (TASK-4791)
```

### Existing Signatures to Use
```ts
// A2UIGraph.svelte <script lang="ts"> (verified at 65144d730)
let { properties }: Props = $props();                                   // 213
let option = $derived(buildGraphOption(properties, resolveColor));      // 229
<ECharts options={option} />                                            // markup 240-246
// ECharts.svelte (after TASK-4790): onChartReady?: (chart: echarts.EChartsType) => (() => void) | void
```

### Does NOT Exist
- ~~frames inside `option.graphic` from `buildGraphOption`~~ — projection happens only in the mounted callback.
- ~~a ResizeObserver here~~ — `ECharts.svelte` already resizes; `rendered` triggers reprojection.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.test.ts", "action": "MODIFY"},
    {"path": "artifacts/logs/feat-754-c4-frames-browser.md", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write a pure-ish `projectFrames(chart, frames)` helper in `<script module>` (testable with a fake chart).
2. Add `handleChartReady(chart)` in the instance script; return cleanup.
3. Wire `<ECharts options={option} onChartReady={handleChartReady} />`.
4. Lifecycle tests with a fake chart (`on/off/convertToPixel/setOption/getOption`), then the browser run.

### `A2UIGraph.svelte` (MODIFY)
```ts
// <script module> — add:
  export const C4_FRAME_ID_PREFIX = 'c4-frame-';
  export function projectFrames(
    convert: (pt: [number, number]) => number[] | undefined,
    frames: BoundaryFrame[],
  ): Record<string, unknown>[] {
    // FILL IN: per frame, project (x,y) and (x+w,y+h); min/max → rect; caption at projected top-left;
    //          skip non-finite; ids `${C4_FRAME_ID_PREFIX}${id}` / `${C4_FRAME_ID_PREFIX}${id}-label`;
    //          silent: true, z below series, style fill 'none' — bounded by spec §3 M6 lifecycle bullet 2
    return [];
  }

// <script lang="ts"> — add after `let option = $derived(...)` (A2UIGraph.svelte:229):
  function handleChartReady(chart: any): () => void {
    let frame = 0;
    let lastKey = '';
    const schedule = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        // FILL IN: frames = computeBoundaryFrames(properties) (latest props, only when kind === 'c4');
        //          elements = projectFrames((p) => chart.convertToPixel({ seriesIndex: 0 }, p), frames);
        //          detect missing owned ids in chart.getOption().graphic; skip setOption when key unchanged
        //          and none missing; emit $action:'remove' for stale owned ids — no recursive loop
      });
    };
    chart.on('rendered', schedule);
    chart.on('graphRoam', schedule);
    schedule();
    return () => {
      chart.off('rendered', schedule);
      chart.off('graphRoam', schedule);
      if (frame) cancelAnimationFrame(frame);
    };
  }
// markup: <ECharts options={option} onChartReady={handleChartReady} />
```

### `A2UIGraph.test.ts` (MODIFY — append after TASK-4791's cases)
```ts
  it('projects boundary frames through chart coordinates', () => { /* FILL IN */ });
  it('reprojects on resize and roam without a render loop', () => { /* FILL IN */ });
  it('restores frames after base option replacement', () => { /* FILL IN */ });
  it('removes obsolete frames and cleans up subscriptions', () => { /* FILL IN */ });
```

### `artifacts/logs/feat-754-c4-frames-browser.md` (CREATE)
Record browser, ECharts version, nested-boundary fixture, screenshots/measurements for each scenario of
spec §3 M6 "Required rendered validation". Mocked conversion alone does NOT satisfy this gate.

### FILL IN checklist
- [ ] `projectFrames`; scheduled update body; 4 test bodies; browser evidence

---

## Acceptance Criteria

- [ ] All 12 C4 vitest cases + existing five pass; `pnpm build` succeeds.
- [ ] Rendered evidence recorded; no render loop or leaked callbacks on remount.

## Validation Commands
- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_graph.py -q`
- `pytest packages/ai-parrot-server/tests/ui/test_vitest_echarts_chart_ready.py -q`

---

## Test Specification
Spec §3 M6 vitest names (last four).

---

## Agent Instructions

Standard FEAT-754 procedure; close with `scripts/sdd/close_task.sh TASK-4792 a2ui-c4-diagrams verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
