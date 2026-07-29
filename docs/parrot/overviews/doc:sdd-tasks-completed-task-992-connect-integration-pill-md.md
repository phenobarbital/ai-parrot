---
type: Wiki Overview
title: 'TASK-992: ConnectIntegrationPill and AgentChat Message Wiring'
id: doc:sdd-tasks-completed-task-992-connect-integration-pill-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: When the backend returns an `auth_required` envelope instead of a normal
  chat
---

# TASK-992: ConnectIntegrationPill and AgentChat Message Wiring

**Feature**: FEAT-144 — Cross-Repository JiraToolkit OAuth2 3LO (Web AgentChat)
**Spec**: `sdd/specs/cross-repository-jiratoolkit-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-990, TASK-988
**Assigned-to**: unassigned

---

## Context

When the backend returns an `auth_required` envelope instead of a normal chat
message, the frontend needs to render an inline "Connect [Provider]" pill that
opens the popup helper. This task creates the pill component and wires it into
the `AgentChat` message renderer.

Implements spec Module 15.

**CROSS-REPO**: This task is in the `navigator-frontend-next` repository.

---

## Scope

- Create `ConnectIntegrationPill.svelte` — inline pill component that:
  - Receives `provider`, `auth_url`, `scopes`, `message` from the envelope.
  - Shows the message text + a "Connect [Provider]" button.
  - Click → opens popup helper with `auth_url` → on success, calls
    `confirmIntegrationEnable` → toast → invites user to retry prompt.
  - No auto-retry (Q-D resolved: explicit retry).
- Modify `AgentChat.svelte` message renderer to detect `type === "auth_required"`
  in agent messages and render `ConnectIntegrationPill` instead of normal text.

**NOT in scope**: IntegrationsMenu (TASK-991), backend envelope translation (TASK-988).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator-frontend-next/src/lib/components/agents/integrations/ConnectIntegrationPill.svelte` | CREATE | Inline connect pill |
| `navigator-frontend-next/src/lib/components/agents/AgentChat.svelte` | MODIFY | Message renderer detection |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```typescript
// From TASK-990:
import { confirmIntegrationEnable } from "$lib/api/integrations";
import { awaitOAuthCallback } from "$lib/oauth/popup";

// Existing:
import { toastStore } from "$lib/stores/toast.svelte";
```

### Existing Pattern — Message Renderer
```svelte
<!-- AgentChat.svelte — the message rendering section.
     Need to identify where messages are rendered and add a condition:
     if (message.type === "auth_required") → render ConnectIntegrationPill
     else → render normal message.
     Read the actual component to find the exact insertion point. -->
```

### Does NOT Exist
- ~~`ConnectIntegrationPill.svelte`~~ — does not exist; this task creates it.
- ~~Pre-existing `auth_required` handling in AgentChat~~ — nothing exists.
- ~~`MessageType` enum including `auth_required`~~ — may not exist; check how
  message types are currently distinguished in the renderer.

---

## Implementation Notes

### Envelope Detection
The backend returns (from TASK-988):
```json
{
  "type": "auth_required",
  "provider": "jira",
  "tool_name": "jira_create_issue",
  "auth_url": "https://auth.atlassian.com/authorize?...",
  "scopes": ["read:jira-work", "write:jira-work"],
  "message": "Jira is not connected. Please connect to continue."
}
```

In the message renderer, check:
```typescript
if (message?.type === "auth_required") {
  // Render ConnectIntegrationPill
}
```

### Pill Component
```svelte
<script lang="ts">
  import { confirmIntegrationEnable } from "$lib/api/integrations";
  import { awaitOAuthCallback } from "$lib/oauth/popup";
  import { toastStore } from "$lib/stores/toast.svelte";

  export let provider: string;
  export let authUrl: string;
  export let message: string;
  export let agentId: string;

  let connecting = false;

  async function handleConnect() {
    connecting = true;
    try {
      const result = await awaitOAuthCallback({
        authUrl,
        allowedOrigin: window.location.origin,
      });
      if (result.success) {
        await confirmIntegrationEnable(agentId, provider);
        toastStore.success(`Connected to ${provider}! You can now retry your prompt.`);
      } else if (result.reason === "popup-blocked") {
        toastStore.error("Popup blocked. Please allow popups and try again.");
      }
    } catch (err) {
      toastStore.error(`Connection failed: ${err.message}`);
    } finally {
      connecting = false;
    }
  }
</script>

<div class="...">
  <p>{message}</p>
  <button on:click={handleConnect} disabled={connecting}>
    {connecting ? "Connecting..." : `Connect ${provider}`}
  </button>
</div>
```

### Key Constraints
- No auto-retry of the user's prompt after connect.
- The pill should render inline in the chat message flow (not as a modal).
- `agentId` must be available to the pill (passed from AgentChat context).
- The pill should look like a chat message with an action — match existing styling.

---

## Acceptance Criteria

- [ ] `ConnectIntegrationPill` renders when message has `type === "auth_required"`.
- [ ] Clicking "Connect [Provider]" opens the popup with the supplied `auth_url`.
- [ ] After successful popup, `confirmIntegrationEnable` is called.
- [ ] Toast shows success message inviting user to retry.
- [ ] Popup-blocked shows appropriate toast.
- [ ] No auto-retry of the prompt.
- [ ] Normal messages continue to render as before (no regression).
- [ ] TypeScript compiles without errors.

---

## Agent Instructions

When you pick up this task:

1. **Read** `AgentChat.svelte` message rendering section to find the exact
   insertion point for `auth_required` detection.
2. **Check** how messages are structured (object shape, where `type` field lives).
3. **Check dependencies** — TASK-990 and TASK-988 must be complete.
4. **Implement** pill component and message renderer wiring.
5. **Test** with a mock `auth_required` message in the chat.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-05-05
**Notes**: Implemented as specified. `ConnectIntegrationPill.svelte` creates an
inline amber-styled pill with lock icon, message text, and "Connect [Provider]"
button. `AgentChat.svelte` imports the pill and detects `type === "auth_required"`
in the message renderer. `AgentMessage` type extended with `type`, `provider`,
`auth_url`, `scopes` fields. `handleSend` detects `auth_required` envelopes from
the backend and stores them with the new type fields. TypeScript check: 0 errors.

**Deviations from spec**: none | describe if any
