---
id: FC-052
query_id: Q027-F2
type: read
intent: "Follow-up: read parrot/auth/oauth2_base.py — AbstractOAuth2Manager generic PKCE/nonce/refresh/vault base."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-049
depth: 2
---

# FC-052 — AbstractOAuth2Manager is the generic 3LO engine: PKCE S256 pair, Redis nonce (10 min) carrying channel/user_id/extra, two-layer persistence (vault_utils encrypted vault = source of truth + Redis 90d hot cache), lock-protected rotating refresh, revoke, aiohttp setup; subclasses implement 4 hooks

## Summary

623 lines. Keys: `oauth2:{provider}:{channel}:{user_id}` (token), `oauth2:{provider}:nonce:{nonce}`, `lock:oauth2:{provider}:refresh:{channel}:{user_id}`, vault name `oauth2_{provider}_{channel}_{user_id}`; TTLs 90d / 10 min / lock 10s (blocking 5s). `AbstractOAuth2TokenSet` Pydantic base. `AbstractOAuth2Manager.__init__(..., vault_writer/reader/deleter=None → vault_utils defaults)`; `setup()` stores manager under `app[f"oauth2_manager_{provider_id}"]` and mounts callback; `use_pkce: ClassVar[bool]`; `_new_pkce_pair()`; `create_authorization_url(channel, user_id, extra_state)`; `handle_callback` → `_persist_token` (vault then Redis; vault failure logged); `get_valid_token` (cache → vault hydrate → locked `_refresh_tokens`); `is_connected`; `revoke` (vault + Redis); abstract `_exchange_code`, `_refresh_request`, `_discover_identity`, `_build_token_set`. Docstring: 'The Jira-specific manager intentionally stays untouched … this module is a parallel surface.'

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2_base.py`
  lines: 38-50
  symbol: `key templates`
  excerpt: |
    _TOKEN_KEY_TEMPLATE = "oauth2:{provider}:{channel}:{user_id}"
    _NONCE_KEY_TEMPLATE = "oauth2:{provider}:nonce:{nonce}"
    _LOCK_KEY_TEMPLATE = "lock:oauth2:{provider}:refresh:{channel}:{user_id}"
    _VAULT_NAME_TEMPLATE = "oauth2_{provider}_{channel}_{user_id}"
    _TOKEN_TTL_SECONDS = 90 * 24 * 60 * 60; _NONCE_TTL_SECONDS = 10 * 60; _REFRESH_LOCK_TIMEOUT = 10
- path: `packages/ai-parrot/src/parrot/auth/oauth2_base.py`
  lines: 89-178
  symbol: `AbstractOAuth2Manager.__init__`
  excerpt: |
    use_pkce: ClassVar[bool] = True
    def __init__(self, ..., vault_writer=None, vault_reader=None, vault_deleter=None):
        from parrot.security.vault_utils import delete_vault_credential, retrieve_vault_credential, store_vault_credential
- path: `packages/ai-parrot/src/parrot/auth/oauth2_base.py`
  lines: 289-345
  symbol: `_new_pkce_pair / create_authorization_url / authorization_url_extra_params`
  excerpt: |
    @staticmethod def _new_pkce_pair() -> Tuple[str, str]
    async def create_authorization_url(self, channel, user_id, extra_state=None):  # nonce 10 min TTL carries channel, user_id, extra, code_verifier
- path: `packages/ai-parrot/src/parrot/auth/oauth2_base.py`
  lines: 354-427
  symbol: `handle_callback / _persist_token`
  excerpt: |
    # 4. Persist: vault (source of truth) + Redis cache.
    async def _persist_token(...): await self._vault_writer(user_id, self._vault_name(channel, user_id), payload)  # failure swallowed+logged; then redis.set(ex=90d)
- path: `packages/ai-parrot/src/parrot/auth/oauth2_base.py`
  lines: 461-505
  symbol: `get_valid_token / revoke`
  excerpt: |
    async def get_valid_token(self, channel, user_id):  # cache -> vault hydrate -> refresh under lock
    async def revoke(self, channel, user_id):  # delete vault + Redis
- path: `packages/ai-parrot/src/parrot/auth/oauth2_base.py`
  lines: 507-575
  symbol: `_refresh_tokens`
  excerpt: |
    lock = self.redis.lock(self._lock_key(channel, user_id), timeout=_REFRESH_LOCK_TIMEOUT, blocking_timeout=_REFRESH_LOCK_BLOCKING_TIMEOUT)
- path: `packages/ai-parrot/src/parrot/auth/oauth2_base.py`
  lines: 577-623
  symbol: `abstract hooks`
  excerpt: |
    _exchange_code(code, code_verifier) · _refresh_request(refresh_token) · _discover_identity(access_token) · _build_token_set(...)

## Notes

THE key finding for S-1: the brainstorm's `ConnectionManager` (start/callback/refresh/revoke, signed state + PKCE, single-flight refresh) already exists generically as `AbstractOAuth2Manager`, but (a) keyed by `(provider, channel, user_id)` not principal, (b) persisted in `vault_utils` DocumentDB/Postgres `user_credentials` rather than the FEAT-735 Identity Vault, (c) Jira is NOT on it, (d) provider behaviour is a subclass, not a descriptor.
