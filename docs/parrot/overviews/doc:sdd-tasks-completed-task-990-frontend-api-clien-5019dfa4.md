---
type: Wiki Overview
title: 'TASK-990: Frontend API Client and OAuth Popup Helper'
id: doc:sdd-tasks-completed-task-990-frontend-api-client-and-popup-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Creates the frontend foundation modules in `navigator-frontend-next`:'
---

# TASK-990: Frontend API Client and OAuth Popup Helper

**Feature**: FEAT-144 — Cross-Repository JiraToolkit OAuth2 3LO (Web AgentChat)
**Spec**: `sdd/specs/cross-repository-jiratoolkit-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-986
**Assigned-to**: unassigned

---

## Context

Creates the frontend foundation modules in `navigator-frontend-next`:
the typed API client for the integrations endpoints and the OAuth popup helper
that manages `window.open` → `postMessage` → `window.close` lifecycle.

Implements spec Modules 12 and 13.

**CROSS-REPO**: This task is in the `navigator-frontend-next` repository,
not `ai-parrot`. The implementing agent must work in the correct repo.

---

## Scope

- Create `src/lib/api/integrations.ts` with typed axios wrappers:
  - `listIntegrations(agentId)` → `GET /api/v1/agents/integrations/{agentId}`
  - `startIntegrationConnect(agentId, provider)` → `POST .../connect`
  - `confirmIntegrationEnable(agentId, provider)` → `POST .../enable`
  - `disconnectIntegration(agentId, provider)` → `DELETE .../{provider}`
- Create `src/lib/oauth/popup.ts` with `awaitOAuthCallback({authUrl, allowedOrigin, timeoutMs})`:
  - Opens `window.open(authUrl, 'oauth-popup', 'width=500,height=700')`.
  - Registers a `message` listener filtered by `event.origin === allowedOrigin`
    AND `event.data?.type === "ai-parrot-oauth-callback"`.
  - Polls `popup.closed` every 500ms.
  - Handles: popup-blocked, cancelled (closed without message), timeout (60s default), error.
  - Cleans up listener + interval on resolve/reject.
  - Returns `{success, payload}` or `{success: false, reason, error?}`.

**NOT in scope**: IntegrationsMenu component (TASK-991), ConnectIntegrationPill (TASK-992).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator-frontend-next/src/lib/api/integrations.ts` | CREATE | Typed API wrappers |
| `navigator-frontend-next/src/lib/oauth/popup.ts` | CREATE | OAuth popup helper |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```typescript
// src/lib/api/http.ts — verified:
// line 142: export function createApiClient(baseURL?: string): AxiosInstance
// Uses Bearer token from localStorage via interceptor

// src/lib/config.ts — verified:
// line 12-13: const apiBaseUrl = ...
// line 31-38: export const config = { apiBaseUrl, tokenStorageKey, ... }

import { createApiClient } from "$lib/api/http";  // http.ts:142
import { config } from "$lib/config";              // config.ts:31
```

### Existing Patterns to Follow
```typescript
// Typical API module pattern in this codebase (check other api/*.ts files):
const client = createApiClient();

export async function listIntegrations(agentId: string) {
  const { data } = await client.get(`/api/v1/agents/integrations/${agentId}`);
  return data;
}
```

### Does NOT Exist
- ~~`src/lib/api/integrations.ts`~~ — does not exist yet; this task creates it.
- ~~`src/lib/oauth/popup.ts`~~ — does not exist yet; this task creates it.
- ~~`src/lib/oauth/` directory~~ — may not exist; create if needed.
- ~~Pre-existing OAuth popup pattern~~ — only one `window.open` exists in the codebase
  (`ExportMenu.svelte:65`) with no postMessage callback. This task establishes
  the pattern.

---

## Implementation Notes

### API Client Types
```typescript
// src/lib/api/integrations.ts

export interface IntegrationDescriptor {
  provider: string;
  display_name: string;
  icon?: string;
  default_scopes: string[];
  connected: boolean;
  enabled_on_agent: boolean;
  account_id?: string;
  display_account_name?: string;
  email?: string;
  connected_at?: string;
}

export interface ConnectInitResponse {
  auth_url: string;
  state: string;
  scopes: string[];
  expires_in: number;
}

export interface DisconnectResponse {
  provider: string;
  disconnected: boolean;
}
```

