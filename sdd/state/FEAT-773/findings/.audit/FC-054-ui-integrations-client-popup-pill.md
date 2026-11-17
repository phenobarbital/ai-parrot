---
id: FC-054
query_id: Q047-F1
type: read
intent: "Follow-up: read UI integrations client, popup helper, ConnectIntegrationPill and AgentChat auth_required handling."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-028
depth: 1
---

# FC-054 — Admin UI: api/integrations.ts (typed 4-route client), oauth/popup.ts awaitOAuthCallback (postMessage ai-parrot-oauth-callback, 60s timeout, popup-blocked/cancelled handling), ConnectIntegrationPill (inline Connect -> popup -> confirmIntegrationEnable), AgentChat renders the pill when rawResult.type === auth_required

## Summary

`api/integrations.ts` (111): `IntegrationDescriptor`, `ConnectInitResponse`, `listIntegrations`, `startIntegrationConnect(agentId, provider, returnOrigin)`, `confirmIntegrationEnable`, `disconnectIntegration`. `oauth/popup.ts` (149): `awaitOAuthCallback({authUrl, allowedOrigin, timeoutMs=60000})` → success/payload | popup-blocked | cancelled | timeout | error. `ConnectIntegrationPill.svelte` (89): props `provider, authUrl, message, agentId`; on click → popup → `confirmIntegrationEnable` → toast 'You can now retry your prompt' (no automatic retry). `AgentChat.svelte:1342-1351` detects `rawResult.type === "auth_required"` and creates a message of `type: "auth_required"`; `:2468-2469` renders `ConnectIntegrationPill`. `IntegrationsMenu.svelte` (167): dropdown list with Connect/Disconnect per provider.

## Citations

- path: `packages/ai-parrot-server/ui/src/lib/api/integrations.ts`
  lines: 1-9
  symbol: `module docstring`
  excerpt: |
    Wraps the four routes exposed by parrot.handlers.integrations.IntegrationsHandler: GET …/{agentId}; POST …/{provider}/connect; POST …/{provider}/enable; DELETE …/{provider}
- path: `packages/ai-parrot-server/ui/src/lib/oauth/popup.ts`
  lines: 1-10
  symbol: `awaitOAuthCallback docstring`
  excerpt: |
    Opens a popup window, registers a message listener, and resolves when the popup sends an "ai-parrot-oauth-callback" postMessage, OR the popup is closed (cancelled), OR the timeout expires.
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/integrations/ConnectIntegrationPill.svelte`
  lines: 20-35
  symbol: `handleConnect`
  excerpt: |
    const result = await awaitOAuthCallback({ authUrl, allowedOrigin: window.location.origin });
    if (result.success) { await confirmIntegrationEnable(agentId, provider); toastStore.success(`Connected to ${provider}! You can now retry your prompt.`); }
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte`
  lines: 1342-1351, 2468-2469
  symbol: `auth_required handling`
  excerpt: |
    if (rawResult.type === "auth_required") { ... type: "auth_required" }
    {#if msg.type === "auth_required"} <ConnectIntegrationPill ...

## Notes

Brainstorm S-3a scope ('ConnectionsPanel + ConnectionCard + store, inline block, popup postMessage, status without reload') is ~70% present in the admin UI. Missing: cross-channel status (agent-scoped list only), WS push on completion (popup-only), automatic retry after connect, granted scopes/expiry display.
