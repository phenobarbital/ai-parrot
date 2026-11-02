# TASK-5057: Per-agent IntegrationsMenu on the connections store; drop `/enable` from the UI

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5053, TASK-5055
**Assigned-to**: unassigned

---

## Context

G6/AC-9 and §3 Module 5: the per-agent `IntegrationsMenu` must read the shared `connectionsStore` (so a connection
finished in another tab or channel shows up live) and must call only `/api/v1/connections*`. The UI's last
`/enable` callers go: `confirmIntegrationEnable` (`integrations.ts:89`), the `EnableResponse` TS type (`:36-38`)
and the menu's call (`IntegrationsMenu.svelte:64`). The pill's call is removed by TASK-5055 — this task depends on it
so deleting the function never breaks the build. AC-11: the connection TS types come from the generated files
(TASK-5052) instead of hand-written interfaces.

---

## Scope

- `IntegrationsMenu.svelte`: list from `connectionsStore.items` (`refresh()` when the menu opens; call
  `connectionsStore.start()` on mount — idempotent, AgentChat already starts it via TASK-5055); connect via
  `startConnect(provider, window.location.origin)` + `awaitOAuthCallback` then `refresh()`; disconnect via
  `disconnect(provider)` then `refresh()`. Keep the `agentId` prop (call sites unchanged).
- `integrations.ts`: delete `EnableResponse` and `confirmIntegrationEnable`; replace the hand-written
  `IntegrationDescriptor`, `ConnectInitResponse`, `DisconnectResponse` interfaces with re-exports of the generated
  types; fix the header comment (no `/enable`). Leave the agent-scoped list/connect/disconnect functions (the routes
  stay as S-1 aliases).
- Tests + pytest wrapper.

**NOT in scope**: the server `/enable` removal (TASK-5048); the pill (TASK-5055); the account pages (TASK-5056).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/integrations/IntegrationsMenu.svelte` | MODIFY | store-backed list; `/api/v1/connections*` only |
| `packages/ai-parrot-server/ui/src/lib/api/integrations.ts` | MODIFY | drop `/enable` client + type; re-export generated types |
| `packages/ai-parrot-server/ui/src/lib/components/agents/integrations/IntegrationsMenu.test.ts` | CREATE | menu tests |
| `packages/ai-parrot-server/tests/ui/test_vitest_integrations_menu.py` | CREATE | pytest wrapper |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import { toastStore } from "$lib/stores/toast.svelte";             // verified: IntegrationsMenu.svelte:2
import { awaitOAuthCallback } from "$lib/oauth/popup";             // verified: IntegrationsMenu.svelte:10
import Icon from "@iconify/svelte";                                 // verified: IntegrationsMenu.svelte:11
import IntegrationItem from "./IntegrationItem.svelte";             // verified: IntegrationsMenu.svelte:12
import { startConnect, disconnect } from "$lib/api/connections";   // created by TASK-5053
import { connectionsStore } from "$lib/stores/connections.svelte"; // created by TASK-5053
export type { IntegrationDescriptor } from "$lib/types/generated/IntegrationDescriptor";   // created by TASK-5052
export type { ConnectInitResponse } from "$lib/types/generated/ConnectInitResponse";       // created by TASK-5052
export type { DisconnectResponse } from "$lib/types/generated/DisconnectResponse";         // created by TASK-5052
```

### Existing Signatures to Use
```ts
// lib/api/integrations.ts: header comment lists the /enable route (:7); IntegrationDescriptor :16-27 (has enabled_on_agent,
//   which the generated type does NOT have); ConnectInitResponse :29-34; EnableResponse :36-38; DisconnectResponse :40-43;
//   createApiClient :49; BASE :51-52; listIntegrations :58; startIntegrationConnect :72; confirmIntegrationEnable :89; disconnectIntegration :103
// IntegrationsMenu.svelte: imports :1-12 (confirmIntegrationEnable :6); props { agentId } :14; state :19-23;
//   loadIntegrations :28-38 (listIntegrations :32); toggleMenu :40-45; handleConnect :50-83 (confirmIntegrationEnable :64);
//   handleDisconnect :88-101; markup iterates `integrations` with IntegrationItem :155-162
// IntegrationItem.svelte:2 imports `type IntegrationDescriptor` from "$lib/api/integrations" and reads
//   integration.icon / display_name / connected / display_account_name — all present on the generated type
// Remaining importers of $lib/api/integrations after TASK-5055: IntegrationItem.svelte, IntegrationsMenu.svelte
//   (verify: grep -rln '\$lib/api/integrations' packages/ai-parrot-server/ui/src)
```

### Does NOT Exist
- ~~`enabled_on_agent` on the generated `IntegrationDescriptor`~~ — the field is gone with agent enablement; nothing in the UI may read it.
- ~~`confirmIntegrationEnable` callers after this task~~ — `grep -rn confirmIntegrationEnable packages/ai-parrot-server/ui/src` must return nothing.
- ~~A per-agent connection list endpoint in the store~~ — the store is principal-scoped; the menu shows the same list for every agent.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/integrations/IntegrationsMenu.svelte", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/api/integrations.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/integrations/IntegrationsMenu.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_integrations_menu.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Svelte 5 runes only; keep the dropdown markup and the outcome toasts unchanged.
- Run `pnpm --dir packages/ai-parrot-server/ui exec svelte-check` (or the build) if available to catch any lingering
  import of the removed symbols; otherwise rely on the grep in "Does NOT Exist".

---

## Implementation Blueprint

