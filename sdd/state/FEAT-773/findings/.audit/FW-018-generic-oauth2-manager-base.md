---
id: FW-018
query_id: Q002
type: wiki_page
intent: "Follow-up: read the generic AbstractOAuth2Manager — is the brainstorm's ConnectionManager already here?"
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: FW-002
depth: 1
---

# FW-018 — `parrot/auth/oauth2_base.py::AbstractOAuth2Manager` IS a provider-agnostic 3LO manager: PKCE S256, signed-nonce state in Redis (10-min TTL), vault+Redis two-layer persistence, distributed-lock refresh with rotating-token safety, provider hooks; keys are still `{provider}:{channel}:{user_id}` and Jira deliberately stays on its own manager

## Summary

Most of the brainstorm's `ConnectionManager` (`start`/`complete`/`get_credentials`/`revoke`, signed state + PKCE, single-flight refresh, descriptor-driven provider behaviour) exists as `AbstractOAuth2Manager`: class attrs `provider_id`, `authorization_url`, `token_url`, `default_scopes`, `token_set_cls`, `use_pkce` (default True, S256 via `_new_pkce_pair`), `require_client_secret`; `create_authorization_url(channel, user_id, extra_state) -> (url, nonce)` stores `{channel, user_id, extra, code_verifier}` at Redis `oauth2:{provider}:nonce:{nonce}` ex 600s; `authorization_url_extra_params()` hook (e.g. `prompt=consent`); `handle_callback(code, state)` one-shot nonce → `_exchange_code` → `_discover_identity` → `_build_token_set` → `_persist_token` (vault `oauth2_{provider}_{channel}_{user_id}` via `vault_utils` writer + Redis `oauth2:{provider}:{channel}:{user_id}` ex 90d); `get_valid_token` cache→vault→refresh; `is_connected`; `revoke` (local delete only); `_refresh_tokens` under Redis lock `lock:oauth2:{provider}:refresh:{channel}:{user_id}` (timeout 10s, blocking 5s), re-reads after lock, persists rotated refresh token; abstract hooks `_exchange_code`, `_refresh_request`, `_discover_identity`, `_build_token_set`; `setup()` wires app slot + routes. Docstring: "The Jira-specific manager intentionally stays untouched — this module is a parallel surface." What is NOT here: principal/tenant keying (keys include `channel`), provider revoke endpoint, `AuthRequirement` declarations, event publication, descriptor-as-data (subclass per provider), identity-probe JSON paths as config.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2_base.py`
  lines: n/a
  symbol: `AbstractOAuth2TokenSet` (`access_token`, `refresh_token`, `expires_at`, `scopes`, `granted_at`, `last_refreshed_at`, `account_id`, `display_name`, `email`, `is_expired`), `AbstractOAuth2Manager` (`create_authorization_url`, `handle_callback`, `_persist_token`, `get_valid_token`, `is_connected`, `revoke`, `_refresh_tokens`, `_new_pkce_pair`, `setup`), `_TOKEN_KEY_TEMPLATE`, `_NONCE_KEY_TEMPLATE`, `_LOCK_KEY_TEMPLATE`, `_VAULT_NAME_TEMPLATE`, `_TOKEN_TTL_SECONDS`, `_NONCE_TTL_SECONDS`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/oauth2_base.py
  excerpt: |
    _TOKEN_KEY_TEMPLATE = "oauth2:{provider}:{channel}:{user_id}"
    _NONCE_KEY_TEMPLATE = "oauth2:{provider}:nonce:{nonce}"
    _LOCK_KEY_TEMPLATE = "lock:oauth2:{provider}:refresh:{channel}:{user_id}"
    _VAULT_NAME_TEMPLATE = "oauth2_{provider}_{channel}_{user_id}"
    use_pkce: ClassVar[bool] = True
    require_client_secret: ClassVar[bool] = True
- path: `packages/ai-parrot/src/parrot/auth/o365_oauth.py`
  lines: n/a
  symbol: `O365OAuthManager(AbstractOAuth2Manager)` — the one concrete subclass
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/o365_oauth.py

## Notes

Spike S2 answer: the reusable PKCE/exchange/refresh code is `AbstractOAuth2Manager`, not the removed MCP `OAuthManager`. `JiraOAuthManager` (`auth/jira_oauth.py`) duplicates the same shape with Jira keys (`jira:oauth:*`, `jira:nonce:*`, `lock:jira:refresh:*`) and `accessible-resources` → `cloud_id`; TASK-4418 "Extract 3LO OAuth Helpers" exists (ledger `issue:b5e64d019469` notes helpers `exchange_code`, `refresh_access_token`, `fetch_accessible_resources`, `fetch_myself` in `jira_oauth.py`). `[cross-lane: type=read, intent=jira_oauth.py — confirm it does NOT subclass AbstractOAuth2Manager and list the TASK-4418 module-level helpers]`.
