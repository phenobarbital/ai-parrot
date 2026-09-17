# TASK-3359: `RemoteWikiClient` — core aiohttp Streamable HTTP JSON-RPC client (M3)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Assigned-to**: unassigned
**Depends-on**: TASK-3351

---

## Context

Spec §3 Module 3, AC7/AC8, design research S5. Core has no Streamable HTTP
client: `MCPClient` (parrot/mcp/integration.py) knows `stdio|http|sse|unix|
websocket|quic` and the only SSE-in-POST parser (`HttpMCPSession`) lives in
ai-parrot-server, which clients must not need. This task writes the minimal
client every remote-mode consumer shares: the CLI proxy (TASK-3362/3363), the
stdio pass-through (TASK-3364). It carries the bearer token and `X-Wiki-Actor`,
decodes JSON or SSE bodies, maps failures to `RemoteWikiError` codes, and
retries **only read-only tools** once after a session expiry (S5: never replay a
write).

---

## Scope

- `RemoteWikiError(Exception)` with `code`, `message`, `url`, `status`; codes: `token_missing`, `unauthorized`, `wiki_not_found`, `unreachable`, `timeout`, `protocol`, `tool_error`, `session_expired`.
- `READ_ONLY_TOOLS` frozenset (spec M3).
- `RemoteWikiClient(remote: WikiRemoteConfig, *, actor: str, session: aiohttp.ClientSession | None = None)`: async context manager; `initialize()`, `list_tools()`, `call_tool(name, arguments)`, `call_tool_text(name, arguments)`, `close()`; `_decode_body(content_type, body)`.
- Headers on every request: `Authorization: Bearer <token>`, `X-Wiki-Actor`, `Accept: application/json, text/event-stream`, `Content-Type: application/json`, `Mcp-Session-Id` once known, `MCP-Protocol-Version: 2025-03-26` after initialize.
- Unit tests against an in-process aiohttp fake (no plugin dependency: `web.AppRunner` + `TCPSite(port=0)`).

**NOT in scope**: CLI rendering (TASK-3362), stdio pass-through (TASK-3364), OAuth.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/remote.py` | CREATE | client + errors |
| `packages/ai-parrot/tests/knowledge/wiki/test_remote_client.py` | CREATE | Unit tests with a fake server |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import aiohttp                                                     # core dependency (used across parrot/interfaces/http.py)
from aiohttp import web                                            # tests only — fake server
from parrot.knowledge.wiki.project import WikiRemoteConfig         # added by TASK-3351 (project.py, before WikiProjectConfig)
from parrot.mcp.server_base import SUPPORTED_PROTOCOL_VERSIONS     # parrot/mcp/server_base.py:17 → ("2024-11-05", "2025-03-26", "2025-06-18"); exported eagerly by parrot/mcp/__init__.py
```

### Existing Signatures to Use
```python
# Reference only (do NOT import — lives in ai-parrot-server): packages/ai-parrot-server/src/parrot/mcp/transports/http.py
class HttpMCPSession: async def _read_sse_response(...)   # :473-530 — SSE body: events separated by blank lines; each `data:` line carries one JSON-RPC message or a batch; the FIRST message whose "id" matches is the response
# Server behaviour the client must match: packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py
_handle_streamable_post   # :629 — requires Accept to include application/json or text/event-stream; `initialize` must not be batched; non-initialize calls need Mcp-Session-Id (else 400/404); responses are JSON or SSE depending on Accept/negotiation
# parrot/mcp/server_base.py
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")   # :17
# TASK-3351: WikiRemoteConfig(url, token_env="WIKITOOLKIT_TOKEN", timeout=30.0, actor=None, verify_tls=True)
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.remote`~~ — created here.
- ~~a core Streamable HTTP client (`parrot.mcp.MCPClient` with transport "streamable-http")~~ — `MCPClient._detect_transport()` has no such branch and its sessions live in ai-parrot-server; do not import `parrot.mcp.integration` (navconfig side effects, spec §7).
- ~~`requests` / `httpx` / `mcp` SDK~~ — forbidden (`ruff` TID251 bans the first two; AC18 bans the SDK at runtime).
- ~~automatic replay of write tools after a 404~~ — only `READ_ONLY_TOOLS` are retried (S5).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/remote.py", "action": "CREATE" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_remote_client.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/server_base.py#SUPPORTED_PROTOCOL_VERSIONS"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Token read in `__init__` from `os.environ[remote.token_env]`; empty/unset → `RemoteWikiError("token_missing", …)` **before** any I/O (AC8).
- Status mapping: 401/403 → `unauthorized`; 404 **without** a session id → `wiki_not_found`; 404 **with** a session id → session expired path; `aiohttp.ClientConnectorError`/`ClientOSError` → `unreachable`; `asyncio.TimeoutError` → `timeout`; unparsable body → `protocol`; JSON-RPC `error` → `tool_error` (message = error.message).
- `call_tool_text` concatenates `content[*].text` (MCP content envelope produced by `MCPToolAdapter._toolresult_to_mcp`, adapter.py:108-148) with `"\n"`.
- One `aiohttp.ClientSession` per client; `verify_tls=False` → `aiohttp.TCPConnector(ssl=False)`.
- Logging via `logging.getLogger(__name__)`; never print.

