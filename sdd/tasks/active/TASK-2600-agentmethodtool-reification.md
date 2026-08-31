# TASK-2600: `AgentMethodTool` reification + exposure set

**Feature**: FEAT-477 — Expose an AI-Parrot Agent as an MCP Server
**Spec**: `sdd/specs/mcp-as-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2599
**Assigned-to**: unassigned

---

## Context

Implements the reification half of spec §3 **Module 1** — the heart of Option D. A
`@mcp_tool`-marked method is turned into a real `AbstractTool` so that `MCPToolAdapter`,
`RemoteMCPServerBase.register_tool()` and `A2AServer._build_skills_from_tools()` all work
on it with **zero new code**.

**This task owns the single most important invariant in the feature (spec OQ2):** a
reified method is placed in a separate *exposure set* and is **NEVER registered into the
owning agent's `ToolManager`**. Decorating a method changes what MCP clients can call and
**nothing else** — it does not make the method LLM-callable inside its own agent.

---

## Scope

- Implement `AgentMethodTool(AbstractTool)` in
  `packages/ai-parrot/src/parrot/mcp/agent_tools.py`: `name`, `description` and
  `args_schema` come from the `MCPToolDeclaration`; `_execute()` invokes the bound method.
- Map declaration annotations onto `routing_meta` (spec OQ7): `requires_confirmation`
  rides `routing_meta["requires_confirmation"]` (the channel `MCPToolAdapter` already
  reads); `read_only_hint` / `idempotent_hint` are carried explicitly.
- Implement the configure-time scan that walks an agent instance for `MCP_TOOL_ATTR`
  markers and builds its **exposure set**.
- Fail loudly at configure time on: a name colliding with an existing tool, a duplicate
  decorated name within one agent, or a method whose declaration is malformed. The message
  must name the agent and the method.
- Hold the agent by **weak reference** so `AgentMethodTool` never drags the agent into
  tool-serialization paths (spec §7 Risks).
- Unit tests, including the merge-blocking OQ2 assertion.

**NOT in scope**: mounting, endpoints, PBAC, identity, job handles. The exposure set is
built and returned here; consuming it is TASK-2602's job.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/agent_tools.py` | MODIFY | Add `AgentMethodTool` + `build_exposure_set()` |
| `packages/ai-parrot/src/parrot/mcp/__init__.py` | MODIFY | Export `AgentMethodTool`, `build_exposure_set` |
| `packages/ai-parrot/tests/mcp/test_agent_tools.py` | MODIFY | Reification + OQ2 invariant tests |

---

## Codebase Contract (Anti-Hallucination)

