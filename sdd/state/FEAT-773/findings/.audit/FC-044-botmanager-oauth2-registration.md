---
id: FC-044
query_id: Q036-F1
type: read
intent: "Follow-up: BotManager OAuth2 provider registration and IntegrationsHandler mounting."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-017
depth: 1
---

# FC-044 — BotManager imports IntegrationsHandler, mounts 4 agent-scoped routes, and registers only JiraOAuth2Provider on startup from app['jira_oauth_manager']

## Summary

`manager.py:41` imports `IntegrationsHandler`; `:2388` `on_startup.append(self._register_oauth2_providers)`; `:2459-2472` routes; `:2789-2807` `_register_oauth2_providers`: `from parrot.auth.oauth2.registry import register_oauth2_provider`, `jira_manager = app.get("jira_oauth_manager")`, warn if None, else `register_oauth2_provider(JiraOAuth2Provider(manager=jira_manager))`. `:2818` comment: registered AFTER provider registration.

## Citations

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 41
  symbol: `import`
  excerpt: |
    from ..handlers.integrations import IntegrationsHandler
- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 2789-2807
  symbol: `BotManager._register_oauth2_providers`
  excerpt: |
    async def _register_oauth2_providers(self, app):
        from parrot.auth.oauth2.registry import register_oauth2_provider
        jira_manager = app.get("jira_oauth_manager")
        if jira_manager is None: self.logger.warning("app[jira_oauth_manager] is not set — Ensure JiraOAuthManager.setup(app) is called before startup.")
        else: register_oauth2_provider(JiraOAuth2Provider(manager=jira_manager))

## Notes

O365 provider registration is left to the host application (per docs FC-033), not BotManager — a unification gap.