---

## Implementation Blueprint

### Steps (in order)
1. Write errors + constants — *why*: the CLI maps `code` to messages/exit codes; names are fixed by the spec.
2. Write the client with a single private `_post(payload)` doing headers/decoding/status mapping — *why*: one place for every failure mapping.
3. Add the read-only retry in `call_tool` — *why*: S5 decision.
4. Fake-server tests; `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/remote.py` (CREATE)
```python
"""Minimal MCP Streamable HTTP client for one remote wiki mount (FEAT-569, core only)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import aiohttp

from parrot.knowledge.wiki.project import WikiRemoteConfig

PROTOCOL_VERSION = "2025-03-26"
READ_ONLY_TOOLS: frozenset[str] = frozenset({
    "wiki_query", "wiki_page", "wiki_related", "wiki_status", "wiki_symbol_lookup", "wiki_code_outline",
    "wiki_blast_radius", "wiki_page_hashes", "ledger_ready", "ledger_context", "wiki_sync_pull",
})
logger = logging.getLogger(__name__)


class RemoteWikiError(Exception):
    """Typed remote failure; ``code`` is one of token_missing|unauthorized|wiki_not_found|unreachable|timeout|protocol|tool_error|session_expired."""

    exit_code = 2

    def __init__(self, code: str, message: str, *, url: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code, self.url, self.status = code, url, status

    def __str__(self) -> str:
        return f"[remote:{self.code}] {self.args[0]} ({self.url})"


def _decode_body(content_type: str, body: bytes, url: str) -> dict[str, Any]:
    """Decode a JSON or SSE (first `data:` message) JSON-RPC response body."""
    try:
        if "text/event-stream" in content_type:
            for line in body.decode("utf-8", errors="replace").splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
            raise ValueError("SSE body without data: line")
        return json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RemoteWikiError("protocol", f"unparsable response: {exc}", url=url) from exc


class RemoteWikiClient:
    """JSON-RPC over MCP Streamable HTTP: initialize → tools/list → tools/call."""

    def __init__(self, remote: WikiRemoteConfig, *, actor: str, session: aiohttp.ClientSession | None = None) -> None:
        token = os.environ.get(remote.token_env, "").strip()
        if not token:
            raise RemoteWikiError("token_missing", f"{remote.token_env} is not set (remote mode)", url=remote.url)
        self._remote, self._token, self._actor = remote, token, actor
        self._session, self._owns_session = session, session is None
        self._session_id: str | None = None
        self._next_id = 0

    async def __aenter__(self) -> "RemoteWikiClient":
        await self.initialize(); return self
    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    def _headers(self) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self._token}", "X-Wiki-Actor": self._actor,
             "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id; h["MCP-Protocol-Version"] = PROTOCOL_VERSION
        return h

    async def _post(self, method: str, params: dict[str, Any], *, notification: bool = False) -> dict[str, Any] | None:
        """One JSON-RPC POST with full status/exception mapping. Returns the `result` (None for notifications)."""
        # FILL IN: build payload ({"jsonrpc":"2.0","method":method,"params":params} + "id" unless notification); ensure self._session;
        #   async with session.post(self._remote.url, json=payload, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=self._remote.timeout)) as resp:
        #     capture resp.headers.get("Mcp-Session-Id") after initialize; 401/403→unauthorized; 404 and no session→wiki_not_found; 404 with session→session_expired;
        #     202/204→None; else data=_decode_body(...); "error" in data → RemoteWikiError("tool_error", data["error"].get("message")); return data.get("result")
        #   except aiohttp.ClientConnectorError/ClientOSError → unreachable; asyncio.TimeoutError → timeout — bounded by AC8
        raise NotImplementedError

    async def initialize(self) -> dict[str, Any]:
        """initialize + notifications/initialized; stores Mcp-Session-Id."""
        self._session_id = None
        result = await self._post("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                                 "clientInfo": {"name": "wikitoolkit", "version": "1.0.0"}})
        await self._post("notifications/initialized", {}, notification=True)
        return result or {}

    async def list_tools(self) -> list[dict[str, Any]]:
        return (await self._post("tools/list", {}) or {}).get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """tools/call; re-initialises once and retries ONLY for READ_ONLY_TOOLS on an expired session."""
        try:
            return await self._post("tools/call", {"name": name, "arguments": arguments}) or {}
        except RemoteWikiError as exc:
            if exc.code != "session_expired" or name not in READ_ONLY_TOOLS:
                raise
            logger.info("remote session expired; re-initialising for read-only tool %s", name)
            await self.initialize()
            return await self._post("tools/call", {"name": name, "arguments": arguments}) or {}

    async def call_tool_text(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self.call_tool(name, arguments)
        return "\n".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
```
**Why this shape**: spec M3 skeleton; `_post` centralises the mapping so the CLI (TASK-3362) can rely on `code` alone. Session id capture on `initialize` mirrors `StreamableHttpMCPServer._create_session` (server mints it on initialize).

