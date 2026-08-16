# TASK-2077: Create MCPServerBase abstract base in core

**Feature**: FEAT-403 — MCP Local Server Core + WikiToolkit MCP
**Spec**: `sdd/specs/mcp-local-server-wikitoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2076
**Assigned-to**: unassigned

---

## Context

The current MCPServerBase in ai-parrot-server mixes universal concerns
(tool registration, JSON-RPC handlers) with remote-only concerns (auth,
aiohttp, resources). This task creates a clean ABC in core with only the
universal part, so local transports can inherit without pulling in aiohttp.

Implements spec Module 2.

---

## Scope

- Create `packages/ai-parrot/src/parrot/mcp/server_base.py` with:
  - `LocalServerConfig` dataclass
  - `MCPServerBase(ABC)` with tool registration + JSON-RPC handlers
- Write unit tests for server base registration and handler dispatch

**NOT in scope**: StdioMCPServer (TASK-2078), RemoteMCPServerBase rename (TASK-2079).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/server_base.py` | CREATE | MCPServerBase ABC + LocalServerConfig |
| `packages/ai-parrot/tests/mcp/test_server_base.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From TASK-2076 (must be completed first)
from parrot.mcp.adapter import MCPToolAdapter  # will be in core after TASK-2076
from parrot.tools.abstract import AbstractTool  # verified: packages/ai-parrot/src/parrot/tools/abstract.py:233
```

### Existing Signatures to Extract From
```python
# packages/ai-parrot-server/src/parrot/mcp/transports/base.py — extract universal part
class MCPServerBase(ABC):  # line 13
    def __init__(self, config: MCPServerConfig):  # line 16
        self.tools: Dict[str, MCPToolAdapter] = {}  # line 18
        self.resources: Dict[str, MCPResource] = {}  # line 19 — NOT in core base
    def register_tool(self, tool: AbstractTool)  # line 156
    def register_tools(self, tools: List[AbstractTool])  # line 177
    async def handle_initialize(self, params) -> dict  # line 313
    async def handle_tools_list(self, params) -> dict  # line 331
    async def handle_tools_call(self, params) -> dict  # line 342
    async def start(self)  # line 359 — abstract
    async def stop(self)  # line 364 — abstract
```

### Target Implementation
```python
@dataclass
class LocalServerConfig:
    name: str = "parrot-mcp-local"
    version: str = "1.0.0"
    description: str = ""
    log_level: str = "WARNING"

class MCPServerBase(ABC):
    def __init__(self, config: LocalServerConfig): ...
    # tool registration (NO allowed_tools/blocked_tools filtering — that's server-only)
    # JSON-RPC handlers (initialize, tools/list, tools/call)
    # abstract start() and stop()
```

### Does NOT Exist
- ~~`parrot.mcp.server_base`~~ — does not exist yet; this task creates it
- ~~`LocalServerConfig`~~ — does not exist yet; this task creates it
- ~~`MCPServerBase` in core~~ — does not exist yet; the one at `transports/base.py:13` is the server version

---

## Implementation Notes

### Key Differences from Server's MCPServerBase
The core base extracts ONLY:
- `__init__` with `self.tools` dict (NO `self.resources`, NO auth)
- `register_tool` (NO `allowed_tools`/`blocked_tools` filtering)
- `register_tools`
- `handle_initialize` / `handle_tools_list` / `handle_tools_call`
- abstract `start()` / `stop()`

Everything else (auth, resources, aiohttp) stays in the server's `RemoteMCPServerBase` (TASK-2079).

### Key Constraints
- Config is `LocalServerConfig` (lightweight dataclass), NOT `MCPServerConfig` (server-side, depends on auth enums)
- No aiohttp, no OAuth imports
- All logging via `self.logger = logging.getLogger(f"MCPServer.{config.name}")`

---

## Acceptance Criteria

- [ ] `from parrot.mcp.server_base import MCPServerBase, LocalServerConfig` works
- [ ] `MCPServerBase` is abstract (cannot instantiate directly)
- [ ] `register_tool()` creates `MCPToolAdapter` and stores it
- [ ] `handle_initialize()` returns correct protocol version and capabilities
- [ ] `handle_tools_list()` returns registered tool definitions
- [ ] `handle_tools_call()` dispatches to the correct adapter
- [ ] `handle_tools_call()` raises for unknown tool names
- [ ] Tests pass: `pytest packages/ai-parrot/tests/mcp/test_server_base.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/mcp/test_server_base.py
import pytest
from parrot.mcp.server_base import MCPServerBase, LocalServerConfig
from parrot.mcp.adapter import MCPToolAdapter

# Use EchoTool from TASK-2076 test pattern

class ConcreteMCPServer(MCPServerBase):
    async def start(self): pass
    async def stop(self): pass

class TestMCPServerBase:
    def test_register_tool(self):
        server = ConcreteMCPServer(LocalServerConfig(name="test"))
        server.register_tool(EchoTool())
        assert "echo" in server.tools

    @pytest.mark.asyncio
    async def test_handle_initialize(self):
        server = ConcreteMCPServer(LocalServerConfig(name="test", version="1.0"))
        result = await server.handle_initialize({})
        assert result["protocolVersion"] == "2024-11-05"
        assert result["serverInfo"]["name"] == "test"

    @pytest.mark.asyncio
    async def test_handle_tools_list(self):
        server = ConcreteMCPServer(LocalServerConfig())
        server.register_tool(EchoTool())
        result = await server.handle_tools_list({})
        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "echo"

    @pytest.mark.asyncio
    async def test_handle_tools_call(self):
        server = ConcreteMCPServer(LocalServerConfig())
        server.register_tool(EchoTool())
        result = await server.handle_tools_call({"name": "echo", "arguments": {"text": "hi"}})
        assert result["isError"] is False

    @pytest.mark.asyncio
    async def test_handle_tools_call_unknown(self):
        server = ConcreteMCPServer(LocalServerConfig())
        with pytest.raises(RuntimeError, match="Tool not found"):
            await server.handle_tools_call({"name": "nope", "arguments": {}})
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2076 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports and signatures still match
4. **Update status** in `sdd/tasks/index/mcp-local-server-wikitoolkit.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2077-mcp-server-base.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-03
**Notes**: Created `LocalServerConfig` dataclass and `MCPServerBase(ABC)` in
`packages/ai-parrot/src/parrot/mcp/server_base.py`, extracting only the
universal part of the server's `MCPServerBase` (registration + JSON-RPC
handlers). Deliberately dropped `allowed_tools`/`blocked_tools` filtering,
`self.resources`, and all auth wiring per the task's contract — those stay
in the server's future `RemoteMCPServerBase` (TASK-2079). All 5 unit tests
pass; `ruff check` clean.

**Deviations from spec**: none.
