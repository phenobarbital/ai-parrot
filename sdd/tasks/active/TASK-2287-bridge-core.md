# TASK-2287: ClaudeAgentToolBridge — tool → SdkMcpTool conversion and in-process handlers

**Feature**: FEAT-434 — Claude Agent Tool Bridge
**Spec**: `sdd/specs/claude-agent-tool-bridge.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1 — the heart of FEAT-434. Converts the live
`ToolManager`'s tools into `claude_agent_sdk.SdkMcpTool` objects grouped into a
single in-process `McpSdkServerConfig`, with handlers that execute **inside the
daemon's own event loop** so tools keep their open connections, auth context,
`working_memory` and toolkit lifecycle.

The single rule that makes the security model work: handlers dispatch through
`ToolManager.execute_tool()`, never `tool.execute()`. That inherits the
TOOL_CALL guardrails (FEAT-406) → `GrantGuard` (FEAT-211) → `ConfirmationGuard`
(FEAT-235) → `tool.execute()` → compression (FEAT-380) chain for free.

---

## Scope

- Create `ClaudeAgentToolBridge` with `__init__(tool_manager, *, namespace="parrot", tool_timeout=None)`.
- `build_server(tools) -> McpSdkServerConfig`: per tool, produce an `SdkMcpTool`
  whose `name`/`description` come from the tool and whose `input_schema` comes
  from `MCPToolAdapter.to_mcp_tool_definition()`.
- **Strip the `confirm` property** from the schema on this path. The adapter
  injects a required `confirm: boolean` because stdio has no HITL channel; in
  process the real `ConfirmationGuard` runs instead, and the sub-agent must not
  be handed a switch it can flip itself.
- Handler closure per tool: `await tool_manager.execute_tool(name, params, ctx)`,
  bounded by `tool_timeout`, converting the `ToolResult` through
  `MCPToolAdapter._toolresult_to_mcp()`.
- Map every failure mode — tool exception, timeout, HITL denial, HITL timeout —
  to a **recoverable MCP error result**. Never raise out of the handler; never
  abort the turn.
- Skip (with a warning) any tool whose schema cannot be extracted, rather than
  failing the whole run.
- `exposed_names() -> list[str]` returning `mcp__<namespace>__<tool>` names.
- Keep the SDK import **strictly lazy** (inside methods), mirroring
  `claude_agent.py`'s `_import_sdk()` contract.
- Write unit tests.

**NOT in scope**: `ClaudeAgentRunOptions` fields and `_build_options()` injection
(TASK-2288); the narrowing/`select()` path (TASK-2289); the HITL channel override
(TASK-2290); caller identity (TASK-2286 — accept a `PermissionContext` parameter
and let the caller supply it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/claude_agent_bridge.py` | CREATE | `ClaudeAgentToolBridge` |
| `tests/clients/test_claude_agent_bridge.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.adapter import MCPToolAdapter          # verified: parrot/mcp/adapter.py:8
from parrot.tools.manager import ToolManager           # verified: parrot/tools/manager.py
from parrot.tools.abstract import AbstractTool, ToolResult   # verified: parrot/tools/abstract.py:234, :199
from parrot.auth.permission import PermissionContext   # verified: parrot/auth/permission.py:81
# LAZY, inside methods only:
from claude_agent_sdk import create_sdk_mcp_server, SdkMcpTool, McpSdkServerConfig
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/adapter.py
class MCPToolAdapter:                                          # line 8
    def __init__(self, tool: AbstractTool): ...                 # line 19
    def _requires_confirmation(self) -> bool: ...               # line 23
    def to_mcp_tool_definition(self) -> dict[str, Any]: ...     # line 27
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]: ...  # line 59
    def _toolresult_to_mcp(self, result: ToolResult) -> dict[str, Any]: ...    # line 108
# to_mcp_tool_definition() injects a REQUIRED `confirm: boolean` into
# input_schema["properties"] when routing_meta["requires_confirmation"] is set,
# and its execute() rejects the call unless confirm=true. On schema-extraction
# failure it degrades to {"type": "object", "properties": {}} with a warning.

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    async def execute_tool(
        self, tool_name: str, parameters: Dict[str, Any],
        permission_context: Optional["PermissionContext"] = None,
    ) -> Any: ...                                               # line 1431
    #   Returns ToolResult(success=False, status='not_found', ...) for an
    #   unknown tool name (line 1452) rather than raising.
    #   Pipeline: TOOL_CALL guardrails (FEAT-406) -> GrantGuard (FEAT-211)
    #   -> ConfirmationGuard (FEAT-235) -> tool.execute() -> compression (FEAT-380)
    def get_all_tools(self) -> List[Union[ToolDefinition, AbstractTool]]: ...  # line 1155
    def get_tool(self, tool_name: str) -> Optional[Any]: ...    # line 1127

# packages/ai-parrot/src/parrot/tools/abstract.py
class ToolResult(BaseModel):                                    # line 199
    success: bool = True; status: str = "success"; result: Any
    error: Optional[str] = None; metadata: Dict[str, Any] = {}
    timestamp: str; files: Optional[list] = []; images: Optional[list] = []
    voice_text: Optional[str] = None; display_data: Optional[Dict[str, Any]] = None
class AbstractTool(EventEmitterMixin, ABC):                     # line 234
    name: str = None; description: str = None                   # lines 249-250
    args_schema: Type[BaseModel] = AbstractToolArgsSchema        # line 251
    routing_meta: Dict = None                                   # line 253

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    confirming_tools: frozenset = frozenset()                   # line 285
    async def _ensure_open(self) -> None: ...                    # line 417
    # line 681: methods in confirming_tools get
    #   tool.routing_meta["requires_confirmation"] = True

# claude-agent-sdk 0.2.140 — verified signatures
create_sdk_mcp_server(name: str, version: str = '1.0.0',
                      tools: list[SdkMcpTool[Any]] | None = None) -> McpSdkServerConfig
# SdkMcpTool dataclass fields: name, description, input_schema, handler, annotations
#   input_schema accepts a plain dict -> the adapter's JSON schema passes through.
#   handler signature: Callable[[Any], Awaitable[dict[str, Any]]]
# McpSdkServerConfig = TypedDict{type: Literal['sdk'], name: str, instance: McpServer}
```