### Steps (in order)
1. Confirm TASK-5055 removed the pill's `confirmIntegrationEnable` import — *why*: deleting the function first breaks the pill.
2. Edit `integrations.ts` (delete + re-export) — *why*: AC-9, AC-11.
3. Switch the menu to the store and `connections.ts` — *why*: live updates from any channel (G1/G2), S-1 routes only.
4. Tests + wrapper; run the Validation Commands.

### `src/lib/api/integrations.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c 'export interface EnableResponse {' integrations.ts) — DELETE the interface (:36-38)
// occurrences: 1 (verified: grep -c 'export async function confirmIntegrationEnable(' integrations.ts) — DELETE the
//   doc comment + function (:85-97)
// occurrences: 1 (verified: grep -c ' *   POST   /api/v1/agents/integrations/{agentId}/{provider}/enable' integrations.ts) — DELETE that header line
// REPLACE the hand-written IntegrationDescriptor (:16-27), ConnectInitResponse (:29-34), DisconnectResponse (:40-43) with:
export type { IntegrationDescriptor } from "$lib/types/generated/IntegrationDescriptor";
export type { ConnectInitResponse } from "$lib/types/generated/ConnectInitResponse";
export type { DisconnectResponse } from "$lib/types/generated/DisconnectResponse";
// FILL IN: the remaining functions use these names as types — add `import type { … }` for them too (a bare
//   `export type { X } from` does not bring X into local scope)
```

### `IntegrationsMenu.svelte` (MODIFY — script block)
```ts
// occurrences: 1 (verified: grep -c '    confirmIntegrationEnable,' IntegrationsMenu.svelte); 1 (verified:
//   grep -c 'await confirmIntegrationEnable(agentId, provider);' …); 1 (verified: grep -c 'integrations = await listIntegrations(agentId);' …)
// REPLACE imports :1-12 with:
  import { onMount } from "svelte";
  import { toastStore } from "$lib/stores/toast.svelte";
  import { disconnect, startConnect } from "$lib/api/connections";
  import { connectionsStore } from "$lib/stores/connections.svelte";
  import { awaitOAuthCallback } from "$lib/oauth/popup";
  import Icon from "@iconify/svelte";
  import IntegrationItem from "./IntegrationItem.svelte";

  let { agentId }: { agentId: string } = $props();   // kept for call-site compatibility (AgentChat.svelte:2152)

  let open = $state(false);
  let loadingProvider = $state<string | null>(null);
  const integrations = $derived(connectionsStore.items);
  const fetching = $derived(connectionsStore.loading);
  const fetchError = $derived(connectionsStore.error);

  onMount(() => connectionsStore.start());

  function toggleMenu(): void {
    open = !open;
    if (open) void connectionsStore.refresh();
  }
// handleConnect: `startConnect(provider, window.location.origin)` instead of startIntegrationConnect(agentId, …);
//   on success → toast + `await connectionsStore.refresh()` (no enable call); keep the other outcome toasts (:67-76)
// handleDisconnect: `await disconnect(provider)` then `await connectionsStore.refresh()`
// FILL IN: rewrite handleConnect/handleDisconnect as above — bounded by AC-9 (only /api/v1/connections*)
```
**Why**: `$derived` keeps the existing markup (`integrations`, `fetching`, `fetchError`) untouched. `agentId` is unused
by the principal-scoped routes but removing the prop would ripple into AgentChat.

### `packages/ai-parrot-server/tests/ui/test_vitest_integrations_menu.py` (CREATE)
```python
"""FEAT-777 (TASK-5057): run the IntegrationsMenu vitest from pytest (validation contract)."""

from ._vitest import run_vitest


def test_integrations_menu_vitest() -> None:
    """Menu reads the connections store and never calls /enable."""
    run_vitest("src/lib/components/agents/integrations/IntegrationsMenu.test.ts")
```

### FILL IN checklist
- [ ] `integrations.ts` local type imports; bounded by AC-11.
- [ ] Menu connect/disconnect handlers; bounded by AC-9.
- [ ] Tests below.

---

## Acceptance Criteria

- [ ] `confirmIntegrationEnable` and `EnableResponse` are gone from the UI (`grep -rn` returns nothing) (AC-9).
- [ ] The menu renders `connectionsStore.items` and calls only `startConnect` / `disconnect` / `refresh` (AC-9).
- [ ] `integrations.ts` re-exports the generated connection types; no hand-written copies remain (AC-11).
- [ ] `pytest packages/ai-parrot-server/tests/ui/test_vitest_integrations_menu.py -q` passes; the TASK-5055 wrapper still passes.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_integrations_menu.py -q`
- `pytest packages/ai-parrot-server/tests/ui/test_vitest_chat_auth_retry.py -q`

---

## Test Specification

```ts
// src/lib/components/agents/integrations/IntegrationsMenu.test.ts
// vi.mock("$lib/stores/connections.svelte", …) with items/loading/error/refresh/start; vi.mock("$lib/api/connections", …)
it("opening the menu refreshes the store and lists its items", async () => { /* FILL IN */ });
it("connect uses startConnect + popup, then refreshes; never calls /enable", async () => { /* FILL IN */ });
it("disconnect calls disconnect(provider) then refreshes", async () => { /* FILL IN */ });
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5057 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seats codex terra/sol (UI; gate unrunnable in sandbox, verified with local vitest)
**Date**: 2026-10-31
**Notes**: Implemented per task; merged and merge-tier validated (only red: 3 failures that also fail on origin/dev: test_o365_refresh x2, slack test_manager_payload_drives_identity_and_dm).

**Deviations from spec**: none | describe if any
