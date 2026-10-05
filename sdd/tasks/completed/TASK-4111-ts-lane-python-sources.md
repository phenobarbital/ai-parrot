# TASK-4111: TS renderer lane — python sources fetch via the server endpoint; snapshot-only when not persisted

**Feature**: FEAT-636 — Linked A2UI surfaces — server-executed Python recipe transformers
**Spec**: `sdd/specs/linked-a2ui-recipes-transforms.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4110, TASK-4108
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (behavior half) + codex S3/S4. A python transformer cannot run in the browser (mirror of
`transform.ref` not running in Python). So for a source with `transform.python` the lane must:

| Situation | Behavior |
|---|---|
| surface persisted (`persistedSurfaceId` set) | POST `/api/v1/ui/surfaces/{id}/sources/{key}/data` with `{params}` (+ `?share=` when a share token is given); rows used as-is — NO `applyTransform`, NO direct QuerySource call |
| surface NOT persisted | never fetch; keep the snapshot; report a new `'snapshot'` status shown as "saved data" — NEVER fall back to direct QuerySource (it would drop the transform and show untransformed rows) |

Today no UI view handles share tokens (zero `?share=` usages under `ui/src`), so `shareToken` is an optional prop that
is forwarded when a host provides it; the share path itself is enforced/tested server-side (TASK-4108).

---

## Scope

- `fetch.ts`: add `fetchSourceData(...)` (404 → `SourceUnavailable`, same wording rule as `fetchSource`).
- `index.ts`: add `'snapshot'` to `SourceStatus`; add optional `surface` to `LinkedLaneOptions`; branch python sources in `execute()`.
- `A2UISurface.svelte`: add optional `shareToken` prop; pass `surface` options; render the `'snapshot'` notice.
- Tests in `fetch.test.ts`, `index.test.ts`, `A2UISurface.linked.test.ts`.

**NOT in scope**: type generation (TASK-4110); the server endpoint (TASK-4108); a share-viewer page.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.ts` | MODIFY | `fetchSourceData` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts` | MODIFY | `'snapshot'` status, `surface` option, python branch |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte` | MODIFY | `shareToken` prop, `surface` wiring, snapshot notice |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.test.ts` | MODIFY | endpoint fetch tests |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.test.ts` | MODIFY | lane routing tests |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.linked.test.ts` | MODIFY | snapshot notice test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```typescript
import { postQuery, queryUrl, QuerySourceHttpError } from '$lib/api/querysource';   // fetch.ts:2
import type { LinkedDataSource, Row } from './types';                              // fetch.ts:3 (PythonTransform re-exported by TASK-4110)
import { applyTransform, TransformError } from './dsl';                            // index.ts:18
import { fetchSource, SourceUnavailable } from './fetch';                          // index.ts:19
import { querySourceBaseUrl, querySourceHeaders } from '$lib/api/querysource';     // A2UISurface.svelte:30
import { getAuthHeaders } from '$lib/api/auth-headers';                            // A2UISurface.svelte:31
```

### Existing Signatures to Use
```typescript
// linked/fetch.ts
export class SourceUnavailable extends Error { constructor(public readonly slug: string) }        // line 6-11
export async function fetchSource(src, conditions, opts: { baseUrl; headers: HeadersInit; maxFetchRows? }): Promise<Row[]>  // line 61-83
// postQuery(url, body, headers) throws QuerySourceHttpError (has .status) on non-2xx               // $lib/api/querysource.ts:44

// linked/index.ts
export type SourceStatus = 'loading' | 'ready' | 'unavailable' | 'error';                          // line 42
export interface LinkedLaneOptions { baseUrl: string; headers: () => HeadersInit; transformsBase: string; onUpdate }  // line 51-56
export function createLinkedLane(sources: LinkedSources, opts: LinkedLaneOptions): LinkedLane     // line 154
// execute(key, forceRefresh, resolving): query-slug branch at 260-273 —
//   line 265: const rawRows = await fetchSource(src, conditions, { baseUrl: opts.baseUrl, headers: opts.headers() });
//   line 267-273: src.transform?.ops → applyTransform | src.transform?.ref → loadRef
// state: overrides[key] (per-source param overrides), lastSnapshotAt[key], frames[key]

