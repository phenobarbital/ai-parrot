# TASK-5055: Connect pill in both chat modes with guarded automatic retry

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5053, TASK-5054
**Assigned-to**: unassigned

---

## Context

Spec §2 "Chat (M4)", §3 Module 4, AC-7, G3. Today the Connect pill appears only in non-streaming mode
(`AgentChat.svelte:1344`), connects through the raw `auth_url`, calls the soon-removed `/enable`
(`ConnectIntegrationPill.svelte:30`) and tells the user to "retry your prompt" (`:31-33`). This task renders the
pill in both modes, connects through `startConnect` (TASK-5053) so origin validation and PBAC apply, and re-sends
the originating prompt **at most once, only** when the server said `retry_safe === true`. The safety decision is
the server's (TASK-5051); the client only enforces the budget and readiness checks.

---

## Scope

- `types/agent.ts`: add `retry_safe?: boolean` and `origin_user_msg_id?: string` to `AgentMessage` (OAuth2 block).
- Streaming path: on a `{type:"auth_required"}` chunk (TASK-5054) append an auth message after the finished bubble.
- Non-streaming path: copy `retry_safe` and the originating user message id into the auth message.
- `ConnectIntegrationPill.svelte`: drop the `authUrl` prop and `confirmIntegrationEnable`; connect via
  `startConnect(provider, window.location.origin, scopes)` + `awaitOAuthCallback`; also listen for a matching
  `connection.completed` on `connectionsStore.onEvent`; call `onConnected(provider)` once; show a manual
  **Retry** button (completed-actions warning) when auto-retry does not apply.
- `AgentChat.svelte`: `handleAuthConnected(msg)` implementing the guard below; start `connectionsStore` on mount
  and `stop()` on destroy.
- Tests (vitest) + pytest wrapper.

**Retry guard (all must hold, else manual Retry only)**: `msg.retry_safe === true`; `msg.origin_user_msg_id`
not already in `autoRetried`; no user message newer than the origin; after `await connectionsStore.refresh()`
the provider's item has `connected === true` and its `scopes_granted` ⊇ `msg.scopes` (when `msg.scopes` is
non-empty). Add the origin id to `autoRetried` **before** awaiting the resend, so popup and SSE completions share
one budget. The resend reuses the origin message id (`handleSend(…, userMsg.id)` via `handleRetry`), so a repeated
auth failure on the retried turn cannot reset the budget.

