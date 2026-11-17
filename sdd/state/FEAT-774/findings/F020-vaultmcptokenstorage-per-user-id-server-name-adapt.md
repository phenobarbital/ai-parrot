---
id: F020
query_id: Q033
type: read
intent: "MCP OAuth2 token storage adapter"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-020]
---

# F020 — VaultMCPTokenStorage: per (user_id, server_name) adapter over VaultTokenStore; degrades to None

## Summary

`VaultMCPTokenStorage(user_id, server_name, vault_store=None)` implements the MCP SDK `TokenStorage` protocol (`get_tokens`/`set_tokens`/`get_client_info`/`set_client_info`) over `VaultTokenStore` (DocumentDB vault via `vault_utils`), with a separate vault key for client registration (`__client_info_{server}`). Every failure is logged and swallowed — fail-open-to-memory, the opposite of S-1's durable-first rule.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/oauth2_storage.py`
  lines: 53-70, 76-98
  symbol: `VaultMCPTokenStorage.__init__ / get_tokens`
  excerpt: |
    def __init__(self, user_id: str, server_name: str, vault_store: Optional[VaultTokenStore] = None)
    def _client_info_server_name(self) -> str: return f"__client_info_{self._server_name}"
    async def get_tokens(self) -> OAuthToken | None:  # returns None on vault failure

## Notes

Requires the DocumentDB vault (server infrastructure) → not usable from a bare CLI/stdio process.
