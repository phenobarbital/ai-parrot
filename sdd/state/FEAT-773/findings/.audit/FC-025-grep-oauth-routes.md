---
id: FC-025
query_id: Q044
type: grep
intent: "R4: existing O365 OAuth routes to retire/alias (/api/o365/oauth/*)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-025 — No /api/o365/oauth/initiate|status routes exist; web integrations API is /api/v1/agents/integrations/{agent_id}[/{provider}/connect|enable|delete]; Jira callback /api/auth/jira/callback; O365 callback /api/auth/oauth2/o365/callback (docs)

## Summary

Grep for `o365/oauth|oauth/initiate|oauth/status|api/auth/o365|api/auth/jira|api/v1/integrations` restricted to route registrations/fetches: `manager.py:2459-2471` (four IntegrationsHandler routes), `auth/routes.py:341` (`/api/auth/jira/callback` + exclude_list), and the built UI bundle (`server/ui/dist/assets/AgentChat-*.js`) calling `/api/v1/agents/integrations/${agentId}` with `connect`/`enable`/DELETE and an `oauth-popup` window listening for `ai-parrot-oauth-callback` postMessage. Zero hits for `o365/oauth`, `oauth/initiate`, `oauth/status`.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/routes.py`
  lines: 341-349
  symbol: `setup_jira_oauth_routes`
  excerpt: |
    app.router.add_get("/api/auth/jira/callback", jira_oauth_callback)
    if "/api/auth/jira/callback" not in exclude_list: exclude_list.append("/api/auth/jira/callback")
- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 2459-2471
  symbol: `IntegrationsHandler routes`
  excerpt: |
    /api/v1/agents/integrations/{agent_id}
    /api/v1/agents/integrations/{agent_id}/{provider}/connect
    /api/v1/agents/integrations/{agent_id}/{provider}/enable
    /api/v1/agents/integrations/{agent_id}/{provider}

## Notes

Brainstorm §3 'Svelte page hitting /api/o365/oauth/initiate|status passing user_id in body' → does NOT exist in this repo. What exists is an agent-scoped integrations API where user_id comes from the session (FC-048). The brainstorm's proposed `/api/v1/connections` differs from the existing `/api/v1/agents/integrations/{agent_id}` only by agent scoping.
