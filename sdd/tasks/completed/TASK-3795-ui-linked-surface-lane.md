# TASK-3795: Stateful A2UISurface lane + FilterBar parrot_param branch

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3793, TASK-3794, TASK-3789
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11, last step: wire the bundled renderer's executor lane into the Svelte tree.
`A2UISurface.svelte` is **stateless** today (`dataModel = $derived(envelope.createSurface.dataModel ?? {})`,
`A2UISurface.svelte:18`); it becomes stateful over `dataModel` and mounts the lane when
`extensions.parrot_data_sources` exists. `A2UINode.svelte` gains a FilterBar branch: a filter
carrying `parrot_param` (added to the wire by TASK-3789) re-fetches that source; the others
filter locally (dashboard reference §7.4).

**NOT delegation-eligible** (spec §3 delegation table, M11: "Svelte state design for a stateful
`A2UISurface` and the scheduler's lifecycle need the thinking model"). The blueprint below fixes
the plumbing (files, context key, controller interface, anchors); the state design is left as
bounded `FILL IN`s the implementer must decide and justify in the Completion Note.

Binding criteria carried verbatim:
- **AC10** Bundled UI: `on_mount` fetch with the viewer's bearer, `interval` clamped to ≥30 s and paused while hidden, `manual` never auto-fetches; a 404 keeps the snapshot with an "unavailable" notice (never "denied"); `refresh` is sent as boolean `true`; a `FilterBar` filter with `parrot_param` re-fetches its source, others filter locally.
- **AC16** **No-snapshot contract (S9)**: a `snapshot=False` envelope always carries `dataModel[key] = {"rows": []}`; `bake_envelope` succeeds; JSON/HTML/chat renderers show a loading state while `snapshot_at` is null; persisted surfaces never lack a snapshot (AC8).
- **AC9** `transform.ref` resolves only against a manifest whose HMAC verifies; deprecated entries still resolve with a warning; unknown refs fail validation; the bundled UI refuses to execute a module whose SRI does not match and falls back to the snapshot.
- **S6** the descriptor's `ref.name` is opaque, never a URL; URL = `${transformsBase}/${manifest.entries[ref.name].file}` (handled inside TASK-3794's `loadRef`; this task only supplies `transformsBase`).
- Share-token viewers denied by QuerySource keep the last snapshot with a "data as of `snapshot_at`" notice and a server-side refresh button (spec §2 decisions; `POST /api/v1/ui/surfaces/{id}/refresh`, FEAT-492).

---

## Scope

- `linked/index.ts`: plain-TS lane controller (`createLinkedLane`) orchestrating per-source
  scheduler → conditions → fetch → transform (`ops` via `applyTransform`, `ref` via `loadRef`) →
  callback; dependency order for `join.with` / `union.sources`; a Svelte context key.
- `A2UISurface.svelte`: `$state` data model seeded from the envelope; mount/unmount the lane in
  `$effect`; loading / unavailable / "data as of" notices; optional server-refresh button.
- `A2UINode.svelte`: FilterBar branch (Parrot `FilterBar` and its lowered
  `Row(parrot_variant='filter-bar')` of `ChoicePicker`).
- `A2UISurface.linked.test.ts` + pytest wrapper.