**NOT in scope**: removing `confirmIntegrationEnable`/`EnableResponse` from `integrations.ts` and the menu (TASK-5057);
stream parsing (TASK-5054); server `retry_safe` (TASK-5051); bot chat mode.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/types/agent.ts` | MODIFY | `retry_safe`, `origin_user_msg_id` on `AgentMessage` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte` | MODIFY | auth message in both modes; retry guard; store lifecycle |
| `packages/ai-parrot-server/ui/src/lib/components/agents/integrations/ConnectIntegrationPill.svelte` | MODIFY | startConnect, onConnected, SSE completion, manual Retry |
| `packages/ai-parrot-server/ui/src/lib/components/agents/integrations/ConnectIntegrationPill.test.ts` | CREATE | pill tests |
| `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.auth-retry.test.ts` | CREATE | streaming pill + guard tests |
| `packages/ai-parrot-server/tests/ui/test_vitest_chat_auth_retry.py` | CREATE | pytest wrapper |
| `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.test.ts` | MODIFY | add `vi.mock("$lib/stores/connections.svelte", …)` — AgentChat now starts the SSE store |
| `packages/ai-parrot-server/ui/src/lib/components/agents/avatar-gating.test.ts` | MODIFY | add `vi.mock("$lib/stores/connections.svelte", …)` — AgentChat now starts the SSE store |
| `packages/ai-parrot-server/ui/src/lib/components/agents/voice-gating.test.ts` | MODIFY | add `vi.mock("$lib/stores/connections.svelte", …)` — AgentChat now starts the SSE store |
| `packages/ai-parrot-server/ui/src/pages/agents/AgentDetail.test.ts` | MODIFY | add `vi.mock("$lib/stores/connections.svelte", …)` — AgentChat now starts the SSE store |
| `packages/ai-parrot-server/ui/src/pages/agents/AgentChatPage.test.ts` | MODIFY | add `vi.mock("$lib/stores/connections.svelte", …)` — AgentChat now starts the SSE store |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import { awaitOAuthCallback } from "$lib/oauth/popup";              // verified: popup.ts:66; result {success} | {reason: popup-blocked|cancelled|timeout|error, error?}
import { toastStore } from "$lib/stores/toast.svelte";              // verified: ConnectIntegrationPill.svelte:4, AgentChat.svelte:43
import Icon from "@iconify/svelte";                                  // verified: ConnectIntegrationPill.svelte:5
import { startConnect } from "$lib/api/connections";                // created by TASK-5053
import { connectionsStore } from "$lib/stores/connections.svelte"; // created by TASK-5053
import type { ConnectionEvent } from "$lib/types/generated/ConnectionEvent";   // created by TASK-5052
```

### Existing Signatures to Use
```ts
// lib/types/agent.ts:25 interface AgentMessage — OAuth2 block :39-43: type?, provider?, auth_url?, scopes?
//   (anchor `  scopes?: string[]; // Requested OAuth2 scopes` :43, count 1)
// AgentChat.svelte (2767 lines — read only these ranges):
//   :2 import { onMount, tick, untrack } from "svelte"; :46 import { onDestroy } from "svelte";
//   :64 import ConnectIntegrationPill …; :199 let messages = $state<AgentMessage[]>([]);
//   :757 async function handleSend(query, methodName?, outputMode?, llm?, kwargs?, existingUserMsgId?)
//   :798 const userMsgId = existingUserMsgId || uuidv4();
//   :849 let finalMessage: AgentMessage | null = null;  (streaming branch)
//   :940 for await (const event of generator) {  chunk :941 / done :954 / suggestions :1050-1061
//   :1344 if (rawResult.type === "auth_required") { assistantMsg = {…type:"auth_required", provider, auth_url, scopes…} } (:1344-1363)
//   :1946 async function handleRetry(msgId: string) — removes msg, resends the user message right before it with its id
//   :2468-2474 {#if msg.type === "auth_required"} <ConnectIntegrationPill provider authUrl message {agentId} />
// ConnectIntegrationPill.svelte: props provider/authUrl/message/agentId (:7-17); handleConnect (:21-52)
// StreamChunk auth variant (TASK-5054): { type: "auth_required"; payload: AuthRequiredPayload; turn_id?: string; retry_safe?: boolean }
// connectionsStore (TASK-5053): items, refresh(), start(), stop(), onEvent(cb) => unsubscribe
// ConnectionEvent.kind "connection.completed" | "connection.revoked" | "connection.refresh_failed" (events.py:14)
// AgentChat.test.ts mocks: $lib/api/stream, $lib/api/agent, chat-db, toast… (:39-75) — copy for the new test file
```

### Does NOT Exist
- ~~`AgentMessage.retry_safe` / `origin_user_msg_id`~~ — added here.
- ~~A client-side computation of retry safety from tool status~~ — forbidden (spec M4); only the server flag counts.
- ~~`onConnected` / `onRetry` props on the pill~~ — added here (`onRetry` and `retrySafe` are additive to the skeleton for the manual Retry button).
- ~~An `auth_required` handler in the streaming loop~~ — today only `chunk|done|suggestions` (:941-1061).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/ui/src/lib/types/agent.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/integrations/ConnectIntegrationPill.svelte", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/integrations/ConnectIntegrationPill.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.auth-retry.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_chat_auth_retry.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.test.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/avatar-gating.test.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/voice-gating.test.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/pages/agents/AgentDetail.test.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/pages/agents/AgentChatPage.test.ts", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Svelte 5 runes only. `autoRetried` is a plain `Set<string>` (not reactive) — it is a guard, not UI state.
- "Multiple outstanding auth requirements disable auto-retry" is enforced by the server (`retry_safe=false`); the
  client shows only the first pill per turn (spec v1).
- Keep the existing `AgentChat.test.ts` passing (it is in the spec's Validation Contract).

---

## Implementation Blueprint

### Steps (in order)
1. Extend `AgentMessage` — *why*: the guard needs the flag and origin id on the auth message.
2. Rewrite the pill's connect flow on `startConnect` and add `onConnected`/`retrySafe`/`onRetry` — *why*: S-1 route applies origin validation + PBAC; `/enable` is going away.
3. Add the streaming `auth_required` branch and the non-streaming fields — *why*: AC-7 "both modes".
4. Add `handleAuthConnected` + store lifecycle — *why*: the single place the budget and readiness checks live.
5. Add the store mock to the five existing tests that render AgentChat (AgentChat.test.ts, avatar-gating.test.ts,
   voice-gating.test.ts, pages/agents/AgentDetail.test.ts, pages/agents/AgentChatPage.test.ts) — *why*: AgentChat now
   calls `connectionsStore.start()` on mount, which would open a real fetch stream in jsdom.
   Mock: `vi.mock("$lib/stores/connections.svelte", () => ({ connectionsStore: { items: [], loading: false, live: false,
   error: null, start: vi.fn(), stop: vi.fn(), refresh: vi.fn(async () => {}), onEvent: vi.fn(() => () => {}) } }))`.
6. Tests + wrapper; run the Validation Commands (including the existing wrapper).

### `lib/types/agent.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '  scopes?: string[]; // Requested OAuth2 scopes' lib/types/agent.ts)
// AFTER — insert below that line (verified: agent.ts:43)
  retry_safe?: boolean; // FEAT-777: server-authored; absent = false. Never computed client-side.
  origin_user_msg_id?: string; // FEAT-777: user message whose turn raised auth_required (retry budget key)
