---
id: F024
query_id: [Q044, Q021-F1]
type: [grep, read]
intent: "R4: existing O365 OAuth routes to retire/alias (/api/o365/oauth/*)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 1
merged_from: [FC-025, FC-047]
---

# F024 — No /api/o365/oauth/initiate|status routes exist; web integrations API is /api/v1/agents/integrations/{agent_id}[/{provider}/connect|enable|delete]; Jira callback /api/auth/jira/callback; O365 callback /api/auth/oauth2/o365/callback (docs)

## Summary

**[FC-025]** Grep for `o365/oauth|oauth/initiate|oauth/status|api/auth/o365|api/auth/jira|api/v1/integrations` restricted to route registrations/fetches: `manager.py:2459-2471` (four IntegrationsHandler routes), `auth/routes.py:341` (`/api/auth/jira/callback` + exclude_list), and the built UI bundle (`server/ui/dist/assets/AgentChat-*.js`) calling `/api/v1/agents/integrations/${agentId}` with `connect`/`enable`/DELETE and an `oauth-popup` window listening for `ai-parrot-oauth-callback` postMessage. Zero hits for `o365/oauth`, `oauth/initiate`, `oauth/status`.

**[FC-047]** 351 lines. `_handle_web_callback` (:84-166) persists via `IntegrationsService().persist_credential(user_id, provider, token_set)` and renders the postMessage page. `jira_oauth_callback` (:232-331): after `handle_callback`, `channel = state_payload.get("channel", "telegram")` (default telegram for back-compat); `web` → web handler; `slack` → `handle_slack_jira_callback`; `msteams` → `handle_msteams_jira_callback`; telegram → `request.app.get("telegram_jira_session_stamper")(telegram_user_id, token_set)` then fire-and-forget `_notify_telegram(notifier, chat_id, …)` using `app.get("jira_oauth_notifier")`. Consent-denial path (:187-229) routes `?error=` similarly. `setup_jira_oauth_routes(app)` (:333-351) mounts + exclude_list.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/routes.py`
  lines: 333-351
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
- path: `packages/ai-parrot/src/parrot/auth/routes.py`
  lines: 277-291
  symbol: `jira_oauth_callback (dispatch)`
  excerpt: |
    channel = state_payload.get("channel", "telegram")
    if channel == "web": ...
    if channel == "slack": from parrot.integrations.slack.oauth_callback import handle_slack_jira_callback
    if channel == "msteams": from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback
- path: `packages/ai-parrot/src/parrot/auth/routes.py`
  lines: 296-322
  symbol: `jira_oauth_callback (telegram)`
  excerpt: |
    stamper = request.app.get("telegram_jira_session_stamper")
    notifier = request.app.get("jira_oauth_notifier")
    asyncio.create_task(_notify_telegram(notifier, ...))

## Notes

**[FC-025]** Brainstorm §3 'Svelte page hitting /api/o365/oauth/initiate|status passing user_id in body' → does NOT exist in this repo. What exists is an agent-scoped integrations API where user_id comes from the session (FC-048). The brainstorm's proposed `/api/v1/connections` differs from the existing `/api/v1/agents/integrations/{agent_id}` only by agent scoping.

**[FC-047]** Completion→channel is a direct in-process dispatch keyed by `state.channel`; core `parrot.auth.routes` lazily imports integrations modules (core→integrations dependency the brainstorm constraint 'core must not depend on integrations' would forbid). Telegram notification requires `app['jira_oauth_notifier']` to be in the same process as the callback.
