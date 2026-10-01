# TASK-3998: Admin UI — map `seriesAxes` / `yAxisLabels` into `ChartBlockData`

**Feature**: FEAT-623 — Infographic → A2UI display hints
**Spec**: `sdd/specs/infographic-a2ui-display-hints.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 5 (admin UI dual axis), first half (5a). The A2UI `Chart` wire
already carries `seriesAxes` (`'left' | 'right'`, parallel to `y`) and
`yAxisLabels` (`[left, right]`). The admin UI drops both at its first hop:
`toChartBlockData` (`a2ui-chart-adapter.ts`) only forwards the singular
`yAxisLabel`. This task makes the hop lossless. It only maps data. Drawing
the second scale is TASK-3999, which depends on the types added here.

This task is independent of the Python side: the wire vocabulary already
exists (`models/outputs.py:397,407`; `catalog/parrot/chart.py:38-44`).

---

## Scope

- Add `axis?: 'left' | 'right'` to `ChartSeriesItem`, and
  `y_axis_labels?: (string | null)[]` to `ChartBlockData`
  (`infographic-types.ts`).
- In `toChartBlockData`:
  - set `item.axis` from `properties.seriesAxes[i]` only when that entry is
    exactly `'left'` or `'right'`;
  - set `data.y_axis_labels` from `properties.yAxisLabels` only when it is an
    array, keeping `string` and `null` entries and coercing anything else to
    `null`.
- Extend `a2ui-chart-adapter.test.ts` with axis-mapping cases.
- Add a pytest wrapper that runs that vitest file (none exists today).

**NOT in scope**:
- rendering a second axis (`InfographicChartBlock.svelte`, `AppChart.svelte`,
  `chart-contract.ts`), which is TASK-3999;
- any Python change;
- `formatA2UIValue` / the en-US pin, which belongs to the `format_cell`
  parity task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/infographic-types.ts` | MODIFY | `ChartSeriesItem.axis`, `ChartBlockData.y_axis_labels` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-chart-adapter.ts` | MODIFY | map `seriesAxes` / `yAxisLabels` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-chart-adapter.test.ts` | MODIFY | axis-mapping cases |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_chart_adapter.py` | CREATE | pytest wrapper running the vitest file |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import { resolveBinding } from './a2ui-binding';  // verified: a2ui-chart-adapter.ts:12
import type { ChartBlockData, ChartSeriesItem, ChartType } from '../infographic/infographic-types';  // verified: a2ui-chart-adapter.ts:13
import { describe, expect, it } from 'vitest';      // verified: a2ui-chart-adapter.test.ts:1
import { toChartBlockData } from './a2ui-chart-adapter';  // verified: a2ui-chart-adapter.test.ts:2
```
```python
from ._vitest import run_vitest  # verified: packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_dsl.py:3
```

### Existing Signatures to Use
```ts
// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/infographic-types.ts
export interface ChartSeriesItem {          // :69
  name: string;                             // :70
  values: (number | null)[];                // :71
  /** Optional per-series color (CSS value). Used when not coloring by sign. */
  color?: string;                           // :73
}
export interface ChartBlockData {           // :76
  // ... x_axis_label?: string;  :82
  y_axis_label?: string;                    // :83
  // ... layout, color_by_sign, positive_color, negative_color (:87-97)
}

// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-chart-adapter.ts
export function toChartBlockData(           // :46
  properties: Record<string, unknown>,
  dataModel: Record<string, unknown>,
): ChartBlockData
//   :59-69  yCols.map((col, i) => { const item: ChartSeriesItem = {...}; if (palette?.[i] !== undefined) item.color = palette[i]; return item; })
//   :67     `if (palette?.[i] !== undefined) item.color = palette[i];`
//   :79     `if (typeof properties.yAxisLabel === 'string') data.y_axis_label = properties.yAxisLabel;`
```
```python
# packages/ai-parrot-server/tests/ui/_vitest.py
UI_DIR = Path(__file__).resolve().parents[2] / "ui"
def run_vitest(*files: str) -> None:  # :14 — runs `pnpm exec vitest run <files>` in UI_DIR; pytest.skip when pnpm/node_modules absent
```
Precedent wrapper (copy its shape): `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_dsl.py`.

