# F004 — AbstractToolkit

**Path**: `packages/ai-parrot/src/parrot/tools/toolkit.py`
**Lines**: 191-518

Auto-discovers public async methods as agent tools.
Constructor takes `**kwargs` (return_direct, base_url, tool_prefix, etc.).

Key attributes:
- `exclude_tools: tuple[str, ...]` — methods excluded from auto-discovery
- `tool_prefix: Optional[str]` — namespace prefix for all tools
- `_pre_execute()` / `_post_execute()` — lifecycle hooks

Lifecycle exclusion list: get_tools, get_tools_filtered, get_tools_sync,
get_tool, list_tool_names, start, stop, cleanup.

Every public async method not in exclude_tools becomes a tool with auto-
generated Pydantic schema from type hints.
