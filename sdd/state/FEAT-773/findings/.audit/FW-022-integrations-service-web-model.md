---
id: FW-022
query_id: Q012
type: wiki_page
intent: "Follow-up: IntegrationsService — the existing web 'connections' backend and its data model."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: FW-012
depth: 1
---

# FW-022 — `parrot/auth/oauth2/service.py::IntegrationsService` already implements list/start_connect/confirm_enable/disconnect/persist_credential for the web channel: per-`(user, provider)` `users_integrations` + per-`(user, agent, toolkit)` `user_agent_toolkits` in DocumentDB, PBAC fail-closed, status probe reads Identity Vault for jira and Session Vault otherwise

## Summary

`IntegrationsService(vault_token_sync=None)`: `list_for_user(user_id, agent_id, request)` → PBAC `integration:list` (fail-closed when `request.app['abac']` missing), iterates `OAuth2ProviderRegistry().all()`, builds `IntegrationDescriptor(provider, display_name, icon, default_scopes, status, enabled_on_agent, account_id, display_account_name, email, connected_at)` with `status` from `_token_status` (`"connected"|"needs_reconnect"`; jira → `_identity_token_status` via `IdentityStore.get_by_provider` + sync `decrypt_credential`; others → `VaultTokenSync.read_tokens_result`; fails open to connected). `start_connect(user_id, agent_id, provider_id, return_origin)` validates origin against `WEB_OAUTH_ALLOWED_ORIGINS`, calls `provider.manager.create_authorization_url(channel="web", user_id, extra_state={channel, provider_id, agent_id, return_origin})` → `ConnectInitResponse(auth_url, state, scopes, expires_in=600)`. `confirm_enable` requires a `users_integrations` row then upserts `UserAgentToolkitRow`. `disconnect` cascades enablement rows then deletes the integration row (local only). `persist_credential(user_id, provider_id, token_set)` writes the metadata row (duck-typed token_set). The brainstorm's `/api/v1/connections` + `list(principal) -> [ConnectionStatus]` is thus ~80% present as `/api/v1/agents/integrations/{agent_id}` — but scoped per agent and keyed by `user_id` string, with channel `"web"` hard-coded.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2/service.py`
  lines: n/a
  symbol: `IntegrationsService` (`list_for_user`, `_vault_sync`, `_identity_store`, `_identity_token_status`, `_token_status`, `start_connect`, `confirm_enable`, `disconnect`, `persist_credential`, `_check_pbac`), `_IDENTITY_OWNED_PROVIDERS`, `_get_allowed_origins`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/oauth2/service.py
  excerpt: |
    _IDENTITY_OWNED_PROVIDERS = frozenset({"jira"})
    extra_state = {"channel": _WEB_CHANNEL, "provider_id": provider_id, "agent_id": agent_id, "return_origin": return_origin}
    auth_url, nonce = await provider.manager.create_authorization_url(channel=_WEB_CHANNEL, user_id=user_id, extra_state=extra_state)
- path: `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py`
  lines: n/a
  symbol: `get_users_integration`, `upsert_users_integration`, `delete_users_integration`, `list_user_agent_toolkits`, `upsert_user_agent_toolkit`, `delete_user_agent_toolkits_by_provider`
- path: `packages/ai-parrot/src/parrot/auth/oauth2/models.py`
  lines: n/a
  symbol: `IntegrationDescriptor`, `ConnectInitResponse`, `UsersIntegrationRow`, `UserAgentToolkitRow`, `AuthRequiredEnvelope`
- path: `packages/ai-parrot-server/src/parrot/handlers/integrations.py`
  lines: n/a
  symbol: `IntegrationsHandler(BaseView)` — `/api/v1/agents/integrations/{agent_id}[/{provider}/connect|/enable]` (FEAT-144 M6; path per spec `parrot/handlers/integrations.py`)

## Notes

`[cross-lane: type=grep, intent=confirm IntegrationsHandler route registration in ai-parrot-server manager and the exact path family]`. The spec text places the handler in core `parrot/handlers/`; since the server split it likely lives in `ai-parrot-server/src/parrot/handlers/integrations.py` — verify.