### Does NOT Exist
- ~~`ChartSeriesItem.axis`~~ and ~~`ChartBlockData.y_axis_labels`~~: added by this task.
- ~~`ChartBlockData.series_axes`~~: do NOT add a parallel array. The axis lives on each series item.
- ~~A pytest wrapper for `a2ui-chart-adapter.test.ts`~~: none in `packages/ai-parrot-server/tests/ui/` (verified 2026-09-30); this task creates it.
- ~~`seriesAxes` handling anywhere under `packages/ai-parrot-server/ui/src/lib`~~: zero matches today.
- ~~`ui/node_modules`~~ in the main checkout (verified 2026-09-30). Run `pnpm install` in `packages/ai-parrot-server/ui` first, or the wrapper skips.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/infographic-types.ts",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-chart-adapter.ts",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-chart-adapter.test.ts",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_chart_adapter.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Never invent.** Set `axis` only for an exact `'left'` or `'right'`.
  `null`, `undefined` or any other value leaves the key absent, matching
  the adapter's existing "omit when not given" style (`:76-85`).
- Indexing is parallel to `y` (`yCols`). `seriesAxes[i]` belongs to
  `yCols[i]`; a shorter array means the remaining series get no axis.
- `y_axis_label` (singular) keeps its current behaviour. `y_axis_labels`
  is additional; do not derive one from the other.
- The adapter stays pure. No Svelte, DOM or logging.

### References in Codebase
- `a2ui-chart-adapter.ts:58-69`: the palette mapping is the exact pattern to mirror for `seriesAxes`.
- navigator-svelte `chart-option.ts:371,399` (other repo): same `seriesAxes` semantics, given only for reference.

---

## Implementation Blueprint

### Steps (in order)
1. Add the two optional fields to `infographic-types.ts`. *Why*: TASK-3999 and this adapter both type-check against them.
2. Read `properties.seriesAxes` once, next to `palette` (`:58`), and set `item.axis` inside the `yCols.map`. *Why*: it is the same parallel-array pattern as `palette`.
3. Map `yAxisLabels` right after the singular `yAxisLabel` line (`:79`). *Why*: it keeps the axis-label forwarding together.
4. Add vitest cases, then the pytest wrapper. *Why*: the validation contract accepts pytest commands only.

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/infographic-types.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c 'export interface ChartSeriesItem {' infographic-types.ts)
// The inner line `  color?: string;` occurs 4× in the file. Attach INSIDE ChartSeriesItem, i.e. after these 3 lines:
//   export interface ChartSeriesItem {          (verified: :69)
//     name: string;
//     values: (number | null)[];
//     /** Optional per-series color (CSS value). Used when not coloring by sign. */
//     color?: string;                            (verified: :73)
// AFTER — insert below ChartSeriesItem's `color?: string;` (:73)
  /** Value axis this series is drawn against (A2UI `Chart.seriesAxes[i]`). Absent = left. */
  axis?: 'left' | 'right';
```
```ts
// occurrences: 1 (verified: grep -c '  y_axis_label?: string;' infographic-types.ts)
// AFTER — insert below `  y_axis_label?: string;` (verified: :83)
  /** Axis names `[left, right]` (A2UI `Chart.yAxisLabels`); used when any series is on the right. */
  y_axis_labels?: (string | null)[];
