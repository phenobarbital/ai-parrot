---
id: F038
query_id: Q026-F3
type: read
intent: "Follow-up: read parrot/auth/oauth2/service.py — IntegrationsService start_connect / persist / status."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-007
depth: 1
merged_from: [FC-039]
---

# F038 — IntegrationsService is the existing ConnectionManager for the web channel: list_for_user, start_connect (origin allowlist, state carries channel=web/provider/agent/return_origin), confirm_enable, disconnect, persist_credential; status reads Identity Vault for jira and VaultTokenSync otherwise; PBAC-checked

## Summary

532 lines. `IntegrationsService(vault_token_sync=None)`. `list_for_user(user_id, agent_id, request)` builds `IntegrationDescriptor`s from `OAuth2ProviderRegistry().all()` + persistence + `_token_status` (Identity Vault for jira via `_identity_store`, `VaultTokenSync` otherwise). `start_connect(user_id, agent_id, provider_id, return_origin)` validates `return_origin ∈ WEB_OAUTH_ALLOWED_ORIGINS`, embeds `extra_state={channel:"web", provider_id, agent_id, return_origin}`, calls `provider.manager.create_authorization_url(channel="web", user_id, extra_state)` → `ConnectInitResponse`. `confirm_enable` (:346) upserts `user_agent_toolkits`; `disconnect` (:406) revokes + cascades; `persist_credential(user_id, provider_id, token_set)` (:440) upserts `UsersIntegrationRow(channel="web")`; `_check_pbac` (:490).

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2/service.py`
  lines: 74-90
  symbol: `IntegrationsService`
  excerpt: |
    class IntegrationsService:
        # Orchestrates OAuth2 provider registry, persistence, and PBAC checks.
        def __init__(self, vault_token_sync: Any = None)
- path: `packages/ai-parrot/src/parrot/auth/oauth2/service.py`
  lines: 155-250
  symbol: `_vault_sync / _identity_store / _identity_token_status / _token_status`
  excerpt: |
    self._vault_token_sync = VaultTokenSync(db_pool=db_pool, redis=app.get("redis"))
    async def _identity_token_status(self, user_id, provider_id, request) -> str
    async def _token_status(self, user_id, provider_id, request) -> str
- path: `packages/ai-parrot/src/parrot/auth/oauth2/service.py`
  lines: 291-345
  symbol: `IntegrationsService.start_connect`
  excerpt: |
    extra_state = {"channel": _WEB_CHANNEL, "provider_id": provider_id, "agent_id": agent_id, "return_origin": return_origin}
    auth_url, nonce = await provider.manager.create_authorization_url(channel=_WEB_CHANNEL, user_id=user_id, extra_state=extra_state)
    return ConnectInitResponse(auth_url=auth_url, state=nonce, scopes=provider.default_scopes, expires_in=600)
- path: `packages/ai-parrot/src/parrot/auth/oauth2/service.py`
  lines: 440-482
  symbol: `IntegrationsService.persist_credential`
  excerpt: |
    row = UsersIntegrationRow(user_id=user_id, provider=provider_id, channel=_WEB_CHANNEL, status="active", account_id=..., scopes=..., cloud_id=getattr(token_set, "cloud_id", None), site_url=...)
    await upsert_users_integration(row)

## Notes

Gap vs brainstorm: service is web-only (channel=web hard-coded) and agent-scoped; Telegram/Teams/Slack start their flows directly on the manager. Status logic diverges per provider (Identity Vault for jira, VaultTokenSync for others).
