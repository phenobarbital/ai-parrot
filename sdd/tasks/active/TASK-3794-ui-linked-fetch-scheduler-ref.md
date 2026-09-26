# TASK-3794: QuerySource client, fetchSource, RefreshScheduler, loadRef

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3792, TASK-3775
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11: the bundled renderer's own executor lane needs three I/O-facing pieces,
each pure enough to unit-test without Svelte:

1. **fetch** — G3: the renderer fetches QuerySource *directly* with the viewer's JWT on
   `POST /api/v3/queries/{slug}` (or `POST /api/v1/{tenant}/queries/{slug}` when
   `source.tenant` is set); ai-parrot-server never proxies. Every QuerySource denial is 404
   (spec §7 risks) → the lane says "unavailable", never "denied".
2. **scheduler** — refresh policy `on_mount` (default) / `manual` / `interval`
   (`interval_seconds >= 30`, paused while hidden, immediate run on resume).
3. **ref loader** — S6: `TransformRef.name` is an opaque `name@version` id, never a URL; the
   renderer resolves the URL from ITS OWN transforms base + the manifest written by TASK-3775's
   format (`{version: 1, entries: {"<name>@<semver>": {file, integrity, deprecated}}, signature}`),
   and refuses a module whose SRI does not match.

Binding criteria carried verbatim:
- **AC9** `transform.ref` resolves only against a manifest whose HMAC verifies; deprecated entries still resolve with a warning; unknown refs fail validation; the bundled UI refuses to execute a module whose SRI does not match and falls back to the snapshot.
- **AC10** Bundled UI: `on_mount` fetch with the viewer's bearer, `interval` clamped to ≥30 s and paused while hidden, `manual` never auto-fetches; a 404 keeps the snapshot with an "unavailable" notice (never "denied"); `refresh` is sent as boolean `true`; a `FilterBar` filter with `parrot_param` re-fetches its source, others filter locally.
- **S6** URL = `${transformsBase}/${manifest.entries[ref.name].file}` — the descriptor's `name` is opaque, never a URL.