### Working reference (PoC that ran successfully)
```python
# The shape to reproduce, verified end to end against this repo:
@sdk_tool("inventory_level", "Current inventory level for a SKU", {"sku": str})
async def _bridged(args):
    return {"content": [{"type": "text", "text": str(...)}]}
server = create_sdk_mcp_server(name="parrot", version="0.1.0", tools=[_bridged])
# sub-agent then calls it as: mcp__parrot__inventory_level
```

### ⚠ Two test trees — migration residue, check before you write

`ai-parrot` was a single package with its tests at the repo root, then became a
uv monorepo; many tests were **copied or moved** into `packages/*/tests/` and the
originals were left in place. So a given module can exist in BOTH trees, and
**which copy is authoritative differs per file** — the monorepo path is not
automatically the current one.

For this feature specifically:

| Path | Status |
|---|---|
| `tests/clients/test_claude_agent.py` | **Canonical.** 15 test functions / 20 cases, `test_claude_agent_live_smoke` at line 378, last touched 2026-08-20. Extend this one. |
| `packages/ai-parrot/tests/clients/test_claude_agent.py` | Separate, older module (2026-04-27, 8 tests): `TestExtendedRunOptions`, `TestBuildOptionsForwardsExtensions`. Still tracked, still runs. Do not break it. |
| `packages/ai-parrot/tests/test_toolmanager_*.py` | Where `ToolManager` tests live (flat, not under `tests/tools/`) — e.g. `test_toolmanager_confirmation.py`, `test_toolmanager_load_tool.py`. |
| `packages/ai-parrot-integrations/tests/agentd/` | Where agentd tests live. Unambiguous — no root duplicate. |
| `tests/integration/` | Root integration tree; exists and is where the live tests go. |

**Before creating or editing a test file**, check whether a same-named module
exists in the other tree (`git ls-files | grep <name>`) and compare mtimes /
content. Editing the stale copy leaves the real suite untouched and the task
looks green while nothing was verified.

### Does NOT Exist
- ~~`ToolManager.to_sdk_mcp_server()`~~ / ~~`.as_mcp_server()`~~ /
  ~~`.to_mcp_server()`~~ / ~~`.sdk_mcp_server`~~ — no ToolManager→MCP factory
  of any name exists.
- ~~`parrot.mcp.adapter.MCPToolkitAdapter`~~ — only the per-tool
  `MCPToolAdapter` exists; there is no toolkit-level adapter.
- `MCPToolAdapter` and `create_sdk_mcp_server` are **not referenced anywhere** in
  `parrot/clients/claude_agent.py` (grep: 0). Nothing is wired today.
- **`ToolManager.get_tools()` is mis-annotated**: declared `-> Dict[str, Any]`
  (manager.py:1151) but returns `self._tools.values()`. Use `get_all_tools()`.
