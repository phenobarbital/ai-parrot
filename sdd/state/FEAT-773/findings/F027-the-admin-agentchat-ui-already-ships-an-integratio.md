---
id: F027
query_id: Q047
type: grep
intent: "R5: admin/AgentChat Svelte UI — existing oauth/connect/popup code and WS event handling."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-028]
---

# F027 — The admin AgentChat UI already ships an integrations menu, per-provider connect/disconnect items, an OAuth popup helper and an inline ConnectIntegrationPill for auth_required replies

## Summary

17 files match `oauth|popup|connect_|integrations` under `packages/ai-parrot-server/ui/src/lib`. Relevant: `api/integrations.ts` (typed client, 12 hits), `oauth/popup.ts` (33), `components/agents/integrations/IntegrationsMenu.svelte` (22), `IntegrationItem.svelte`, `ConnectIntegrationPill.svelte` (5), `components/agents/AgentChat.svelte` (5), `types/agent.ts` (auth_required envelope fields). Others are unrelated (chart popups, DataMap).

## Citations

- path: `packages/ai-parrot-server/ui/src/lib/api/integrations.ts`
  lines: 1-40
  symbol: `IntegrationDescriptor / ConnectInitResponse`
  excerpt: |
    GET /api/v1/agents/integrations/{agentId}; POST .../{provider}/connect; POST .../{provider}/enable; DELETE .../{provider}
    export interface IntegrationDescriptor { provider; display_name; icon?; default_scopes; connected; enabled_on_agent; account_id?; display_account_name?; email?; connected_at? }
- path: `packages/ai-parrot-server/ui/src/lib/oauth/popup.ts`
  lines: 1-45
  symbol: `awaitOAuthCallback`
  excerpt: |
    Opens a popup window, registers a message listener ("ai-parrot-oauth-callback"), resolves on success / cancelled / timeout / popup-blocked
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/integrations/IntegrationsMenu.svelte`
  lines: 1-167
  symbol: `IntegrationsMenu`
  excerpt: |
    dropdown listing IntegrationDescriptor[] with Connect/Disconnect -> connect -> popup -> confirmIntegrationEnable
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/integrations/ConnectIntegrationPill.svelte`
  lines: 1-89
  symbol: `ConnectIntegrationPill`
  excerpt: |
    inline Connect <provider> pill rendered for msg.type === auth_required
- path: `packages/ai-parrot-server/ui/src/lib/types/agent.ts`
  lines: 39-40
  symbol: `auth_required fields`
  excerpt: |
    // OAuth2 auth_required envelope fields
    type?: string; // "auth_required" for OAuth2 prompts

## Notes

Brainstorm §10 'a Svelte Connections panel or A2UI auth block — nothing shipped' → WRONG for the admin UI (`packages/ai-parrot-server/ui`): a per-agent integrations menu + inline auth pill shipped (TASK-987/990 lineage). Completion arrives via popup postMessage, not a WS event. The TROC AgentChat UI is a different repo and was not inspected. See FC-054/FC-055.
