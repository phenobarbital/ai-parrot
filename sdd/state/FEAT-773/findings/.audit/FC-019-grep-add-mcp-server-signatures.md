---
id: FC-019
query_id: Q038
type: grep
intent: "R3: current add_*_mcp_server signatures on the MCP mixin (where credentials are bound)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-019 — add_*_mcp_server live in parrot/mcp/integration.py (MCP mixin) with Agent-level wrappers in bots/agent.py; add_oauth_mcp_server and add_netsuite_mcp_server take user_id at add-time

## Summary

22 definitions. `parrot/mcp/integration.py`: `add_mcp_server(config)` :1363, `add_local_mcp_server` :1367, `add_http_mcp_server` :1374, `add_api_key_mcp_server` :1387, `add_oauth_mcp_server` :1394, `add_perplexity_mcp_server` :1443, `add_fireflies_mcp_server` :1448, `add_chrome_devtools_mcp_server` :1473, `add_obscura_mcp_server` :1528, `add_google_maps_mcp_server` :1569, `add_quic_mcp_server` :1582, `add_websocket_mcp_server` :1589, `add_alphavantage_mcp_server` :1690, `add_netsuite_mcp_server` :1706, `add_genmedia_mcp_servers` :1786. `bots/agent.py` :1038-1200 re-exposes five; `tools/mcp_mixin.py:57 add_mcp_server`.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/integration.py`
  lines: 1394
  symbol: `add_oauth_mcp_server`
  excerpt: |
    async def add_oauth_mcp_server(self, name, url, user_id, oauth2: Optional[MCPOAuth2Config] = None, client_id=None, auth_url=None, token_url=None, scopes=None, client_secret=None, **kwargs)
- path: `packages/ai-parrot/src/parrot/mcp/integration.py`
  lines: 1706
  symbol: `add_netsuite_mcp_server`
  excerpt: |
    async def add_netsuite_mcp_server(self, account_id: str, client_id: str, user_id: str, **kwargs)
- path: `packages/ai-parrot/src/parrot/bots/agent.py`
  lines: 1038-1200
  symbol: `Agent.add_*_mcp_server`
  excerpt: |
    add_mcp_server, add_mcp_server_url, add_local_mcp_server, add_http_mcp_server, add_api_key_mcp_server

## Notes

See FC-043 for full signatures/excerpts.
