# TASK-747: AbstractToolkit Lifecycle Hooks (_pre_execute / _post_execute)

**Feature**: FEAT-107 — Jira OAuth 2.0 (3LO) Per-User Authentication
**Spec**: `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of the spec. The entire OAuth feature depends on toolkits being able to run pre-execution logic (credential resolution, authorization checks). Currently `ToolkitTool._execute()` calls `self.bound_method(**kwargs)` directly with no hooks. This task adds `_pre_execute()` and `_post_execute()` lifecycle hooks to `AbstractToolkit` and wires them into `ToolkitTool._execute()`.

These hooks are framework-level primitives reusable by any toolkit, not just Jira.

---

## Scope

- Add `async def _pre_execute(self, tool_name: str, **kwargs) -> None` to `AbstractToolkit` (no-op base).
- Add `async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any` to `AbstractToolkit` (returns result unchanged by default).
- Modify `ToolkitTool._execute()` to:
  1. Resolve the parent toolkit instance from `self.bound_method.__self__`
  2. Call `await toolkit._pre_execute(self.name, **kwargs)` before the bound method
  3. Call `await toolkit._post_execute(self.name, result, **kwargs)` after the bound method
  4. Return the (possibly transformed) result from `_post_execute`
- Write unit tests verifying hooks are called, exceptions propagate, and result transformation works.

**NOT in scope**: `AuthorizationRequired` exception (TASK-748), `PermissionContext.channel` (TASK-749), any Jira-specific logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/toolkit.py` | MODIFY | Add hooks to AbstractToolkit, wire into ToolkitTool._execute() |
| `packages/ai-parrot/tests/unit/test_toolkit_hooks.py` | CREATE | Unit tests for lifecycle hooks |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool  # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:18,140
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema  # verified: packages/ai-parrot/src/parrot/tools/abstract.py:71,23
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:18
class ToolkitTool(AbstractTool):
    def __init__(self, name: str, bound_method: callable, description: str = None, args_schema: Type[BaseModel] = None, **kwargs)
    self.bound_method: callable  # line 41
    async def _execute(self, **kwargs) -> Any:  # line 127
        return await self.bound_method(**kwargs)  # line 137

# packages/ai-parrot/src/parrot/tools/toolkit.py:140
class AbstractToolkit(ABC):
    _tool_cache: Dict[str, ToolkitTool]  # line 208
    _tools_generated: bool  # line 209
    exclude_tools: tuple[str, ...]  # line 177
    tool_prefix: Optional[str] = None  # line 191
    def __init__(self, **kwargs)  # line 196
    async def start(self) -> None  # line 212 — no-op, override in subclasses
    async def stop(self) -> None  # line 219
    async def cleanup(self) -> None  # line 226
    def get_tools(self, ...) -> List[AbstractTool]  # line 233
    def _generate_tools(self) -> None  # line 286
    def _create_tool_from_method(self, name: str, attr: callable) -> ToolkitTool  # exists (auto-generated tools)
```

### Does NOT Exist
- ~~`AbstractToolkit._pre_execute()`~~ — does NOT exist yet (this task creates it)
- ~~`AbstractToolkit._post_execute()`~~ — does NOT exist yet (this task creates it)
- ~~`ToolkitTool.toolkit`~~ — no reference to parent toolkit on ToolkitTool; use `self.bound_method.__self__`

---

## Implementation Notes

### Pattern to Follow
```python
# In AbstractToolkit (add after cleanup method, ~line 231):
async def _pre_execute(self, tool_name: str, **kwargs) -> None:
    """Hook called before every tool execution. Override in subclasses."""
    pass

async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any:
    """Hook called after every tool execution. Override for observability/transformation."""
    return result
