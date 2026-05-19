---
id: F005
query: Q006
type: grep+read
target: packages/ai-parrot/src/parrot/tools/toolkit.py
---

# F005 — AbstractToolkit and @tool Decorator Verification

**Status**: Confirmed with clarifications

## AbstractToolkit(ABC) — packages/ai-parrot/src/parrot/tools/toolkit.py

### Key methods
- `get_tools(permission_context?, resolver?) -> List[AbstractTool]` — returns all tools
- `get_tools_filtered(permission_context, resolver) -> List[AbstractTool]` — async, Layer 1 filtering
- `get_tool(name) -> Optional[AbstractTool]` — single tool by name
- `list_tool_names() -> List[str]`

### Tool discovery mechanism
`_generate_tools()` introspects all public async methods (skipping `_`-prefixed and management methods).
Each method becomes a `ToolkitTool` instance.

### Features
- Namespace support: `tool_prefix`, `prefix_separator`
- Lifecycle hooks: `_pre_execute(tool_name, **kwargs)`, `_post_execute(tool_name, result, **kwargs)`
- `exclude_tools` list to skip specific methods

## @tool decorator — packages/ai-parrot/src/parrot/tools/decorators.py
```python
def tool(_func=None, *, name=None, description=None, schema=None, auto_register=False)
```
For standalone functions only. Sets `_tool_metadata` and `_is_tool = True`.

## Clarification
- `@tool` is for standalone functions
- `AbstractToolkit` uses introspection, NOT @tool
- In ai-parrot-tools, toolkit methods use `@tool_schema(PydanticInputModel)` decorator
