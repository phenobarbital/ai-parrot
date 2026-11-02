---
id: FC-004
query_id: Q017
type: grep
intent: "Loopback redirect / token-store precedent in parrot.mcp"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-004 — No loopback OAuth in parrot.mcp; token stores exist (memory/redis/vault)

## Summary

parrot.mcp has no loopback redirect, no `webbrowser`, no 127.0.0.1 callback listener for a CLI OAuth flow. What exists: `TokenStore` + `InMemoryTokenStore`/`RedisTokenStore`/`VaultTokenStore` (oauth.py) keyed `(user_id, server_name)`, `VaultMCPTokenStorage` adapting the MCP SDK `TokenStorage` protocol (oauth2_storage.py), and `MCPOAuth2Config.redirect_base_url` whose default is `NAVIGATOR_BASE_URL` → `http://127.0.0.1:8000` with path `/api/auth/oauth2/mcp/callback` — i.e. the aiohttp server's callback, not a CLI loopback.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 22-26, 42-49, 63-70
  symbol: `TokenStore / RedisTokenStore._key / VaultTokenStore`
  excerpt: |
    class TokenStore:
        async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]: ...
    class RedisTokenStore(TokenStore):
        def _key(user_id: str, server_name: str) -> str:
            return f"mcp:oauth:{server_name}:{user_id}"
    class VaultTokenStore(TokenStore):  # mcp_oauth_{server_name}_{user_id}

- path: `packages/ai-parrot/src/parrot/mcp/oauth2_config.py`
  lines: 79-91
  symbol: `MCPOAuth2Config.redirect_path / redirect_base_url`
  excerpt: |
    redirect_path: str = Field(default="/api/auth/oauth2/mcp/callback", ...)
    redirect_base_url: str = Field(default="", description=(
        "... When empty, the NAVIGATOR_BASE_URL environment variable is used, falling back to 'http://127.0.0.1:8000'. "))

- path: `packages/ai-parrot/src/parrot/mcp/oauth2_storage.py`
  lines: 29-62
  symbol: `VaultMCPTokenStorage`
  excerpt: |
    class VaultMCPTokenStorage(TokenStorage):
        def __init__(self, user_id: str, server_name: str, vault_store: Optional[VaultTokenStore] = None)


## Notes

Other 127.0.0.1 hits (registry.py:207, integration.py:1070-1162) are Chrome DevTools URLs, unrelated.
