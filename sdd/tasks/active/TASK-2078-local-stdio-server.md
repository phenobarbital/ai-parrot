# TASK-2078: Create LocalMCPServerBase + StdioMCPServer in core

**Feature**: FEAT-403 — MCP Local Server Core + WikiToolkit MCP
**Spec**: `sdd/specs/mcp-local-server-wikitoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2077
**Assigned-to**: unassigned

---

## Context

This task creates the concrete local transport layer: a `LocalMCPServerBase`
extension point and a `StdioMCPServer` that does JSON-RPC over stdin/stdout.
This is the core deliverable that enables any ai-parrot package to expose
tools as a local MCP server without depending on ai-parrot-server.

Implements spec Module 3.

---

## Scope

- Create `packages/ai-parrot/src/parrot/mcp/local_server.py` with:
  - `LocalMCPServerBase(MCPServerBase)` — extension point for local transports
  - `StdioMCPServer(LocalMCPServerBase)` — JSON-RPC over stdin/stdout
- Update `packages/ai-parrot/src/parrot/mcp/__init__.py` to export all new classes from Modules 1-3
- Write unit tests with mock stdin/stdout

**NOT in scope**: Server-side `StdioMCPServer` reparenting (TASK-2079). Wiki tools (TASK-2080).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/local_server.py` | CREATE | LocalMCPServerBase + StdioMCPServer |
| `packages/ai-parrot/src/parrot/mcp/__init__.py` | MODIFY | Add exports for adapter, server_base, local_server |
| `packages/ai-parrot/tests/mcp/test_local_server.py` | CREATE | Unit + integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From TASK-2077 (must be completed first)
from parrot.mcp.server_base import MCPServerBase, LocalServerConfig

# From TASK-2076
from parrot.mcp.adapter import MCPToolAdapter

# Current core __init__.py (verified: packages/ai-parrot/src/parrot/mcp/__init__.py)
# Uses extend_path at line 2-3 for PEP 420 namespace merging
```

### Reference Implementation (server's StdioMCPServer)
```python
# packages/ai-parrot-server/src/parrot/mcp/transports/stdio.py
class StdioMCPServer(MCPServerBase):  # line 16
    def __init__(self, config: MCPServerConfig):  # line 19
        super().__init__(config)
        self._request_id = 0
        self._running = False

    async def start(self):  # line 24
        # readline loop on sys.stdin, dispatch to handle_*, print to stdout

    async def stop(self):  # line 60
        self._running = False

    async def _handle_request(self, request: dict) -> Optional[dict]:  # line 64
        # Routes: initialize, tools/list, tools/call, notifications/initialized
        # Returns JSON-RPC response dict or None for notifications
```

### Does NOT Exist
- ~~`parrot.mcp.local_server`~~ — does not exist yet; this task creates it
- ~~`LocalMCPServerBase`~~ — does not exist yet; this task creates it
- ~~Core `StdioMCPServer`~~ — does not exist yet; the one at `transports/stdio.py:16` is the server version

---

## Implementation Notes

### StdioMCPServer Design
Model closely on server's `StdioMCPServer` (verified at `transports/stdio.py:16-100`)
but with these differences:
- Inherits `LocalMCPServerBase` (not server's MCPServerBase)
- Constructor takes `LocalServerConfig` (not `MCPServerConfig`)
- All logging to stderr (stdout is the MCP channel) — use `logging.StreamHandler(sys.stderr)`
- `sys.stdin.readline()` is blocking; use `asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)` for proper async

### JSON-RPC Protocol
- One JSON object per line on stdin
- One JSON object per line on stdout (via `print(json.dumps(response), flush=True)`)
- Notifications (no `id` field) get no response
- Handle methods: `initialize`, `tools/list`, `tools/call`, `notifications/initialized`
- Unknown methods return JSON-RPC error code -32603

### __init__.py Updates
Add to the existing `__init__.py`:
```python
from .adapter import MCPToolAdapter, MCPResource
from .server_base import MCPServerBase, LocalServerConfig
from .local_server import LocalMCPServerBase, StdioMCPServer
```
And extend `__all__` with these names.

### Key Constraints
- No aiohttp imports
- stdout must not be polluted with log messages (all logging → stderr)
- Must handle graceful shutdown via `stop()`

---

## Acceptance Criteria

- [ ] `from parrot.mcp.local_server import LocalMCPServerBase, StdioMCPServer` works
- [ ] `from parrot.mcp import MCPToolAdapter, MCPServerBase, LocalServerConfig, StdioMCPServer` works
- [ ] StdioMCPServer reads JSON-RPC from stdin and writes responses to stdout
- [ ] Notifications (no `id`) produce no response
- [ ] Unknown methods return JSON-RPC error
- [ ] `stop()` cleanly exits the read loop
- [ ] Tests pass: `pytest packages/ai-parrot/tests/mcp/test_local_server.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/mcp/test_local_server.py
import pytest
import json
import asyncio
from unittest.mock import patch, MagicMock
from parrot.mcp.local_server import StdioMCPServer, LocalMCPServerBase
from parrot.mcp.server_base import LocalServerConfig


class TestStdioMCPServer:
    @pytest.mark.asyncio
    async def test_handle_request_initialize(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        response = await server._handle_request({
            "jsonrpc": "2.0", "id": 1,
            "method": "initialize", "params": {}
        })
        assert response["id"] == 1
        assert response["result"]["protocolVersion"] == "2024-11-05"

    @pytest.mark.asyncio
    async def test_handle_request_tools_list(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        # register a tool first
        server.register_tool(EchoTool())
        response = await server._handle_request({
            "jsonrpc": "2.0", "id": 2,
            "method": "tools/list", "params": {}
        })
        assert len(response["result"]["tools"]) == 1

    @pytest.mark.asyncio
    async def test_handle_request_tools_call(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        server.register_tool(EchoTool())
        response = await server._handle_request({
            "jsonrpc": "2.0", "id": 3,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"text": "hi"}}
        })
        assert response["result"]["isError"] is False

    @pytest.mark.asyncio
    async def test_handle_notification_no_response(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        response = await server._handle_request({
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        })
        assert response is None

    @pytest.mark.asyncio
    async def test_handle_unknown_method(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        response = await server._handle_request({
            "jsonrpc": "2.0", "id": 4,
            "method": "unknown/method", "params": {}
        })
        assert "error" in response
        assert response["error"]["code"] == -32603
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2077 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports and signatures still match
4. **Update status** in `sdd/tasks/index/mcp-local-server-wikitoolkit.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2078-local-stdio-server.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
