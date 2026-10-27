# TASK-4769: ChatBubble: render inline A2UI surfaces

**Feature**: FEAT-755 — Inline A2UI Component Routing
**Spec**: `sdd/specs/inline-a2ui-component-routing.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4768
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (bubble half) — the last mile, and the actual UI gap.

Decomposition finding worth stating plainly: `A2UISurface` is imported **only** by
`InfographicCanvas.svelte`. `ChatBubble.svelte` references no A2UI symbol at all
(`grep a2ui ChatBubble.svelte` → 0 hits). So the four components already render
(`A2UINode.svelte:214-249`); what is missing is that the chat bubble never mounts a
surface.

This task adds one lazy import and one `{:else if}` branch, gated by `features.a2ui`
and placed *before* the `structured_chart` branch.

---

## Scope

- Lazily import `A2UISurface` in the existing `$effect` block when the message is an inline A2UI answer.
- Add an `{:else if}` branch before the `structured_chart` branch rendering `A2UISurface`.
- Extend `ChatBubble.test.ts` for the flag-on, flag-off and no-marker cases.
- Create the pytest wrapper `packages/ai-parrot-server/tests/ui/test_vitest_chatbubble_inline_a2ui.py` — the validation contract accepts pytest commands only.

**NOT in scope**: `a2ui-presentation.ts` / `a2ui-kind.ts` (TASK-4768), `A2UINode.svelte` (already renders all four components), and navigator-frontend-next (out of scope for the whole feature).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.svelte` | MODIFY | Lazy import + inline A2UI branch |
| `packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.test.ts` | MODIFY | Render tests |
| `packages/ai-parrot-server/tests/ui/test_vitest_chatbubble_inline_a2ui.py` | CREATE | pytest wrapper so the validation contract can see this vitest file |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references from the actual codebase. Use these exact
> imports, class names, and method signatures. DO NOT invent, guess, or assume any
> import, attribute, or method not listed here. Verified against `e21bc561e+ (dev @ 2026-10-27, re-verified at /sdd-task time)`.

### Verified Imports
```python
// ChatBubble.svelte
import { isInlinePresentation } from '$lib/components/agents/canvas/a2ui/a2ui-presentation';  // TASK-4768
import { features } from '$lib/features';  // verified: ui/src/lib/features.ts:31 declares `a2ui`
// A2UISurface is LAZY — imported inside the existing $effect, like ECharts:
//   import('$lib/components/agents/canvas/a2ui/A2UISurface.svelte').then((m) => (A2UISurfaceComp = m.default));
```

### Existing Signatures to Use
```python
// ChatBubble.svelte:39-45 — the existing lazy-import $effect, the pattern to copy
  $effect(() => {
    if (isUser) return;
    const mode = message.output_mode;                                   // :41
    if (features.charts && mode === "echarts" && message.output && !EChartsComp) {
      import("$lib/components/visualizations/ECharts.svelte").then(
        (m) => (EChartsComp = m.default),
      );

// ChatBubble.svelte:1149 — the branch the new one goes BEFORE
        {:else if message.output_mode === "structured_chart" && message.output}

// ui/src/lib/features.ts:31
  a2ui: __AGENTCHAT_A2UI__,

// canvas/a2ui/a2ui-presentation.ts (TASK-4768)
export function isInlinePresentation(envelope: A2UIEnvelope | null | undefined): boolean
```