(HMAC verification of the manifest is server-side — TASK-3775/TASK-3777; the browser cannot hold
`PARROT_A2UI_MANIFEST_KEY`. The UI's enforcement is the SRI check.)

---

## Scope

- `lib/api/querysource.ts`: URL builder + bearer-authenticated `POST` (native `fetch`, headers
  from `getAuthHeaders()`), throwing typed errors.
- `linked/fetch.ts`: `fetchSource(src, conditions, opts)` per the spec skeleton; 404 ⇒
  `SourceUnavailable`; `refresh` only ever as boolean `true`; `querylimit = maxFetchRows`
  (AC17, default 5000); `multi_output` frame selection.
- `linked/scheduler.ts`: `RefreshScheduler` (clamp, `visibilitychange` pause/resume, `manual` inert).
- `linked/ref.ts`: `loadRef(ref, opts)` — manifest lookup, integrity equality, sha384 SRI of the
  fetched bytes, injectable module importer; `null` on unknown / mismatch / failure.
- Vitest for each + one pytest wrapper.

**NOT in scope**: Svelte wiring, loading/unavailable UI, FilterBar (TASK-3795); DSL (TASK-3793);
server manifest publishing (TASK-3776). No axios for these calls (`apiClient` is bound to the
admin API origin and its 401 interceptor logs the user out — a QuerySource 401/404 must not).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/api/querysource.ts` | CREATE | QuerySource URL + POST client |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.ts` | CREATE | `fetchSource`, `SourceUnavailable` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/scheduler.ts` | CREATE | `RefreshScheduler` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/ref.ts` | CREATE | `loadRef` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.test.ts` | CREATE | fetch tests |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/scheduler.test.ts` | CREATE | scheduler tests |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/ref.test.ts` | CREATE | ref tests |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_runtime.py` | CREATE | pytest wrapper |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```typescript
import { getAuthHeaders } from '$lib/api/auth-headers';   // auth-headers.ts: export function getAuthHeaders(): Record<string, string>  (Bearer from localStorage[config.tokenStorageKey])
import { config } from '$lib/config';                     // config.ts: export const config = { apiBaseUrl, apiWithCredentials, basePath, … } (NO querysource field)
import type { LinkedDataSource, RefreshPolicy, Row, TransformRef } from './types';   // created by TASK-3792
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
```

### Existing Signatures to Use
```typescript
// ui/src/lib/config.ts
const apiBaseUrl = rawBaseUrl.replace(/\/$/, "");   // same-origin "" by default; env PUBLIC_API_URL
// envPrefix ['VITE_', 'PUBLIC_'] (vite.config.ts) → import.meta.env.PUBLIC_* is readable client-side
// ui/src/lib/api/http.ts — axios apiClient with a 401 → authStore.handle401() interceptor (DO NOT reuse for QuerySource)
```
```text
QuerySource 5.1.1 (../querysource, tag 5.1.1): POST /api/v3/queries/{slug} (single + MultiQuery via QueryHandler,
  handlers/multi.py); POST /api/v1/{tenant}/queries/{slug} (TenantQueryHandler, handlers/tenant.py). Every denial → 404.
  `refresh` is bool(raw) server-side (providers/abstract.py) — send boolean true or omit.
Manifest file (format fixed by TASK-3775 linked/manifest.py::TransformManifest):
  {"version": 1, "entries": {"<name>@<semver>": {"file": "<name>@<semver>.js", "integrity": "sha384-…", "deprecated": bool}}, "signature": "…"}
  served anonymously at /static/a2ui/transforms/manifest.json (TASK-3776 publishes it).
```

### Does NOT Exist
- ~~`ui/src/lib/api/querysource.ts`, `a2ui/linked/{fetch,scheduler,ref}.ts`~~ — created here.
- ~~`config.querysourceUrl`~~ — add NO field to `config.ts` (not in this task's files); read `import.meta.env.PUBLIC_QUERYSOURCE_URL` locally in `querysource.ts`.
- ~~`/api/v3/{tenant}/queries/{slug}`~~ — the tenant route is `/api/v1/{tenant}/queries/{slug}`.
- ~~`TransformRef.url`~~ — never; opaque `name`.
- ~~a 403 from QuerySource~~ — denials are 404.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/ui/src/lib/api/querysource.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/scheduler.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/ref.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/scheduler.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/ref.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_runtime.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `fetchSource` keeps the spec skeleton signature; `maxFetchRows?: number` is an ADDITIVE
  optional opt (default 5000) — AC17 "every executor lane sends `querylimit = max_fetch_rows`".
- `refresh`: delete the key unless it is exactly `true` (never send `"true"`/`1`).
- MultiQuery responses: normalise to ONE row array — the frame named `multi_output`, else
  `result`, else the single frame (S4, same rule as Python `QuerySlugSource`). Verify the actual
  v3 JSON shapes (single: record array vs envelope; multi: `{name: records}`) in
  `../querysource/querysource/handlers/multi.py` / `handlers/service.py` before coding.
- Scheduler uses `setInterval`/`clearInterval` + `document.addEventListener('visibilitychange', …)`;
  `stop()` removes the listener (no leaks on unmount).
- SRI: `crypto.subtle.digest('SHA-384', bytes)` → base64 → `sha384-<b64>`; it must equal BOTH
  `ref.integrity` and the manifest entry's `integrity`. Module execution goes through an
  injectable `importModule(url)` (default: `import(/* @vite-ignore */ blobUrl)`), so tests never
  execute code and a host CSP that forbids blob modules degrades to `null` (CSP is the host
  page's responsibility — spec §7 risks).
- A `deprecated: true` entry still loads, with `console.warn` (AC9).

---

## Implementation Blueprint

### Steps (in order)
1. Write `querysource.ts` — *why*: `fetch.ts` depends on its URL rule and error type.
2. Write `fetch.ts` + `fetch.test.ts` (mock `globalThis.fetch` with `vi.fn`) — *why*: URL/tenant/404/refresh/querylimit are AC-bound.
3. Write `scheduler.ts` + test with `vi.useFakeTimers()` — *why*: clamp and pause are time-based.
4. Write `ref.ts` + test with an injected importer — *why*: SRI mismatch must never import.
5. Wrapper; run `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_runtime.py -q`.

### `packages/ai-parrot-server/ui/src/lib/api/querysource.ts` (CREATE)
```typescript
/**
 * QuerySource client for linked A2UI surfaces (FEAT-598, spec G3).
 * The renderer calls QuerySource DIRECTLY with the viewer's bearer — ai-parrot-server never proxies.
 * Native fetch (not the admin axios client, whose 401 interceptor logs the user out).
 */
import { getAuthHeaders } from '$lib/api/auth-headers';
import { config } from '$lib/config';

/** Base URL of the QuerySource API; defaults to the admin API origin (same-origin ""). */
export const querySourceBaseUrl: string = (
  (import.meta.env.PUBLIC_QUERYSOURCE_URL as string | undefined) ?? config.apiBaseUrl
).replace(/\/$/, '');

export class QuerySourceHttpError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = 'QuerySourceHttpError';
  }
}

/** `/api/v3/queries/{slug}` or `/api/v1/{tenant}/queries/{slug}` (spec G3, AC4). */
export function queryUrl(baseUrl: string, slug: string, tenant: string | null | undefined): string {
  const s = encodeURIComponent(slug);
  return tenant ? `${baseUrl}/api/v1/${encodeURIComponent(tenant)}/queries/${s}` : `${baseUrl}/api/v3/queries/${s}`;
}

export function querySourceHeaders(): HeadersInit {
  return { 'Content-Type': 'application/json', ...getAuthHeaders() };
}

export async function postQuery(url: string, body: Record<string, unknown>, headers: HeadersInit): Promise<unknown> {
  const res = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body) });
  if (!res.ok) throw new QuerySourceHttpError(res.status, `QuerySource ${res.status}`);
  return res.json();
}
```

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.ts` (CREATE)
```typescript
/** fetchSource — one linked source against QuerySource (FEAT-598, spec M11 skeleton, AC4/AC10/AC17). */
import { postQuery, queryUrl, QuerySourceHttpError } from '$lib/api/querysource';
import type { LinkedDataSource, Row } from './types';

/** Raised for every QuerySource 404 — the UI says "unavailable", NEVER "denied" (spec §7 risks). */
export class SourceUnavailable extends Error {
  constructor(public readonly slug: string) {
    super(`source '${slug}' unavailable`);
    this.name = 'SourceUnavailable';
  }
}

export const DEFAULT_MAX_FETCH_ROWS = 5000;

export async function fetchSource(
  src: LinkedDataSource,
  conditions: Record<string, unknown>,
  opts: { baseUrl: string; headers: HeadersInit; maxFetchRows?: number },
): Promise<Row[]> {
  const cap = opts.maxFetchRows ?? DEFAULT_MAX_FETCH_ROWS;
  // deriveConditions never emits `limit` (TASK-3770/TASK-3793); the lane re-applies request.limit bounded by the cap (S8/AC17)
  const body: Record<string, unknown> = { ...conditions, querylimit: Math.min(src.request.limit ?? cap, cap) };
  if (body.refresh !== true) delete body.refresh;
  let payload: unknown;
  try {
    payload = await postQuery(queryUrl(opts.baseUrl, src.slug, src.tenant ?? null), body, opts.headers);
  } catch (err) {
    if (err instanceof QuerySourceHttpError && err.status === 404) throw new SourceUnavailable(src.slug);
    throw err;
  }
  // FILL IN: normalise payload → Row[] (single record array / envelope; MultiQuery → multi_output ?? 'result' ?? the single frame; empty → []) — bounded by S4 + the verified QuerySource 5.1.1 response shape
  return payload as Row[];
}
```

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/scheduler.ts` (CREATE)
```typescript
/** RefreshScheduler — on_mount | manual | interval (FEAT-598, AC10). */
import type { RefreshPolicy } from './types';

export const MIN_INTERVAL_SECONDS = 30;

export class RefreshScheduler {
  private timer: ReturnType<typeof setInterval> | null = null;
  private readonly onVisibility = (): void => this.handleVisibility();

  constructor(private readonly policy: RefreshPolicy, private readonly run: () => Promise<void>) {}

  /** Clamp to >= 30 s (spec M1/M11). */
  get intervalMs(): number {
    return Math.max(MIN_INTERVAL_SECONDS, this.policy.interval_seconds ?? MIN_INTERVAL_SECONDS) * 1000;
  }

  start(): void {
    // FILL IN: on_mount → one immediate run; manual → nothing; interval → immediate run (unless document.hidden) + setInterval(intervalMs) + visibilitychange listener — bounded by AC10
  }

  stop(): void {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    document.removeEventListener('visibilitychange', this.onVisibility);
  }

  private handleVisibility(): void {
    // FILL IN: hidden → clear the interval; visible → immediate run + restart the interval — bounded by "paused while hidden, immediate fetch on resume"
  }
}
```

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/ref.ts` (CREATE)
```typescript
/**
 * loadRef — catalogued `transform.ref` modules (FEAT-598, S6, AC9).
 * URL = `${transformsBase}/${manifest.entries[ref.name].file}`; `ref.name` is opaque, never a URL.
 * Returns null on unknown ref, integrity mismatch, SRI mismatch, or any load failure → caller keeps the snapshot.
 */
import type { Row, TransformRef } from './types';

export type RowTransform = (rows: Row[]) => Row[];
interface ManifestEntry { file: string; integrity: string; deprecated?: boolean }
interface Manifest { version: number; entries: Record<string, ManifestEntry> }

export async function sriOf(bytes: ArrayBuffer): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-384', bytes));
  return `sha384-${btoa(String.fromCharCode(...digest))}`;
}

export async function loadRef(
  ref: TransformRef,
  opts: { transformsBase: string; importModule?: (url: string) => Promise<unknown> },
): Promise<RowTransform | null> {
  const base = opts.transformsBase.replace(/\/$/, '');
  try {
    const manifest = (await (await fetch(`${base}/manifest.json`)).json()) as Manifest;
    const entry = manifest.entries?.[ref.name];
    if (!entry || entry.integrity !== ref.integrity) return null;
    if (entry.deprecated) console.warn(`a2ui transform ${ref.name} is deprecated`);
    // FILL IN: fetch `${base}/${entry.file}` bytes; sriOf(bytes) !== ref.integrity → null (never import); else blob URL → (opts.importModule ?? default dynamic import)(url) → default export must be a function, else null — bounded by AC9 + S6
    return null;
  } catch {
    return null;
  }
}
```

### `…/linked/fetch.test.ts` (CREATE)
```typescript
// FEAT-598 (TASK-3794): fetchSource URL rule, 404 → SourceUnavailable, refresh boolean, querylimit (AC4/AC10/AC17).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchSource, SourceUnavailable } from './fetch';

afterEach(() => vi.restoreAllMocks());

describe('fetchSource', () => {
  it('posts to /api/v3/queries/{slug} with querylimit when tenant is null', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([{ a: 1 }])));
    // FILL IN: build a minimal LinkedDataSource literal; assert URL, method POST, body.querylimit === 5000, bearer header passed through
    expect(spy).toBeDefined();
  });
  // FILL IN: tenant 'acme' → /api/v1/acme/queries/{slug}; 404 → rejects SourceUnavailable; refresh 'true'/1 dropped, true kept; multi_output frame selection
  it('exports SourceUnavailable', () => expect(new SourceUnavailable('x').name).toBe('SourceUnavailable'));
});
```

### `…/linked/scheduler.test.ts` (CREATE)
```typescript
// FEAT-598 (TASK-3794): 30 s clamp, manual inert, pause while hidden, immediate run on resume (AC10).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RefreshScheduler } from './scheduler';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('RefreshScheduler', () => {
  it('clamps interval_seconds below 30 to 30 s', () => {
    const s = new RefreshScheduler({ policy: 'interval', interval_seconds: 5 } as never, async () => {});
    expect(s.intervalMs).toBe(30_000);
  });
  // FILL IN: manual → run never called; on_mount → once; interval → runs every 30 s; hidden (Object.defineProperty(document,'hidden')) + dispatch visibilitychange → no runs; visible → immediate run; stop() clears
});
```

### `…/linked/ref.test.ts` (CREATE)
```typescript
// FEAT-598 (TASK-3794): loadRef resolves opaque ids via the manifest; SRI mismatch never imports (AC9, S6).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadRef } from './ref';

