# TASK-5053: Admin UI connections API client and rune store (list + SSE)

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5052
**Assigned-to**: unassigned

---

## Context

Spec §2 "Panel and cleanup" and §3 Module 5: one rune store, `lib/stores/connections.svelte.ts`, owns the
user's connection list, the SSE reader for `GET /api/v1/connections/events` (TASK-5040), and refetch-on-event.
The panel (TASK-5056), the per-agent menu (TASK-5057) and the chat pill (TASK-5055) all read it. The SSE stream is
a hint: `GET /api/v1/connections` is authoritative, so the store refetches on every (re)connect and on every
event (D1). The admin UI authenticates with a bearer header from `localStorage`, so the reader uses `fetch`
+ `ReadableStream`, never `EventSource` (browsers cannot set headers on it).

---

## Scope

- Create `lib/api/connections.ts` with the 7 functions of the spec skeleton (list, get, startConnect,
  disconnect, previewChannelLink, confirmChannelLink, openConnectionEvents).
- Create `lib/stores/connections.svelte.ts` (`ConnectionsStore` class + `connectionsStore` singleton):
  `items`/`loading`/`live` runes, `refresh()`, idempotent `start()` with 1 s → 30 s backoff, `stop()`,
  `onEvent(cb)` returning an unsubscribe.
- Write vitest tests for both, plus the pytest wrapper.

**NOT in scope**: components or pages (TASK-5056), pill/AgentChat (TASK-5055), IntegrationsMenu and removing
`integrations.ts` symbols (TASK-5057), the server endpoints (TASK-5040, TASK-5041).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/api/connections.ts` | CREATE | axios + fetch-SSE client for `/api/v1/connections*` and `/api/v1/channel-links*` |
| `packages/ai-parrot-server/ui/src/lib/api/connections.test.ts` | CREATE | client + SSE frame parser tests |
| `packages/ai-parrot-server/ui/src/lib/stores/connections.svelte.ts` | CREATE | `ConnectionsStore` rune store |
| `packages/ai-parrot-server/ui/src/lib/stores/connections.test.ts` | CREATE | refresh-on-open/event, backoff, stop aborts |
| `packages/ai-parrot-server/tests/ui/test_vitest_connections_store.py` | CREATE | pytest wrapper running both vitest files |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import { createApiClient, ApiError } from "$lib/api/http";             // verified: http.ts:179 (createApiClient(baseURL?): AxiosInstance), :31 (ApiError)
import { getAuthHeaders } from "$lib/api/auth-headers";                // verified: auth-headers.ts:16 → { Authorization: "Bearer …" } | {}
import { config } from "$lib/config";                                  // verified: config.ts:52 (config.apiBaseUrl)
import type { IntegrationDescriptor } from "$lib/types/generated/IntegrationDescriptor";   // created by TASK-5052
import type { ConnectInitResponse } from "$lib/types/generated/ConnectInitResponse";       // created by TASK-5052
import type { DisconnectResponse } from "$lib/types/generated/DisconnectResponse";         // created by TASK-5052
import type { ConnectionEvent } from "$lib/types/generated/ConnectionEvent";               // created by TASK-5052
import type { ChannelLinkPreview } from "$lib/types/generated/ChannelLinkPreview";         // created by TASK-5052
```

### Existing Signatures to Use
```ts
// lib/api/integrations.ts — pattern for an axios module (:49 `const client = createApiClient();`; :58 list; :72 start;
//   start sends { return_origin } body + Origin header :80-84)
// lib/api/stream.ts:176-198 — fetch pattern: `${baseUrl ?? config.apiBaseUrl}/api/…`, headers from getAuthHeaders(),
//   AbortError rethrown, non-2xx → ApiError(`HTTP ${status}`, status === 401 ? "auth" : "server", status)
// Server routes (S-1, verified manager.py:2488-2490): GET /api/v1/connections, GET /api/v1/connections/{provider},
//   POST /api/v1/connections/{provider}/start  body {return_origin, scopes?} (handlers/connections.py:94-100),
//   DELETE /api/v1/connections/{provider}
// New routes: GET /api/v1/connections/events (TASK-5040), GET /api/v1/channel-links/{nonce} and
//   POST /api/v1/channel-links/{nonce}/confirm body {confirm: true} (TASK-5041)
// SSE frame format (spec §2, M1): "event: connection\ndata: <ConnectionEvent JSON>\n\n"; keep-alive ": keep-alive\n\n"
// Store pattern: lib/stores/auth.svelte.ts / toast.svelte.ts (class with $state fields, exported singleton)
```