### Does NOT Exist
- ~~any `a2ui` reference in `ChatBubble.svelte` today~~ — `grep -c a2ui ChatBubble.svelte` returns **0**; this task introduces the first one.
- ~~`A2UISurface` imported anywhere outside `InfographicCanvas.svelte` / `A2UINode.svelte`~~ — it is not.
- ~~a new renderer for KPICard/InfoCard/Timeline/Graph~~ — `A2UINode.svelte:214-249` already dispatches all four; do NOT add a second rendering stack.
- ~~`message.a2ui_envelope` being absent on the message type~~ — verify the field on the message type before use; the handler passes it through (`handlers/agent.py:2855-2874`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.svelte",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.test.ts",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/ui/test_vitest_chatbubble_inline_a2ui.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Svelte 5 runes only** (`$state`, `$derived`, `$effect`, `$props`) — never `export let`.
- **Lazy import.** `A2UISurface` pulls the whole A2UI render tree; load it inside the existing `$effect` exactly like `ECharts`, never as a top-level import.
- **Gate on `features.a2ui`.** With the flag off, behaviour must be byte-identical to today.
- **Branch order**: the new `{:else if}` goes **before** the `structured_chart` branch at `:1149`, because an A2UI envelope and a structured_chart output can both be present and the envelope wins.
- Guard with all three: `features.a2ui && message.output_mode === "a2ui" && isInlinePresentation(message.a2ui_envelope)`. Without the marker check, a dashboard envelope would render inside a chat bubble.
- No edits under `src/lib/types/generated/`.

### References in Codebase
- `ChatBubble.svelte:39-62` — the lazy-import `$effect` to copy.
- `ChatBubble.svelte:1149` — the `structured_chart` branch to insert before.
- `canvas/InfographicCanvas.svelte` — the only current `A2UISurface` mount, for prop shape.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Business-logic branches, edge
> cases and test bodies are `FILL IN` stubs by design. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Verify `message.a2ui_envelope` exists on the message type — *why*: the template guard dereferences it.
2. Add the lazy import to the existing `$effect` — *why*: matching the ECharts pattern keeps the bundle split the component already relies on.
3. Insert the `{:else if}` before `structured_chart` — *why*: when both are present the envelope is the richer, intended rendering.
4. Extend `ChatBubble.test.ts` for flag-on / flag-off / no-marker — *why*: AC-1..AC-4.

### `packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.svelte` (MODIFY — lazy import)
```svelte
<!-- occurrences: 1 (verified: grep -c '    const mode = message.output_mode;' packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.svelte) -->
<!-- AFTER — inside the existing $effect, below `const mode = message.output_mode;`
     (verified: ChatBubble.svelte:41), alongside the ECharts branch: -->
    if (
      features.a2ui &&
      mode === "a2ui" &&
      isInlinePresentation(message.a2ui_envelope) &&
      !A2UISurfaceComp
    ) {
      import("$lib/components/agents/canvas/a2ui/A2UISurface.svelte").then(
        (m) => (A2UISurfaceComp = m.default),
      );
    }
<!-- FILL IN: declare `let A2UISurfaceComp = $state<Component | null>(null);` beside the
     other lazy component holders, matching their exact declaration style
     — bounded by AC-1 -->
```
**Why**: `A2UISurface` recursively pulls `A2UINode` and every component renderer, so it must stay out of the initial bundle — the same reason `ECharts` is lazy here.

### `packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.svelte` (MODIFY — render branch)
```svelte
<!-- occurrences: 1 (verified: grep -c '        {:else if message.output_mode === "structured_chart" && message.output}' packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.svelte) -->
<!-- BEFORE — insert immediately ABOVE the structured_chart branch
     (verified: ChatBubble.svelte:1149): -->
        {:else if features.a2ui && message.output_mode === "a2ui" && isInlinePresentation(message.a2ui_envelope) && A2UISurfaceComp}
          <!-- FILL IN: mount <A2UISurfaceComp ... /> with the envelope prop.
               Copy the prop names from InfographicCanvas.svelte's A2UISurface usage —
               do NOT invent them — bounded by AC-2 -->
```
**Why**: placing it before `structured_chart` means a turn that produced both an envelope and a chart config renders the envelope, which is the richer artifact the router asked for. The `A2UISurfaceComp` truthiness check keeps the branch inert until the lazy import resolves.

### `packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.test.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c 'describe("ChatBubble", () => {' packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.test.ts)
// AFTER — append cases inside the existing `describe("ChatBubble", ...)` block
// (verified: ChatBubble.test.ts:41). Do NOT modify existing assertions.
// FILL IN:
//   - features.a2ui on + output_mode "a2ui" + inline marker -> A2UISurface mounted
//   - same message with features.a2ui OFF -> NOT mounted, bubble otherwise unchanged
//   - output_mode "a2ui" WITHOUT the inline marker -> NOT mounted (dashboard case)
//   - a structured_chart message is unaffected
// — bounded by AC-1..AC-4
```
**Why**: the flag-off and no-marker cases are the regression guards — they are what prove this change is invisible to every existing surface.


### `packages/ai-parrot-server/tests/ui/test_vitest_chatbubble_inline_a2ui.py` (CREATE)
```python
"""FEAT-755 (TASK-4769): run the ChatBubble inline-A2UI vitest suite from pytest."""

from ._vitest import run_vitest


def test_chatbubble_inline_a2ui_vitest() -> None:
    """ChatBubble mounts A2UISurface for an inline A2UI message under features.a2ui."""
    run_vitest(
        "src/lib/components/agents/ChatBubble.test.ts",
    )
```
**Why**: `check_task_graph` rejects a non-pytest `## Validation Commands` entry — a bare
vitest command is invisible to `select_tests.py`. `_vitest.run_vitest` (verified:
`packages/ai-parrot-server/tests/ui/_vitest.py`) shells out to `pnpm exec vitest run` in
the UI directory and **skips** cleanly when `pnpm` or `node_modules` is absent, so the
suite stays green on a backend-only checkout. Follow
`tests/ui/test_vitest_a2ui_chart_adapter.py` exactly — same import, same one-call shape.

### FILL IN checklist
- [ ] `ChatBubble.svelte` — the `A2UISurfaceComp` state declaration in the file's existing style; bounded by AC-1
- [ ] `ChatBubble.svelte` — the `<A2UISurfaceComp />` mount with prop names copied from `InfographicCanvas.svelte`; bounded by AC-2
- [ ] `ChatBubble.test.ts` — the four render cases; bounded by AC-1..AC-4

---

## Acceptance Criteria

- [ ] **AC-1**: with `features.a2ui` on, an `output_mode: "a2ui"` message carrying an inline marker lazily loads and mounts `A2UISurface` in the bubble.
- [ ] **AC-2**: the mounted surface receives the envelope using the same prop names `InfographicCanvas.svelte` uses — no invented props.
- [ ] **AC-3**: with `features.a2ui` off, the bubble behaves exactly as today; existing `ChatBubble.test.ts` assertions pass unmodified.
- [ ] **AC-4**: an `a2ui` message **without** the inline marker does NOT render in the bubble (that is a dashboard surface, destined for the canvas).
- [ ] Svelte 5 runes only; `A2UISurface` is lazily imported, never top-level; no edits under `src/lib/types/generated/`.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_chatbubble_inline_a2ui.py -q`

---

## Test Specification

Extend `packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.test.ts` inside its existing `describe("ChatBubble", ...)`.

AC-3 and AC-4 are the ones that matter: the flag-off path and the marker-less path must
both leave the bubble exactly as it is today. `A2UISurface.test.ts` and `A2UINode.test.ts`
must pass untouched — this task adds a *mount point*, not a renderer.

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