- ~~`ClaudeAgentRunOptions.tool_timeout`~~ — not a field yet (TASK-2288 adds it);
  this task takes `tool_timeout` as a constructor argument.
- ~~`MCPToolAdapter.to_sdk_mcp_tool()`~~ — does not exist; conversion lives in
  this new module, and the adapter must **not** be forked or edited.

---

## Implementation Notes

### Key Constraints
- **Never call `tool.execute()` directly.** Dispatch only through
  `ToolManager.execute_tool()` — this is an acceptance criterion asserted by test.
- **Reuse `MCPToolAdapter`, do not fork or modify it.** The stdio proxy
  (`parrot mcp-serve`) depends on its current behaviour including the `confirm`
  shim. The `confirm`-property removal is post-processing on the bridge side: copy
  the schema dict, drop the `confirm` key from `properties`, and drop it from
  `required` if listed.
- `import parrot.clients.claude_agent_bridge` MUST succeed without the
  `[claude-agent]` extra installed. Follow `claude_agent.py`'s `_import_sdk()`
  pattern — no SDK import at module scope, not even under `TYPE_CHECKING` in a way
  that executes.
- `execute_tool()` returns a `ToolResult` for a not-found tool rather than
  raising — handle both shapes.
- Use `asyncio.wait_for` for `tool_timeout`; a genuinely blocking tool belongs in
  `asyncio.to_thread`, which is the tool author's responsibility but worth a
  docstring note.
- Google-style docstrings, strict type hints, `self.logger` (CLAUDE.md).

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/claude_agent.py:377` — `_collect_messages`, for the lazy-SDK pattern
- `packages/ai-parrot/src/parrot/mcp/adapter.py:59` — the adapter's own `execute()`, for how it maps results and errors
- `packages/ai-parrot-integrations/src/parrot/integrations/agentd/mcp_server.py` — the stdio proxy, the other consumer of the adapter (must not regress)

---

## Acceptance Criteria

- [ ] `build_server()` returns an `McpSdkServerConfig` with one `SdkMcpTool` per input tool
- [ ] `input_schema` comes from `MCPToolAdapter.to_mcp_tool_definition()`
- [ ] The `confirm` property is absent from every produced schema (properties AND required)
- [ ] `MCPToolAdapter` itself is unmodified — the stdio proxy's schemas still contain `confirm`
- [ ] Handlers dispatch through `ToolManager.execute_tool()`; no code path calls `tool.execute()` — asserted by test
- [ ] A successful call returns MCP content built by `_toolresult_to_mcp()`
- [ ] Tool exception → recoverable MCP error result, no raise
- [ ] Timeout → recoverable MCP error result naming the tool, no raise
- [ ] HITL denial → recoverable MCP error result, no raise
- [ ] A tool whose schema cannot be extracted is skipped with a warning; others still exposed
- [ ] `exposed_names()` returns `mcp__<namespace>__<tool>` strings
- [ ] `import parrot.clients.claude_agent_bridge` succeeds without `claude_agent_sdk`
- [ ] All tests pass: `pytest tests/clients/test_claude_agent_bridge.py -v`
- [ ] `pytest tests/clients/test_claude_agent.py -v` still 20 passed
- [ ] No new `ruff check` findings

---

## Test Specification

```python
# tests/clients/test_claude_agent_bridge.py
import pytest


class TestServerAssembly:
    def test_tool_becomes_sdk_mcp_tool_with_adapter_schema(self): ...
    def test_confirm_property_stripped_from_properties_and_required(self): ...
    def test_adapter_not_mutated_stdio_schema_keeps_confirm(self): ...
    def test_schema_extraction_failure_skips_only_that_tool(self): ...
    def test_exposed_names_use_mcp_ns_prefix(self): ...

class TestHandlerDispatch:
    async def test_handler_dispatches_through_execute_tool(self, monkeypatch): ...
    async def test_handler_never_calls_tool_execute_directly(self, monkeypatch): ...
    async def test_handler_maps_toolresult_to_mcp_content(self): ...
    async def test_permission_context_forwarded(self): ...

class TestRecoverableFailures:
    async def test_tool_error_becomes_error_result(self): ...
    async def test_timeout_becomes_error_result(self): ...
    async def test_hitl_denial_becomes_error_result(self): ...
    async def test_handler_never_raises(self): ...

class TestLazyImport:
    def test_module_imports_without_sdk(self, monkeypatch): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/claude-agent-tool-bridge.json` → `"in-progress"`
5. **Implement** following the scope above
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