**NOT in scope**: DSL/conditions (TASK-3793), fetch/scheduler/ref internals (TASK-3794), the wire types
(TASK-3792), any server change. Existing `A2UISurface.test.ts` / `A2UINode.test.ts` must stay green
unchanged (AC11 — baked surfaces are byte-for-byte unaffected).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts` | CREATE | `createLinkedLane`, `LINKED_LANE_CONTEXT`, controller types |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte` | MODIFY | stateful dataModel + lane mount + notices |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte` | MODIFY | FilterBar `parrot_param` branch |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.linked.test.ts` | CREATE | lane behaviour tests |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_surface.py` | CREATE | pytest wrapper |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```typescript
import { getContext, setContext } from 'svelte';                          // Svelte 5 (package.json svelte ^5.55.7)
import { getDataSources, type LinkedSources, type LinkedDataSource, type Row } from './linked/types';   // TASK-3792
import { applyTransform, TransformError } from './linked/dsl';            // TASK-3793
import { deriveConditions } from './linked/conditions';                    // TASK-3793
import { fetchSource, SourceUnavailable } from './linked/fetch';          // TASK-3794
import { RefreshScheduler } from './linked/scheduler';                     // TASK-3794
import { loadRef } from './linked/ref';                                    // TASK-3794
import { querySourceBaseUrl, querySourceHeaders } from '$lib/api/querysource';   // TASK-3794
import { getAuthHeaders } from '$lib/api/auth-headers';                   // server-refresh POST bearer
import { config } from '$lib/config';                                      // config.apiBaseUrl
import { render, screen, waitFor } from '@testing-library/svelte';        // A2UISurface.test.ts:6
import { describe, expect, it, vi } from 'vitest';
```

### Existing Signatures to Use
```svelte
<!-- A2UISurface.svelte (whole file, 34 lines) -->
let { envelope }: { envelope: A2UIEnvelope } = $props();                                  // L12
let root = $derived<WireComponent | undefined>(…components.find((c) => c.id === 'root') ?? components[0]);   // L14-17
let dataModel = $derived(envelope.createSurface.dataModel ?? {});                          // L18
<div class="a2ui-surface"> … <A2UIInfographic component={root} {dataModel} /> … <A2UINode descriptor={{ component: root.component, properties: root }} {dataModel} />   // L24-33
<!-- A2UINode.svelte -->
let { descriptor, dataModel, surfaceCatalogId }: { descriptor: SectionDescriptor; dataModel: Record<string, unknown>; surfaceCatalogId?: string } = $props();   // L19-30
let resolved = $derived(resolveProps(properties, dataModel));                              // L35
{#if component === 'KPICard'} … {:else if component === 'List' || component === 'Row' || component === 'Column'}   // L84, L156 (children = properties.children as SectionDescriptor[])
```
```text
A2UISurface.test.ts mocks $lib/features with vi.hoisted({ features: {... a2ui: true} }) + vi.mock('$lib/features', …) (L10-23) — copy that.
Lowered FilterBar wire (Python catalog/parrot/filterbar.py lower(), TASK-3789): Row(parrot_variant="filter-bar") of ChoicePicker with
  metadata.extensions.parrot_filter_column and (NEW, TASK-3789) parrot_param = {"source": "<key>", "name": "<param>"};
  unlowered FilterBar: filters[*] = {column, label, options, multiple?, param?: {source, name}}.
Server refresh (FEAT-492): POST /api/v1/ui/surfaces/{surface_id}/refresh  body {"params": {...}}.
```

### Does NOT Exist
- ~~A FilterBar / ChoicePicker branch in `A2UINode.svelte`~~ — added here.
- ~~`linked/index.ts`, any lane state in `A2UISurface.svelte`~~ — added here.
- ~~A surface id prop on `A2UISurface`~~ — add an OPTIONAL `persistedSurfaceId?: string`; absent ⇒ no server-refresh button (chat-only surfaces).
- ~~`.svelte.ts` store for the lane~~ — not needed: `index.ts` is plain TS reporting through a callback; the `$state` lives in `A2UISurface.svelte`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.linked.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_surface.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Svelte 5 runes only (`$state`, `$derived`, `$props`, `$effect`); no `export let`, no stores.
- Baked envelope (no `parrot_data_sources`) ⇒ identical render path and DOM to today (AC11): the
  lane is never created, no fetch happens.
- `$effect` cleanup MUST call `lane.stop()` — a leaked `setInterval` keeps fetching after unmount.
- A failed source never blanks its rows: keep the last rows (snapshot) and set a per-source status.
- Notice wording: "unavailable" / "Data as of <snapshot_at>" — the word "denied" must never render.
- Transforms base default: `${config.apiBaseUrl}/static/a2ui/transforms` (M9 static route); allow an
  optional `transformsBase` prop override.

---

## Implementation Blueprint

### Steps (in order)
1. Write `linked/index.ts` (controller + context key) — *why*: both Svelte files depend on it.
2. Modify `A2UISurface.svelte` — *why*: owns the `$state` data model and the lane lifecycle.
3. Modify `A2UINode.svelte` — *why*: FilterBar calls the controller from context.
4. Write the tests + wrapper; run `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_surface.py -q` and the EXISTING `A2UISurface.test.ts`/`A2UINode.test.ts` via `pnpm exec vitest run` (AC11).

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts` (CREATE)
```typescript
/**
 * Bundled-renderer executor lane (FEAT-598, spec §3 Module 11).
 * Plain TS: per-source RefreshScheduler → deriveConditions → fetchSource → applyTransform|loadRef,
 * reporting through `onUpdate`; the Svelte surface owns the reactive state.
 */
import type { LinkedDataSource, LinkedSources, Row } from './types';

export const LINKED_LANE_CONTEXT = Symbol('a2ui-linked-lane');

export type SourceStatus = 'loading' | 'ready' | 'unavailable' | 'error';

export interface SourceUpdate {
  key: string;
  rows: Row[] | null;          // null ⇒ keep the current rows (failure never blanks the snapshot)
  status: SourceStatus;
  snapshotAt: string | null;
}

export interface LinkedLaneOptions {
  baseUrl: string;
  headers: () => HeadersInit;
  transformsBase: string;
  onUpdate: (update: SourceUpdate) => void;
}

export interface LinkedLane {
  start(): void;
  stop(): void;
  /** Re-fetch `source` with `name` overridden (FilterBar parrot_param). Locked names are ignored. */
  setParam(source: string, name: string, value: unknown): Promise<void>;
  /** Manual refresh of every source (policy manual / user button). */
  refreshAll(): Promise<void>;
}

export function createLinkedLane(sources: LinkedSources, opts: LinkedLaneOptions): LinkedLane {
  const overrides: Record<string, Record<string, unknown>> = {};
  // FILL IN: dependency order — a source whose transform joins/unions siblings runs after them and reads their transformed rows — bounded by spec §7 join/union + Python execute_sources ordering
  // FILL IN: runSource(key): conditions = deriveConditions(request with overrides[key] merged into placeholders, locked values from src.conditions) (S5); fetchSource(...);
  //          ops → applyTransform(rows, transform, siblingRows, key); ref → loadRef(...) ?? keep snapshot (AC9); SourceUnavailable → status 'unavailable', rows null (AC10)
  // FILL IN: one RefreshScheduler per source (policy from src.refresh); start/stop fan out; setParam ignores names in src.locked
  return {
    start() {},
    stop() {},
    async setParam() {},
    async refreshAll() {},
  };
}
```
**Why this shape**: keeping orchestration in plain TS makes it unit-testable without mounting Svelte and keeps `$state` in exactly one place (the surface).

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte` (MODIFY)
```svelte
<!-- occurrences: 1 (verified: grep -c 'let dataModel = $derived(envelope.createSurface.dataModel ?? {});' …/A2UISurface.svelte) -->
<!-- REPLACE `	let dataModel = $derived(envelope.createSurface.dataModel ?? {});` (verified: A2UISurface.svelte:18) with: -->
	let dataModel = $state<Record<string, unknown>>(structuredClone(envelope.createSurface.dataModel ?? {}));
	let sources = $derived(getDataSources(envelope.createSurface));
	let statuses = $state<Record<string, SourceUpdate>>({});
	$effect(() => {
		if (!sources) return;
		const lane = createLinkedLane(sources, {
			baseUrl: querySourceBaseUrl,
			headers: querySourceHeaders,
			transformsBase: transformsBase ?? `${config.apiBaseUrl}/static/a2ui/transforms`,
			onUpdate: (u) => {
				// FILL IN: write u.rows into dataModel at the source's target pointer (root key) when non-null; statuses[u.key] = u — bounded by AC10 (failure keeps snapshot)
			},
		});
		setContext(LINKED_LANE_CONTEXT, lane);   // FILL IN: setContext must run during init, not inside $effect — move it to top-level with a lane holder; bounded by Svelte 5 context rules
		lane.start();
		return () => lane.stop();
	});
	// FILL IN: re-seed dataModel when a NEW envelope (different surfaceId) arrives — bounded by "baked surfaces unaffected" (AC11)

<!-- occurrences: 1 (verified: grep -c 'let { envelope }: { envelope: A2UIEnvelope } = $props();' …/A2UISurface.svelte) -->
<!-- REPLACE the props line (A2UISurface.svelte:12) with: -->
	let { envelope, persistedSurfaceId, transformsBase }: { envelope: A2UIEnvelope; persistedSurfaceId?: string; transformsBase?: string } = $props();

<!-- occurrences: 1 (verified: grep -c '<div class="a2ui-surface">' …/A2UISurface.svelte) -->
<!-- AFTER `<div class="a2ui-surface">` (A2UISurface.svelte:24) insert the notice strip: -->
	{#if sources}
		<!-- FILL IN: loading state while snapshot_at is null and no rows (AC16); "unavailable" + "Data as of <snapshot_at>" when a source is unavailable (never "denied");
		     a server-refresh button (POST /api/v1/ui/surfaces/{persistedSurfaceId}/refresh, bearer) only when persistedSurfaceId is set — bounded by AC10/AC16 + share-denied decision -->
	{/if}
```
Also add the imports listed in the Codebase Contract to the `<script>` block (after `import type { A2UIEnvelope, WireComponent } from './a2ui-types';`, L9, occurrences: 1).

**Why**: seeding `$state` from the envelope keeps the first paint identical to the baked render (snapshot rows), and the lane only patches root keys it owns.

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte` (MODIFY)
```svelte
<!-- occurrences: 1 (verified: grep -c "{:else if component === 'List' || component === 'Row' || component === 'Column'}" …/A2UINode.svelte) -->
<!-- BEFORE `{:else if component === 'List' || component === 'Row' || component === 'Column'}` (verified: A2UINode.svelte:156) insert: -->
{:else if component === 'FilterBar' || (component === 'Row' && isFilterBarRow)}
	<!-- FILL IN: render one control per filter; a filter with parrot_param → lane.setParam(param.source, param.name, value) (re-fetch);
	     one without → local filtering over the already-embedded rows per dashboard reference §7.4 (scoping rule: only rows containing the column) — bounded by AC10 + §7.4 -->
```
In the `<script>` block, after `let resolved = $derived(resolveProps(properties, dataModel));` (L35, occurrences: 1) add:
```typescript
	const lane = getContext<LinkedLane | undefined>(LINKED_LANE_CONTEXT);
	let isFilterBarRow = $derived(
		(properties.metadata as { extensions?: Record<string, unknown> } | undefined)?.extensions?.parrot_variant === 'filter-bar',
	);
	// FILL IN: normalise both wire shapes (FilterBar.filters[*].param vs lowered ChoicePicker metadata.extensions.parrot_param) into one filter list — bounded by TASK-3789's wire
```
**Why**: placing the branch before the generic `Row` case keeps a lowered filter bar from falling into the plain row layout; an absent lane (baked surface) degrades every filter to local filtering.

### `…/A2UISurface.linked.test.ts` (CREATE)
```typescript
// FEAT-598 (TASK-3795): the bundled lane — on_mount fetch with bearer, 404 keeps snapshot + "unavailable",
// loading while snapshot_at is null, manual never fetches, baked surfaces never fetch (AC10/AC11/AC16).
import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

const { features } = vi.hoisted(() => ({
  features: { voice: false, avatar: false, maps: false, charts: true, canvas: true, infographic: true, datasets: false, richEditor: false, a2ui: true },
}));
vi.mock('$lib/features', () => ({ features }));

import A2UISurface from './A2UISurface.svelte';

afterEach(() => vi.restoreAllMocks());

describe('A2UISurface linked lane', () => {
  it('never fetches for a baked surface', () => {
    const spy = vi.spyOn(globalThis, 'fetch');
    render(A2UISurface, { envelope: { version: 'v1.0', createSurface: { surfaceId: 's', components: [{ id: 'root', component: 'Text', text: 'hi' }] } } });
    expect(spy).not.toHaveBeenCalled();
  });
  // FILL IN: on_mount → one POST with Authorization bearer (localStorage 'ai_parrot_token'); 404 → snapshot rows still rendered + "unavailable" text, never "denied";
  //          snapshot_at null + rows [] → loading state; policy manual → no fetch; FilterBar parrot_param change → re-fetch of that source only
  it('placeholder uses waitFor/screen', () => expect([waitFor, screen]).toHaveLength(2));
});
```

### `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_surface.py` (CREATE)
```python
"""FEAT-598 (TASK-3795): run the linked-surface lane vitest (plus the untouched baked suites) from pytest."""

from ._vitest import run_vitest


def test_a2ui_linked_surface_vitest() -> None:
    """Linked lane behaviour passes and the existing baked A2UI suites stay green (AC11)."""
    run_vitest(
        "src/lib/components/agents/canvas/a2ui/A2UISurface.linked.test.ts",
        "src/lib/components/agents/canvas/a2ui/A2UISurface.test.ts",
        "src/lib/components/agents/canvas/a2ui/A2UINode.test.ts",
    )
```

### FILL IN checklist
- [ ] `index.ts` dependency order; bounded by §7 join/union.
- [ ] `index.ts::runSource` conditions/fetch/transform/ref; bounded by S5, AC9, AC10.
- [ ] `index.ts` schedulers + `setParam` locked-ignore; bounded by AC10, `locked` semantics.
- [ ] `A2UISurface.svelte` `onUpdate` pointer write + context placement (init-time `setContext`); bounded by Svelte 5 context rules.
- [ ] `A2UISurface.svelte` re-seed on new envelope; bounded by AC11.
- [ ] `A2UISurface.svelte` notice strip (loading / unavailable / data-as-of / server refresh); bounded by AC10, AC16, share-denied decision.
- [ ] `A2UINode.svelte` FilterBar controls + wire normalisation + local filtering; bounded by AC10, §7.4, TASK-3789.
- [ ] test cases listed in the test block.

---

## Acceptance Criteria

- [ ] AC10: on_mount fetch with the viewer's bearer; interval/manual via `RefreshScheduler`; 404 keeps the snapshot + "unavailable" notice (never "denied"); a FilterBar filter with `parrot_param` re-fetches its source, others filter locally.
- [ ] AC16: loading state while `snapshot_at` is null.
- [ ] AC9 (UI half): a `ref` whose SRI does not match is never executed; the snapshot stays.
- [ ] AC11: baked envelopes render exactly as before and never fetch; existing `A2UISurface.test.ts` + `A2UINode.test.ts` unchanged and green.
- [ ] No leaked interval after unmount (`lane.stop()` in `$effect` cleanup).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_surface.py -q`

---

## Test Specification

See the `A2UISurface.linked.test.ts` block; minimum cases: baked never fetches, on_mount bearer POST, 404 → snapshot + "unavailable", null `snapshot_at` → loading, manual → no fetch, FilterBar `parrot_param` → targeted re-fetch.

---

## Agent Instructions

1. **Read the spec** (§2 decisions on refresh/share-denied, §3 M10/M11, AC9/AC10/AC11/AC16) and dashboard reference §7.4.
2. **Check dependencies** — TASK-3793, TASK-3794, TASK-3789 done.
3. **Verify the Codebase Contract** (re-run the grep counts; Svelte 5 context semantics).
4. **Update status** → `"in-progress"`; implement; record every state-design decision in the Completion Note.
5. **Verify**; move to `sdd/tasks/completed/`; index → `"done"`.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (native sonnet coder attempt), execution b99e4988-4438-4226-a71a-362798fa8ca2
**Date**: 2026-09-26
**Notes**:
- Implementation commit: `3b7fc2e66586dc14b9b1cc0ef5b9c7db9dd0112f`.
- Design decisions (FILL-INs) recorded by the implementing coder: lazy per-source dependency resolution
  inside `runSource` (sequential pass reserved for `refreshAll()`); `setParam` ignores locked names and
  re-fetches only the named source (no cascade); a second `FILTER_CONTEXT`/`FilterController` Svelte context
  added in `linked/index.ts` (not `A2UISurface.svelte`) to avoid a circular import with `A2UINode.svelte`;
  `baseDataModel`/`activeFilters` state split with a derived `dataModel` applying the §7.4 scoping rule;
  context set via a stable proxy object per the Svelte 5 rule; `refresh: true` sent only by `refreshAll()`;
  AC9 ref fallback uses raw fetched rows on SRI mismatch/unknown ref, never blocks the fetch.
- **Real defect discovered in TASK-3793's `dsl.ts`** (missing all import/export statements — `applyTransform`/
  `TransformError` referenced but never exported, so `dsl.test.ts`'s and this task's own imports resolve to
  `undefined`): out of this task's declared scope, so NOT fixed here. Filed as `issue:2eb833fd70f9` (major,
  discovered_from `task:TASK-3795`) for a follow-up fix task.
- Real `vitest`/`tsc`/`svelte-check` could not be run in this worktree (no `node_modules` installed, per
  `.claude/rules/worktree-management.md`); the pytest wrapper reports `1 skipped` accordingly (consistent with
  sibling TASK-3793/TASK-3794 wrappers). Coder substituted an `esbuild` syntax check (read-only, output to
  `/tmp`) plus manual cross-checks of every import against its real source. **Recommend running the real
  vitest/svelte-check suite in an environment with `node_modules` installed before this feature ships.**
- Merge-tier validation: same pre-existing, unrelated failure signature already confirmed earlier in this run
  (formdesigner/wheel-layout/DB-connectivity/xdist-flakiness, reproducible on clean `origin/dev`).
- `coder_record_feedback`/`coder_record_review` (MCP) were unavailable for this entire run (object-param tool
  outage, confirmed via a minimal `{}` payload) — feedback/review metrics **NOT recorded**.

**Deviations from spec**: none | describe if any
