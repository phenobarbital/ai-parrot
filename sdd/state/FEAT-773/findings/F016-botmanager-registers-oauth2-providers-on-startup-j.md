---
id: F016
query_id: [Q036, Q036-F1]
type: [grep, read]
intent: "R2/R4: where BotManager sets jira_oauth_manager / user_socket_manager and mounts OAuth routes."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 1
merged_from: [FC-017, FC-044]
---

# F016 — BotManager registers OAuth2 providers on startup (Jira only), mounts IntegrationsHandler at /api/v1/agents/integrations/{agent_id}[...], and defers user_socket_manager reads to on_startup

## Summary

**[FC-017]** Grep in `packages/ai-parrot-server/src/parrot/manager/`: `manager.py:2388` appends `self._register_oauth2_providers` to `on_startup`; `:2789-2807` reads `app.get("jira_oauth_manager")` and calls `register_oauth2_provider(JiraOAuth2Provider(manager=jira_manager))` (warns if unset — the boot warning the brainstorm saw). `:2459-2472` mount four `IntegrationsHandler` routes. `:2310`, `:2449`, `:2925` defer `app['user_socket_manager']` access to `on_startup`. No O365 provider registration in BotManager (only Jira).

**[FC-044]** `manager.py:41` imports `IntegrationsHandler`; `:2388` `on_startup.append(self._register_oauth2_providers)`; `:2459-2472` routes; `:2789-2807` `_register_oauth2_providers`: `from parrot.auth.oauth2.registry import register_oauth2_provider`, `jira_manager = app.get("jira_oauth_manager")`, warn if None, else `register_oauth2_provider(JiraOAuth2Provider(manager=jira_manager))`. `:2818` comment: registered AFTER provider registration.

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
- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 41
  symbol: `import`
  excerpt: |
    from ..handlers.integrations import IntegrationsHandler

## Notes

**[FC-017]** Who constructs `JiraOAuthManager`/`O365OAuthManager` and stores them on the app was not found in BotManager — it is application bootstrap (docs FC-033 show `manager.setup()` by the host app). [cross-lane: type=git_log, intent=when _register_oauth2_providers and IntegrationsHandler routes landed]

**[FC-044]** O365 provider registration is left to the host application (per docs FC-033), not BotManager — a unification gap.