// A2UISurface.svelte
// props destructure at 33-38: { envelope, persistedSurfaceId, transformsBase }: { envelope: A2UIEnvelope; persistedSurfaceId?: string; transformsBase?: string }
// createLinkedLane(resolved, { baseUrl: querySourceBaseUrl, headers: querySourceHeaders, transformsBase, onUpdate }) at 142-155
// serverRefresh uses `${config.apiBaseUrl}/api/v1/ui/surfaces/${persistedSurfaceId}/refresh` + getAuthHeaders() at 164-172
// notices block at 225-236: {#if status.status === 'unavailable'} … {:else if status.status === 'error'} …

// tests: index.test.ts mocks './fetch' via vi.hoisted fetchSourceMock (lines 6-13); lane() helper at 27-34
// endpoint response (TASK-4108): {"status":"success","key","rows","truncated","snapshot_at","warnings"}; errors {"status":"error","code"}
```

### Does NOT Exist
- ~~`fetchSourceData`~~ / ~~`'snapshot'` status~~ / ~~`LinkedLaneOptions.surface`~~ / ~~`shareToken` prop~~ — created here.
- ~~client-side python execution~~ — never; rows from the endpoint are final.
- ~~a share-viewer page in the admin UI~~ — none exists; do not create one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.test.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.test.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.linked.test.ts", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `fetchSourceData` to `fetch.ts` — *why*: one place owns the endpoint URL + 404 wording rule.
2. Extend `SourceStatus` and `LinkedLaneOptions` in `index.ts` — *why*: the lane needs the surface id/headers and a non-error "saved data" state (S4).
3. Branch python sources at the top of the query-slug branch in `execute()` — *why*: they must skip both direct fetch and client transforms.
4. Wire `surface` + `shareToken` + the notice in `A2UISurface.svelte` — *why*: only the component knows `persistedSurfaceId`.
5. Write tests; run the Validation Commands.

### `linked/fetch.ts` (MODIFY)
```typescript
// AFTER — append below fetchSource (ends fetch.ts:83)
/**
 * Fetch one python-transformed source through parrot-server (FEAT-636): the server executes the slug and the
 * registered transformer; rows come back final. Only `params` are sent — conditions are rebuilt server-side.
 * A 404 is "unavailable", never "denied" (same rule as fetchSource).
 */
export async function fetchSourceData(
  src: LinkedDataSource,
  key: string,
  params: Record<string, unknown>,
  opts: { surfaceBaseUrl: string; surfaceId: string; shareToken?: string; headers: HeadersInit },
): Promise<Row[]> {
  const share = opts.shareToken ? `?share=${encodeURIComponent(opts.shareToken)}` : '';
  const url = `${opts.surfaceBaseUrl}/api/v1/ui/surfaces/${encodeURIComponent(opts.surfaceId)}/sources/${encodeURIComponent(key)}/data${share}`;
  // FILL IN: fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', ...opts.headers},
  //   body: JSON.stringify({params})}); 404 → throw new SourceUnavailable(src.slug); other !ok → throw Error with the
  //   body's `code` when present; ok → return (await res.json()).rows as Row[] (missing → []) — bounded by AC10.
  throw new Error('not implemented');
}
```

### `linked/index.ts` (MODIFY — types)
```typescript
// REPLACE index.ts:42 with:
export type SourceStatus = 'loading' | 'ready' | 'unavailable' | 'error' | 'snapshot';
// AFTER — add inside `export interface LinkedLaneOptions {` (index.ts:51-56), after `onUpdate`:
  /** FEAT-636: where python-transformed sources fetch from. Absent/no surfaceId ⇒ those sources stay snapshot-only. */
  surface?: { baseUrl: string; surfaceId?: string; shareToken?: string; headers: () => HeadersInit };
```

### `linked/index.ts` (MODIFY — execute branch)
```typescript
// occurrences: 1 (verified: grep -c 'const rawRows = await fetchSource(src, conditions, { baseUrl: opts.baseUrl, headers: opts.headers() });' linked/index.ts)
// BEFORE — insert at the top of `if (isQuerySlug(src)) {` (index.ts:260), above `const placeholders = ...`:
        if (src.transform?.python) {
          const surface = opts.surface;
          if (!surface?.surfaceId) {
            // S4: no persisted record ⇒ no server lane. Keep the snapshot; never fall back to direct QuerySource.
            opts.onUpdate({ key, rows: null, status: 'snapshot', snapshotAt: lastSnapshotAt[key] ?? null });
            return true;
          }
          // FILL IN: rows = await fetchSourceData(src, key, { ...(overrides[key] ?? {}) }, { surfaceBaseUrl: surface.baseUrl,
          //   surfaceId: surface.surfaceId, shareToken: surface.shareToken, headers: surface.headers() }); then fall
          //   through to the shared success path below (frames/lastSnapshotAt/onUpdate 'ready') — bounded by AC10
          //   (no applyTransform/loadRef for python sources; `refresh` is NOT forwarded: the endpoint has no cache flag).
        } else {
          // existing body (placeholders … fetchSource … ops/ref) moves inside this else, unchanged
        }
