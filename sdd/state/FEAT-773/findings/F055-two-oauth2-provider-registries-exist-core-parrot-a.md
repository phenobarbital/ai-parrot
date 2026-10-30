---
id: F055
query_id: Q002
type: wiki_query
intent: "Orient: OAuth2 provider registry + generic callback routes (which package, how providers register)."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FW-002]
---

# F055 — Two OAuth2 provider registries exist (core `parrot.auth.oauth2.OAuth2ProviderRegistry` + integrations `OAUTH2_PROVIDERS` dict) and two callback route modules (`auth/routes.py` Jira-specific, `auth/oauth2_routes.py` generic)

## Summary

Core `parrot/auth/oauth2/` (FEAT-144, TASK-983) holds `OAuth2Provider` ABC (`provider_id`, `display_name`, `icon`, `default_scopes`, `pbac_action_namespace`, abstract `manager` property and `toolkit_factory(credential_resolver)`), the in-memory singleton `OAuth2ProviderRegistry` (`register/get/all`, `_reset` for tests) and `register_oauth2_provider()`; concrete providers: `JiraOAuth2Provider` (`jira_provider.py`), `O365OAuth2Provider` (`o365_provider.py`), `WorkIQOAuth2Provider` (`workiq_provider.py`), `O365DeviceCodeCredentialResolver` (`o365_devicecode_provider.py`), plus `MCPOAuth2Provider` (TASK-1661). Separately, `parrot/integrations/core/auth/oauth2_providers.py` (FEAT-225 lift of the Telegram FEAT-036 dict) is a *login-IdP* catalog (`OAuth2ProviderConfig`: authorization_url/token_url/userinfo_url/default_scopes — Google) used for channel sign-in, not for tool credentials. Callback routes: `auth/routes.py` mounts `GET /api/auth/jira/callback` (excluded from navigator-auth middleware via `exclude_list`) branching on `state_payload["channel"]` ∈ {web, slack, msteams, telegram}; `auth/oauth2_routes.py` provides `make_oauth2_callback(provider_id)` / `setup_oauth2_routes(app, provider_id, callback_path)` (default path `/api/auth/oauth2/{provider}/callback`), `_handle_web_callback`, `handle_mcp_oauth2_callback`/`setup_mcp_oauth2_callback`, and `register_a2a_resume_hook` (TASK-1645). So "a single callback endpoint per provider" already exists in shape; Jira is the exception on its own legacy path.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2/registry.py`
  lines: n/a
  symbol: `OAuth2Provider`, `OAuth2ProviderRegistry`, `register_oauth2_provider`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/oauth2/registry.py (score=0.43)
- path: `packages/ai-parrot/src/parrot/auth/oauth2/__init__.py`
  lines: n/a
  symbol: `_WEB_CHANNEL = "web"`, re-exports `JiraOAuth2Provider`, `IntegrationsService`, models
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/oauth2/__init__.py (score=0.69)
- path: `packages/ai-parrot/src/parrot/auth/oauth2/o365_provider.py`
  lines: n/a
  symbol: `O365OAuth2Provider`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/oauth2/o365_provider.py (score=0.39)
- path: `packages/ai-parrot/src/parrot/auth/oauth2_routes.py`
  lines: n/a
  symbol: `make_oauth2_callback`, `setup_oauth2_routes`, `_handle_web_callback`, `handle_mcp_oauth2_callback`, `setup_mcp_oauth2_callback`, `register_a2a_resume_hook`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/oauth2_routes.py (score=0.19)
- path: `packages/ai-parrot/src/parrot/auth/routes.py`
  lines: n/a
  symbol: `jira_oauth_callback`, `setup_jira_oauth_routes`, `_handle_web_callback`, `_handle_oauth_error`, `_notify_telegram`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/routes.py
- path: `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/oauth2_providers.py`
  lines: n/a
  symbol: `OAUTH2_PROVIDERS`, `OAuth2ProviderConfig`, `get_provider`
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/core/auth/oauth2_providers.py (score=0.42)
- path: `sdd/tasks/completed/TASK-983-oauth2-models-and-registry.md`
  lines: n/a
  symbol: TASK-983 OAuth2 Integration Models and Provider Registry (FEAT-144)
  wiki_page_id: file:sdd/tasks/completed/TASK-983-oauth2-models-and-registry.md (score=1.00)
- path: `sdd/tasks/completed/TASK-1661-mcp-oauth2-provider.md`
  lines: n/a
  symbol: `MCPOAuth2Provider` registered in the same registry
  wiki_page_id: file:sdd/tasks/completed/TASK-1661-mcp-oauth2-provider.md (score=0.83)

## Notes

Name collision hazard for the proposal: the brainstorm proposes `OAuthProviderRegistry`; the codebase already has `OAuth2ProviderRegistry` (core, tool-credential providers) AND `OAUTH2_PROVIDERS` (integrations, login IdPs). The provider "descriptor" today is a class (`OAuth2Provider` subclass wrapping a manager), not data. `[cross-lane: type=read, intent=read oauth2_routes.py to confirm auth-middleware exclusion and that the generic callback handles PKCE/web/telegram channels]`.
