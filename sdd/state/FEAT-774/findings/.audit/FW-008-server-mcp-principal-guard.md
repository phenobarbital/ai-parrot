---
id: FW-008
query_id: Q005
type: wiki_query
intent: "Orient: server-side MCP principal guard and session store — how an MCP caller's principal is established when parrot is the MCP server."
executed_at: 2026-10-30T15:23:30Z
duration_ms: 2200
parent_id: null
depth: 2
---

# FW-008 — Server-side MCP (FEAT-477): `resolve_principal(request["mcp_user"])` → `PermissionContext(channel="mcp")`, fail-closed tenant, PBAC per agent/tool

## Summary

`packages/ai-parrot-server/src/parrot/mcp/principal_guard.py` converts whichever HTTP auth path fired (`AuthMethod.OAUTH2_EXTERNAL` via token introspection, or `AuthMethod.API_KEY`) into one `PermissionContext` and publishes it on the shared `_pctx_var` (`parrot/auth/context.py`). `resolve_principal(request, mount_config, *, audit_hook=None)` (L128-175) reads `request["mcp_user"]["user_id"]` and `token_info`, resolves the tenant by `token_info.tenant_id` → `org_id` → `AgentMCPMountConfig.default_tenant_id` → **401** (never defaults), and builds the context via `build_principal_context`; `MCP_CHANNEL = "mcp"`. `runtime_key(pctx)` = `(tenant_id, principal)`; `PBACGuard` filters `tools/list` and re-verifies every `tools/call` against `mcp:agent:{name}:tool:{tool}` with an injectable `audit_sink`. This is the authenticated-MCP precedent: an **HTTP** MCP caller already carries a principal; the stdio hosts (Claude Code / Codex running `parrot mcp-local`) have none (FW-003). A CLI login token presented as a bearer to this same path would make the HTTP transport the natural S-4 route for "MCP tools in CLI".

## Citations

- path: `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py`
  lines: 1-30
  symbol: module docstring
  excerpt: |
    Principal resolution + tenant binding + `_pctx_var` publication. FEAT-477, Module 3 ...
    Converts whichever auth path fired (`AuthMethod.OAUTH2_EXTERNAL` via introspection, or `AuthMethod.API_KEY`)
    into a single `PermissionContext` and publishes it on the existing `_pctx_var` (parrot/auth/context.py:33)

- path: `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py`
  lines: 60-75
  symbol: imports / `MCP_CHANNEL`
  excerpt: |
    from parrot.auth.context import _pctx_var
    from parrot.auth.permission import PermissionContext, build_principal_context
    MCP_CHANNEL = "mcp"

- path: `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py`
  lines: 84-103
  symbol: `resolve_tenant`
  excerpt: |
    return token_info.get("tenant_id") or token_info.get("org_id") or getattr(mount_config, "default_tenant_id", None)

- path: `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py`
  lines: 128-175
  symbol: `resolve_principal`
  excerpt: |
    async def resolve_principal(request, mount_config, *, audit_hook=None) -> "PermissionContext | web.Response":
        mcp_user = request.get("mcp_user")
        if not isinstance(mcp_user, dict) or not mcp_user.get("user_id"): return _unauthorized(...)
        principal = mcp_user["user_id"]; token_info = mcp_user.get("token_info") or {}
        tenant_id = resolve_tenant(token_info, mount_config)

- path: `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py`
  symbol: `runtime_key` / `published_principal` / `PBACGuard`
  excerpt: |
    def runtime_key(pctx): (tenant_id, principal)
    def published_principal(pctx): publish pctx on _pctx_var for the async-with block
    class PBACGuard: tools_list(params, pctx) policy-filtered; tools_call(params, pctx) re-verified, audited, size/deadline-policed

## Notes

Wiki: `dir:packages/ai-parrot-server/src/parrot/mcp` (1.00; 16 entries), `sym:#runtime_key` (0.77), `TASK-2604` (0.20), `sym:#resolve_principal` (0.02), tests `packages/ai-parrot-server/tests/mcp/test_principal_resolution.py`. `session_store.py` was not surfaced by the query beyond the dir listing. The `mcp_user["user_id"]` here is whatever navigator-auth introspection returns — likely the same identity family S-1 U1 keys on; confirming that is a codebase-lane job.
[cross-lane: type=read, intent=principal_guard.py:128-175 + the `_authenticate_request` that populates request["mcp_user"] — what `user_id` is (Navigator id vs email)]
[cross-lane: type=read, intent=ai-parrot-server mcp/session_store.py header — what a session binds]
