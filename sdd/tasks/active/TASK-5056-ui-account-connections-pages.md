# TASK-5056: Account › Connections panel and Slack link-confirm page

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5053
**Assigned-to**: unassigned

---

## Context

G1/AC-1: `/account/connections` lists every registered provider for the logged-in user with status, account,
scopes, expiry and channels, with Connect / Reconnect / Disconnect over `/api/v1/connections*` only.
G4/AC-5 (D2): `/account/link?token=…` is where a Slack user, signed in to the admin UI, confirms linking their Slack
identity. Loading the page only **previews** (GET); nothing is written until an explicit **Confirm** click (POST with
`{confirm: true}`); Cancel writes nothing. The `/account` section already exists (FEAT-772: `/account/security`,
`"account"` in `appSections`, `/account` in `SPA_SECTIONS`) — this task adds routes and one nav entry only.

---

## Scope

- `ConnectionsPanel.svelte` (component): rows from `connectionsStore.items`; status badge
  (connected | needs_reconnect | disconnected), account (`display_account_name` ?? `email`), `scopes_granted`,
  `expires_at`, `channels`; Connect / Reconnect (`startConnect` + `awaitOAuthCallback`, then `refresh()`),
  Disconnect (`disconnect`, then `refresh()`).
- `pages/account/Connections.svelte`: page wrapper; `connectionsStore.start()` on mount, `stop()` on destroy.
- `pages/account/LinkChannel.svelte`: read `token` from `window.location.search`; `previewChannelLink` on load;
  show Slack team/user ids and the current Navigator account plus the access implication text; Confirm →
  `confirmChannelLink` once (button disabled while pending/after success); Cancel → navigate away, no request;
  distinct copy for 409 (already linked to another account — contact an administrator), 410 (link expired — run
  `/login` in Slack again), other errors.
- `App.svelte`: routes `/account/connections`, `/account/link` (`requiresAuth: true`) next to `/account/security`.
- `nav.ts`: a "Connections" entry (section `"user"`) right after the "Account" entry.
- Tests + pytest wrapper.

**NOT in scope**: `appSections`, `SPA_SECTIONS` (already done by FEAT-772 — do not touch `config.ts` or
`serving.py`); the per-agent menu (TASK-5057); server routes (TASK-5040, TASK-5041).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/account/ConnectionsPanel.svelte` | CREATE | connections table + actions |
| `packages/ai-parrot-server/ui/src/lib/components/account/ConnectionsPanel.test.ts` | CREATE | panel tests |
| `packages/ai-parrot-server/ui/src/pages/account/Connections.svelte` | CREATE | page; store lifecycle |
| `packages/ai-parrot-server/ui/src/pages/account/LinkChannel.svelte` | CREATE | preview + explicit confirm |
| `packages/ai-parrot-server/ui/src/pages/account/LinkChannel.test.ts` | CREATE | link page tests |
| `packages/ai-parrot-server/ui/src/App.svelte` | MODIFY | two routes |
| `packages/ai-parrot-server/ui/src/lib/nav.ts` | MODIFY | "Connections" nav entry |
| `packages/ai-parrot-server/tests/ui/test_vitest_account_connections.py` | CREATE | pytest wrapper |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import { onDestroy, onMount } from "svelte";
import { ApiError } from "$lib/api/http";                                      // verified: http.ts:31 (status available on the error)
import { awaitOAuthCallback } from "$lib/oauth/popup";                        // verified: popup.ts:66
import { toastStore } from "$lib/stores/toast.svelte";                        // verified: used by Security-era components
import { authStore } from "$lib/stores/auth.svelte";                          // verified: pages/account/Security.svelte:14
import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";          // verified: Security.svelte:15
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "$lib/ui/internal/shadcn/ui/card/index.js";  // verified: Security.svelte:16-22
import { router } from "$lib/router.svelte";                                  // verified: router.svelte.ts (navigate(); used in Topbar.svelte:39)
import { connectionsStore } from "$lib/stores/connections.svelte";           // created by TASK-5053
import { startConnect, disconnect, previewChannelLink, confirmChannelLink } from "$lib/api/connections";  // created by TASK-5053
import type { IntegrationDescriptor } from "$lib/types/generated/IntegrationDescriptor";  // created by TASK-5052
import type { ChannelLinkPreview } from "$lib/types/generated/ChannelLinkPreview";        // created by TASK-5052
```