### Does NOT Exist
- ~~`EventSource` with an `Authorization` header~~ — impossible; use fetch streaming.
- ~~`lib/api/connections.ts`, `lib/stores/connections.svelte.ts`~~ — created here.
- ~~A WebSocket for connections~~ — `lib/services/websocket-service.ts` is a no-op stub (FEAT-476) and must NOT change (AC-4).
- ~~An `agentId` parameter on connection routes~~ — `/api/v1/connections*` is principal-scoped, not agent-scoped.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/ui/src/lib/api/connections.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/api/connections.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/stores/connections.svelte.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/stores/connections.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_connections_store.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Svelte 5 runes only; shared state lives in the `.svelte.ts` file (conventions).
- One SSE reader per tab: `start()` is idempotent; `stop()` aborts it (spec §7 "Redis connection count").
- Refetch, do not patch: on open and on every event call `refresh()` — duplicates and gaps are harmless (D1).
- Never log tokens; `ConnectionEvent` carries no token material.

---

## Implementation Blueprint

### Steps (in order)
1. Write `connections.ts` axios functions — *why*: one client for every connections route; the menu and pill stop using agent-scoped routes.
2. Write `openConnectionEvents` as a fetch reader that splits on blank lines and dispatches `event: connection` frames — *why*: bearer header requires fetch (spec §2 Push).
3. Write the store — *why*: single owner of list + stream so components never open their own streams.
4. Write the tests and the wrapper; run the Validation Commands.

### `packages/ai-parrot-server/ui/src/lib/api/connections.ts` (CREATE)
```ts
/** Principal-scoped connections client (FEAT-777 M5): /api/v1/connections*, /api/v1/channel-links*. */
import { ApiError, createApiClient } from "$lib/api/http";
import { getAuthHeaders } from "$lib/api/auth-headers";
import { config } from "$lib/config";
import type { ChannelLinkPreview } from "$lib/types/generated/ChannelLinkPreview";
import type { ConnectInitResponse } from "$lib/types/generated/ConnectInitResponse";
import type { ConnectionEvent } from "$lib/types/generated/ConnectionEvent";
import type { DisconnectResponse } from "$lib/types/generated/DisconnectResponse";
import type { IntegrationDescriptor } from "$lib/types/generated/IntegrationDescriptor";

const client = createApiClient();
const BASE = "/api/v1/connections";
const enc = encodeURIComponent;

export async function listConnections(): Promise<IntegrationDescriptor[]> {
  const { data } = await client.get<IntegrationDescriptor[]>(BASE);
  return data;
}

export async function getConnection(provider: string): Promise<IntegrationDescriptor> {
  const { data } = await client.get<IntegrationDescriptor>(`${BASE}/${enc(provider)}`);
  return data;
}

export async function startConnect(
  provider: string,
  returnOrigin: string,
  scopes?: string[],
): Promise<ConnectInitResponse> {
  const { data } = await client.post<ConnectInitResponse>(
    `${BASE}/${enc(provider)}/start`,
    scopes ? { return_origin: returnOrigin, scopes } : { return_origin: returnOrigin },
  );
  return data;
}

export async function disconnect(provider: string): Promise<DisconnectResponse> {
  const { data } = await client.delete<DisconnectResponse>(`${BASE}/${enc(provider)}`);
  return data;
}

export async function previewChannelLink(token: string): Promise<ChannelLinkPreview> {
  const { data } = await client.get<ChannelLinkPreview>(`/api/v1/channel-links/${enc(token)}`);
  return data;
}

export async function confirmChannelLink(token: string): Promise<{ channel: string; linked: boolean }> {
  const { data } = await client.post<{ channel: string; linked: boolean }>(
    `/api/v1/channel-links/${enc(token)}/confirm`,
    { confirm: true },
  );
  return data;
}

/** Parse one SSE block ("event: …\ndata: …"); returns the event, or null for comments/other events/bad JSON. */
export function parseSseBlock(block: string): ConnectionEvent | null {
  // FILL IN: collect `event:` and (possibly multi-line) `data:` fields; ignore lines starting with ":" (keep-alive);
  //   return JSON.parse(data) only when event === "connection" — bounded by the M1 frame format (spec §2)
  return null;
}

/** Read the SSE stream until it ends or `signal` aborts; calls onEvent per `connection` frame. */
export async function openConnectionEvents(
  onEvent: (e: ConnectionEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`${config.apiBaseUrl}${BASE}/events`, {
    headers: { Accept: "text/event-stream", ...getAuthHeaders() },
    signal,
  });
  if (!response.ok || !response.body) {
    throw new ApiError(`HTTP ${response.status}`, response.status === 401 ? "auth" : "server", response.status);
  }
  // FILL IN: TextDecoder loop; buffer, split on "\n\n" (normalize "\r\n"), parseSseBlock each block,
  //   call onEvent for non-null; keep the trailing partial block; releaseLock in finally — mirror stream.ts:118-130
}
```
**Why this shape**: function names, routes and signatures are fixed by the spec M5 skeleton. `parseSseBlock` is
exported only so the parser is unit-testable without a network.

