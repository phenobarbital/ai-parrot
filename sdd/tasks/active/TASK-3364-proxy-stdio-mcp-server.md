# TASK-3364: `ProxyStdioMCPServer` — `wikitoolkit mcp` forwards to the remote when `remote` is configured (M6c)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3358, TASK-3359
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (pass-through part), AC12 — the **v1 intermediate install
path** (brainstorm decision): existing `.mcp.json` / `.codex/config.toml`
entries keep launching `wikitoolkit mcp`; when the repo resolves a `remote`,
that stdio server forwards `tools/list` and `tools/call` to the remote server
through `RemoteWikiClient`, adding `X-Wiki-Actor`. This is what makes remote
mode work for Codex (whose native HTTP client cannot send custom headers) with
no reinstall. Depends on TASK-3358 (same file, builder in place) and TASK-3359
(client).

---

## Scope

- `ProxyStdioMCPServer(StdioMCPServer)`: holds a `RemoteWikiClient`; `handle_initialize` answers locally with `serverInfo.name = "wikitoolkit"` and description `"remote proxy → <url>"`; `handle_tools_list` → `{"tools": await client.list_tools()}` (cached per process after first success); `handle_tools_call` → `await client.call_tool(name, arguments)`; `RemoteWikiError` → JSON-RPC error object `{code: -32000, message: str(exc), data: {"remote_code": exc.code}}` (never exit).
- `create_proxy_mcp_server(remote: WikiRemoteConfig) -> StdioMCPServer`: actor = `remote.actor or _authoring_identity(None)`; lazily connect on first request (`initialize()` of the client inside `start` or first call).
- `main()`: after config load, `remote = resolve_remote(config)`; if set → `create_proxy_mcp_server(remote)` and skip the `is_built()` check; else today's path.
- Tests: drive `_handle_request` directly with dicts against the fake remote.

**NOT in scope**: native HTTP installers (TASK-3365/3366), CLI proxy (TASK-3362).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | proxy server class, factory, `main()` switch |
| `packages/ai-parrot/tests/knowledge/wiki/test_proxy_stdio.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.local_server import StdioMCPServer            # parrot/mcp/local_server.py:36 (import under contextlib.redirect_stdout(sys.stderr), as mcp_server.py:~105 does)
from parrot.mcp.server_base import LocalServerConfig, negotiate_protocol_version   # server_base.py:48, :28
from parrot.knowledge.wiki.remote import RemoteWikiClient, RemoteWikiError         # TASK-3359
from parrot.knowledge.wiki.project import WikiRemoteConfig, resolve_remote          # TASK-3351
from parrot.knowledge.wiki.cli import _authoring_identity                            # cli.py:3027 — import lazily inside the factory (cli imports mcp_server.main lazily at :1359; avoid a module-level cycle)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/server_base.py
class MCPServerBase(ABC):                                                    # :57
    def __init__(self, config: LocalServerConfig); self.tools: dict[str, MCPToolAdapter]
    async def handle_initialize(self, params) -> dict   # :~78 — {"protocolVersion": negotiate_protocol_version(params.get("protocolVersion")), "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {name, version, description}}
    async def handle_tools_list(self, params) -> dict   # :~95 — {"tools": [adapter.to_mcp_tool_definition() ...]}
    async def handle_tools_call(self, params) -> dict   # :~105 — params["name"], params.get("arguments", {}); raises RuntimeError for unknown tool
# packages/ai-parrot/src/parrot/mcp/local_server.py
class StdioMCPServer(LocalMCPServerBase):                                     # :36
    async def start(self)                                                     # :44 — stdin loop → _handle_request → print(json.dumps(response))
    async def _handle_request(self, request: dict) -> dict | None            # :~88 — dispatches initialize / tools/list / tools/call / notifications/initialized; exceptions → {"jsonrpc":"2.0","id":…,"error":{"code":-32603,"message":str(e)}}
# packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py (after TASK-3358)
def create_wiki_mcp_server(root: Path) -> StdioMCPServer                       # thin wrapper
def main() -> None                                                             # :~261-289 — `root = find_project_root(...)`; `config = load_effective_config(root).config`; `if not config.is_built(root): … exit(1)`; `server = create_wiki_mcp_server(root)` (1 occurrence); `_ensure_stderr_logging()`; `asyncio.run(server.start())`
```

### Does NOT Exist
- ~~`ProxyStdioMCPServer` / `create_proxy_mcp_server`~~ — created here.
- ~~`StdioMCPServer.register_remote(...)`~~ — no such hook; override the three `handle_*` methods.
- ~~`MCPServerBase.handle_tools_list` accepting a cached list~~ — override it entirely.
- ~~stdout logging~~ — stdout is the JSON-RPC channel; use `self.logger` (stderr) only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_proxy_stdio.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer",
    "sym:packages/ai-parrot/src/parrot/mcp/server_base.py#MCPServerBase.handle_tools_list",
    "sym:packages/ai-parrot/src/parrot/mcp/server_base.py#MCPServerBase.handle_tools_call",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py#main"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Never `sys.exit` after the stdio loop starts; a remote failure is a JSON-RPC error on that request only (AC12).
- Lazy client `initialize()` on first `tools/list`/`tools/call` (so `wikitoolkit mcp` starts even if the remote is momentarily down); re-initialize on the next request after a failure.
- `main()` in remote mode must **not** require `is_built()` (there may be no local plane).
- Keep `_ensure_stderr_logging()` calls exactly where they are.

---

## Implementation Blueprint

