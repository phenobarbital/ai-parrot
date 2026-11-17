---
id: F019
query_id: Q032
type: read
intent: "MCP client OAuth module"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-019]
---

# F019 — parrot.mcp.oauth: TokenStore trio + NetSuite M2M; OAuthManager removed (FEAT-262) → MCP SDK OAuthClientProvider

## Summary

`oauth.py` holds the `TokenStore` interface with in-memory/Redis/Vault stores keyed `(user_id, server_name)` (Redis key `mcp:oauth:{server}:{user}`, vault name `mcp_oauth_{server}_{user}`) and `NetSuiteM2MAuth` (client-credentials JWT assertion, `ensure_token(user_id="m2m")`). The trailing comment records that the in-house `OAuthManager` was removed in FEAT-262; authorization-code flows use the MCP SDK's `OAuthClientProvider` with `VaultMCPTokenStorage`.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 275-280
  symbol: `module tail comment`
  excerpt: |
    # OAuthManager was removed in FEAT-262 (TASK-1665).
    # Use parrot.mcp.oauth2_config.MCPOAuth2Config and the MCP SDK's
    # OAuthClientProvider (mcp.client.auth.oauth2) for authorization code flows,
    # Token storage is handled by parrot.mcp.oauth2_storage.VaultMCPTokenStorage.
- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 168-201, 232-237
  symbol: `NetSuiteM2MAuth.ensure_token`
  excerpt: |
    class NetSuiteM2MAuth:
        def __init__(self, *, client_id, certificate_id, private_key_path, account_id, token_url=None, scopes=None, token_store=None)
        async def ensure_token(self, user_id: str = "m2m") -> str:

## Notes

These stores are parrot-as-MCP-CLIENT token caches (parrot calling remote MCP servers), a different direction from S-4's delegated connections.