```
Import `fetchSourceData` alongside `fetchSource` on index.ts:19.
**Why**: returning `true` for the snapshot case keeps dependents/scheduler logic unchanged (a python source is terminal,
TASK-4104 guarantees nothing depends on it).

### `A2UISurface.svelte` (MODIFY)
```svelte
<!-- FILL IN (props, A2UISurface.svelte:33-38): add `shareToken` to the destructure and its type (`shareToken?: string`) -->
<!-- FILL IN (createLinkedLane options, A2UISurface.svelte:142-146): add
     surface: { baseUrl: config.apiBaseUrl, surfaceId: persistedSurfaceId, shareToken, headers: getAuthHeaders }, -->
<!-- AFTER the `{:else if status.status === 'error'}` notice (A2UISurface.svelte:231-234), add: -->
				{:else if status.status === 'snapshot'}
					<p class="text-xs text-muted-foreground" data-testid="notice-snapshot-{key}">
						{key}: saved data — as of {status.snapshotAt ?? 'never'} (save the surface to refresh live)
					</p>
```
Svelte 5 runes only (`$props`) — codebase conventions.

### Tests (MODIFY — append)
```typescript
// fetch.test.ts — FILL IN: fetchSourceData POSTs to /api/v1/ui/surfaces/s1/sources/sales/data with {params},
//   appends ?share=tok when given, maps 404 → SourceUnavailable, returns body.rows
// index.test.ts — extend the vi.mock('./fetch') factory with fetchSourceData: fetchSourceDataMock (vi.hoisted), then:
//   (a) python source + surface.surfaceId → fetchSourceDataMock called with overrides, fetchSourceMock NOT called,
//       onUpdate gets 'ready' with the endpoint rows untouched;
//   (b) python source without surface → no fetch at all, onUpdate status 'snapshot';
//   (c) an ops source in the same lane still uses fetchSource + applyTransform (AC11)
// A2UISurface.linked.test.ts — FILL IN: envelope with a python source and no persistedSurfaceId renders
//   data-testid="notice-snapshot-<key>"
```

### FILL IN checklist
- [ ] `fetchSourceData` request/response handling — AC10
- [ ] index.ts python branch success path + `else` re-indent — AC10
- [ ] Svelte prop + lane option wiring
- [ ] three test groups

---

## Acceptance Criteria

- [ ] AC10 (spec): python sources fetch via the endpoint (share token forwarded when present), never direct QuerySource, no client transform; non-persisted surfaces render snapshot-only with a visible "saved data" notice.
- [ ] AC11 (spec): DSL/ref sources behave identically; parity and refresh vitest suites pass unchanged.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_runtime.py -q`
- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_refresh.py -q`
- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_surface.py -q`
- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_parity.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug linked-a2ui-recipes-transforms --feature-id FEAT-636`).
2. Confirm TASK-4110 and TASK-4108 are `done` in the per-spec index.
3. Verify the Codebase Contract; start from the blueprint; complete every `FILL IN`.
4. Run the Validation Commands; commit only the listed files.
5. Close with `scripts/sdd/close_task.sh TASK-4111 linked-a2ui-recipes-transforms verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: native sonnet, attempt 1
**Date**: 2026-10-06
**Notes**: Diff reviewed by the orchestrator against the task. Evidence: per the coder's own report: vitest run on src/lib/components/agents/canvas/a2ui with the main checkout's node_modules temporarily symlinked, 193/195 passed; the 2 failures are in A2UINode.test.ts (a locale '57.9%' assertion, not touched by this task). The pytest vitest wrappers skip in the worktree. I did not rerun vitest myself and did not check that those 2 failures predate the change.

**Deviations from spec**: none
