# TASK-4791: `A2UIGraph.svelte` C4 types, symbols and pure frame computation

**Feature**: FEAT-754 — C4 architecture diagrams as a `Graph` kind
**Spec**: `sdd/specs/a2ui-c4-diagrams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6, pure half. Only the wire shape of spec §2 is needed (frozen), so this runs in
parallel with the Python tasks. Adds the C4 types, `c4SymbolFor`, `computeBoundaryFrames` and the C4
path inside the pure `buildGraphOption`. The mounted projection lifecycle is TASK-4792.

---

## Scope

- Types: `C4Level`, `C4ElementType`, `C4BoundaryType`, `RelHint`, `BoundaryFrame`; new optional props on
  `GraphNodeProps`, `GraphEdgeProps`, `GraphGroupProps`, `GraphLayoutProps`, `GraphProperties` (spec §3 M6 skeleton).
- `c4SymbolFor`, `computeBoundaryFrames` (abstract layout coords; `[]` unless `hasCompletePositions`; padding 20 × depth;
  member positions ∪ child frames, nested via `parent`).
- `buildGraphOption` C4 path: symbols/captions, dashed `*_ext`, `label + "\n[technology]"`, tooltip lines,
  bidirectional `symbol: ['arrow','arrow']`, edge label `"<label> [<technology>]"`, `hint` ignored. NO `graphic` frames in the option.
- Non-C4 output byte-identical.
- Append the 8 pure vitest cases to `A2UIGraph.test.ts`.

**NOT in scope**: `onChartReady` usage, projection, the 4 lifecycle tests (TASK-4792); `A2UINode.svelte`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte` | MODIFY | types + pure C4 path |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.test.ts` | MODIFY | 8 pure cases |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_graph.py` | CREATE | pytest wrapper running A2UIGraph.test.ts (repo convention) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import { buildGraphOption, hasCompletePositions, type GraphProperties } from './A2UIGraph.svelte';  // verified: A2UIGraph.test.ts:5-6
```

### Existing Signatures to Use
```ts
// A2UIGraph.svelte <script module> (verified at 65144d730)
export type GraphNodeState  14-20;  export interface GraphNodeProps { 22-30;  GraphEdgeProps 32-38;  GraphGroupProps 40-44;
GraphPosition 46-49;  GraphLayoutProps 51-56;  GraphSelectionProps 58-61;  GraphProperties 65-76
export const STATE_TO_STATUS 80-87
export function hasCompletePositions(properties: GraphProperties): boolean   // 106-110
export function tooltipText(...)                                             // 116 (reuse for meta lines)
export function buildGraphOption(properties: GraphProperties, resolveColor: (token: string) => string = (token) => token): Record<string, unknown>  // 131-134
    const usePositions = hasCompletePositions(properties);                   // 135
// A2UIGraph.test.ts: describe 10; tests 11, 53, 69, 81, 93 (`  it('represents node group membership', () => {` at 93)
```

### Does NOT Exist
- ~~`computeBoundaryFrames`, `c4SymbolFor`, `BoundaryFrame`~~ — created HERE.
- ~~raw-coordinate `graphic` entries in `buildGraphOption`~~ — forbidden.
- ~~mermaid / dagre / elkjs npm packages~~.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.test.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_graph.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the type aliases and optional props — *why*: wire shape mirrors spec §2.
2. Add `c4SymbolFor` and `computeBoundaryFrames` as pure exports.
3. Branch inside `buildGraphOption` only when `properties.kind === 'c4'`.
4. Append tests; confirm the existing five still pass untouched.

### `A2UIGraph.svelte` (MODIFY, `<script module>`)
```ts
// occurrences: 1 (verified: grep -c '  export interface GraphNodeProps {' A2UIGraph.svelte → line 22) — BEFORE it:
  export type C4Level = 'context' | 'container' | 'component' | 'dynamic';
  export type C4ElementType = 'person' | 'person_ext' | 'system' | 'system_ext' | 'system_db' | 'system_db_ext'
    | 'system_queue' | 'system_queue_ext' | 'container' | 'container_ext' | 'container_db' | 'container_db_ext'
    | 'container_queue' | 'container_queue_ext' | 'component' | 'component_ext' | 'component_db'
    | 'component_db_ext' | 'component_queue' | 'component_queue_ext';
  export type C4BoundaryType = 'enterprise' | 'system' | 'container' | 'generic';
  export type RelHint = 'up' | 'down' | 'left' | 'right' | 'back';
  export interface BoundaryFrame { id: string; label: string; depth: number; x: number; y: number; w: number; h: number }
// add to interfaces: GraphNodeProps { c4Type?: C4ElementType; technology?: string; description?: string }
//   GraphEdgeProps { technology?: string; hint?: RelHint; bidirectional?: boolean }
//   GraphGroupProps { parent?: string; c4Type?: C4BoundaryType }
//   GraphLayoutProps { shapeInRow?: number; boundaryInRow?: number }
//   GraphProperties { level?: C4Level }   — FILL IN: confirm GraphProperties.kind union includes 'c4'

  /** ECharts symbol + caption + external flag for a C4 element type (table in spec §3 M6). */
  export function c4SymbolFor(c4Type: C4ElementType | undefined): { symbol: string; caption: string; external: boolean } {
    const t = c4Type ?? '';
    const external = t.endsWith('_ext');
    if (t.startsWith('person')) return { symbol: 'circle', caption: 'Person', external };
    if (t.includes('_db')) return { symbol: 'roundRect', caption: '[DB]', external };
    if (t.includes('_queue')) return { symbol: 'rect', caption: '[Queue]', external };
    return { symbol: 'rect', caption: '', external };
  }

  /** Nested boundary frames from member positions (mirror of the backend's `_group_boxes`); [] unless positions are complete. */
  export function computeBoundaryFrames(properties: GraphProperties): BoundaryFrame[] {
    if (!hasCompletePositions(properties)) return [];
    // FILL IN: children-first union of member points and child frames, padding 20 per side,
    //          depth from parent chain, label "<label> [<c4Type> boundary]" — bounded by spec §3 M6 (d)
    return [];
  }

// occurrences: 1 (verified: grep -c '    const usePositions = hasCompletePositions(properties);' → line 135)
// FILL IN: after it, `const isC4 = properties.kind === 'c4';` and apply (a)–(c) of spec §3 M6 to node/edge
//          mapping only when isC4 — non-C4 objects must be byte-identical (no new keys, same key order)
```

### `A2UIGraph.test.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c "  it('represents node group membership', () => {" → line 93) — append AFTER that test's closing `});`
  it('renders c4 boundary frames from complete positions', () => { /* FILL IN */ });
  it('nests child boundary frames inside their parent', () => { /* FILL IN */ });
  it('maps c4 element types to symbols and captions', () => { /* FILL IN */ });
  it('dashes external elements', () => { /* FILL IN */ });
  it('adds technology as a second label line', () => { /* FILL IN */ });
  it('draws bidirectional edges with two arrowheads', () => { /* FILL IN */ });
  it('c4 without positions falls back to circular with no frames', () => { /* FILL IN */ });
  it('non-c4 option is unchanged by the c4 path', () => { /* FILL IN */ });