### Existing Signatures to Use
```ts
// App.svelte:32-37 (FEAT-772)
//     // FEAT-772: user-level account pages (passkey management).
//     { path: "/account/security", component: () => import("./pages/account/Security.svelte"), requiresAuth: true },
// lib/nav.ts:13 type NavSection = "user" | "admin"; :15 interface NavEntry {path,label,icon,section};
//   entries :29-54; "Account" entry :36-41 { path: "/account/security", label: "Account", icon: "M12 3l7 4v5…", section: "user" }
// pages/account/Security.svelte — page structure to mirror (Card layout, $state loading/error, refresh())
// pages/account/Security.test.ts — test pattern (@testing-library/svelte render/fireEvent/waitFor, vi.spyOn on the api module)
// IntegrationDescriptor fields (models.py:39-52): provider, display_name, icon, default_scopes, connected, status,
//   account_id, display_account_name, email, connected_at, channels, scopes_granted, expires_at (epoch seconds), updated_at
// ChannelLinkPreview (spec §2): channel, channel_user_id, team_id, nav_user_id
// Confirm responses (TASK-5041): 200 {channel, linked:true}; 400 missing confirm; 401; 403; 409 conflict; 410 expired/spent
```

### Does NOT Exist
- ~~`/account/connections`, `/account/link` routes or pages~~ — created here.
- ~~A query-param helper on `router`~~ — read `new URLSearchParams(window.location.search).get("token")`.
- ~~An "account" entry missing from `appSections`/`SPA_SECTIONS`~~ — both already present (`config.ts:62`, `serving.py:40`); never re-add.
- ~~Auto-confirm on page load~~ — rejected by D2 hardening (ledger `0cbfeffa739c`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/ui/src/lib/components/account/ConnectionsPanel.svelte", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/account/ConnectionsPanel.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/pages/account/Connections.svelte", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/pages/account/LinkChannel.svelte", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/pages/account/LinkChannel.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/App.svelte", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/nav.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_account_connections.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Svelte 5 runes only; Tailwind 4 + existing shadcn wrappers; icons via `@iconify/svelte`.
- The link page must perform **zero** writes on load and on Cancel (AC-5) — test it by asserting the confirm API was never called.
- Never send identity fields in the confirm body — the server takes the principal from the session (AC-5).

---

## Implementation Blueprint

### Steps (in order)
1. Add routes and nav entry — *why*: pages must be reachable; section setup already exists.
2. Build `ConnectionsPanel` over `connectionsStore` — *why*: single source of list + live updates (M5).
3. Build `Connections.svelte` with store lifecycle — *why*: one stream per open tab.
4. Build `LinkChannel.svelte` preview/confirm — *why*: explicit-consent contract (D2, AC-5).
5. Tests + wrapper; run the Validation Command.

### `src/App.svelte` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '      path: "/account/security",' src/App.svelte)
// AFTER the closing `},` of the /account/security route object (verified: App.svelte:33-37) insert:
    // FEAT-777: user connections + Slack account linking.
    {
      path: "/account/connections",
      component: () => import("./pages/account/Connections.svelte"),
      requiresAuth: true,
    },
    {
      path: "/account/link",
      component: () => import("./pages/account/LinkChannel.svelte"),
      requiresAuth: true,
    },
```

### `src/lib/nav.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '    path: "/account/security",' src/lib/nav.ts)
// AFTER the closing `},` of the "Account" entry (verified: nav.ts:36-41) insert:
  {
    path: "/account/connections",
    label: "Connections",
    icon: "M10 14a4 4 0 005.66 0l3-3a4 4 0 10-5.66-5.66l-1 1M14 10a4 4 0 00-5.66 0l-3 3a4 4 0 105.66 5.66l1-1",
    section: "user",
  },
```
**Why**: the `section: "user"` anchor occurs twice in nav.ts; the path line is unique.

### `src/pages/account/LinkChannel.svelte` (CREATE)
```svelte
<!-- Account › Link channel (FEAT-777 M5, D2). Preview on load; write only on explicit Confirm. -->
<script lang="ts">
  import { onMount } from "svelte";
  import { ApiError } from "$lib/api/http";
  import { confirmChannelLink, previewChannelLink } from "$lib/api/connections";
  import { router } from "$lib/router.svelte";
  import type { ChannelLinkPreview } from "$lib/types/generated/ChannelLinkPreview";

  const token = new URLSearchParams(window.location.search).get("token") ?? "";

  let preview = $state<ChannelLinkPreview | null>(null);
  let state = $state<"loading" | "ready" | "confirming" | "linked" | "conflict" | "expired" | "error">("loading");

  function classify(err: unknown): "conflict" | "expired" | "error" {
    const status = err instanceof ApiError ? err.status : undefined;
    return status === 409 ? "conflict" : status === 410 ? "expired" : "error";
  }

  onMount(async () => {
    if (!token) { state = "expired"; return; }
    try {
      preview = await previewChannelLink(token);
      state = "ready";
    } catch (err) {
      state = classify(err);
    }
  });

  async function confirm(): Promise<void> {
    if (state !== "ready") return;           // single submit
    state = "confirming";
    try {
      await confirmChannelLink(token);
      state = "linked";
    } catch (err) {
      state = classify(err);
    }
  }

  function cancel(): void {
    router.navigate("/account/connections"); // no request — Cancel performs no write
  }