```

```python
# In ToolkitTool._execute (replace line 137):
async def _execute(self, **kwargs) -> Any:
    toolkit = self.bound_method.__self__
    if isinstance(toolkit, AbstractToolkit):
        await toolkit._pre_execute(self.name, **kwargs)
    result = await self.bound_method(**kwargs)
    if isinstance(toolkit, AbstractToolkit):
        result = await toolkit._post_execute(self.name, result, **kwargs)
    return result
```

### Key Constraints
- Must be backward compatible — existing toolkits that don't override hooks pay zero cost.
- `_pre_execute` and `_post_execute` must be added to the `_generate_tools` exclusion list (line 298-301) so they are NOT exposed as tools.
- The hooks are async to support I/O operations (credential resolution, metrics).

---

## Acceptance Criteria

- [ ] `AbstractToolkit._pre_execute()` and `_post_execute()` exist as async no-op methods
- [ ] `ToolkitTool._execute()` calls both hooks around the bound method
- [ ] Exceptions from `_pre_execute` propagate to caller (not swallowed)
- [ ] `_post_execute` return value replaces the original result
- [ ] `_pre_execute` and `_post_execute` do NOT appear as tools in `get_tools()`
- [ ] All existing tests still pass (zero regression)
- [ ] New unit tests pass: `pytest packages/ai-parrot/tests/unit/test_toolkit_hooks.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_toolkit_hooks.py
import pytest
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool


class SpyToolkit(AbstractToolkit):
    """Test toolkit that records hook calls."""
    def __init__(self):
        super().__init__()
        self.pre_calls = []
        self.post_calls = []

    async def _pre_execute(self, tool_name, **kwargs):
        self.pre_calls.append((tool_name, kwargs))

    async def _post_execute(self, tool_name, result, **kwargs):
        self.post_calls.append((tool_name, result))
        return result

    async def greet(self, name: str) -> str:
        """Say hello."""
        return f"Hello, {name}"


class RaisingToolkit(AbstractToolkit):
    async def _pre_execute(self, tool_name, **kwargs):
        raise PermissionError("Not authorized")

    async def do_something(self) -> str:
        """Do a thing."""
        return "done"


class TransformToolkit(AbstractToolkit):
    async def _post_execute(self, tool_name, result, **kwargs):
        return f"[transformed] {result}"

    async def compute(self) -> str:
        """Compute."""
        return "raw"


class TestLifecycleHooks:
    @pytest.mark.asyncio
    async def test_pre_execute_called_before_tool(self):
        tk = SpyToolkit()
        tools = tk.get_tools()
        greet_tool = [t for t in tools if t.name == "greet"][0]
        await greet_tool._execute(name="World")
        assert len(tk.pre_calls) == 1
        assert tk.pre_calls[0][0] == "greet"

    @pytest.mark.asyncio
    async def test_post_execute_called_after_tool(self):
        tk = SpyToolkit()
        tools = tk.get_tools()
        greet_tool = [t for t in tools if t.name == "greet"][0]
        result = await greet_tool._execute(name="World")
        assert result == "Hello, World"
        assert len(tk.post_calls) == 1

    @pytest.mark.asyncio
    async def test_pre_execute_exception_propagates(self):
        tk = RaisingToolkit()
        tools = tk.get_tools()
        tool = [t for t in tools if t.name == "do_something"][0]
        with pytest.raises(PermissionError, match="Not authorized"):
            await tool._execute()

    @pytest.mark.asyncio
    async def test_post_execute_transforms_result(self):
        tk = TransformToolkit()
        tools = tk.get_tools()
        tool = [t for t in tools if t.name == "compute"][0]
        result = await tool._execute()
        assert result == "[transformed] raw"

    def test_hooks_not_exposed_as_tools(self):
        tk = SpyToolkit()
        tool_names = [t.name for t in tk.get_tools()]
        assert "_pre_execute" not in tool_names
        assert "_post_execute" not in tool_names
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm `ToolkitTool._execute()` still calls `self.bound_method(**kwargs)` at line ~137
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-747-abstracttoolkit-lifecycle-hooks.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
