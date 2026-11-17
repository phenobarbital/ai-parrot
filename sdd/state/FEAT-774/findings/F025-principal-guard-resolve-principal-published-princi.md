---
id: F025
query_id: Q038
type: read
intent: "Server MCP principal guard header"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-025]
---

# F025 — principal_guard: resolve_principal + published_principal + PBACGuard; channel 'mcp'; _pctx_var publication

## Summary

Header read confirms FC-009 and adds: `MCP_CHANNEL = "mcp"`, `resolve_tenant` precedence (token `tenant_id` → `org_id` → mount `default_tenant_id`, client_id never a tenant), `runtime_key(pctx) = (tenant_id, user_id)`, `published_principal()` context manager over `parrot.auth.context._pctx_var`, and `PBACGuard` (line 389) re-verifying `tools/call` against `mcp:agent:{name}:tool:{tool}` deny-by-default.

## Citations

- path: `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py`
  lines: 54-67, 75-94, 178-188
  symbol: `imports / resolve_tenant / runtime_key`
  excerpt: |
    from parrot.auth.context import _pctx_var
    from parrot.auth.permission import PermissionContext, build_principal_context
    MCP_CHANNEL = "mcp"
    def resolve_tenant(token_info, mount_config) -> str | None:
        return token_info.get("tenant_id") or token_info.get("org_id") or getattr(mount_config, "default_tenant_id", None)
    def runtime_key(pctx) -> tuple[str, str]: return (pctx.tenant_id, pctx.user_id)

## Notes

`mcp_user["user_id"]` is whatever navigator-auth introspection returns — the same Navigator user id S-1 keys connections on.
