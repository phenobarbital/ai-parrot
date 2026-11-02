---
id: FC-009
query_id: Q022
type: grep
intent: "Server-side MCP principal binding"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-009 — parrot-as-MCP-server resolves principal from request['mcp_user'] (bearer introspection or API key)

## Summary

`principal_guard.resolve_principal` turns `request["mcp_user"]` (set by the HTTP transport's `_authenticate_request` for `AuthMethod.OAUTH2_EXTERNAL` introspection or `API_KEY`) into a `PermissionContext` with `channel="mcp"`, tenant precedence token claims → mount default → fail closed 401 (`WWW-Authenticate: Bearer realm="mcp"`), and publishes it on `_pctx_var`. `SessionStore` (InMemory/Redis) tracks HTTP MCP sessions/stream events only.

## Citations

- path: `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py`
  lines: 128-175
  symbol: `resolve_principal`
  excerpt: |
    mcp_user = request.get("mcp_user")
    if not isinstance(mcp_user, dict) or not mcp_user.get("user_id"):
        return _unauthorized("No authenticated principal for this request")
    principal = mcp_user["user_id"]; token_info = mcp_user.get("token_info") or {}
    tenant_id = resolve_tenant(token_info, mount_config)
    roles = frozenset(mcp_user.get("scopes") or [])
    return build_principal_context(principal, channel=MCP_CHANNEL, tenant_id=tenant_id, roles=roles)

- path: `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py`
  lines: 191-208
  symbol: `published_principal`
  excerpt: |
    token = _pctx_var.set(pctx)
    try: yield pctx
    finally: _pctx_var.reset(token)

- path: `packages/ai-parrot-server/src/parrot/mcp/session_store.py`
  lines: 91-113, 217, 282
  symbol: `SessionStore / InMemorySessionStore / RedisSessionStore`
  excerpt: |
    class SessionStore: async def create_session(...)


## Notes

This is the server-side identity path a CLI could reuse: a CLI holding a navigator-auth bearer token is identified exactly like an MCP client of parrot's HTTP MCP server.
