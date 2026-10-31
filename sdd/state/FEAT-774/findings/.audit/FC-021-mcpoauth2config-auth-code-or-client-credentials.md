---
id: FC-021
query_id: Q034
type: read
intent: "MCP OAuth2 config model"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-021 — MCPOAuth2Config: auth-code or client-credentials; redirect is the server callback path

## Summary

`MCPOAuth2Config` supports `authorization_code` and `client_credentials` grants, RFC 7591 dynamic registration (client_id None), and a redirect built from `redirect_base_url` (default `NAVIGATOR_BASE_URL` / `http://127.0.0.1:8000`) + `redirect_path` `/api/auth/oauth2/mcp/callback`. No device-code grant. Presets: `netsuite`, `fireflies`.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/oauth2_config.py`
  lines: 15-24, 79-91, 139-173
  symbol: `MCPOAuth2GrantType / MCPOAuth2Config / _PRESETS`
  excerpt: |
    class MCPOAuth2GrantType(str, Enum): AUTHORIZATION_CODE = "authorization_code"; CLIENT_CREDENTIALS = "client_credentials"
    redirect_path: str = Field(default="/api/auth/oauth2/mcp/callback")
    _PRESETS = [MCPOAuth2Preset(name="netsuite", ...), MCPOAuth2Preset(name="fireflies", ...)]


## Notes

-
