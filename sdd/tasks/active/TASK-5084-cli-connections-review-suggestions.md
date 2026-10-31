# TASK-5084: FEAT-774 review suggestions — insecure http server, discovery origin, ConnectionCache file checks + lock, client sessions, no-store

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5081
**Assigned-to**: unassigned
**Discovered-from**: `issue:73db45b2286a`

---

## Context

TASK-5081 fixed the numbered findings of the FEAT-774 review and split its trailing suggestions
into `issue:73db45b2286a`. This task resolves those suggestions (a)–(f).

## Scope

1. **(a) Insecure `http://` server.** `cli/login.py` gains `is_insecure_remote_http(url) -> bool`
   (true for an `http://` URL whose host is not loopback: `localhost`, `127.0.0.0/8`, `::1`).
   `parrot login` refuses such a `--server` (exit 2) unless `--allow-insecure-http` is passed.
   `parrot agent --server` (`cli/agent_repl.py`) prints a yellow warning when it would send a
   bearer to such a URL (it does not refuse: `--token` over http stays possible).
2. **(b) Discovery origin.** In `cli/login.py`, every endpoint read from authorization-server
   metadata (`device_authorization_endpoint`, `token_endpoint`, `userinfo_endpoint`,
   `revocation_endpoint`) must share the `--server` / `record.server_url` origin; a mismatch raises
   `DeviceCodeError("invalid_metadata", ...)` (login/refresh) or skips revocation (logout).
   The generic `device_code.py` engine is unchanged (provider endpoints may span origins).
3. **(c) `ConnectionCache` file checks + cross-process lock** (`auth/oauth2/local_cache.py`).
   `_read_sync` opens with `O_NOFOLLOW` and requires a regular file owned by `os.getuid()` with no
   group/other bits; any failure logs a warning and is treated as empty. `put`/`delete` hold an
   `fcntl.flock` on a 0600 sidecar `<cache>.lock` across the read-modify-write.
4. **(d) Unclosed sessions.** `toolkit_server._ToolkitStdioMCPServer` keeps the
   `ServerConnectionsClient` it creates and closes it in `stop()`; the client is closed at once when
   identity binding fails. The REPL broker client (`agent_repl._run`) is owned by `_run` and closed
   when the REPL exits.
5. **(e) `Cache-Control: no-store`** on the `POST /connections/{provider}/token` success response
   (`ai-parrot-server/.../handlers/connections.py`), plus `Pragma: no-cache`.
6. **(f) AC-4 adapter check.** `MCPToolAdapter` with no execution context calls `tool.execute()`
   with no `_`-prefixed kwargs (by design since TASK-4975). Add a regression test that pins it.

**NOT in scope**: changing the `device_code.py` engine, refusing http in the REPL, agentd.

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/cli/login.py`
- `packages/ai-parrot/src/parrot/cli/agent_repl.py`
- `packages/ai-parrot/src/parrot/auth/oauth2/local_cache.py`
- `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`
- `packages/ai-parrot-server/src/parrot/handlers/connections.py`
- `packages/ai-parrot/tests/cli/test_login.py`
- `packages/ai-parrot/tests/auth/test_connection_cache.py`
- `packages/ai-parrot/tests/mcp/test_adapter_execution_context.py`
- `packages/ai-parrot-server/tests/unit/test_connections_cli_routes.py`
- `tests/mcp/test_toolkit_server_login.py`

## Codebase Contract

- `LoginStore._locked()` / `load_optional()` in `cli/login.py` — the O_NOFOLLOW + fstat + flock pattern to mirror.
- `_origin()` / `_same_origin()` in `cli/agent_repl.py` — origin comparison (scheme, host, effective port).
- `ServerConnectionsClient.close()` in `auth/oauth2/remote_client.py` — closes an owned session; idempotent.
- `build_cli_broker(store, providers, *, client=None)` in `auth/oauth2/local_cache.py`.

## Acceptance Criteria

- [ ] `parrot login --server http://example.com` exits 2 without `--allow-insecure-http`; loopback http is accepted.
- [ ] A metadata endpoint on another origin is rejected during login and refresh.
- [ ] A symlinked, group-readable or foreign-owned cache file reads as empty; put/delete take the sidecar lock.
- [ ] The stdio server and the REPL close the `ServerConnectionsClient` they create.
- [ ] The token route response carries `Cache-Control: no-store`.
- [ ] A test pins that the adapter passes no `_`-kwargs without a context.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src pytest -q packages/ai-parrot/tests/cli/test_login.py packages/ai-parrot/tests/auth/test_connection_cache.py packages/ai-parrot/tests/mcp/test_adapter_execution_context.py packages/ai-parrot-server/tests/unit/test_connections_cli_routes.py tests/mcp/test_toolkit_server_login.py packages/ai-parrot/tests/cli/test_repl_identity_matrix.py
```

## Completion Note

*(filled on completion)*
