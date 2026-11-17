---
id: FC-043
query_id: Q038-F1
type: read
intent: "Follow-up: read add_oauth_mcp_server and add_netsuite_mcp_server bodies."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-019
depth: 1
---

# FC-043 — add_oauth_mcp_server(name, url, user_id, oauth2: MCPOAuth2Config | legacy params) and add_netsuite_mcp_server(account_id, client_id, user_id, **kwargs) bind user_id at add-time via create_*_mcp_server factories

## Summary

`parrot/mcp/integration.py:1394-1442`: `add_oauth_mcp_server(self, name, url, user_id, oauth2=None, client_id=None, auth_url=None, token_url=None, scopes=None, client_secret=None, **kwargs)` → `create_oauth_mcp_server(..., user_id=user_id, ...)` → `add_mcp_server(config)`; docstring 'user_id: User identifier for token storage scoping'. `:1706-1740` `add_netsuite_mcp_server(account_id, client_id, user_id, **kwargs)` → `create_netsuite_mcp_server(...)`, scope fixed `["mcp"]`, kwargs `token_store`, `redirect_host`, `redirect_port`.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/integration.py`
  lines: 1394-1407
  symbol: `add_oauth_mcp_server`
  excerpt: |
    async def add_oauth_mcp_server(self, name: str, url: str, user_id: str, oauth2: Optional[MCPOAuth2Config] = None, client_id=None, auth_url=None, token_url=None, scopes=None, client_secret=None, **kwargs) -> List[str]
- path: `packages/ai-parrot/src/parrot/mcp/integration.py`
  lines: 1429-1441
  symbol: `add_oauth_mcp_server body`
  excerpt: |
    config = create_oauth_mcp_server(name=name, url=url, user_id=user_id, oauth2=oauth2, ...)
    return await self.add_mcp_server(config)
- path: `packages/ai-parrot/src/parrot/mcp/integration.py`
  lines: 1706-1740
  symbol: `add_netsuite_mcp_server`
  excerpt: |
    async def add_netsuite_mcp_server(self, account_id: str, client_id: str, user_id: str, **kwargs) -> List[str]:
        # kwargs: token_store, redirect_host, redirect_port

## Notes

Brainstorm §3 row `add_oauth_mcp_server(name, url, client_id, client_secret, auth_url, token_url, scopes, user_id)` → signature confirmed (plus `oauth2=` config). Add-time `user_id` binding persists.