// FILL IN: import computeBoundaryFrames, c4SymbolFor in the import line (5-6)
```

### `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_graph.py` (CREATE)
```python
"""FEAT-754 (TASK-4791): run the A2UIGraph vitest from pytest (validation contract)."""

from ._vitest import run_vitest  # verified: packages/ai-parrot-server/tests/ui/_vitest.py


def test_a2ui_graph_vitest() -> None:
    """A2UIGraph option/frame vitest passes."""
    run_vitest("src/lib/components/agents/canvas/a2ui/A2UIGraph.test.ts")
```

### FILL IN checklist
- [ ] `computeBoundaryFrames` algorithm; C4 node/edge mapping; 8 test bodies

---

## Acceptance Criteria

- [ ] 8 new pure cases pass; existing five unchanged.
- [ ] `buildGraphOption` emits no raw `graphic` frames.

## Validation Commands
- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_graph.py -q`

---

## Test Specification
Spec §3 M6 vitest names (first eight).

---

## Agent Instructions

Standard FEAT-754 procedure; close with `scripts/sdd/close_task.sh TASK-4791 a2ui-c4-diagrams verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: opus (native), attempt 1
**Date**: 2026-10-27
**Notes**: vitest A2UIGraph.test.ts 13/13 passed (coder and sdd-worker) + pytest wrapper. Engine task/merge-tier gate's vitest runner stayed red (`pnpm exec vitest`: "Command vitest not found" in the validation sandbox, exit 254) although the same command passes from a normal shell; merged on explicit user authorization (manual `git merge --no-ff`) with sdd-worker-run test evidence. finalize_task not used: it requires a green engine validation ref.

**Deviations from spec**: none
