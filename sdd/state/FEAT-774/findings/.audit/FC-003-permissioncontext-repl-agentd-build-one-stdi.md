---
id: FC-003
query_id: Q016
type: grep
intent: "PermissionContext usage in MCP / CLI / agentd"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-003 — PermissionContext: REPL + agentd build one; stdio MCP servers have none

## Summary

`PermissionContext` appears in the CLI (identity/repl/agent_repl/session) and in agentd, where `JsonRpcUnixServer._resolve_identity` maps the UDS peer's OS uid to a username and builds `build_principal_context(username, channel="agentd")`, falling back to a configured `ServiceIdentityConfig` (default user_id `"1001"`, tenant `"default"`). `packages/ai-parrot/src/parrot/mcp/` has zero matches: the stdio MCP server / toolkit server never build or receive a principal.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py`
  lines: 323-361
  symbol: `JsonRpcUnixServer._resolve_identity`
  excerpt: |
    _pid, uid, _gid = await asyncio.to_thread(_read_peercred, sock)
    username = await asyncio.to_thread(_uid_to_username, uid)
    return build_principal_context(username, channel="agentd"), "peercred"
    except (AttributeError, OSError, KeyError) as exc:
        return self.service_identity.to_permission_context(), "service_identity"

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py`
  lines: 198-220
  symbol: `ServiceIdentityConfig.to_permission_context`
  excerpt: |
    ctx = build_principal_context(self.user_id, channel=channel, tenant_id=self.tenant_id, roles=self.roles or None)
    ctx.extra["window_seconds"] = self.window_seconds

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py`
  lines: 374-381, 568-570
  symbol: `AgentDaemon (respondent / metadata)`
  excerpt: |
    if not respondent and session.permission_context is not None:
        respondent = session.permission_context.user_id
    metadata.setdefault("permission_context", session.permission_context)

- path: `packages/ai-parrot/src/parrot/cli/repl.py`
  lines: 44-65
  symbol: `REPLConfig.permission_context`
  excerpt: |
    permission_context: Optional[Any] = None


## Notes

agentd principal = OS username (peercred), not a Navigator user_id. Absence: no PermissionContext in parrot/mcp/*.py.
