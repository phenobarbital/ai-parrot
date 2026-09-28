---
id: F035
query_id: Q030
type: read
intent: Existing JS/TS A2UI renderer in the admin UI and its chart/table libraries
executed_at: 2026-09-28T18:24:17Z
parent_id: null
depth: 0
---
# F035 — Bundled Svelte renderer (A2UISurface/A2UINode): layerchart for Chart, ECharts only for Graph, plain table
## Summary
The admin UI ships a display-only A2UI v1.0 renderer at `ui/src/lib/components/agents/canvas/a2ui/`: `A2UISurface.svelte` (surface + linked lane mount + refresh), `A2UINode.svelte` (dispatch by component name). KPICard → `InfographicHeroCardBlock`; Chart → `toChartBlockData()` → `InfographicChartBlock` → `AppChart` (**layerchart**, not echarts); DataTable → `InfographicTableBlock` (positional rows, no grid.js); FilterBar handled un-lowered and lowered; ECharts (`visualizations/ECharts.svelte`, echarts/core) is used only for viz-core `Graph`. The FEAT-598 linked runtime (`linked/`: index/fetch/dsl/conditions/scheduler/ref) is plain TS, framework-free except `fetch.ts` importing `$lib/api/querysource`; `LinkedLane` exposes `start/stop/setParam/refreshAll` — **no per-source refresh method** (refresh is all-sources).
## Citations
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte`
  lines: 204-222
  symbol: `-`
  excerpt: |
    {#if component === 'KPICard'}
    	<InfographicHeroCardBlock label={String(resolved.label ?? '')} value=... trend=... trend_value={resolved.delta ...}
    {:else if component === 'Chart'}
    	<InfographicChartBlock {...toChartBlockData(properties, dataModel)} />
    {:else if component === 'DataTable'}
    	<InfographicTableBlock {...tableData} />
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-chart-adapter.ts`
  lines: 46-69
  symbol: `toChartBlockData`
  excerpt: |
    const x = typeof properties.x === 'string' ? properties.x : 'label';
    const yCols = Array.isArray(properties.y) ? (properties.y as string[]) : [];
    const rawRows = resolveBinding(properties.data, dataModel);
    const labels = rows.map((row) => String(row?.[x] ?? ''));
    const series = yCols.map((col, i) => ({ name: col, values: rows.map(...) }));
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/blocks/InfographicChartBlock.svelte`
  lines: 2-5
  symbol: `-`
  excerpt: |
    // ai-parrot (FEAT-476 TASK-2595): AppChart (layerchart) — gated behind
    // features.charts (spec §3 Module 5 "gate cross-surface imports").
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte`
  lines: 198
  symbol: `-`
  excerpt: |
    import ECharts from '$lib/components/visualizations/ECharts.svelte';
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts`
  lines: 1-19, 54-61
  symbol: `LinkedLane`, `createLinkedLane`
  excerpt: |
    * Plain TS: per-source RefreshScheduler → deriveConditions → fetchSource → applyTransform|loadRef,
    * reporting through `onUpdate`; the Svelte surface owns the reactive state.
    export interface LinkedLane { start(): void; stop(): void;
      setParam(source: string, name: string, value: unknown): Promise<void>;
      refreshAll(): Promise<void>; }
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.ts`
  lines: 2
  symbol: `-`
  excerpt: |
    import { postQuery, queryUrl, QuerySourceHttpError } from '$lib/api/querysource';
## Implications
- Nothing in the repo maps A2UI Chart → echarts in JS today; `a2ui-chart-adapter.ts` (rows→labels/series) is the closest TS reference for the row pivot.
- The linked lane (`dsl.ts` transforms, `conditions.ts`, `scheduler.ts`) is the TS reference implementation of FEAT-598 semantics; a standalone HTML example can port/bundle it (swap the `$lib/api/querysource` import) rather than re-implement joins/filters.
- Per-widget refresh needs a new "refresh one source" capability (the lane's internal `runSource(key, forceRefresh)` exists but is not exported on `LinkedLane`).
- The dashboard doc says Chart → AppChart and "never an ECharts option on the wire" — the echarts choice for FEAT-610 is a renderer-side decision, consistent with the contract.