```

### `ConnectIntegrationPill.svelte` (MODIFY — script block)
```ts
// occurrences: 1 each (verified: grep -c 'import { confirmIntegrationEnable } from "$lib/api/integrations";' and
//   grep -c '    authUrl: string;' ConnectIntegrationPill.svelte) — replace the whole <script> block (:1-53) with:
  import { onDestroy } from "svelte";
  import Icon from "@iconify/svelte";
  import { startConnect } from "$lib/api/connections";
  import { awaitOAuthCallback } from "$lib/oauth/popup";
  import { connectionsStore } from "$lib/stores/connections.svelte";
  import { toastStore } from "$lib/stores/toast.svelte";

  let {
    provider, message, agentId, scopes = [], retrySafe = false, onConnected, onRetry,
  }: {
    provider: string; message: string; agentId: string; scopes?: string[]; retrySafe?: boolean;
    onConnected?: (provider: string) => void; onRetry?: () => void;
  } = $props();

  let connecting = $state(false);
  let connected = $state(false);
  let notified = false;

  function notifyConnected(): void {
    if (notified) return;        // popup + SSE may both fire: report once
    notified = true;
    connected = true;
    onConnected?.(provider);
  }

  const unsubscribe = connectionsStore.onEvent((e) => {
    if (e.kind === "connection.completed" && e.provider === provider) notifyConnected();
  });
  onDestroy(unsubscribe);

  async function handleConnect(): Promise<void> {
    connecting = true;
    try {
      const { auth_url } = await startConnect(provider, window.location.origin, scopes.length ? scopes : undefined);
      const result = await awaitOAuthCallback({ authUrl: auth_url, allowedOrigin: window.location.origin });
      // FILL IN: success → notifyConnected(); keep the existing popup-blocked/cancelled/timeout/error toasts (:34-44)
    } catch (err: unknown) {
      toastStore.error(`Connection failed: ${err instanceof Error ? err.message : "unknown error"}`);
    } finally {
      connecting = false;
    }
  }
```
**Why**: `agentId` stays in props (skeleton) even though the S-1 route is principal-scoped. Markup: keep the bubble;
after `connected && !retrySafe` show a "Retry" button calling `onRetry` with the text "Retrying may repeat actions that
already completed." — # FILL IN: markup, bounded by spec M4 "manual Retry button explaining that completed actions may repeat".

### `AgentChat.svelte` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '} else if (event.type === "suggestions") {' AgentChat.svelte) — streaming loop (:1050).
// ADD a sibling branch after the suggestions branch closes (before the loop's closing brace):
            } else if (event.type === "auth_required") {
              // FILL IN: append ONE AgentMessage {id: uuidv4(), role:"assistant", type:"auth_required",
              //   content: event.payload.message || "Authorization required to use this feature.",
              //   provider: event.payload.provider, scopes: event.payload.scopes ?? [],
              //   retry_safe: event.retry_safe === true, origin_user_msg_id: userMsgId, timestamp: new Date(),
              //   metadata like :1355-1361} — only the first auth chunk per turn (spec v1)
```
```ts
// occurrences: 1 (verified: grep -c 'if (rawResult.type === "auth_required")' AgentChat.svelte) — non-streaming (:1344).
// In the assistantMsg literal (:1345-1362) add:  retry_safe: rawResult.retry_safe === true, origin_user_msg_id: userMsgId,
```
```ts
// occurrences: 1 (verified: grep -c 'async function handleRetry(msgId: string) {' AgentChat.svelte)
// BEFORE — insert above handleRetry (verified: AgentChat.svelte:1946)
  const autoRetried = new Set<string>(); // origin user-message ids already auto-resent (popup + SSE share it)

  async function handleAuthConnected(msg: AgentMessage): Promise<void> {
    const origin = msg.origin_user_msg_id;
    if (msg.retry_safe !== true || !origin || autoRetried.has(origin)) return;
    // FILL IN: return if any user message appears after `origin` in `messages` (no newer message);
    //   autoRetried.add(origin) BEFORE any await; await connectionsStore.refresh(); find item by msg.provider;
    //   require connected && scopes_granted ⊇ (msg.scopes ?? []); then await handleRetry(msg.id) — bounded by AC-7
  }
```
```svelte
<!-- occurrences: 1 (verified: grep -c 'authUrl={msg.auth_url ?? ""}' AgentChat.svelte) — REPLACE the pill props (:2469-2474) -->
                    <ConnectIntegrationPill
                      provider={msg.provider ?? ""}
                      message={msg.content}
                      {agentId}
                      scopes={msg.scopes ?? []}
                      retrySafe={msg.retry_safe === true}
                      onConnected={() => handleAuthConnected(msg)}
                      onRetry={() => handleRetry(msg.id)}
                    />
```
```ts
// Store lifecycle — FILL IN: in the existing onMount add connectionsStore.start(); in the existing onDestroy add
//   connectionsStore.stop() — do not create a second onMount/onDestroy if one exists (verify with grep first)
```

