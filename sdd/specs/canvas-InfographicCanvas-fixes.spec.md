---
type: feature
base_branch: dev
feature_id: FEAT-666
tags: [bugfix, frontend, a2ui]
---

# FEAT-666 — InfographicCanvas share-token passthrough

**Ledger issue**: `issue:cc87f5b49f44`

## Problem

`InfographicCanvas.svelte` renders `<A2UISurface>` on line 358 without
passing a `shareToken` prop. `A2UISurface` accepts `shareToken?: string`
(line 38-39) and threads it through to `linked/fetch.ts` where it becomes
a `?share=` query param on data-fetch URLs. Without it, share-link viewers
who access a linked-surface infographic get 404s from the per-source data
endpoint.

## Solution

1. Accept an optional `shareToken?: string` prop on `InfographicCanvas`.
2. Forward it to `<A2UISurface shareToken={shareToken} ...>` on line 358.

The caller (`CanvasPanel.svelte` / `AgentChat.svelte`) already has access
to share context via URL params or tab data; wiring is out of scope for
this fix — only the prop passthrough is missing.

## Files

- `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/InfographicCanvas.svelte`
- `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte` (no changes needed, already accepts the prop)

## Acceptance Criteria

- AC1: `InfographicCanvas` accepts `shareToken?: string` in `$props()`.
- AC2: `<A2UISurface>` call site passes `shareToken={shareToken}`.
- AC3: Existing `InfographicCanvas.a2ui.test.ts` passes unchanged.
