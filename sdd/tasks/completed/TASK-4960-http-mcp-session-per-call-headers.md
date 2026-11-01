# TASK-4960: HttpMCPSession: request-local headers and principal-partitioned MCP sessions

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (G9, S9, AC-11). `MCPClient.call_tool` receives per-call headers but drops them
(integration.py:442), and `HttpMCPSession` has no per-call parameter; it also keeps one `Mcp-Session-Id` for the whole
connection, so a server-side authenticated session could be reused by another principal. This task makes the HTTP
session accept immutable per-call headers on `call_tool` → `_send_request` (retries included) and partition
initialized MCP sessions by principal (derived from the per-call bearer). Connection-level OAuth/token_supplier is
overridden only for that request; shared headers/config/session defaults are never mutated.

---

## Scope

- `call_tool(tool_name, arguments, *, headers=None)`; `_send_request(method, params=None, *, headers=None, partition=None)`.
- Partition key = `sha256(per-call Authorization value)[:16]` when per-call headers carry `Authorization`, else the
  default partition (today's behaviour). Each partition keeps its own `Mcp-Session-Id` / protocol version and runs its
  own `initialize` handshake on first use (serialize per-partition init with an `asyncio.Lock`).
- Per-call `Authorization` wins over `_oauth2_provider` / `token_supplier` for that request only.
- Unit test with an aiohttp test server recording headers.

**NOT in scope**: core client/config changes and the end-to-end gate (TASK-4961); other transports (stdio/sse/ws/quic).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/transports/http.py` | MODIFY | per-call headers + partitions |
| `packages/ai-parrot-server/tests/unit/test_http_mcp_session_headers.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
import hashlib, asyncio
from parrot.mcp.client import MCPClientConfig            # verified: mcp/client.py:133 (already imported by http.py)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/mcp/transports/http.py
class HttpMCPSession:                                           # :203
    def __init__(self, config: MCPClientConfig, logger)          # :206 — _base_headers, _oauth2_provider, _mcp_session_id, _protocol_version
    async def connect(self)                                      # :337 — builds _base_headers, initializes
    async def _initialize_session(self)                          # :372
    async def _send_request(self, method: str, params: dict = None) -> dict   # :390 — req_headers incl. Mcp-Session-Id (:412),
                                                                 #   Authorization from _oauth2_provider (:418) or token_supplier (:422); 429 retry (:433);
                                                                 #   captures issued Mcp-Session-Id (:445)
    async def _send_notification(self, method, params=None)      # :532
    async def call_tool(self, tool_name: str, arguments: dict):  # :580 anchor
```

### Does NOT Exist
- ~~`HttpMCPSession.call_tool(..., headers=)`~~ — added here.
- ~~per-principal MCP sessions~~ — added here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/mcp/transports/http.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/test_http_mcp_session_headers.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/mcp/transports/http.py#HttpMCPSession"
  ]
}
```

---

## Implementation Notes

- Never log header values; log the partition key only.
- Copy dicts (`dict(headers)`) — the caller's mapping and `_base_headers` stay untouched.
- The default partition reuses the existing `_mcp_session_id` fields so non-delegated behaviour is byte-for-byte unchanged.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Partition state + helpers (block) — *why*: AC-11 session isolation.
2. Thread `headers`/`partition` through `_send_request` (incl. the 429 retry loop) and `call_tool` — *why*: per-call bearer on every retry.
3. Tests.

### `packages/ai-parrot-server/src/parrot/mcp/transports/http.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def call_tool(self, tool_name: str, arguments: dict):' transports/http.py → :580)
    async def call_tool(self, tool_name: str, arguments: dict, *, headers: Optional[Dict[str, str]] = None):
        """Call a tool; per-call ``headers`` apply to this request only (and select the principal partition)."""
        if not self._initialized:
            raise MCPConnectionError("Session not initialized")
        partition = self._partition_for(headers)
        await self._ensure_partition_initialized(partition, headers)
        result = await self._send_request("tools/call", {"name": tool_name, "arguments": arguments},
                                          headers=headers, partition=partition)
        # KEEP the existing result → ToolCallResult conversion

    @staticmethod
    def _partition_for(headers: Optional[Dict[str, str]]) -> Optional[str]:
        """None = default partition; else a non-reversible key of the per-call Authorization value."""
        auth = (headers or {}).get("Authorization")
        return hashlib.sha256(auth.encode()).hexdigest()[:16] if auth else None

    async def _ensure_partition_initialized(self, partition: Optional[str], headers: Optional[Dict[str, str]]) -> None:
        # FILL IN: default partition → return; else under a per-partition asyncio.Lock run the initialize request +
        #          notifications/initialized with these headers and store that partition's session id/protocol version
        raise NotImplementedError
# _send_request(self, method, params=None, *, headers=None, partition=None):
#   FILL IN: pick session id/protocol version from the partition (default → today's fields); after building req_headers,
#            `req_headers.update(headers)` for this request only (per-call Authorization overrides provider/supplier);
#            capture an issued Mcp-Session-Id into the partition's state; keep the 429 retry using the same headers
```

### FILL IN checklist
- [ ] partition state dict + locks in `__init__`, cleared in `disconnect`
- [ ] `_ensure_partition_initialized`
- [ ] `_send_request` header merge + partition session ids (retry path too)
- [ ] tests: two principals → distinct Authorization + distinct Mcp-Session-Id; base headers unmodified; default partition unchanged

---

## Acceptance Criteria

- [ ] AC-11 (transport): per-call Authorization reaches the server on the first try and on a 429 retry
- [ ] Two principals get different `Mcp-Session-Id`s; shared headers/config are not mutated
- [ ] Calls without per-call headers behave exactly as before

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_http_mcp_session_headers.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_http_mcp_session_headers.py
@pytest.mark.asyncio
async def test_per_call_bearer_and_partitioned_sessions(aiohttp_server): ...
@pytest.mark.asyncio
async def test_retry_keeps_per_call_headers(aiohttp_server): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat sonnet (native)
**Date**: 2026-10-30
**Notes**: Implemented per task; merged, engine lint clean. Merge-tier validation: only red is pre-existing test_oauth_callback_routes::test_invalid_state_returns_400 (fails on dev too; ledger issue:e7b7e5906b6e).