### `packages/ai-parrot-server/ui/src/lib/stores/connections.svelte.ts` (CREATE)
```ts
/** Single owner of the user's connections list + SSE reader (FEAT-777 M5). */
import { listConnections, openConnectionEvents } from "$lib/api/connections";
import type { ConnectionEvent } from "$lib/types/generated/ConnectionEvent";
import type { IntegrationDescriptor } from "$lib/types/generated/IntegrationDescriptor";

const BACKOFF_MIN_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;

export class ConnectionsStore {
  items = $state<IntegrationDescriptor[]>([]);
  loading = $state(false);
  live = $state(false);
  error = $state<string | null>(null);

  #abort: AbortController | null = null;
  #listeners = new Set<(e: ConnectionEvent) => void>();

  async refresh(): Promise<void> {
    this.loading = true;
    try {
      this.items = await listConnections();
      this.error = null;
    } catch (err) {
      this.error = err instanceof Error ? err.message : "Failed to load connections";
    } finally {
      this.loading = false;
    }
  }

  /** Idempotent: opens the SSE reader once; refresh() on open and on each event. */
  start(): void {
    if (this.#abort) return;
    this.#abort = new AbortController();
    void this.#run(this.#abort.signal);
  }

  stop(): void {
    this.#abort?.abort();
    this.#abort = null;
    this.live = false;
  }

  onEvent(cb: (e: ConnectionEvent) => void): () => void {
    this.#listeners.add(cb);
    return () => this.#listeners.delete(cb);
  }

  async #run(signal: AbortSignal): Promise<void> {
    let delay = BACKOFF_MIN_MS;
    while (!signal.aborted) {
      // FILL IN: set live=true and void this.refresh() when the stream opens (refetch on every (re)connect);
      //   await openConnectionEvents(e => { void this.refresh(); notify listeners (isolate exceptions) }, signal);
      //   on normal end or error: live=false; reset delay after a successful open; sleep `delay` (abort-aware),
      //   then delay = Math.min(delay * 2, BACKOFF_MAX_MS) — bounded by spec M5 "backoff 1s→30s"; AbortError exits
      break;
    }
  }
}

export const connectionsStore = new ConnectionsStore();
```
**Why**: the field and method names are the spec skeleton; `error` is an additive field for the panel's error
state. Listeners are isolated so a pill callback can never kill the shared stream.

### `packages/ai-parrot-server/tests/ui/test_vitest_connections_store.py` (CREATE)
```python
"""FEAT-777 (TASK-5053): run the connections client/store vitests from pytest (validation contract)."""

from ._vitest import run_vitest


def test_connections_store_vitest() -> None:
    """Connections client, SSE parsing, store refresh/backoff/stop."""
    run_vitest("src/lib/api/connections.test.ts", "src/lib/stores/connections.test.ts")
```

### FILL IN checklist
- [ ] `parseSseBlock` — multi-line data, comments ignored; bounded by the M1 frame format.
- [ ] `openConnectionEvents` read loop — partial blocks across reads; bounded by stream.ts buffering pattern.
- [ ] `ConnectionsStore.#run` — refresh on open + per event, 1 s→30 s backoff, abort exits; bounded by M5 skeleton.
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] Exported functions and `ConnectionsStore` API match the spec M5 skeleton exactly.
- [ ] `start()` twice opens one stream; `stop()` aborts the fetch and sets `live=false`.
- [ ] `refresh()` runs on stream open and on each `connection` frame; keep-alive comments trigger nothing.
- [ ] Reconnect delays grow 1 s, 2 s, 4 s … capped at 30 s.
- [ ] No `EventSource`, no WebSocket; Svelte 5 runes only.
- [ ] `pytest packages/ai-parrot-server/tests/ui/test_vitest_connections_store.py -q` passes.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_connections_store.py -q`

---

## Test Specification

```ts
// src/lib/stores/connections.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const listConnections = vi.fn();
const openConnectionEvents = vi.fn();
vi.mock("$lib/api/connections", () => ({ listConnections, openConnectionEvents }));

describe("ConnectionsStore", () => {
  beforeEach(() => { vi.useFakeTimers(); listConnections.mockResolvedValue([]); });
  afterEach(() => { vi.useRealTimers(); vi.resetModules(); });

  it("refreshes on open and on every event", async () => { /* FILL IN */ });
  it("start() is idempotent", async () => { /* FILL IN: openConnectionEvents called once */ });
  it("backs off 1s → 30s between reconnects", async () => { /* FILL IN: reject openConnectionEvents repeatedly */ });
  it("stop() aborts the signal and stops reconnecting", async () => { /* FILL IN */ });
});

// src/lib/api/connections.test.ts — parseSseBlock: event frame → object; ": keep-alive" → null;
//   other event name → null; malformed JSON → null; openConnectionEvents sends Authorization header and
//   dispatches frames split across reads (mock global fetch with a ReadableStream).
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-web-slack.json`
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Blueprint; complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5053 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
