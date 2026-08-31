# TASK-2599: `@mcp_tool` decorator + declaration model

**Feature**: FEAT-477 — Expose an AI-Parrot Agent as an MCP Server
**Spec**: `sdd/specs/mcp-as-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the declaration half of spec §3 **Module 1**. This is the head of the
dependency graph: TASK-2600 (reification), TASK-2602 (mount) and TASK-2607 (job handles)
all build on it.

Spec §2 Overview #3: *having at least one decorated method **is** the opt-in* — there is
no `expose_as_mcp` flag and no server-side allowlist.

Spec goal **G9**: the decorator must be importable from core `ai-parrot` with **no extras
installed**, so an agent can declare its MCP surface without depending on
`ai-parrot-server`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/mcp/agent_tools.py` (core distribution).
- Implement the `MCPToolDeclaration` Pydantic model exactly as specified in §2 Data Models.
- Implement the `mcp_tool(...)` decorator. It **marks only** — it attaches the declaration
  to the function object and returns it unchanged. Reification is TASK-2600's job.
- Enforce mandatory fields: `name`, `description`, `args_schema`, `returns`, `scope`.
  **No schema inference in v1** (spec §1 Non-Goals). Missing any field is a loud failure.
- Validate that the decorated callable is `async`; a sync method is an error.
- Error messages must name the **agent class and method** so the failure is actionable
  (spec §2 Edge Cases: *"fail at configure time with the agent name and method in the
  message. Never silently skip."*).
- Unit tests per the Test Specification below.

**NOT in scope**: `AgentMethodTool`, the configure-time scan, the exposure set, or any
`routing_meta` mapping — all TASK-2600. Any `ai-parrot-server` import. Any mount code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/agent_tools.py` | CREATE | `MCPToolDeclaration` + `mcp_tool` decorator |
| `packages/ai-parrot/src/parrot/mcp/__init__.py` | MODIFY | Export `mcp_tool`, `MCPToolDeclaration` |
| `packages/ai-parrot/tests/mcp/test_agent_tools.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against `dev` on 2026-08-31 (post PR #1274). Use these exact
> imports and signatures. Do NOT invent alternatives.

### Verified Imports
```python
# core only — this module must NOT import anything from ai-parrot-server (G9)
from parrot.tools.abstract import AbstractTool, ToolResult
from pydantic import BaseModel, Field
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool:
    name: str = None                              # :296
    args_schema: Type[BaseModel] = AbstractToolArgsSchema   # :298
    routing_meta: Dict = None                     # declared :300, set per-instance :373
    def __init__(self, ..., routing_meta: Optional[Dict] = None, ...)  # :342

# packages/ai-parrot/src/parrot/mcp/adapter.py
class MCPToolAdapter:                             # :8
    # :10-18 docstring — honors routing_meta["requires_confirmation"] by injecting a
    # required `confirm` boolean into inputSchema and rejecting unconfirmed calls.
    # This is the EXISTING precedent for carrying MCP metadata on a tool.
```

### Does NOT Exist
- ~~`@mcp_tool` / `def mcp_tool`~~ — you are creating it. `grep -rn "def mcp_tool" packages/` is empty.
- ~~`MCPToolSpec`~~ — a prior draft's name. The model is `MCPToolDeclaration`.
- ~~`parrot.interfaces.mcp`~~ — `parrot/interfaces/` exists but has no `mcp.py`.
- ~~`AgentMethodTool`~~ — created in TASK-2600, not here.
- ~~Schema inference from a method signature~~ — explicitly out of scope in v1.

---

## Implementation Notes

### Pattern to Follow
Attach the declaration to the function as a dunder attribute so TASK-2600's scan can find
it by `getattr`. Keep the decorator a pure marker — no registry, no global state:

```python
MCP_TOOL_ATTR = "__mcp_tool_declaration__"

def mcp_tool(*, name: str, description: str, args_schema: Type[BaseModel],
             returns: Type[BaseModel], scope: str, read_only_hint: bool = False,
             idempotent_hint: bool = False, requires_confirmation: bool = False,
             max_result_tokens: int | None = None):
    def decorator(fn):
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"@mcp_tool requires an async method: {fn.__qualname__}")
        setattr(fn, MCP_TOOL_ATTR, MCPToolDeclaration(...))
        return fn
    return decorator
```

### Key Constraints
- Core-only imports (G9). A `from parrot.mcp.transports...` import here is a bug.
- Pydantic v2 models; `args_schema` / `returns` are `Type[BaseModel]`, validate with
  `arbitrary_types_allowed` or a field validator asserting `issubclass(..., BaseModel)`.
- Google-style docstrings and strict type hints throughout.
- Raise at **decoration** time for the async check and for a non-`BaseModel` schema; the
  agent-name-qualified error surfaces at configure time (TASK-2600).

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/adapter.py:8` — how `routing_meta` already carries MCP metadata
- `packages/ai-parrot/src/parrot/tools/abstract.py:342` — `routing_meta` constructor arg

---

## Acceptance Criteria

- [ ] `MCPToolDeclaration` matches spec §2 Data Models field-for-field
- [ ] Omitting any of `name`/`description`/`args_schema`/`returns`/`scope` raises
- [ ] Decorating a sync method raises `TypeError` naming the method
- [ ] A non-`BaseModel` `args_schema` or `returns` raises
- [ ] The decorator returns the function unchanged (still callable/awaitable as before)
- [ ] `from parrot.mcp.agent_tools import mcp_tool` works with **core only** (G9)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/mcp/test_agent_tools.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/mcp/agent_tools.py`

---

## Test Specification

```python
import pytest
from pydantic import BaseModel
from parrot.mcp.agent_tools import mcp_tool, MCPToolDeclaration, MCP_TOOL_ATTR


class Args(BaseModel):
    q: str

class Ret(BaseModel):
    ok: bool


class TestMcpToolDecorator:
    def test_marks_function_with_declaration(self):
        @mcp_tool(name="f", description="d", args_schema=Args, returns=Ret, scope="s")
        async def f(self, q: str): ...
        decl = getattr(f, MCP_TOOL_ATTR)
        assert isinstance(decl, MCPToolDeclaration)
        assert decl.name == "f" and decl.scope == "s"

    def test_rejects_sync_method(self):
        with pytest.raises(TypeError, match="async"):
            @mcp_tool(name="f", description="d", args_schema=Args, returns=Ret, scope="s")
            def f(self): ...

    @pytest.mark.parametrize("missing", ["name", "description", "args_schema", "returns", "scope"])
    def test_every_field_is_mandatory(self, missing):
        kwargs = dict(name="f", description="d", args_schema=Args, returns=Ret, scope="s")
        kwargs.pop(missing)
        with pytest.raises(TypeError):
            mcp_tool(**kwargs)

    def test_rejects_non_basemodel_schema(self):
        with pytest.raises((TypeError, ValueError)):
            @mcp_tool(name="f", description="d", args_schema=dict, returns=Ret, scope="s")
            async def f(self): ...

    def test_annotation_defaults(self):
        @mcp_tool(name="f", description="d", args_schema=Args, returns=Ret, scope="s")
        async def f(self): ...
        decl = getattr(f, MCP_TOOL_ATTR)
        assert decl.read_only_hint is False and decl.idempotent_hint is False
        assert decl.requires_confirmation is False and decl.max_result_tokens is None
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/mcp-as-agent.spec.md` — §2 Data Models and §3 Module 1.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** before writing code.
4. **Update status** in `sdd/tasks/index/mcp-as-agent.json` → `"in-progress"`.
5. **Implement** per scope.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
