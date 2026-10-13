# TASK-4287 — Pass shareToken from InfographicCanvas to A2UISurface

- **Feature**: canvas-InfographicCanvas-fixes
- **Feature ID**: FEAT-666
- **Spec**: sdd/specs/canvas-InfographicCanvas-fixes.spec.md
- **Status**: pending
- **Priority**: high
- **Estimated effort**: S
- **Depends-on**: []

## Context

`InfographicCanvas.svelte` renders `<A2UISurface>` on line 358 without a
`shareToken` prop. `A2UISurface` accepts it (line 38-39) and threads it to
the linked-surface data fetcher as a `?share=` query param. Without it,
share-link viewers of linked-surface infographics get 404s.

## Scope

- Add `shareToken?: string` to `InfographicCanvas`'s `$props()`.
- Forward it to the `<A2UISurface>` call on line 358.

### NOT in scope

- Wiring `shareToken` from parent components (CanvasPanel, AgentChat).
- Changes to A2UISurface itself (it already accepts the prop).

## Files to Modify

- `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/InfographicCanvas.svelte`

## Codebase Contract

### Verified Imports
- `A2UISurface` — imported on line 21 of InfographicCanvas.svelte

### Existing Signatures
- `A2UISurface $props: { envelope: A2UIEnvelope; persistedSurfaceId?: string; transformsBase?: string; shareToken?: string }` — A2UISurface.svelte:37-39

## Acceptance Criteria

- AC1: `InfographicCanvas` accepts `shareToken?: string` in its `$props()` destructuring.
- AC2: `<A2UISurface>` call passes `shareToken={shareToken}`.
- AC3: Existing `InfographicCanvas.a2ui.test.ts` passes.

## Validation Commands

```bash
cd packages/ai-parrot-server/ui && npx vitest run src/lib/components/agents/canvas/InfographicCanvas.a2ui.test.ts --reporter=verbose 2>&1 | tail -20
```

## Completion Note

(filled on completion)