> VERIFIED against `dev` on 2026-08-31 (post PR #1274).

### Verified Imports
```python
# core only (G9)
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.mcp.agent_tools import MCPToolDeclaration, MCP_TOOL_ATTR   # TASK-2599
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool:
    name: str = None                                        # :296
    args_schema: Type[BaseModel] = AbstractToolArgsSchema    # :298
    routing_meta: Dict = None                                # declared :300, per-instance :373
    def __init__(self, ..., routing_meta: Optional[Dict] = None, ...)   # :342

# packages/ai-parrot/src/parrot/mcp/adapter.py
class MCPToolAdapter:                                        # :8
    def __init__(self, tool: AbstractTool)                   # :19
    def _requires_confirmation(self) -> bool                 # :23  reads routing_meta
    def to_mcp_tool_definition(self) -> dict[str, Any]       # :27
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]   # :59
    def _toolresult_to_mcp(self, result: ToolResult) -> dict[str, Any]     # :108

# packages/ai-parrot/src/parrot/bots/abstract.py
self.tool_manager: ToolManager = ToolManager(...)            # :386   <-- MUST NOT be touched

# packages/ai-parrot/src/parrot/tools/manager.py
def get_tool(self, tool_name: str) -> Optional[Any]          # :1231
def list_tools(self) -> List[str]                            # :1251
def tool_count(self) -> int                                  # :2053
```

### Does NOT Exist
- ~~`AgentMethodTool`~~ — you are creating it.
- ~~`AgentMethodAdapter`~~ — Option A's design; **rejected**. Reuse `MCPToolAdapter` as-is.
- ~~`ToolManager.register_exposure_set()`~~ — no such method. The exposure set is NOT a
  `ToolManager` concept; keep it a separate collection.
- ~~`AbstractTool.mcp_annotations`~~ — not a real attribute. Annotations ride `routing_meta`.

---

## Implementation Notes

### Pattern to Follow
```python
class AgentMethodTool(AbstractTool):
    def __init__(self, agent, method_name: str, declaration: MCPToolDeclaration):
        self._agent_ref = weakref.ref(agent)     # never a strong ref
        self._method_name = method_name
        super().__init__(
            name=declaration.name,
            description=declaration.description,
            routing_meta={
                "requires_confirmation": declaration.requires_confirmation,
                "read_only_hint": declaration.read_only_hint,
                "idempotent_hint": declaration.idempotent_hint,
            },
        )
        self.args_schema = declaration.args_schema

    async def _execute(self, **kwargs) -> ToolResult:
        agent = self._agent_ref()
        if agent is None:
            raise RuntimeError(f"agent for tool {self.name!r} is gone")
        return await getattr(agent, self._method_name)(**kwargs)
```

### Key Constraints
- **OQ2 is non-negotiable.** Do not call `agent.tool_manager.register*` anywhere in this
  task. The test below is a merge blocker.
- Weak reference to the agent — see spec §7 "Bound-method reference cycles".
- Do not resolve the agent at construction time and cache the bound method; resolve per
  call so a reloaded agent is picked up (TASK-2602 depends on this).
- Async throughout; `self.logger` for diagnostics.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/adapter.py:23` — how `routing_meta` is consumed
- `packages/ai-parrot-server/src/parrot/a2a/server.py:425` — `_tool_to_skill` uses
  `args_schema.model_json_schema()`; your `args_schema` must support that

---

## Acceptance Criteria

- [ ] `AgentMethodTool` is a real `AbstractTool` and `MCPToolAdapter(tool)` accepts it
      unmodified
- [ ] `to_mcp_tool_definition()` produces a valid MCP tool definition from it
- [ ] `requires_confirmation=True` produces the adapter's `confirm` injection
- [ ] **OQ2 invariant**: after building the exposure set, no decorated name appears in
      `agent.tool_manager.list_tools()`
- [ ] Duplicate decorated names within one agent fail at configure time, naming the agent
- [ ] A name colliding with an existing registered tool fails at configure time
- [ ] The agent is held weakly (no reference cycle; tool survives agent GC with a clean error)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/mcp/test_agent_tools.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/mcp/agent_tools.py`

---

## Test Specification

```python
class TestReification:
    def test_reified_is_abstracttool_and_adapts(self, exposed_agent):
        tools = build_exposure_set(exposed_agent)
        tool = tools[0]
        assert isinstance(tool, AbstractTool)
        defn = MCPToolAdapter(tool).to_mcp_tool_definition()
        assert defn["name"] == tool.name and "inputSchema" in defn

    def test_reified_tool_not_in_tool_manager(self, exposed_agent):
        """OQ2 INVARIANT — merge blocker. Decorating exposes over MCP and nothing else."""
        before = set(exposed_agent.tool_manager.list_tools())
        tools = build_exposure_set(exposed_agent)
        after = set(exposed_agent.tool_manager.list_tools())
        assert after == before
        assert {t.name for t in tools}.isdisjoint(after)

    def test_annotations_map_to_routing_meta(self, exposed_agent):
        tool = build_exposure_set(exposed_agent)[0]
        assert "requires_confirmation" in tool.routing_meta
        assert "read_only_hint" in tool.routing_meta

    async def test_execute_calls_bound_method(self, exposed_agent):
        tool = build_exposure_set(exposed_agent)[0]
        result = await tool._execute(q="x")
        assert result is not None

    def test_duplicate_name_fails_with_agent_in_message(self, agent_with_dup_names):
        with pytest.raises(ValueError, match=r"(?s)agent.*method"):
            build_exposure_set(agent_with_dup_names)

    def test_agent_held_weakly(self):
        agent = make_agent(); tool = build_exposure_set(agent)[0]
        ref = weakref.ref(agent); del agent; gc.collect()
        assert ref() is None
```

---

## Agent Instructions

1. **Read the spec** — §2 Overview #1, §3 Module 1, §7 Risks, and OQ2 in §8.
2. **Check dependencies** — TASK-2599 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing code.
4. **Update status** in `sdd/tasks/index/mcp-as-agent.json` → `"in-progress"`.
5. **Implement** per scope. Do NOT touch `tool_manager`.
6. **Verify** all acceptance criteria — especially the OQ2 test.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
