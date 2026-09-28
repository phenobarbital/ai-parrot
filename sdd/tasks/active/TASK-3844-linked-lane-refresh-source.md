# TASK-3844: LinkedLane.refreshSource(key) in the admin UI lane

**Feature**: FEAT-610 — A2UI Linked Surfaces E2E example
**Spec**: `sdd/specs/a2ui-linked-e2e-test.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (FEAT-610), design research S4/S5. The TS lane exposes only `refreshAll`
(`index.ts:54-61`), so no renderer can refresh a single widget.

---

## Scope

- Add `refreshSource(key: string): Promise<void>` to `interface LinkedLane` and the returned object.
- Semantics: unknown or `failed` key → no-op; otherwise `delete frames[key]`, `await runSource(key, true)`, then re-run
  (in `executionOrder` order) every source whose `deps` include `key` (transform dependents). Concurrent calls for the
  same key share one in-flight promise.
- `refreshAll()` unchanged (sequential, dependency order — S5).
- New `linked/index.test.ts` + pytest wrapper `tests/ui/test_vitest_a2ui_linked_refresh.py`.

**NOT in scope**: `A2UISurface.svelte` (TASK-3845); the example's vanilla port (TASK-3850).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts` | MODIFY | interface + implementation |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.test.ts` | CREATE | vitest suite |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_refresh.py` | CREATE | pytest wrapper |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `f20d82332` (dev, 2026-09-29). Re-check line numbers before editing — earlier tasks in this
> feature may have shifted them.

### Verified Imports
```ts
import { createLinkedLane, type LinkedLane } from './index';   // index.ts:140, :54
// fetch.ts exports fetchSource + SourceUnavailable (mock './fetch' with vi.mock, as fetch.test.ts / A2UISurface.linked.test.ts do)
```
```python
from ._vitest import run_vitest   # packages/ai-parrot-server/tests/ui/_vitest.py:14
```
### Existing Signatures to Use
```ts
// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts
export interface LinkedLane { start(); stop(); setParam(source, name, value): Promise<void>;
  /** Manual refresh of every source (policy manual / user button). */
  refreshAll(): Promise<void>; }                                           // lines 54-61 (anchor :60)
export function createLinkedLane(sources: LinkedSources, opts: LinkedLaneOptions): LinkedLane   // line 140
async function ensureFrame(key, resolving)  // uses `inFlight[key]` map for dedup (≈ line 150-159)
async function runSource(key: string, forceRefresh: boolean, resolving: Set<string> = new Set()): Promise<void>  // line 161
    async refreshAll() {                                                   // line 225
      const { order } = executionOrder(sources, deps);                     // line 228
// closure state used: sources, deps (key → referenced keys), frames, failed (Set), overrides, inFlight
```
### Does NOT Exist
- ~~`LinkedLane.refreshSource`~~ — created here. ~~A public `runSource`~~ — stays internal.
- ~~An existing `linked/index.test.ts`~~ — create it (lane behaviour is also covered in `A2UISurface.linked.test.ts`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.test.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_refresh.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: no dependency; only writer of linked/index.ts — TASK-3845 depends on it for the refreshSource member.
- Production data: any live query uses `ENV=prod`, read-only. Never commit tokens, passwords or DSNs.
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src:packages/ai-parrot-server/src`
  as needed; never `uv sync` inside a worktree.

---

## Implementation Blueprint

**Steps (in order)**
1. Read `index.ts:140-240` to confirm `deps`, `failed`, `inFlight`, `executionOrder` names.
2. Add the interface member below `refreshAll(): Promise<void>;` (line 60).
3. Add the method after `refreshAll` in the returned object — reuse `runSource`, never a new fetch path, because the
   browser must not send conditions of its own (S4).
4. Write the vitest + wrapper; run the wrapper.

```ts
// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts — AFTER — insert below `  refreshAll(): Promise<void>;` (verified: index.ts:60)
// occurrences: 1 (verified: grep -c '  refreshAll(): Promise<void>;' index.ts)
  /** Manual refresh of ONE source (per-widget refresh button). Unknown/failed keys are a no-op. */
  refreshSource(key: string): Promise<void>;
```
```ts
// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts — inside the returned object, AFTER the closing `},` of `async refreshAll() {` (verified: index.ts:225)
// occurrences: 1 (verified: grep -c '    async refreshAll() {' index.ts)
    async refreshSource(key) {
      if (!(key in sources) || failed.has(key)) return;
      // FILL IN: in-flight dedup — keep a `refreshing: Record<string, Promise<void>>` declared next to `inFlight`;
      //   return the existing promise for `key` when present — bounded by S4 ("concurrent calls share one request").
      delete frames[key];
      await runSource(key, true);
      // FILL IN: re-run transform dependents — for k of executionOrder(sources, deps).order where deps[k] includes key
      //   (and k !== key): delete frames[k]; await runSource(k, true) — bounded by S5 (dependency order, sequential).
    },
```
**Why**: dependents read `frames[key]`; without re-running them they would show stale derived rows.

```ts
// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.test.ts — CREATE
// FEAT-610 (TASK-3844): refreshSource re-fetches exactly one key; unknown keys are a no-op; refreshAll unchanged.
import { afterEach, describe, expect, it, vi } from 'vitest';
// FILL IN: vi.mock('./fetch', ...) so fetchSource records (slug, conditions) calls and resolves rows.
import { createLinkedLane } from './index';

describe('LinkedLane.refreshSource', () => {
  it('re-fetches only that key with refresh=true', async () => { /* FILL IN — AC5, AC8 */ });
  it('is a no-op for an unknown key', async () => { /* FILL IN */ });
  it('re-runs transform dependents after the key', async () => { /* FILL IN — S5 */ });
  it('dedups concurrent calls for the same key', async () => { /* FILL IN — S4 */ });
  it('refreshAll still fetches every source in order', async () => { /* FILL IN */ });
});
```
```python
# packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_refresh.py — CREATE
"""FEAT-610 (TASK-3844): run the LinkedLane.refreshSource vitest suite from pytest."""

from ._vitest import run_vitest


def test_a2ui_linked_refresh_vitest() -> None:
    """refreshSource re-fetches one key; refreshAll unchanged."""
    run_vitest("src/lib/components/agents/canvas/a2ui/linked/index.test.ts")
```
**FILL IN checklist**
- [ ] dedup map; dependents loop; vitest bodies + fetch mock (copy the mock shape from `fetch.test.ts`).
- [ ] also run `pnpm exec svelte-check` in `packages/ai-parrot-server/ui` (spec §7: never run before) and note the result.

---

## Acceptance Criteria

- [ ] `LinkedLane.refreshSource(key)` exists; re-fetches only that key (+ its transform dependents) (AC5, AC8).
- [ ] unknown/failed key is a no-op; concurrent calls share one request.
- [ ] `refreshAll` behaviour unchanged; the new vitest passes via the pytest wrapper.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_refresh.py -q`
- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_runtime.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `index.test.ts` (5 cases) | AC5, AC8, S4, S5 |

---

## Agent Instructions

1. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
2. Implement exactly the files listed; no refactors outside scope.
3. `ruff check --fix` the touched Python files; run the Validation Commands.
4. Commit code only: `feat(a2ui-linked-e2e-test): TASK-3844 — LinkedLane.refreshSource(key) in the admin UI lane`.
5. Close with `scripts/sdd/close_task.sh TASK-3844 a2ui-linked-e2e-test verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
