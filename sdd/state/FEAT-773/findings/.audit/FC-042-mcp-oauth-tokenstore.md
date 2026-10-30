---
id: FC-042
query_id: Q039-F1
type: read
intent: "Follow-up: read parrot/mcp/oauth.py — what remains after OAuthManager removal."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-020
depth: 1
---

# FC-042 — parrot/mcp/oauth.py keeps TokenStore ABC with InMemoryTokenStore, RedisTokenStore (mcp:oauth:{server}:{user_id}) and VaultTokenStore (vault_utils), plus NetSuiteM2MAuth (JWT bearer, zero-arg token_supplier)

## Summary

280 lines. `TokenStore.get/set/delete(user_id, server_name)`; `RedisTokenStore._key` → `mcp:oauth:{server_name}:{user_id}` (no TTL); `VaultTokenStore` (:63-166) uses `store/retrieve/delete_vault_credential` with `_vault_name(user_id, server_name)`; `NetSuiteM2MAuth` (:168-280) builds an RS256 assertion, `ensure_token(user_id="m2m")`, exposes `token_supplier` property (`str | None`). No PKCE/authorization-code code in this file (moved to oauth2_state/transport).

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 22-26
  symbol: `TokenStore`
  excerpt: |
    class TokenStore:
        async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]
        async def set(self, user_id: str, server_name: str, token: Dict[str, Any]) -> None
        async def delete(self, user_id: str, server_name: str) -> None
- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 42-61
  symbol: `RedisTokenStore`
  excerpt: |
    def _key(user_id, server_name): return f"mcp:oauth:{server_name}:{user_id}"
- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 63-166
  symbol: `VaultTokenStore`
  excerpt: |
    class VaultTokenStore(TokenStore):  # backed by parrot.security.vault_utils
- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 168-280
  symbol: `NetSuiteM2MAuth`
  excerpt: |
    class NetSuiteM2MAuth: ensure_token(user_id=m2m); @property token_supplier -> str | None

## Notes

MCP tokens are keyed `(user_id, server_name)` — a fourth token store shape. `WebOAuthManager`/`StateStore`/`NeedsAuthorizationError` absent (FC-020).
