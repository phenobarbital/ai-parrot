---
id: FW-005
query_id: Q003
type: wiki_query
intent: "Orient: the agent daemon (agentd) — JSON-RPC over UDS, MCP stdio proxy, how a caller is identified."
executed_at: 2026-10-30T15:22:00Z
duration_ms: 2400
parent_id: null
depth: 2
---

# FW-005 — agentd binds a `PermissionContext` per UDS connection from `SO_PEERCRED` (OS user, `channel="agentd"`) — the one CLI-grade principal binding that exists

## Summary

`parrot.integrations.agentd` (ai-parrot-integrations; commands `serve/attach/ask/status/install-service/mcp-serve` at `cli/__init__.py:135-140`) is a per-agent daemon on a Unix socket (`server.py:JsonRpcUnixServer`, socket `chmod 0o600`, dir `0o700`). FEAT-434 added connection-time identity: `_resolve_identity()` reads `SO_PEERCRED` → uid → `pwd` username → `build_principal_context(username, channel="agentd")`, falling back to `ServiceIdentityConfig.from_env().to_permission_context()`; `Session.permission_context` / `identity_source` (`"peercred"` | `"service_identity"`) are set in `_handle_connection` and forwarded by `service.py` as `metadata["permission_context"]` on every RPC. `mcp_server.py:run_mcp_proxy` serves daemon tools (`ask_agent`, `agent_info`, `invoke_method`, …) over the core `StdioMCPServer`; `proxy.py:DaemonAgentProxy` (L184-256) lets `parrot agent` attach to a daemon. The principal is the **OS username**, not a Navigator `user_id` — a mapping step S-4 would have to add, but the binding seam (per-connection, fail-safe fallback, audit source) is a direct template.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 134-140
  symbol: `cli._lazy_commands`
  excerpt: |
    "serve": "parrot.integrations.agentd.cli", "attach": ..., "ask": ..., "status": ..., "install-service": ...,
    "mcp-serve": "parrot.integrations.agentd.cli",

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py`
  lines: 28
  symbol: imports
  excerpt: |
    from parrot.auth.permission import PermissionContext, build_principal_context

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py`
  lines: 58-72
  symbol: `_read_peercred`
  excerpt: |
    def _read_peercred(sock: socket.socket) -> tuple[int, int, int]:   # SO_PEERCRED (pid, uid, gid)

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py`
  lines: 116-145
  symbol: `Session`
  excerpt: |
    permission_context: The caller's resolved `PermissionContext` (FEAT-434) — the OS user of the UDS peer,
    or the configured service identity ... identity_source: "peercred" or "service_identity"

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py`
  lines: 214-240
  symbol: `JsonRpcUnixServer.__init__`
  excerpt: |
    service_identity: ServiceIdentityConfig | None = None,
    self.service_identity = service_identity or ServiceIdentityConfig.from_env()

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py`
  lines: 275-301
  symbol: `JsonRpcUnixServer.start`
  excerpt: |
    os.chmod(self.socket_path, 0o600)   # :275
    os.chmod(parent, 0o700)             # :301

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py`
  lines: 323-363
  symbol: `JsonRpcUnixServer._resolve_identity`
  excerpt: |
    _pid, uid, _gid = await asyncio.to_thread(_read_peercred, sock)
    username = await asyncio.to_thread(_uid_to_username, uid)
    return build_principal_context(username, channel="agentd"), "peercred"
    except (AttributeError, OSError, KeyError):
        return self.service_identity.to_permission_context(), "service_identity"

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py`
  lines: 365-372
  symbol: `JsonRpcUnixServer._handle_connection`
  excerpt: |
    session.permission_context, session.identity_source = await self._resolve_identity(writer)

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py`
  lines: 564-570
  symbol: `AgentDaemon`
  excerpt: |
    # FEAT-434: forward the caller's resolved identity (SO_PEERCRED -> OS user, or the service-identity fallback)
    metadata.setdefault("permission_context", session.permission_context)

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/mcp_server.py`
  symbol: `run_mcp_proxy`
  excerpt: |
    def run_mcp_proxy(name_or_socket): Connect to a daemon and serve its tools over MCP stdio.
    # built on parrot.mcp.local_server.StdioMCPServer

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/proxy.py`
  lines: 184-256
  symbol: `DaemonAgentProxy`
  excerpt: |
    class DaemonAgentProxy:  # load/list_agents/close over JSON-RPC UDS; mirrors ServerAgentProxy

## Notes

Wiki: `dir:...agentd` (1.00; 10 files: __init__, cli, client, config, mcp_server, protocol, proxy, server, service, tools), `sym:...proxy.py#DaemonAgentProxy` (0.63), `sdd/specs/agent-cli-daemon.spec.md` (0.54), `sym:...mcp_server.py#run_mcp_proxy` (0.50), `TASK-2215` (0.16). `service.py:323-341` mentions a service-identity "deployment default" and imports from `parrot.auth` lazily. Tests: `packages/ai-parrot-integrations/tests/agentd/{test_proxy,test_mcp_proxy,test_e2e}.py`.
[cross-lane: type=read, intent=agentd/config.py ServiceIdentityConfig — fields and env vars; whether a Navigator user id could be configured]
[cross-lane: type=grep, intent=`build_principal_context` definition in parrot/auth/permission.py — signature and what user_id type it accepts]
