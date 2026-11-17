---
id: F034
query_id: FC-003-f1
type: grep
intent: "Depth-2: build_principal_context contract"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: FC-003
depth: 1
merged_from: [FC-034]
---

# F034 — build_principal_context(principal, *, channel, tenant_id=None, roles=None) — tenant defaults to principal

## Summary

`parrot.auth.permission.build_principal_context` builds a minimal `PermissionContext` for a bare principal id; docstring: used where a caller has an authenticated identity but no pre-built context (REST session user id, scheduler principal, agentd peercred, MCP guard). `tenant_id` defaults to `principal` when not given — a CLI resolver must pass the real tenant or inherit that quirk.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/permission.py`
  lines: 166-188
  symbol: `build_principal_context`
  excerpt: |
    def build_principal_context(principal: str, *, channel: str, tenant_id: Optional[str] = None,
                                roles: Optional[frozenset[str]] = None) -> "PermissionContext":
        """Build a minimal ``PermissionContext`` for a bare principal identifier. ...
            tenant_id: Tenant/org identifier. Defaults to ``principal`` when not ...

## Notes

Shared helper for every non-web principal path (agentd, server MCP guard); natural target for a CLI resolver.
