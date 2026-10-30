---
id: FC-017
query_id: Q036
type: grep
intent: "R2/R4: where BotManager sets jira_oauth_manager / user_socket_manager and mounts OAuth routes."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-017 — BotManager registers OAuth2 providers on startup (Jira only), mounts IntegrationsHandler at /api/v1/agents/integrations/{agent_id}[...], and defers user_socket_manager reads to on_startup

## Summary

Grep in `packages/ai-parrot-server/src/parrot/manager/`: `manager.py:2388` appends `self._register_oauth2_providers` to `on_startup`; `:2789-2807` reads `app.get("jira_oauth_manager")` and calls `register_oauth2_provider(JiraOAuth2Provider(manager=jira_manager))` (warns if unset — the boot warning the brainstorm saw). `:2459-2472` mount four `IntegrationsHandler` routes. `:2310`, `:2449`, `:2925` defer `app['user_socket_manager']` access to `on_startup`. No O365 provider registration in BotManager (only Jira).

## Citations

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 2388
  symbol: `BotManager.setup`
  excerpt: |
    self.app.on_startup.append(self._register_oauth2_providers)
- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 2459-2472
  symbol: `BotManager route registration`
  excerpt: |
    "/api/v1/agents/integrations/{agent_id}", IntegrationsHandler
    "/api/v1/agents/integrations/{agent_id}/{provider}/connect", IntegrationsHandler
    "/api/v1/agents/integrations/{agent_id}/{provider}/enable", IntegrationsHandler
    "/api/v1/agents/integrations/{agent_id}/{provider}", IntegrationsHandler
- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 2789-2807
  symbol: `BotManager._register_oauth2_providers`
  excerpt: |
    jira_manager = app.get("jira_oauth_manager")
    if jira_manager is None: warning "app[jira_oauth_manager] is not set — Ensure JiraOAuthManager.setup(app) is called before startup."
    register_oauth2_provider(JiraOAuth2Provider(manager=jira_manager))

## Notes

Who constructs `JiraOAuthManager`/`O365OAuthManager` and stores them on the app was not found in BotManager — it is application bootstrap (docs FC-033 show `manager.setup()` by the host app). [cross-lane: type=git_log, intent=when _register_oauth2_providers and IntegrationsHandler routes landed]