### Popup Helper Contract
```typescript
// src/lib/oauth/popup.ts

export interface OAuthCallbackResult {
  success: true;
  payload: {
    provider: string;
    account_id?: string;
    display_name?: string;
  };
}

export interface OAuthCallbackFailure {
  success: false;
  reason: "popup-blocked" | "cancelled" | "timeout" | "error";
  error?: string;
}

export type OAuthCallbackOutcome = OAuthCallbackResult | OAuthCallbackFailure;

export function awaitOAuthCallback(options: {
  authUrl: string;
  allowedOrigin: string;
  timeoutMs?: number;
}): Promise<OAuthCallbackOutcome>;
```

### Key Constraints
- Popup helper validates `event.origin === allowedOrigin` AND
  `event.data?.type === "ai-parrot-oauth-callback"` — both must match.
- Cross-origin or wrong-type messages are silently dropped (not logged).
- If `window.open` returns `null`, resolve immediately with `{success: false, reason: "popup-blocked"}`.
- Clean up: remove `message` listener AND clear the interval on EVERY exit path.
- The `allowedOrigin` should typically be `window.location.origin`.

---

## Acceptance Criteria

- [ ] `listIntegrations(agentId)` calls `GET /api/v1/agents/integrations/{agentId}`.
- [ ] `startIntegrationConnect(agentId, provider)` calls `POST .../connect`.
- [ ] `confirmIntegrationEnable(agentId, provider)` calls `POST .../enable`.
- [ ] `disconnectIntegration(agentId, provider)` calls `DELETE .../{provider}`.
- [ ] All API functions use `createApiClient()` from `$lib/api/http`.
- [ ] Popup helper validates `event.origin` AND `event.data.type`.
- [ ] Popup-blocked case returns `{success: false, reason: "popup-blocked"}`.
- [ ] Timeout case (default 60s) returns `{success: false, reason: "timeout"}`.
- [ ] User closes popup → `{success: false, reason: "cancelled"}`.
- [ ] Cleanup occurs on all exit paths (no memory leaks).
- [ ] TypeScript compiles without errors.

---

## Test Specification

Tests for popup helper use DOM mocking (e.g., `vitest` with `jsdom`):

```typescript
// src/lib/oauth/__tests__/popup.test.ts
import { describe, it, expect, vi } from 'vitest';
import { awaitOAuthCallback } from '../popup';

describe('awaitOAuthCallback', () => {
  it('returns popup-blocked when window.open returns null', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    const result = await awaitOAuthCallback({
      authUrl: 'https://auth.atlassian.com/...',
      allowedOrigin: 'https://app.example.com',
    });
    expect(result).toEqual({ success: false, reason: 'popup-blocked' });
  });

  it('resolves on valid postMessage', async () => {
    // Mock window.open, simulate postMessage
    ...
  });

  it('ignores messages from wrong origin', async () => {
    // Simulate message with wrong origin — should not resolve
    ...
  });

  it('returns timeout after timeoutMs', async () => {
    // Mock with long-running popup, short timeout
    ...
  });
});
```

---

## Agent Instructions

When you pick up this task:

1. **Switch to navigator-frontend-next** repository.
2. **Read** `src/lib/api/http.ts` to confirm `createApiClient` signature.
3. **Read** `src/lib/config.ts` to confirm `config` shape.
4. **Check** existing API modules in `src/lib/api/` for the established pattern.
5. **Check dependencies** — verify TASK-986 endpoints exist in the backend.
6. **Implement** both modules + tests.

---

## Completion Note

**Completed by**: sdd-worker agent
**Date**: 2026-05-05
**Notes**: Implemented both modules exactly as specified.
- `src/lib/api/integrations.ts`: typed API wrappers for all four integrations endpoints
  using `createApiClient()` from `$lib/api/http`.
- `src/lib/oauth/popup.ts`: `awaitOAuthCallback()` with popup-blocked detection,
  postMessage listener (validates origin + type), 500ms poll, 60s default timeout,
  cleanup on all exit paths.
- `src/lib/oauth/__tests__/popup.test.ts`: 7 vitest/jsdom tests — popup-blocked,
  valid postMessage, wrong origin, wrong type, timeout, cancelled (user closes popup),
  error postMessage. All 7 pass.
- Installed vitest and jsdom as devDependencies in navigator-frontend-next to support
  browser-environment tests (existing tests don't need jsdom but popup tests do).
- TypeScript compiles without errors in our new files (pre-existing shadcn errors unaffected).
- Committed in navigator-frontend-next repo on dev branch (commit 3eedf19).

**Deviations from spec**: none
