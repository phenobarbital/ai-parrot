# TASK-4790: `ECharts.svelte` optional `onChartReady` lifecycle callback

**Feature**: FEAT-754 — C4 architecture diagrams as a `Graph` kind
**Spec**: `sdd/specs/a2ui-c4-diagrams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6, "Chart-instance lifecycle". `A2UIGraph.svelte` (TASK-4792) must project C4 boundary
frames through the live chart, so the shared `ECharts.svelte` gains an optional callback receiving
the live instance. Callers that do not pass it keep today's behaviour exactly.

---

## Scope

- Add `onChartReady?: (chart: echarts.EChartsType) => (() => void) | void` to `Props`.
- Call it once per live chart instance after its first `setOption`; retain its cleanup; call the cleanup
  before disposing/replacing that instance (incl. the core→full rebuild path) and on destroy.
- If the callback identity changes, clean up the old subscription and attach the new one to the live instance.
- Create `ECharts.test.ts` (vitest): callback at initialization, replacement, instance recreation after lazy
  full-build loading, disposal.

**NOT in scope**: anything in `A2UIGraph.svelte`; new npm dependencies.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/visualizations/ECharts.svelte` | MODIFY | optional callback + cleanup |
| `packages/ai-parrot-server/ui/src/lib/components/visualizations/ECharts.test.ts` | CREATE | lifecycle tests |
| `packages/ai-parrot-server/tests/ui/test_vitest_echarts_chart_ready.py` | CREATE | pytest wrapper running the vitest file (repo convention) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import { onDestroy } from "svelte";                 // verified: ECharts.svelte:2
// `echarts` namespace already imported in ECharts.svelte (used as echarts.EChartsType at :131)
import { render } from '@testing-library/svelte';   // project test stack (codebase conventions)
import { describe, it, expect, vi } from 'vitest';
```

### Existing Signatures to Use
```ts
// packages/ai-parrot-server/ui/src/lib/components/visualizations/ECharts.svelte (verified at 65144d730)
interface Props { options: any; theme?: string | object; className?: string; style?: string; }   // 116-121
let { options, theme = "light", className = "", style = "width: 100%; height: 400px;" }: Props = $props();  // 123-128
let chartInstance: echarts.EChartsType | null = null;                 // 131
$effect(() => { if (chartContainer && options) { initOrUpdateChart(); } });   // 229-233
async function initOrUpdateChart()                                     // 240
  // full-build swap: `chartInstance.dispose(); chartInstance = null;` 252-254; init 257-263
  chartInstance.setOption(safeOptions, true);                          // 267
onDestroy(() => { ...; chartInstance?.dispose(); chartInstance = null; })  // 276-283
```

### Does NOT Exist
- ~~`ECharts.test.ts`~~ — created HERE.
- ~~an existing `onChartReady`/`onInit` prop~~.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/ui/src/lib/components/visualizations/ECharts.svelte", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/visualizations/ECharts.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_echarts_chart_ready.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Svelte 5 runes only; match surrounding formatting (double quotes in this file).
- The callback must run after the FIRST `setOption` of each instance, never on every update.

---

## Implementation Blueprint

### Steps (in order)
1. Extend `Props` and the `$props()` destructure.
2. Add `readyCleanup` / `readyFor` state and a `detachReady()` helper.
3. Call `detachReady()` before every `dispose()`; after `setOption`, attach when `readyFor !== chartInstance`.
4. Add an `$effect` reacting to `onChartReady` identity changes.
5. Write tests mocking `echarts.init`.

### `ECharts.svelte` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '  interface Props {' ECharts.svelte → line 116)
  interface Props {
    options: any;
    theme?: string | object;
    className?: string;
    style?: string;
    /** Called once per live chart instance after its first setOption; may return a cleanup. */
    onChartReady?: (chart: echarts.EChartsType) => (() => void) | void;
  }
  // destructure: add `onChartReady,`

  let readyCleanup: (() => void) | null = null;
  let readyFor: echarts.EChartsType | null = null;
  let readyCallback: Props["onChartReady"] = undefined;

  function detachReady() {
    readyCleanup?.();
    readyCleanup = null;
    readyFor = null;
  }

  function attachReady() {
    if (!chartInstance || !onChartReady || readyFor === chartInstance) return;
    readyCallback = onChartReady;
    readyFor = chartInstance;
    readyCleanup = onChartReady(chartInstance) || null;
  }
// FILL IN: call detachReady() before `chartInstance.dispose()` at :253 and in onDestroy (:281);
//          call attachReady() right after `chartInstance.setOption(safeOptions, true);` (:267);
//          $effect: when onChartReady !== readyCallback and a chart is live → detachReady(); attachReady()
//          — bounded by spec §3 M6 lifecycle bullet 1
```

### `ECharts.test.ts` (CREATE)
```ts
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/svelte';
import ECharts from './ECharts.svelte';

describe('ECharts onChartReady', () => {
  it('calls the callback once after the first setOption', async () => { /* FILL IN */ });
  it('cleans up and re-attaches when the callback changes', async () => { /* FILL IN */ });
  it('re-attaches after instance recreation for the full build', async () => { /* FILL IN */ });
  it('runs the cleanup on unmount', async () => { /* FILL IN */ });
});
// FILL IN: vi.mock the echarts module(s) the component resolves (check resolveLib) — bounded by no new npm dependency
```

### `packages/ai-parrot-server/tests/ui/test_vitest_echarts_chart_ready.py` (CREATE)
```python
"""FEAT-754 (TASK-4790): run the ECharts onChartReady vitest from pytest (validation contract)."""

from ._vitest import run_vitest  # verified: packages/ai-parrot-server/tests/ui/_vitest.py (used by test_vitest_a2ui_linked_types.py)


def test_echarts_chart_ready_vitest() -> None:
    """ECharts onChartReady lifecycle vitest passes."""
    run_vitest("src/lib/components/visualizations/ECharts.test.ts")
```

### FILL IN checklist
- [ ] detach before dispose (both sites) / attach after setOption / identity $effect
- [ ] echarts mocking and four test bodies

---

## Acceptance Criteria

- [ ] Callers without the prop behave exactly as today.
- [ ] Callback lifecycle tests pass; `pnpm build` succeeds.

## Validation Commands
- `pytest packages/ai-parrot-server/tests/ui/test_vitest_echarts_chart_ready.py -q`

---

## Test Specification
See blueprint.

---

## Agent Instructions

Standard FEAT-754 procedure (vitest in `packages/ai-parrot-server/ui`); close with
`scripts/sdd/close_task.sh TASK-4790 a2ui-c4-diagrams verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