afterEach(() => vi.restoreAllMocks());

describe('loadRef', () => {
  it('returns null for a ref not in the manifest', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ version: 1, entries: {} })));
    const importModule = vi.fn();
    expect(await loadRef({ name: 'x@1.0.0', integrity: 'sha384-a' } as never, { transformsBase: '/static/a2ui/transforms', importModule })).toBeNull();
    expect(importModule).not.toHaveBeenCalled();
  });
  // FILL IN: URL joined as `${base}/${entry.file}`; bytes whose sha384 ≠ integrity → null + importModule not called; matching bytes → importModule called, returns the default-export fn; deprecated → console.warn + still resolves
});
```

### `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_runtime.py` (CREATE)
```python
"""FEAT-598 (TASK-3794): run the linked fetch / scheduler / ref vitest suites from pytest."""

from ._vitest import run_vitest


def test_a2ui_linked_runtime_vitest() -> None:
    """fetch.ts, scheduler.ts and ref.ts suites pass."""
    run_vitest(
        "src/lib/components/agents/canvas/a2ui/linked/fetch.test.ts",
        "src/lib/components/agents/canvas/a2ui/linked/scheduler.test.ts",
        "src/lib/components/agents/canvas/a2ui/linked/ref.test.ts",
    )
```

### FILL IN checklist
- [ ] `fetch.ts` payload normalisation; bounded by S4 + verified QuerySource 5.1.1 response shapes.
- [ ] `scheduler.ts::start` / `handleVisibility`; bounded by AC10.
- [ ] `ref.ts` byte fetch + SRI + import; bounded by AC9 + S6.
- [ ] the three test files' remaining cases.

---

## Acceptance Criteria

- [ ] AC4 (renderer half): `tenant` routes to `/api/v1/{tenant}/queries/{slug}`; `null` → `/api/v3/queries/{slug}`.
- [ ] AC10 (lane half): bearer sent; interval ≥ 30 s and paused while hidden; `manual` never auto-runs; 404 ⇒ `SourceUnavailable`; `refresh` only boolean `true`.
- [ ] AC17 (renderer half): every fetch sends `querylimit` (default 5000).
- [ ] AC9 (UI half) / S6: opaque `name` resolved via manifest; SRI mismatch ⇒ `null`, module never imported.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_runtime.py -q`

---

## Test Specification

See the three test blocks above; every AC bullet in this task maps to at least one `it(...)`.

---

## Agent Instructions

1. **Read the spec** (G3, §3 M9/M11, §7 risks, AC9/AC10/AC17).
2. **Check dependencies** — TASK-3792 (types) and TASK-3775 (manifest format) done.
3. **Verify the Codebase Contract** (auth-headers/config exports; QuerySource response shape).
4. **Update status** → `"in-progress"`; implement; complete every `FILL IN`.
5. **Verify**; move to `sdd/tasks/completed/`; index → `"done"`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
