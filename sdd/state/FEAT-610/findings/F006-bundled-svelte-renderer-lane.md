---
id: F006
query_id: Q006
type: read
intent: Check whether any existing JS/TS renderer implements the linked refresh, and at what granularity
executed_at: 2026-09-28T18:21:51Z
parent_id: null
depth: 0
---
# F006 — Only the bundled Svelte UI implements the lane; no per-widget refresh button exists
## Summary
The single existing executor is the Svelte admin UI lane in
`packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/` (types, conditions, dsl, fetch,
scheduler, ref, index + vitest files). `createLinkedLane` exposes `start/stop`, `setParam(source, name, value)`
(re-fetches one source; used by FilterBar `parrot_param`) and `refreshAll()` (sequential, dependency-ordered,
sends `refresh: true`). `A2UISurface.svelte` becomes stateful, patches `dataModel` via `onUpdate`, and renders
per-source text notices ("data as of …", "unavailable", "could not load"), but no Svelte component calls
`refreshAll` — there is no refresh button, and no per-widget refresh API. Nothing in `parrot/outputs` (HTML
renderers/baking) executes descriptors; they only see the snapshot (G9). `dsl.ts` now has proper exports (the
missing-export defect filed from TASK-3795 as issue:2eb833fd70f9 appears fixed on dev).
## Citations
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts`
  lines: 54-61, 140, 218-235
  symbol: `LinkedLane`, `createLinkedLane`
  excerpt: |
    export interface LinkedLane {
      start(): void;
      stop(): void;
      /** Re-fetch `source` with `name` overridden (FilterBar parrot_param). Locked names are ignored. */
      setParam(source: string, name: string, value: unknown): Promise<void>;
      /** Manual refresh of every source (policy manual / user button). */
      refreshAll(): Promise<void>;
    }
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte`
  lines: 100-106, 166-185
  symbol: `laneProxy`
  excerpt: |
    const laneProxy: LinkedLane = {
      ...
      refreshAll: () => lane?.refreshAll() ?? Promise.resolve(),
    };
    setContext(LINKED_LANE_CONTEXT, laneProxy);
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/dsl.ts`
  lines: 12, 32
  symbol: `TransformError`, `applyTransform`
  excerpt: |
    export class TransformError extends Error {
    export function applyTransform(rows: Row[], spec: TransformSpec | null | undefined, frames: Record<string, Row[]>): Row[] {
## Implications
- The HTML5 (echarts + grid.js) renderer in FEAT-610 is net-new; the TS files (`conditions.ts`, `dsl.ts`, `fetch.ts` `selectFrame`, `scheduler.ts`) are the closest reference to port to plain JS, but they import `$lib` aliases and are not published standalone.
- A per-widget refresh button must be designed in FEAT-610 (map widget → source key → re-fetch); it is not in the contract.
- TASK-3795 noted real vitest/svelte-check never ran in the worktree (only an esbuild syntax check) — treat the Svelte lane as lightly verified.