### FILL IN checklist
- [ ] `_post` body incl. session creation (`aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False) if not verify_tls else None)`) and status mapping — bounded by AC8.
- [ ] Tests' fake server routes: 401 on bad token, 404 on unknown path, 404 on unknown session (after forgetting it), SSE-wrapped response variant.

---

## Acceptance Criteria

- [ ] Constructing with the token env unset raises `RemoteWikiError(code="token_missing")` before any network call.
- [ ] Against the fake server: `initialize()` captures `Mcp-Session-Id`; `call_tool_text("wiki_query", …)` returns the joined text; every request carries `Authorization`, `X-Wiki-Actor`, `Accept` headers (asserted server-side).
- [ ] `_decode_body` handles `application/json` and `text/event-stream` bodies; garbage → `protocol`.
- [ ] Mapping: 401→`unauthorized`; 404 (no session)→`wiki_not_found`; refused connection→`unreachable`; slow server + `timeout=1`→`timeout`; JSON-RPC error→`tool_error`.
- [ ] Fake server that forgets the session: `wiki_query` → one re-initialize + success; `wiki_remember` → `session_expired`, not re-sent (server counts calls).
- [ ] `ruff check` clean; no `requests`/`httpx`/`mcp` imports.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_remote_client.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_remote_client.py
import asyncio, json, pytest
from aiohttp import web
from parrot.knowledge.wiki.project import WikiRemoteConfig
from parrot.knowledge.wiki.remote import READ_ONLY_TOOLS, RemoteWikiClient, RemoteWikiError, _decode_body


class Fake:
    def __init__(self): self.seen = []; self.session = "s1"; self.forget = False; self.calls = 0
    async def handle(self, request: web.Request):
        self.seen.append(dict(request.headers)); body = await request.json()
        if request.headers.get("Authorization") != "Bearer t0k3n": return web.Response(status=401)
        if body["method"] == "initialize":
            self.session = f"s{len(self.seen)}"; return web.json_response({"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2025-03-26"}}, headers={"Mcp-Session-Id": self.session})
        if body["method"].startswith("notifications/"): return web.Response(status=202)
        if self.forget and request.headers.get("Mcp-Session-Id") != self.session: return web.Response(status=404)
        self.calls += 1
        return web.json_response({"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": "hello"}]}})


@pytest.fixture
async def server():
    fake = Fake(); app = web.Application(); app.router.add_post("/mcp/w", fake.handle)
    runner = web.AppRunner(app); await runner.setup(); site = web.TCPSite(runner, "127.0.0.1", 0); await site.start()
    port = runner.addresses[0][1]; yield fake, f"http://127.0.0.1:{port}/mcp/w"; await runner.cleanup()


async def test_roundtrip_and_headers(server, monkeypatch):
    fake, url = server; monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    async with RemoteWikiClient(WikiRemoteConfig(url=url), actor="human:t") as c:
        assert await c.call_tool_text("wiki_query", {"question": "x"}) == "hello"
    assert fake.seen[-1]["X-Wiki-Actor"] == "human:t" and "text/event-stream" in fake.seen[-1]["Accept"]


async def test_error_mapping(server, monkeypatch):
    fake, url = server
    monkeypatch.delenv("WIKITOOLKIT_TOKEN", raising=False)
    with pytest.raises(RemoteWikiError) as e: RemoteWikiClient(WikiRemoteConfig(url=url), actor="a")
    assert e.value.code == "token_missing"
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "bad")
    with pytest.raises(RemoteWikiError) as e:
        async with RemoteWikiClient(WikiRemoteConfig(url=url), actor="a"): pass
    assert e.value.code == "unauthorized"


async def test_session_expiry_retries_reads_only(server, monkeypatch):
    fake, url = server; monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    async with RemoteWikiClient(WikiRemoteConfig(url=url), actor="a") as c:
        c._session_id = "stale"; fake.forget = True
        assert "wiki_query" in READ_ONLY_TOOLS and await c.call_tool_text("wiki_query", {}) == "hello"
        c._session_id = "stale"; before = fake.calls
        with pytest.raises(RemoteWikiError) as e: await c.call_tool("wiki_remember", {})
        assert e.value.code == "session_expired" and fake.calls == before


def test_decode_sse():
    body = b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
    assert _decode_body("text/event-stream", body, "u")["result"]["ok"] is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3351 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `WikiRemoteConfig` fields and `SUPPORTED_PROTOCOL_VERSIONS`
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
