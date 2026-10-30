---
id: FC-002
query_id: Q021
type: read
intent: "R2: read JiraOAuthManager — Redis key format, refresh/lock, accessible-resources, callback handling."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-002 — JiraOAuthManager lives in core parrot/auth/jira_oauth.py; Redis hot cache jira:oauth:{channel}:{user_id}, 90d TTL, lock-protected rotating refresh, CredentialSink Protocol for the durable owner

## Summary

`parrot/auth/jira_oauth.py` (824 lines). Constants: `_TOKEN_KEY_PREFIX="jira:oauth"` → `jira:oauth:{channel}:{user_id}`, nonce `jira:nonce:{nonce}` (10 min TTL), lock `lock:jira:refresh:{channel}:{user_id}`, token TTL 90 days. Module-level stateless helpers `build_authorization_url`, `exchange_code`, `refresh_access_token`, `fetch_accessible_resources`, `fetch_myself` (TASK-4418). A `CredentialSink` Protocol (`persist`, `persist_minted(channel,user_id,token,state_payload)`) lets the app inject the durable owner (navigator-auth Identity Vault) without core importing server code. `handle_callback(code,state)` consumes the nonce, exchanges, fetches accessible-resources → cloud_id, writes Redis, then calls the sink (failures logged, never fail the link). `_refresh_tokens` uses `redis.lock` with blocking timeout; `validate_token` probes the token; `revoke` deletes the Redis key. No PKCE (confidential client).

## Citations

- path: `packages/ai-parrot/src/parrot/auth/jira_oauth.py`
  lines: 44-50
  symbol: `_TOKEN_KEY_PREFIX`
  excerpt: |
    _TOKEN_KEY_PREFIX = "jira:oauth"  # jira:oauth:{channel}:{user_id}
    _NONCE_KEY_PREFIX = "jira:nonce"
    _LOCK_KEY_PREFIX = "lock:jira:refresh"
    _TOKEN_TTL_SECONDS = 90 * 24 * 60 * 60
    _NONCE_TTL_SECONDS = 10 * 60
- path: `packages/ai-parrot/src/parrot/auth/jira_oauth.py`
  lines: 231-259
  symbol: `CredentialSink`
  excerpt: |
    class CredentialSink(Protocol):
        async def persist(self, channel: str, user_id: str, token: JiraTokenSet) -> None
        async def persist_minted(self, channel, user_id, token, state_payload: Dict[str, Any]) -> None
- path: `packages/ai-parrot/src/parrot/auth/jira_oauth.py`
  lines: 262-286
  symbol: `JiraOAuthManager.__init__`
  excerpt: |
    def __init__(self, client_id, client_secret, redirect_uri, *, app=None, redis_url=None, redis_client=None, scopes=None, http_session=None, credential_sink: Optional[CredentialSink] = None)
- path: `packages/ai-parrot/src/parrot/auth/jira_oauth.py`
  lines: 396-405
  symbol: `_token_key`
  excerpt: |
    def _token_key(channel, user_id): return f"{_TOKEN_KEY_PREFIX}:{channel}:{user_id}"
- path: `packages/ai-parrot/src/parrot/auth/jira_oauth.py`
  lines: 481-562
  symbol: `handle_callback`
  excerpt: |
    async def handle_callback(self, code: str, state: str) -> Tuple[JiraTokenSet, Dict[str, Any]]:
        state_payload = await self.consume_state(state)
        ...
        await self._write_token(self._token_key(channel, user_id), token)
        if self._credential_sink is not None:
            await self._credential_sink.persist_minted(channel, user_id, token, state_payload)
- path: `packages/ai-parrot/src/parrot/auth/jira_oauth.py`
  lines: 602-611
  symbol: `get_valid_token`
  excerpt: |
    async def get_valid_token(self, channel: str, user_id: str) -> Optional[JiraTokenSet]
- path: `packages/ai-parrot/src/parrot/auth/jira_oauth.py`
  lines: 691-694
  symbol: `revoke`
  excerpt: |
    async def revoke(self, channel, user_id): await self.redis.delete(self._token_key(channel, user_id))
- path: `packages/ai-parrot/src/parrot/auth/jira_oauth.py`
  lines: 697-800
  symbol: `_refresh_tokens`
  excerpt: |
    lock = self.redis.lock(lock_name, blocking_timeout=_REFRESH_LOCK_BLOCKING_TIMEOUT)
    acquired = await lock.acquire()  # losers re-read the key

## Notes

Brainstorm §3 row 1 → EXISTS, in **core** (`ai-parrot`), not integrations/tools. Key format confirmed. Jira has its own manager; a parallel generic `AbstractOAuth2Manager` exists (see FC-052) and the module docstring says the Jira manager 'intentionally stays untouched'.
