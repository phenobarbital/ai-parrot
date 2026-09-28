# TASK-3845: A2UISurface.svelte per-widget refresh and Refresh all

**Feature**: FEAT-610 — A2UI Linked Surfaces E2E example
**Spec**: `sdd/specs/a2ui-linked-e2e-test.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3844
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (FEAT-610). The surface needs a "Refresh all" control for linked surfaces and a per-source
refresh control. Every widget has its own source key (spec §2), so one control per source key = per-widget refresh.

---

## Scope

- `laneProxy` gains `refreshSource: (key) => lane?.refreshSource(key) ?? Promise.resolve()`.
- In the `{#if sources}` notices block: a `Refresh all` button (`data-testid="refresh-all"`) calling
  `laneProxy.refreshAll()`, and per source entry a small button (`data-testid="refresh-{key}"`) calling
  `laneProxy.refreshSource(key)`. Keep the persisted-surface `serverRefresh` button as is.
- Svelte 5 runes only. Extend `A2UISurface.linked.test.ts`.

**NOT in scope**: `A2UINode.svelte`; any new catalog prop (spec Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte` | MODIFY | laneProxy + controls |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.linked.test.ts` | MODIFY | two new cases |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `f20d82332` (dev, 2026-09-29). Re-check line numbers before editing — earlier tasks in this
> feature may have shifted them.

### Existing Signatures to Use
```svelte
<!-- packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte -->
	const laneProxy: LinkedLane = {                                           // line 101
		refreshAll: () => lane?.refreshAll() ?? Promise.resolve(),            // line 105 (anchor)
	};
	let sourceEntries = $derived(sources ? Object.entries(statuses) : []);    // ≈ line 155
			{#each sourceEntries as [key, status] (key)}                       // ≈ line 167
			{#if persistedSurfaceId}                                           // ≈ line 188
```
```ts
// A2UISurface.linked.test.ts — envelopeWithSource(sourceOverrides) helper at line 25; mocks '$lib/features'
```
### Does NOT Exist
- ~~A `refresh` component prop / Grid container~~ — refresh is a renderer affordance only.
- ~~A per-widget refresh HTTP endpoint~~ — client-side lane only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.linked.test.ts",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: depends on TASK-3844: laneProxy forwards LinkedLane.refreshSource, which TASK-3844 adds to linked/index.ts.
- Production data: any live query uses `ENV=prod`, read-only. Never commit tokens, passwords or DSNs.
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src:packages/ai-parrot-server/src`
  as needed; never `uv sync` inside a worktree.

---

## Implementation Blueprint

**Steps (in order)**
1. Add `refreshSource` to `laneProxy` (TypeScript requires every `LinkedLane` member once TASK-3844 lands).
2. Add the controls inside the notices block — there, because statuses are keyed by source key already.
3. Extend the linked test; run the wrapper.

```svelte
<!-- A2UISurface.svelte — AFTER — insert below `		refreshAll: () => lane?.refreshAll() ?? Promise.resolve(),` (verified: A2UISurface.svelte:105) -->
<!-- occurrences: 1 -->
		refreshSource: (key) => lane?.refreshSource(key) ?? Promise.resolve(),
```
```svelte
<!-- A2UISurface.svelte — inside `{#each sourceEntries as [key, status] (key)}`, after the status `{/if}` -->
<!-- FILL IN: disambiguate — quote the `{/if}` + `{/each}` lines to attach uniquely -->
				<button type="button" class="text-xs underline self-start" data-testid="refresh-{key}"
					onclick={() => laneProxy.refreshSource(key)}>Refresh {key}</button>
<!-- and BEFORE `{#if persistedSurfaceId}` (occurrences: FILL IN via grep -c) -->
			<button type="button" class="text-xs underline self-start" data-testid="refresh-all"
				onclick={() => laneProxy.refreshAll()}>Refresh all</button>
```
**Why**: buttons call the proxy (stable across envelope changes), never `lane` directly.

```ts
// A2UISurface.linked.test.ts — append two cases
it('per-source refresh button calls refreshSource(key) once', async () => { /* FILL IN — AC5: click refresh-sales; assert one fetch for sales */ });
it('Refresh all re-fetches every source', async () => { /* FILL IN — AC5/AC8 */ });
```
**FILL IN checklist**
- [ ] anchors in the each-block; the two test bodies (reuse the file's fetch mock).

---

## Acceptance Criteria

- [ ] "Refresh all" and a per-source refresh control render for linked surfaces (AC5).
- [ ] clicking a per-source control issues exactly one fetch for that source (AC8).
- [ ] existing linked + baked surface suites still pass.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_surface.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `A2UISurface.linked.test.ts` (+2) | AC5, AC8 |

---

## Agent Instructions

1. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
2. Implement exactly the files listed; no refactors outside scope.
3. `ruff check --fix` the touched Python files; run the Validation Commands.
4. Commit code only: `feat(a2ui-linked-e2e-test): TASK-3845 — A2UISurface.svelte per-widget refresh and Refresh all`.
5. Close with `scripts/sdd/close_task.sh TASK-3845 a2ui-linked-e2e-test verified` and fill the Completion Note.

---

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 108.7s · Tokens: n/a

Implemented per spec: laneProxy.refreshSource + Refresh all / per-source buttons (diff reviewed). NOT VERIFIED: A2UISurface.linked.test.ts fails 4/6 on clean dev already (svelte effect_update_depth_exceeded, ledger issue:da9483df1382); in the worktree the 2 new refresh tests fail with the same error (6 failed | 2 passed of 8), so the vitest pass cannot be confirmed in this environment. Closed as partial. Merge-tier sweep skipped (env-red, see TASK-3842).
