---
id: F049
query_id: F025-f1
type: read
intent: "Depth-2: what populates request['mcp_user'] in the server MCP transport and what its user_id is (token sub vs navigator-auth session)"
executed_at: 2026-10-30T15:30:19Z
duration_ms: 0
parent_id: F025
depth: 2
---

# F049 — mcp_user comes from three auth paths: external introspection (user_id = token sub or client_id), navigator-auth session (userdata dict), API key record

## Summary

`transports/base.py:_authenticate_request` (:174) dispatches on `AuthMethod`. `_authenticate_oauth_external` (:233-252) validates the bearer through the configured introspection endpoint and sets `request["mcp_user"] = {"user_id": token_info.get("sub") or token_info.get("client_id"), "scopes": …, "token_info": token_info}`; `_authenticate_bearer` (:254-267) uses navigator-auth `auth.get_session(request)` and stores the whole `userdata` dict as `mcp_user` (falls through unauthenticated when `app["auth"]` is missing — development mode); the API-key path sets `{"user_id": record.user_id, "scopes": record.scopes}` (:218). So the "Navigator user_id" a CLI login token yields depends on which auth method the mount uses: with navigator-auth sessions it is the session userdata (same family as `resolve_user_id`), with external introspection it is the IdP `sub`.

## Citations

- path: `packages/ai-parrot-server/src/parrot/mcp/transports/base.py`
  lines: 174-182
  symbol: `_authenticate_request`
  excerpt: |
    async def _authenticate_request(self, request: web.Request) -> web.Response | None:
        auth_method = self.config.auth_method
        if auth_method == AuthMethod.NONE:
- path: `packages/ai-parrot-server/src/parrot/mcp/transports/base.py`
  lines: 233-252
  symbol: `_authenticate_oauth_external`
  excerpt: |
    token_info = await self.external_oauth.validate_token(token)
    request["mcp_user"] = {
        "user_id": token_info.get("sub") or token_info.get("client_id"),
        "scopes": token_info.get("scope", "").split() if token_info.get("scope") else [],
        "token_info": token_info,
    }
- path: `packages/ai-parrot-server/src/parrot/mcp/transports/base.py`
  lines: 254-267
  symbol: `_authenticate_bearer`
  excerpt: |
    auth = request.app.get("auth")
    if not auth: ... # Fall through if auth not configured (development mode)
    userdata = await auth.get_session(request)
    request["mcp_user"] = userdata
- path: `packages/ai-parrot-server/src/parrot/mcp/transports/base.py`
  lines: 218
  symbol: `_authenticate_request (API key branch)`
  excerpt: |
    request["mcp_user"] = {"user_id": record.user_id, "scopes": record.scopes}

## Notes

Verified inline by the parent (grep + read of :174-182, :230-270). Implication for S-4: a CLI identity endpoint should sit behind navigator-auth session/bearer auth (so `resolve_user_id` yields the Navigator id) rather than the external-introspection mount, whose `sub` is an IdP subject — the Entra OID case S-1 U1 made secondary.
