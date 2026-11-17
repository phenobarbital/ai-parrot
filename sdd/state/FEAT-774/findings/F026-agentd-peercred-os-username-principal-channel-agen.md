---
id: F026
query_id: Q040
type: read
intent: "agentd UDS server identity"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-026]
---

# F026 — agentd: peercred → OS username principal (channel 'agentd'); fallback service identity; socket 0600

## Summary

`JsonRpcUnixServer` binds a 0600 UDS under a 0700 dir, resolves each connection's identity via `SO_PEERCRED` → `pwd` username → `build_principal_context(username, channel="agentd")`, falling back to `ServiceIdentityConfig` (env `AGENTD_SERVICE_IDENTITY_*`, defaults user_id `1001`, tenant `default`, confirmation window 0). The principal is an OS username, not a Navigator id, and `tenant_id` defaults to the principal when not given (permission.py:188).

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py`
  lines: 58-89, 228-243, 363-377
  symbol: `_read_peercred / _uid_to_username / __init__ / _handle_connection`
  excerpt: |
    _PEERCRED_FORMAT = "3i"
    def _read_peercred(sock) -> tuple[int, int, int]: ... SO_PEERCRED
    def _uid_to_username(uid: int) -> str: return pwd.getpwuid(uid).pw_name
    self.service_identity = service_identity or ServiceIdentityConfig.from_env()
    session.permission_context, session.identity_source = await self._resolve_identity(writer)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py`
  lines: 131-166
  symbol: `ServiceIdentityConfig`
  excerpt: |
    display_name: str = "parrot agent server"; user_id: str = "1001"; tenant_id: str = "default"; roles: frozenset[str]

## Notes

agentd's `parrot mcp-serve` (mcp_server.py, not read) proxies tools to the daemon over this UDS — its callers inherit the peercred principal, so a Navigator mapping would have to be OS-user → Navigator user (new).
