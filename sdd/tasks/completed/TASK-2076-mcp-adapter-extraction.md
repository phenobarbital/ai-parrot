# TASK-2076: Extract MCPToolAdapter + MCPResource to core

**Feature**: FEAT-403 — MCP Local Server Core + WikiToolkit MCP
**Spec**: `sdd/specs/mcp-local-server-wikitoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

MCPToolAdapter and MCPResource currently live in ai-parrot-server but have
zero external dependencies beyond core's AbstractTool and ToolResult. Moving
them to core is the foundation for the entire local MCP server hierarchy —
every subsequent task depends on these being importable from core.

Implements spec Module 1.

---

## Scope

- Copy `MCPToolAdapter` from `packages/ai-parrot-server/src/parrot/mcp/adapter.py` to `packages/ai-parrot/src/parrot/mcp/adapter.py`
- Copy `MCPResource` from `packages/ai-parrot-server/src/parrot/mcp/resources.py` to `packages/ai-parrot/src/parrot/mcp/resources.py`
- Replace server's `adapter.py` with a shim that re-exports from core
- Replace server's `resources.py` with a shim that re-exports from core
- Write unit tests for the adapter in core

**NOT in scope**: MCPServerBase, StdioMCPServer, or any transport code (those are TASK-2077/2078).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/adapter.py` | CREATE | MCPToolAdapter moved from server |
| `packages/ai-parrot/src/parrot/mcp/resources.py` | CREATE | MCPResource moved from server |
| `packages/ai-parrot-server/src/parrot/mcp/adapter.py` | MODIFY | Replace with shim re-export |
| `packages/ai-parrot-server/src/parrot/mcp/resources.py` | MODIFY | Replace with shim re-export |
| `packages/ai-parrot/tests/mcp/test_adapter.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Core — tools (these are what the adapter depends on)
from parrot.tools.abstract import AbstractTool, ToolResult  # verified: packages/ai-parrot/src/parrot/tools/abstract.py:233,198

# Core — MCP __init__.py uses extend_path for namespace merging
# verified: packages/ai-parrot/src/parrot/mcp/__init__.py:2-3
from pkgutil import extend_path
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/mcp/adapter.py — FULL FILE to move
class MCPToolAdapter:  # line 7
    def __init__(self, tool: AbstractTool)  # line 10
    def to_mcp_tool_definition(self) -> Dict[str, Any]  # line 14
    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]  # line 32
    def _toolresult_to_mcp(self, result: ToolResult) -> Dict[str, Any]  # line 65

# packages/ai-parrot-server/src/parrot/mcp/resources.py — FULL FILE to move
@dataclass
class MCPResource:  # line 5
    uri: str; name: str; description: Optional[str]; mime_type: Optional[str]
    def to_dict(self) -> dict[str, Any]  # line 16

# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):  # line 233
    name: str = None  # line 248
    description: str = None  # line 249
    args_schema: Type[BaseModel] = AbstractToolArgsSchema  # line 250
    async def _execute(self, **kwargs) -> Any:  # line 471

class ToolResult(BaseModel):  # line 198
    success: bool  # line 200
    status: str = "success"  # line 201
    result: Any  # line 202
    error: Optional[str] = None  # line 203
    metadata: Dict[str, Any]  # line 204
```

### Consumers of adapter/resources in server (shim must cover)
```
transports/base.py:9   — from parrot.mcp.adapter import MCPToolAdapter
transports/base.py:11  — from parrot.mcp.resources import MCPResource
simple_server.py:17    — from parrot.mcp.resources import MCPResource
```

### Does NOT Exist
- ~~`parrot.mcp.adapter` in core~~ — does not exist yet; this task creates it
- ~~`parrot.mcp.resources` in core~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow
The adapter and resource files are self-contained — move them verbatim.
The only import they need from core is `AbstractTool` and `ToolResult`.

### Shim Pattern
```python
# packages/ai-parrot-server/src/parrot/mcp/adapter.py (after)
"""Shim — MCPToolAdapter moved to core in FEAT-403."""
from parrot.mcp.adapter import MCPToolAdapter  # noqa: F401
__all__ = ["MCPToolAdapter"]
```

### Key Constraints
- The core `adapter.py` and `resources.py` file names intentionally collide
  with server files — PEP 420 `extend_path` resolves core first.
- The shim in server must re-export the same names so existing `from parrot.mcp.adapter import MCPToolAdapter` still works.
- Zero external dependencies — only stdlib + core's AbstractTool/ToolResult.

---

## Acceptance Criteria

- [ ] `from parrot.mcp.adapter import MCPToolAdapter` resolves to core
- [ ] `from parrot.mcp.resources import MCPResource` resolves to core
- [ ] Server shims re-export correctly (no ImportError)
- [ ] Existing server code that imports from `parrot.mcp.adapter` still works
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/mcp/test_adapter.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/mcp/adapter.py packages/ai-parrot/src/parrot/mcp/resources.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/mcp/test_adapter.py
import pytest
from pydantic import BaseModel, Field
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.mcp.adapter import MCPToolAdapter
from parrot.mcp.resources import MCPResource


class EchoInput(BaseModel):
    text: str = Field(..., description="Text to echo")

class EchoTool(AbstractTool):
    name = "echo"
    description = "Echo input back"
    args_schema = EchoInput
    async def _execute(self, text: str) -> str:
        return text


class TestMCPToolAdapter:
    def test_to_mcp_definition(self):
        adapter = MCPToolAdapter(EchoTool())
        defn = adapter.to_mcp_tool_definition()
        assert defn["name"] == "echo"
        assert defn["description"] == "Echo input back"
        assert "properties" in defn["inputSchema"]

    @pytest.mark.asyncio
    async def test_execute_success(self):
        adapter = MCPToolAdapter(EchoTool())
        result = await adapter.execute({"text": "hello"})
        assert result["isError"] is False
        assert any("hello" in c["text"] for c in result["content"])

    @pytest.mark.asyncio
    async def test_execute_error(self):
        class FailTool(AbstractTool):
            name = "fail"
            description = "Always fails"
            args_schema = EchoInput
            async def _execute(self, **kwargs):
                raise ValueError("boom")
        adapter = MCPToolAdapter(FailTool())
        result = await adapter.execute({"text": "x"})
        assert result["isError"] is True


class TestMCPResource:
    def test_to_dict(self):
        r = MCPResource(uri="file:///test", name="test", description="A test")
        d = r.to_dict()
        assert d["uri"] == "file:///test"
        assert d["name"] == "test"
        assert d["description"] == "A test"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm imports and signatures still match
4. **Update status** in `sdd/tasks/index/mcp-local-server-wikitoolkit.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2076-mcp-adapter-extraction.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-03
**Notes**: `MCPToolAdapter` and `MCPResource` moved verbatim to
`packages/ai-parrot/src/parrot/mcp/{adapter,resources}.py`. Server files
replaced with re-export shims. Added `# noqa: BLE001` on the two
intentional blind-except blocks in the adapter (matches existing repo
convention, e.g. `parrot/auth/oauth2_routes.py`) to satisfy the task's
lint acceptance criterion — behavior unchanged from the original file.
Ran `ruff check --fix` for import sorting/typing-syntax modernization
(`Dict`→`dict`, `Optional[X]`→`X | None`) on the new core files only;
content is otherwise a verbatim move. Verified existing consumers
(`transports/base.py`, `transports/stdio.py`) still import fine through
the shim. All 4 unit tests pass; `ruff check` clean on all 4
create/modify files.

**Deviations from spec**: none — content matches the task's Codebase
Contract exactly; only cosmetic lint fixes applied to the new core copies.