### `packages/ai-parrot-server/tests/ui/test_vitest_chat_auth_retry.py` (CREATE)
```python
"""FEAT-777 (TASK-5055): run the chat auth-required / auto-retry vitests from pytest (validation contract)."""

from ._vitest import run_vitest


def test_chat_auth_retry_vitest() -> None:
    """Pill in both modes; one guarded auto-retry; manual retry otherwise."""
    run_vitest(
        "src/lib/components/agents/AgentChat.auth-retry.test.ts",
        "src/lib/components/agents/integrations/ConnectIntegrationPill.test.ts",
        "src/lib/components/agents/AgentChat.test.ts",
        "src/lib/components/agents/avatar-gating.test.ts",
        "src/lib/components/agents/voice-gating.test.ts",
        "src/pages/agents/AgentDetail.test.ts",
        "src/pages/agents/AgentChatPage.test.ts",
    )
```

### FILL IN checklist
- [ ] Pill: success/other outcomes; Retry markup + warning copy; bounded by spec M4.
- [ ] Streaming branch: one auth message per turn; bounded by spec v1 "first pill".
- [ ] `handleAuthConnected`: newer-message check, mark-before-await, refresh + scope check; bounded by AC-7.
- [ ] Store start/stop in existing lifecycle hooks; bounded by spec §7 "one stream per tab".
- [ ] Tests below.

---

## Acceptance Criteria

- [ ] Streaming and non-streaming auth turns both render the pill (AC-7).
- [ ] The pill never calls `/enable` and never uses `auth_url` from the payload; it calls `startConnect`.
- [ ] Safe turn + provider/scopes ready → exactly one resend, even when popup success and SSE completion both fire.
- [ ] A repeated auth failure on the retried turn does not trigger a second automatic resend.
- [ ] `retry_safe` false/absent, a newer user message, or missing scopes → no automatic resend; manual Retry shown with the warning.
- [ ] Existing `AgentChat.test.ts`, `avatar-gating`, `voice-gating`, `AgentDetail`, `AgentChatPage` tests still pass with the store mocked.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_chat_auth_retry.py -q`
- `pytest packages/ai-parrot-server/tests/ui/test_vitest_suggestion_stream_trailer.py -q`

---

## Test Specification

```ts
// src/lib/components/agents/AgentChat.auth-retry.test.ts — copy the vi.mock block of AgentChat.test.ts (:39-75),
// plus vi.mock("$lib/stores/connections.svelte", …) and vi.mock("$lib/api/connections", …)
it("streaming: renders the pill from an auth_required chunk", async () => { /* FILL IN */ });
it("auto-retries once when retry_safe and scopes are ready (popup + SSE race)", async () => { /* FILL IN */ });
it("repeated auth failure on the retried turn does not resend again", async () => { /* FILL IN */ });
it("no auto-retry when retry_safe is false/absent; manual Retry warns", async () => { /* FILL IN */ });
it("no auto-retry when a newer user message exists or scopes are missing", async () => { /* FILL IN */ });

// src/lib/components/agents/integrations/ConnectIntegrationPill.test.ts
it("connects through startConnect, not the payload auth_url", async () => { /* FILL IN */ });
it("calls onConnected once on popup success or a matching SSE completion", async () => { /* FILL IN */ });
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5055 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seats codex sol/terra/luna (UI; gate unrunnable in sandbox, verified with local vitest; only 3 pre-existing UI failures)
**Date**: 2026-10-31
**Notes**: Implemented per task; merged and merge-tier validated (only red: 3 failures that also fail on origin/dev: test_o365_refresh x2, slack test_manager_payload_drives_identity_and_dm).

**Deviations from spec**: none | describe if any
