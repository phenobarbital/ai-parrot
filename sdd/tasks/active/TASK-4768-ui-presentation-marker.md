# TASK-4768: UI: parrot_presentation reader & kind precedence

**Feature**: FEAT-755 — Inline A2UI Component Routing
**Spec**: `sdd/specs/inline-a2ui-component-routing.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4765
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (marker half). The frontend currently *infers* whether a surface
is a widget, infographic or dashboard from its root component
(`a2ui-kind.ts:30`, the `inferKind()` heuristic the reference doc calls "lossy").

The emitter now states it outright via the surface-level `parrot_presentation`
extension, so this task adds a reader for it and lets it win over the heuristic.

A useful finding from decomposition: `A2UINode.svelte:214-249` **already renders**
KPICard, InfoCard, Timeline and viz-core Graph. Nothing in the renderer needs building
— the gap is purely that nothing tells it "this is an inline chat answer", and that
`ChatBubble` never mounts an A2UI surface at all (TASK-4769).

---

## Scope

- Create `a2ui-presentation.ts` with `PRESENTATION_EXTENSION`, `PresentationExtension`, `getPresentation`, `isInlinePresentation`.
- Make `inferSurfaceKind` prefer the marker's `kind` when present, falling back to today's heuristic.
- Create `a2ui-presentation.test.ts`; extend `a2ui-kind.test.ts` for marker precedence.

**NOT in scope**: `ChatBubble.svelte` (TASK-4769), any change to `A2UINode.svelte` (it already renders all four components), and any change to generated types (the marker lives inside `metadata.extensions`, already typed loosely).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-presentation.ts` | CREATE | Marker reader |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.ts` | MODIFY | Marker precedence over the heuristic |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-presentation.test.ts` | CREATE | Unit tests |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.test.ts` | MODIFY | Precedence tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references from the actual codebase. Use these exact
> imports, class names, and method signatures. DO NOT invent, guess, or assume any
> import, attribute, or method not listed here. Verified against `e21bc561e+ (dev @ 2026-10-27, re-verified at /sdd-task time)`.

### Verified Imports
```python
// a2ui-presentation.ts
import type { A2UIEnvelope, CreateSurface } from './a2ui-types';  // verified: a2ui-types.ts
import type { SurfaceKind } from './a2ui-kind';                   // verified: a2ui-kind.ts
```

### Existing Signatures to Use
```python
// canvas/a2ui/a2ui-kind.ts:30 (line VERIFIED FRESH — spec said :31, it moved)
export type SurfaceKind = 'widget' | 'infographic' | 'dashboard';
export function inferSurfaceKind(surface: CreateSurface): SurfaceKind {
  const root = surface.components.find((c) => c.id === 'root');
  if (!root) return 'widget';
  if (INFOGRAPHIC_LIKE_ROOTS.has(root.component)) { ... }
  return 'widget';
}
export function hasInfographicRoot(envelope: A2UIEnvelope | null | undefined): boolean
export function isLinkedSurface(envelope: A2UIEnvelope | null | undefined): boolean

// The marker the emitter stamps (TASK-4765), at createSurface.metadata.extensions:
//   parrot_presentation: { kind: "widget", inline: true, origin: "chat_turn", component: "KPICard" }