```
**Why**: the axis is per series, which keeps `series` the single source of
truth. The labels mirror the wire's `[left, right]` shape.

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-chart-adapter.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c "const palette = Array.isArray(properties.palette)" a2ui-chart-adapter.ts)
// AFTER — insert below `const palette = Array.isArray(properties.palette) ? (properties.palette as string[]) : undefined;` (verified: :58)
  const seriesAxes = Array.isArray(properties.seriesAxes) ? (properties.seriesAxes as unknown[]) : undefined;
```
```ts
// occurrences: 1 (verified: grep -c "if (palette?.\[i\] !== undefined) item.color = palette\[i\];" a2ui-chart-adapter.ts)
// AFTER — insert below `    if (palette?.[i] !== undefined) item.color = palette[i];` (verified: :67)
    const axis = seriesAxes?.[i];
    if (axis === 'left' || axis === 'right') item.axis = axis;
```
```ts
// occurrences: 1 (verified: grep -c "if (typeof properties.yAxisLabel === 'string') data.y_axis_label = properties.yAxisLabel;" a2ui-chart-adapter.ts)
// AFTER — insert below that line (verified: :79)
  if (Array.isArray(properties.yAxisLabels)) {
    data.y_axis_labels = (properties.yAxisLabels as unknown[]).map((l) =>
      typeof l === 'string' ? l : null,
    );
  }
```
**Why**: this mirrors the palette pattern, and an invalid entry is dropped
rather than guessed (spec §5 "Never guess").

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-chart-adapter.test.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c "it('handles an unresolved/missing data binding gracefully (empty rows)', () => {" a2ui-chart-adapter.test.ts)
// AFTER — insert a new `it(...)` group after that test's closing `});` (:85), before the final `});` (:86)
  it('maps seriesAxes onto each series, parallel to y', () => {
    const result = toChartBlockData(
      { type: 'line', x: 'label', y: ['2026', '2025'], data: { path: '/charts/chart-0' }, seriesAxes: ['left', 'right'] },
      dataModel,
    );
    expect(result.series.map((s) => s.axis)).toEqual(['left', 'right']);
  });

  it('omits axis for null / unknown / missing entries', () => {
    // FILL IN: seriesAxes [null, 'up'] and a shorter array [ 'right' ] for two y cols —
    // assert `'axis' in series[k]` is false where the entry is not exactly 'left'|'right'. Bounded by Key Constraints.
  });

  it('forwards yAxisLabels as [left, right], coercing non-strings to null', () => {
    // FILL IN: yAxisLabels ['USD', 7] → y_axis_labels ['USD', null]; absent → key absent; yAxisLabel still set independently.
  });
```

### `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_chart_adapter.py` (CREATE)
```python
"""FEAT-623 (TASK-3998): run the admin UI chart-adapter vitest suite from pytest."""

from ._vitest import run_vitest


def test_a2ui_chart_adapter_vitest() -> None:
    """toChartBlockData maps seriesAxes / yAxisLabels losslessly."""
    run_vitest("src/lib/components/agents/canvas/a2ui/a2ui-chart-adapter.test.ts")
```
**Why**: the validation contract accepts pytest commands only. This uses
the same wrapper as `test_vitest_a2ui_linked_dsl.py`.

### FILL IN checklist
- [ ] `a2ui-chart-adapter.test.ts`: the null / unknown / short-array axis test body (Key Constraints: never invent)
- [ ] `a2ui-chart-adapter.test.ts`: the `yAxisLabels` coercion test body (Scope bullet 2)

---

## Acceptance Criteria

- [ ] `toChartBlockData` sets `series[i].axis` only for an exact `'left'`/`'right'`, and never for other values.
- [ ] `toChartBlockData` sets `y_axis_labels` only when `yAxisLabels` is an array. Non-string entries become `null`.
- [ ] Existing adapter tests still pass unchanged.
- [ ] The vitest suite runs green through the pytest wrapper (with `pnpm install` done in `packages/ai-parrot-server/ui`; otherwise the wrapper skips, and the completion note must say whether it ran or skipped).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_chart_adapter.py -q`

---

## Test Specification

See the blueprint test block. Cases: the mapping (`['left','right']`),
invalid and short arrays, `yAxisLabels` coercion, and the existing cases
unchanged.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug infographic-a2ui-display-hints --feature-id FEAT-623`), never on `dev`.
2. Read the spec (§3 Module 5, §6, §7 stop rule context).
3. No dependencies.
4. Verify the Codebase Contract: re-run each `grep -c` anchor.
5. Mark `"in-progress"` in `sdd/tasks/index/infographic-a2ui-display-hints.json`.
6. Implement from the blueprint and complete the FILL INs.
7. Run the Validation Commands. Run `pnpm install` in the UI dir first if `node_modules` is absent.
8. Commit only the four listed files.
9. Close with `scripts/sdd/close_task.sh TASK-3998 infographic-a2ui-display-hints verified`.
10. Fill in the Completion Note.

---

## Completion Note



**Completed by**: sdd-worker (Claude Sonnet 5.5, fallback sequential loop — parrot-sdd-coder unavailable)
**Date**: 2026-09-30
**Notes**: seriesAxes -> ChartSeriesItem.axis (only exact left/right), yAxisLabels -> y_axis_labels (non-strings -> null); vitest cases + pytest wrapper pass.

**Deviations from spec**: none | describe if any
