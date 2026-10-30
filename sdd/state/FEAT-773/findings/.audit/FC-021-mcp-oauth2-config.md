---
id: FC-021
query_id: Q040
type: read
intent: "R3: read MCPOAuth2Config models/presets (PKCE, public client, refresh)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-021 — MCPOAuth2Config is a Pydantic model (client_id, optional client_secret for public clients, auth_url, token_url, scopes, grant_type, redirect_path/base_url, extra_token_params) with a presets registry (netsuite, fireflies placeholder)

## Summary

`parrot/mcp/oauth2_config.py` (204 lines). `MCPOAuth2GrantType` enum (AUTHORIZATION_CODE 'browser-based OAuth2 flow with PKCE', …). `MCPOAuth2Config(client_id, client_secret: Optional — 'not used for public clients or PKCE-only flows', auth_url, token_url, scopes, grant_type, redirect_path, redirect_base_url, extra_token_params)`. `MCPOAuth2Preset(name, display_name, auth_url, token_url, scopes, grant_type, url_template, required_params)`; `_PRESETS` contains `netsuite` and a future-use `fireflies`; `get_mcp_oauth2_preset(name)`, `list_mcp_oauth2_presets()`.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/oauth2_config.py`
  lines: 27-96
  symbol: `MCPOAuth2Config`
  excerpt: |
    class MCPOAuth2Config(BaseModel):
        client_id: Optional[str]; client_secret: Optional[str]  # optional for public clients
        auth_url; token_url; scopes: List[str]; grant_type: MCPOAuth2GrantType; redirect_path: str; redirect_base_url: str; extra_token_params
- path: `packages/ai-parrot/src/parrot/mcp/oauth2_config.py`
  lines: 98-135
  symbol: `MCPOAuth2Preset`
  excerpt: |
    class MCPOAuth2Preset(BaseModel): name; display_name; auth_url; token_url; scopes; grant_type; url_template; required_params
- path: `packages/ai-parrot/src/parrot/mcp/oauth2_config.py`
  lines: 136-204
  symbol: `_PRESETS / get_mcp_oauth2_preset`
  excerpt: |
    _PRESETS: list[MCPOAuth2Preset] = [ netsuite..., fireflies(future) ]
    def get_mcp_oauth2_preset(name) -> MCPOAuth2Preset | None

## Notes

This preset model is a second 'provider descriptor as data' shape (alongside `OAuth2Provider` subclasses). Public-client/PKCE support is declared here; the exchange logic lives elsewhere (oauth2_state / transport), not inspected.