// canvas/a2ui/linked/types.ts — getDataSources() is the existing precedent for reading
// a surface-level extension defensively; mirror its shape.
```

### Does NOT Exist
- ~~`a2ui-presentation.ts`~~ — this task creates it.
- ~~a `kind` field on the A2UI wire format~~ — there is none; `a2ui-kind.ts:4-9` says so explicitly. The marker is an *extension*, not a wire field.
- ~~a generated TS type for `parrot_presentation`~~ — none needed; `metadata.extensions` is already typed loosely (`a2ui-types.ts`). Do NOT hand-edit `src/lib/types/generated/`.
- ~~`inferKind()`~~ — the exported name is `inferSurfaceKind`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-presentation.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.ts",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-presentation.test.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.test.ts",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Svelte 5 / TS strict.** Explicit types on every exported function. No `any` on the public surface.
- **Defensive parsing.** `getPresentation` returns `null` when the extension is absent, is not an object, or lacks the expected fields — a malformed marker must never throw into a render. Mirror `getDataSources()` in `canvas/a2ui/linked/types.ts`.
- **Backwards compatibility is an acceptance criterion**: with no marker, `inferSurfaceKind` must return exactly what it returns today. The existing `a2ui-kind.test.ts` assertions must pass unmodified.
- Only accept a marker `kind` that is a valid `SurfaceKind`; anything else falls back to the heuristic rather than propagating a bad value.
- Tests are `vitest` next to the code; no prettier/eslint step exists — match surrounding formatting.

### References in Codebase
- `canvas/a2ui/a2ui-kind.ts:1-40` — the heuristic, its doc comment, and `SurfaceKind`.
- `canvas/a2ui/linked/types.ts` — `getDataSources()`, the defensive surface-level extension reader to mirror.
- `docs/outputs/a2ui-v1.md:140-158` — the `parrot_*` extension convention.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Business-logic branches, edge
> cases and test bodies are `FILL IN` stubs by design. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `a2ui-presentation.ts` with a defensive reader — *why*: a malformed marker arriving from a server must degrade, not throw into the render tree.
2. Make the marker win in `inferSurfaceKind`, validating the kind first — *why*: the emitter knows what it produced; the heuristic is the fallback.
3. Keep the no-marker path byte-identical — *why*: AC-3; every existing surface must render exactly as before.
4. Write/extend the vitest suites — *why*: AC-1..AC-4.

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-presentation.ts` (CREATE)
```ts
/**
 * Reader for the surface-level `parrot_presentation` extension (FEAT-755).
 *
 * The backend emitter stamps this on every inline chat answer, so a renderer no
 * longer has to infer "widget vs dashboard" from the root component
 * (`a2ui-kind.ts`'s lossy heuristic). Absent or malformed => null, never a throw.
 */
import type { A2UIEnvelope, CreateSurface } from './a2ui-types';
import type { SurfaceKind } from './a2ui-kind';

export const PRESENTATION_EXTENSION = 'parrot_presentation';

export interface PresentationExtension {
  kind: SurfaceKind;
  inline: boolean;
  origin: 'chat_turn' | string;
  component: string;
}

/** The surface-level `metadata.extensions.parrot_presentation`, or null when absent/malformed. */
export function getPresentation(surface: CreateSurface): PresentationExtension | null {
  // FILL IN: defensive read of surface.metadata?.extensions?.[PRESENTATION_EXTENSION];
  //          require an object with a string `component` and a boolean `inline`;
  //          accept `kind` ONLY when it is a valid SurfaceKind, else null.
  //          Mirror getDataSources() in ./linked/types.ts — bounded by AC-1/AC-2
}

/** True when the envelope was produced as an inline chat answer (`inline === true`). */
export function isInlinePresentation(envelope: A2UIEnvelope | null | undefined): boolean {
  // FILL IN: null-safe envelope?.createSurface -> getPresentation -> inline === true
  //          — bounded by AC-2
}
```
**Why this shape**: `isInlinePresentation` takes the whole envelope (not a surface) because that is what `ChatBubble` holds on `message.a2ui_envelope` — TASK-4769 calls it directly in a template guard, so it must be null-safe.

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c 'export function inferSurfaceKind(surface: CreateSurface): SurfaceKind {' packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.ts)
// NOTE: the spec's Edit Sites table says :31 — it moved to :30 on dev. Verified fresh.
// AFTER — at the TOP of `inferSurfaceKind`'s body (verified: a2ui-kind.ts:30), before the
// existing `const root = ...` line:
//   FILL IN: const declared = getPresentation(surface);
//            if (declared) return declared.kind;
//   Then leave the existing heuristic EXACTLY as it is as the fallback.
// Import getPresentation from './a2ui-presentation'.
// — bounded by AC-3/AC-4
```
**Why**: an early return keeps the diff to two lines and leaves the heuristic untouched, which is what makes AC-3 (no behaviour change without a marker) easy to prove.

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-presentation.test.ts` (CREATE)
```ts
import { describe, expect, it } from 'vitest';
import { getPresentation, isInlinePresentation } from './a2ui-presentation';

describe('getPresentation', () => {
  // FILL IN: a well-formed marker parses to all four fields;
  //          absent extensions -> null; a non-object marker -> null;
  //          an invalid `kind` -> null (NOT a coerced value);
  //          no throw for any malformed input — bounded by AC-1
});

describe('isInlinePresentation', () => {
  // FILL IN: inline:true -> true; inline:false -> false;
  //          null / undefined / no-marker envelope -> false — bounded by AC-2
});
```

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.test.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c "describe('inferSurfaceKind', () => {" packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.test.ts)
// AFTER — append cases inside the existing `describe('inferSurfaceKind', ...)` block
// (verified: a2ui-kind.test.ts:14). Do NOT modify the existing assertions — they are
// the AC-3 regression guard.
// FILL IN: a marker with kind:'dashboard' on a KPICard root returns 'dashboard'
//          (marker beats heuristic); an invalid marker kind falls back to the
//          heuristic's answer — bounded by AC-4
```
**Why**: the existing block already covers the heuristic exhaustively; appending to it proves precedence without duplicating fixtures.

### FILL IN checklist
- [ ] `a2ui-presentation.ts::getPresentation` — defensive parse + kind validation; bounded by AC-1
- [ ] `a2ui-presentation.ts::isInlinePresentation` — null-safe envelope check; bounded by AC-2
- [ ] `a2ui-kind.ts::inferSurfaceKind` — two-line early return; bounded by AC-3/AC-4
- [ ] `a2ui-presentation.test.ts` + `a2ui-kind.test.ts` — the four test groups; bounded by AC-1..AC-4

---

## Acceptance Criteria

- [ ] **AC-1**: `getPresentation` returns all four fields for a well-formed marker, and `null` for absent / non-object / invalid-`kind` markers — never throwing.
- [ ] **AC-2**: `isInlinePresentation` is `true` only for `inline === true`; `null`, `undefined` and marker-less envelopes return `false`.
- [ ] **AC-3**: with no marker, `inferSurfaceKind` returns exactly today's result — the existing `a2ui-kind.test.ts` assertions pass unmodified.
- [ ] **AC-4**: a valid marker `kind` wins over the root-component heuristic; an invalid one falls back to it.
- [ ] TypeScript strict passes; no edits under `src/lib/types/generated/`.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pnpm --dir packages/ai-parrot-server/ui vitest run src/lib/components/agents/canvas/a2ui/a2ui-presentation.test.ts`
- `pnpm --dir packages/ai-parrot-server/ui vitest run src/lib/components/agents/canvas/a2ui/a2ui-kind.test.ts`

---

## Test Specification

Create `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-presentation.test.ts` and extend `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.test.ts`.

The existing `describe('inferSurfaceKind', ...)` assertions must pass **unmodified** —
they are the AC-3 regression guard. If one needs changing, the early return has altered
the no-marker path and the change is wrong.

Note this package uses `pnpm` and `vitest`; there is no prettier/eslint step, so match
the surrounding formatting by hand.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug inline-a2ui-component-routing --feature-id FEAT-755`)
2. **Read the spec** at `sdd/specs/inline-a2ui-component-routing.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/inline-a2ui-component-routing.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/inline-a2ui-component-routing.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <ID> inline-a2ui-component-routing verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