</script>
<!-- FILL IN: Card markup — show preview.team_id / preview.channel_user_id (Slack) and preview.nav_user_id (this account),
     the sentence "This Slack account will be able to use your connections", Confirm + Cancel buttons (disabled unless
     state === "ready"), and the copy for linked / conflict (contact an administrator) / expired (run /login in Slack again)
     / error — bounded by AC-5 and spec M5 LinkChannel comment -->
```
**Why**: the state machine makes double submit and write-on-load impossible by construction. Verify `ApiError` exposes
`status` (http.ts:31) before relying on it; if it differs, adapt `classify` only.

### `ConnectionsPanel.svelte` / `Connections.svelte` (CREATE)
```ts
// ConnectionsPanel <script>: let busy = $state<string | null>(null); rows = connectionsStore.items
//   async function connect(p: IntegrationDescriptor) { busy = p.provider; try { const { auth_url } = await startConnect(p.provider,
//     window.location.origin); const r = await awaitOAuthCallback({ authUrl: auth_url, allowedOrigin: window.location.origin });
//     // FILL IN: r.success → toast + connectionsStore.refresh(); other reasons → same toasts as IntegrationsMenu.svelte:67-74
//   } finally { busy = null } }
//   async function remove(p) { // FILL IN: disconnect(p.provider) → refresh(); error toast }
//   FILL IN: badge from p.status ?? (p.connected ? "connected" : "disconnected"); expires_at → toLocaleString(); channels join
// Connections.svelte: onMount(() => { connectionsStore.start(); void connectionsStore.refresh(); }); onDestroy(() => connectionsStore.stop());
//   render <ConnectionsPanel /> inside a Card titled "Connections"
```

### `packages/ai-parrot-server/tests/ui/test_vitest_account_connections.py` (CREATE)
```python
"""FEAT-777 (TASK-5056): run the Account › Connections / Link vitests from pytest (validation contract)."""

from ._vitest import run_vitest


def test_account_connections_vitest() -> None:
    """Connections panel actions and the preview-then-confirm link page."""
    run_vitest(
        "src/lib/components/account/ConnectionsPanel.test.ts",
        "src/pages/account/LinkChannel.test.ts",
    )
```

### FILL IN checklist
- [ ] LinkChannel markup and copy; bounded by AC-5.
- [ ] ConnectionsPanel connect/disconnect/badge/expiry; bounded by AC-1.
- [ ] Tests below.

---

## Acceptance Criteria

- [ ] `/account/connections` renders status, account, scopes, expiry, channels; Connect/Reconnect/Disconnect call only `/api/v1/connections*` (AC-1).
- [ ] `/account/link` load calls only the preview; Cancel makes no request; Confirm posts once; 409/410/error copy shown (AC-5).
- [ ] "Connections" nav entry appears in the user section after "Account"; no change to `config.ts` / `serving.py`.
- [ ] `pytest packages/ai-parrot-server/tests/ui/test_vitest_account_connections.py -q` passes, and the FEAT-772 account wrapper still passes.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_account_connections.py -q`
- `pytest packages/ai-parrot-server/tests/ui/test_vitest_account_navigation.py -q`

---

## Test Specification

```ts
// src/pages/account/LinkChannel.test.ts
it("load previews only; never confirms", async () => { /* FILL IN: spy previewChannelLink resolves; confirmChannelLink not called */ });
it("shows both identities", async () => { /* FILL IN */ });
it("Cancel performs no write", async () => { /* FILL IN */ });
it("Confirm posts once even on double click", async () => { /* FILL IN */ });
it("409 / 410 / generic error copy", async () => { /* FILL IN */ });

// src/lib/components/account/ConnectionsPanel.test.ts
it("renders status/account/scopes/expiry/channels", async () => { /* FILL IN: mock connectionsStore.items */ });
it("connect → startConnect + popup → refresh; disconnect → refresh", async () => { /* FILL IN */ });
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5056 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
