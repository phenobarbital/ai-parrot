# TASK-2890: Implement the bundled UI Graph component and catalog-aware dispatch

**Feature**: FEAT-529 - A2UI Graph component under the viz-core catalog
**Spec**: sdd/specs/a2ui-graph-component.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2885
**Assigned-to**: unassigned

## Context

Implements Module 7. The bundled Svelte canvas must distinguish viz-core Graph
from any future same-named Parrot component and render it with the existing
ECharts wrapper, while preserving the current feature flag and placeholder.

## Scope

- Add A2UIGraph.svelte with positioned/circular ECharts graph rendering.
- Resolve component catalog ID from the component, then the surface default.
- Dispatch Graph only for viz-core and keep bare Graph unsupported on Parrot surfaces.
- Map state to semantic Tailwind tokens, render groups/tooltips/selection, and expose node click hook.
- Add explicit catalog ID typing/constant usage in the UI.
- Add Vitest coverage for option building and catalog-aware dispatch.

NOT in scope: action transport/runtime, server-side renderers, new UI graph
dependencies, Graph schema changes, or editing user-moved positions.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte | CREATE | Bundled Graph canvas component |
| packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte | MODIFY | Catalog-aware Graph dispatch |
| packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-types.ts | MODIFY | Wire catalog typing |
| packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.test.ts | CREATE | Graph option and interaction tests |
| packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.test.ts | MODIFY | Dispatch regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    import ECharts from $lib/components/visualizations/ECharts.svelte
    import { features } from $lib/features

### Existing Signatures to Use

    packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte:62-133
    Existing component dispatch is an if/else-if chain by bare component name.

    packages/ai-parrot-server/ui/src/lib/components/visualizations/ECharts.svelte:10,85
    ECharts is imported from echarts/core and has an existing lazy full-build path.

    packages/ai-parrot-server/ui/src/lib/features.ts:31
    The a2ui feature flag is already exposed as features.a2ui.

### Does NOT Exist

- A2UIGraph.svelte - no Graph UI component exists.
- Catalog-aware dispatch in A2UINode.svelte - it currently reads only bare names.
- A2UITimeline.svelte - do not create it for this feature.
- Mermaid/dagre/elkjs/svelteflow/layerchart UI dependencies - use existing ECharts.
- Action runtime transport - onNodeClick is a hook/no-op in this task.

## Implementation Notes

- Use positions with layout none; fall back to circular without positions.
- Use Graph size only as an intent/container class, never as pixels.
- Add Graph catalogId precedence over the surface default.
- Do not dispatch a Graph lacking viz-core identity on a Parrot-default surface.

## Acceptance Criteria

- [ ] Viz-core Graph renders behind features.a2ui.
- [ ] Nodes, links, state roles, groups, selection, tooltips, and aria label are represented.
- [ ] Missing positions use circular layout.
- [ ] Node click calls the optional hook without inventing action transport.
- [ ] Bare Graph on a Parrot surface keeps the unsupported placeholder.
- [ ] Vitest tests pass without new dependencies.

## Test Specification

- A2UIGraph.test.ts: builds ECharts option from positions.
- A2UIGraph.test.ts: falls back to circular without positions.
- A2UINode.test.ts: dispatches viz-core Graph.
- A2UINode.test.ts: rejects bare Graph on Parrot default.

## Agent Instructions

1. Verify existing Svelte component props and ECharts wrapper API before coding.
2. Keep existing dispatch branches and feature flag intact.
3. Run the UI Vitest suite and avoid adding a graph library.

### Completion Note

Implemented as specified. `A2UIGraph.svelte` uses a Svelte 5 `<script
module>` block to export `buildGraphOption`/`hasCompletePositions`/
`STATE_TO_STATUS` as plain, directly-importable functions — tested in
`A2UIGraph.test.ts` with ZERO rendering/canvas involved, exactly the two
named behaviors (positions -> `layout:"none"`, missing/incomplete
positions -> `"circular"`) plus selection/group coverage.

**Token mapping deviation (documented, not a divergence from spec
intent)**: this app's own theme schema (`src/lib/styles/themes/
_schema.css`) has NO `--accent-green`/`--accent-amber`/`--accent-red`/
`--neutral-muted` tokens — those are server-side `DesignSystem` names only.
Mapped the SAME five status roles to this app's own EXISTING shadcn/
Tailwind tokens instead (`--chart-2`/`--chart-3`/`--destructive`/
`--primary`/`--muted-foreground`), resolved to a concrete colour at render
time via the identical `getComputedStyle` probe pattern already
established by `AppChart.svelte` (Canvas rendering cannot resolve `var()`).

**Catalog resolution gap (documented, out of this task's file list)**:
`A2UISurface.svelte` — the true root dispatcher — is NOT in this task's
Files table and was not modified. It does not yet pass its own surface
`catalogId` down as `surfaceCatalogId`, so today only a Graph carrying its
OWN explicit `catalogId` (which `build_graph`/the LLM producer always set,
per spec) resolves correctly from the true root; the `surfaceCatalogId`
prop and its resolution precedence are fully implemented and tested at the
`A2UINode`/nested-descriptor level (both the `descriptor.catalogId` and
`A2UISurface`'s `properties.catalogId` nesting shapes are handled). Wiring
`A2UISurface.svelte`'s own default through is a small, obvious follow-up.

Verification: `pnpm install` (fresh, no lockfile changes) then `vitest run`
→ 294 passed across 45 files (the full UI suite, not just the new tests) —
`A2UIGraph.test.ts` (5), `A2UINode.test.ts` (18, 15 pre-existing + 3 new).
`svelte-check` shows 22 pre-existing errors in UNRELATED files (AppChart.svelte,
AgentChat.svelte, TabsAI.svelte, slider.svelte, ...) and ZERO in any file
this task touched or created.
