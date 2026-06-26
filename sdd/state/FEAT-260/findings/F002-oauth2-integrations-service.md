# F002 — Full OAuth2 IntegrationsService + provider registry (EXISTS)

**Query**: Q007/Q011 (read `auth/oauth2/service.py`, ls `auth/oauth2/`)
**Verdict**: VERIFIED EXISTS — large overlap with brainstorm §8 "must be built".

- `auth/oauth2/` package: `service.py`, `registry.py`, `persistence.py`, `models.py`, `jira_provider.py`, `o365_provider.py`.
- `IntegrationsService` (service.py:67):
  - `start_connect(user_id, agent_id, provider_id, return_origin)` → `ConnectInitResponse(auth_url, state nonce, scopes, expires_in=600)` (l.140). Validates `return_origin` against `WEB_OAUTH_ALLOWED_ORIGINS`.
  - `persist_credential(user_id, provider_id, token_set)` (l.289) — called from OAuth callback; upserts `users_integrations`.
  - `confirm_enable` / `disconnect` / `list_for_user` (PBAC-filtered, fail-closed).
- `OAuth2ProviderRegistry` holds providers; **jira AND o365 already registered**.
- Persistence: `users_integrations` (per-user credential) + `user_agent_toolkits` (per-agent enablement) tables.
- Providers' `create_authorization_url(channel, user_id, extra_state)` already issue the **state nonce** the brainstorm calls for.

**Implication**: The brainstorm's "account-linking map + authenticated web surface + nonce issuance" largely EXISTS for the **web channel**. Genuinely-new work = bind this to the **A2A channel** + add work-iq/fireflies providers.
