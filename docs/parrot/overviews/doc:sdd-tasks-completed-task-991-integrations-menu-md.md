---
type: Wiki Overview
title: 'TASK-991: IntegrationsMenu Svelte Component'
id: doc:sdd-tasks-completed-task-991-integrations-menu-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The "+ Integrations" dropdown/popover in the `AgentChat` toolbar is the primary
---

# TASK-991: IntegrationsMenu Svelte Component

**Feature**: FEAT-144 — Cross-Repository JiraToolkit OAuth2 3LO (Web AgentChat)
**Spec**: `sdd/specs/cross-repository-jiratoolkit-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-990
**Assigned-to**: unassigned

---

## Context

The "+ Integrations" dropdown/popover in the `AgentChat` toolbar is the primary
UI for users to connect and manage their OAuth2 integrations. It lists all
available providers, shows connection status, and triggers the popup flow.

Implements spec Module 14.

**CROSS-REPO**: This task is in the `navigator-frontend-next` repository.

---

## Scope

- Create `IntegrationsMenu.svelte` — dropdown/popover triggered by a toolbar button.
  - On open, calls `listIntegrations(agentId)`.
  - Renders one `IntegrationItem.svelte` per result.
  - Each item shows: icon, provider name, status badge (Connected / Not connected).
  - Action button: Connect (if not connected) / Disconnect (if connected).
  - Connect flow: `startIntegrationConnect` → `awaitOAuthCallback` →
    `confirmIntegrationEnable` → refresh menu + toast success.
  - Disconnect flow: `disconnectIntegration` → refresh menu + toast.
  - Empty state: "No integrations available" (when PBAC filters everything — Q-C resolved: always render button).
- Create `IntegrationItem.svelte` — single item in the menu.
- Inject the toolbar button into `AgentChat.svelte` between Refresh and Canvas-toggle
  (toolbar @ L954-975).
- Handle popup-blocked: toast "Popup blocked. Please allow popups for this site."
- Handle errors: toast with message.

**NOT in scope**: ConnectIntegrationPill (TASK-992), backend changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator-frontend-next/src/lib/components/agents/integrations/IntegrationsMenu.svelte` | CREATE | Menu component |
| `navigator-frontend-next/src/lib/components/agents/integrations/IntegrationItem.svelte` | CREATE | Single item component |
| `navigator-frontend-next/src/lib/components/agents/AgentChat.svelte` | MODIFY | Inject toolbar button at L954-975 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```typescript
// From TASK-990:
import {
  listIntegrations,
  startIntegrationConnect,
  confirmIntegrationEnable,
  disconnectIntegration,
  type IntegrationDescriptor,
} from "$lib/api/integrations";
import { awaitOAuthCallback } from "$lib/oauth/popup";

// Existing UI primitives — verified:
import { toastStore } from "$lib/stores/toast.svelte";    // verified exists
import AppDialog from "$lib/ui/components/AppDialog.svelte"; // verified exists
```

### Existing Patterns to Follow
```svelte
<!-- AgentChat.svelte toolbar pattern (L954-975):
     <button class="btn btn-ghost btn-xs btn-square ...">
       <Icon icon="mdi:..." class="size-3.5" />
     </button>
     New button goes between Refresh and Canvas-toggle buttons.
-->
```

### Does NOT Exist
- ~~`IntegrationsMenu.svelte`~~ — does not exist; this task creates it.
- ~~`IntegrationItem.svelte`~~ — does not exist; this task creates it.
- ~~`src/lib/components/agents/integrations/` directory~~ — may not exist; create.
- ~~Pre-existing integrations UI~~ — nothing exists yet.
- ~~`popover` Svelte component~~ — check if the project has one. May use `AppDialog`
  or a custom dropdown. Check existing toolbar menus for the pattern.

---

## Implementation Notes

### Toolbar Button Pattern
```svelte
<!-- In AgentChat.svelte toolbar, between Refresh and Canvas-toggle: -->
<button
  class="btn btn-ghost btn-xs btn-square"
  on:click={toggleIntegrationsMenu}
  title="Integrations"
>
  <Icon icon="mdi:puzzle-plus-outline" class="size-3.5" />
</button>
```

### Connect Flow in IntegrationsMenu
```typescript
async function handleConnect(provider: string) {
  try {
    const { auth_url } = await startIntegrationConnect(agentId, provider);
    const result = await awaitOAuthCallback({
      authUrl: auth_url,
      allowedOrigin: window.location.origin,
    });
    if (result.success) {
      await confirmIntegrationEnable(agentId, provider);
      toastStore.success(`Connected to ${provider}`);
      await refreshMenu();
    } else if (result.reason === "popup-blocked") {
      toastStore.error("Popup blocked. Please allow popups and try again.");
    } else if (result.reason === "cancelled") {
      // User closed popup, no toast needed
    } else if (result.reason === "timeout") {
      toastStore.error("Authorization timed out. Please try again.");
    }
  } catch (err) {
    toastStore.error(`Failed to connect: ${err.message}`);
  }
}
```

### Key Constraints
- `agentId` comes from the `AgentChat` component props.
- Always render the button (Q-C resolved: always render).
- Empty state shows "No integrations available".
- Toast messages should be user-friendly.
- After connect or disconnect, refresh the menu data.

---

## Acceptance Criteria

- [ ] "+ Integrations" button renders in AgentChat toolbar between Refresh and Canvas-toggle.
- [ ] Click opens menu populated from `listIntegrations(agentId)`.
- [ ] Each integration shows: icon, name, status badge.
- [ ] "Connect" button triggers popup flow → enables integration → toast success.
- [ ] "Disconnect" button triggers disconnect → toast → menu refresh.
- [ ] Popup-blocked: toast message shown.
- [ ] Empty menu shows "No integrations available".
- [ ] TypeScript compiles without errors.
- [ ] Component renders correctly with zero, one, and multiple integrations.

---

## Agent Instructions

When you pick up this task:

1. **Read** `AgentChat.svelte` lines 940-990 to find the exact toolbar injection point.
2. **Check** the existing toolbar button pattern (icon, classes, size).
3. **Check** whether the project uses `AppDialog` for dropdowns or has a separate popover.
4. **Check dependencies** — TASK-990 must be complete.
5. **Implement** components and toolbar injection.

---

## Completion Note

**Completed by**: sdd-worker agent
**Date**: 2026-05-05
**Notes**: Implemented as specified.
- `IntegrationItem.svelte`: renders icon (falls back to mdi:puzzle-outline),
  display_name, status badge (Connected/Not connected badge), Connect/Disconnect
  button with loading disabled state.
- `IntegrationsMenu.svelte`: DaisyUI dropdown, button trigger with mdi:puzzle-plus-outline
  icon matching existing toolbar style, loads integrations on open, handles connect flow
  (startIntegrationConnect → awaitOAuthCallback → confirmIntegrationEnable), handles
  disconnect, all outcomes produce appropriate toasts (blocked, timeout, error), cancelled
  is silent, empty state shows "No integrations available".
- `AgentChat.svelte`: imported IntegrationsMenu, injected `<IntegrationsMenu {agentId} />`
  between Refresh button and Canvas-toggle block.
- svelte-check: 0 errors. TypeScript compiles cleanly.
- Committed in navigator-frontend-next on dev (commit ee3712b).

**Deviations from spec**: none