### Steps (in order)
1. Add `ProxyStdioMCPServer` + `create_proxy_mcp_server` below `create_wiki_mcp_server` — *why*: both stdio factories side by side.
2. Switch in `main()` — *why*: AC12 requires the existing entry point to pick the proxy.
3. Tests; `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` (MODIFY — block 1)
```python
# occurrences: 1 (verified: grep -c '^def main() -> None:' packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py)
# BEFORE — insert above `def main() -> None:` (verified: mcp_server.py:~261)
def create_proxy_mcp_server(remote: Any) -> Any:
    """Stdio server that forwards tools/list + tools/call to the remote wiki mount (FEAT-569 pass-through)."""
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.mcp.local_server import StdioMCPServer
        from parrot.mcp.server_base import LocalServerConfig
    from parrot.knowledge.wiki.cli import _authoring_identity
    from parrot.knowledge.wiki.remote import RemoteWikiClient, RemoteWikiError

    class ProxyStdioMCPServer(StdioMCPServer):  # type: ignore[misc,valid-type]
        """Forwarding stdio server; a remote failure is a JSON-RPC error, never a process exit."""

        def __init__(self, config: Any, remote_cfg: Any, actor: str) -> None:
            super().__init__(config)
            self._remote_cfg, self._actor = remote_cfg, actor
            self._client: Any | None = None
            self._tools_cache: list[dict[str, Any]] | None = None

        async def _client_ready(self) -> Any:
            if self._client is None:
                client = RemoteWikiClient(self._remote_cfg, actor=self._actor)
                await client.initialize()
                self._client = client
            return self._client

        async def handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
            if self._tools_cache is None:
                self._tools_cache = await (await self._client_ready()).list_tools()
            return {"tools": self._tools_cache}

        async def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
            try:
                return await (await self._client_ready()).call_tool(params.get("name", ""), params.get("arguments", {}) or {})
            except RemoteWikiError as exc:
                self._client = None  # re-initialise on the next request
                raise RuntimeError(str(exc)) from exc  # _handle_request turns this into the JSON-RPC error envelope

    actor = remote.actor or _authoring_identity(None)
    return ProxyStdioMCPServer(LocalServerConfig(name="wikitoolkit", version="1.0.0",
                                                 description=f"remote proxy → {remote.url}"), remote, actor)


```
**Why this shape**: overriding the two handlers is the whole forwarding surface (`_handle_request`, local_server.py:~88, already wraps exceptions into `-32603` errors); the class is defined inside the factory so the lazy `parrot.mcp` import discipline of this module is preserved.

### `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` (MODIFY — block 2: main switch)
```python
# occurrences: 1 (verified: grep -c '    server = create_wiki_mcp_server(root)' mcp_server.py)
# REPLACE the `if not config.is_built(root): … sys.exit(1)` block + `server = create_wiki_mcp_server(root)` (mcp_server.py:~272-286) with:
    from parrot.knowledge.wiki.project import resolve_remote

    remote = resolve_remote(config)
    if remote is not None:
        server = create_proxy_mcp_server(remote)
    else:
        if not config.is_built(root):
            print(f"Error: wiki not built yet for {root}. Run `wikitoolkit build` first.", file=sys.stderr)
            sys.exit(1)
        server = create_wiki_mcp_server(root)
```
**Why**: the remote path needs no local plane (AC12); the local path is byte-identical (same message, same exit code).

### FILL IN checklist
- [ ] `handle_initialize` override only if the base's `serverInfo` needs the remote description (it uses `self.config.description` — already set via `LocalServerConfig`, so likely no override needed; confirm).
- [ ] Test the `-32603` envelope for a down remote by calling `await server._handle_request({...})`.

---

## Acceptance Criteria

- [ ] With `remote` configured and the fake remote up: `_handle_request({"method":"initialize",…})` → local `serverInfo.name == "wikitoolkit"`; `tools/list` → the fake's tools; `tools/call` → forwarded, and the fake saw `X-Wiki-Actor`.
- [ ] Fake down → `tools/call` returns a JSON-RPC `error` (code -32603, message containing `[remote:`) and the server object is still usable (next call after the fake returns works).
- [ ] `main()` with `remote` configured and **no** `wiki.db` starts the proxy (monkeypatch `asyncio.run` to capture the server type); without `remote` and no plane → today's error + exit 1.
- [ ] Existing `test_mcp_server.py` unchanged; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_proxy_stdio.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_proxy_stdio.py
import pytest
from parrot.knowledge.wiki.mcp_server import create_proxy_mcp_server
from parrot.knowledge.wiki.project import WikiRemoteConfig
# reuse `server` fixture (Fake aiohttp remote) from test_remote_client.py


async def test_forwarding(server, monkeypatch):
    fake, url = server; monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    srv = create_proxy_mcp_server(WikiRemoteConfig(url=url, actor="agent:proxy-test"))
    init = await srv._handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
    assert init["result"]["serverInfo"]["name"] == "wikitoolkit"
    tools = await srv._handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert "tools" in tools["result"]
    call = await srv._handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "wiki_query", "arguments": {"question": "x"}}})
    assert call["result"]["content"][0]["text"] == "hello" and fake.seen[-1]["X-Wiki-Actor"] == "agent:proxy-test"


async def test_remote_down_is_jsonrpc_error(monkeypatch):
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    srv = create_proxy_mcp_server(WikiRemoteConfig(url="http://127.0.0.1:9/mcp/w"))
    resp = await srv._handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "wiki_query", "arguments": {}}})
    assert resp["error"]["code"] == -32603 and "[remote:" in resp["error"]["message"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3358, TASK-3359 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `StdioMCPServer._handle_request` and `MCPServerBase.handle_initialize`
4. **Update status** in `sdd/tasks/index/wikitoolkit-http-mcp.json` → `"in-progress"`
5. **Implement** from the blueprint
6. **Verify** acceptance criteria; run the Validation Commands
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
