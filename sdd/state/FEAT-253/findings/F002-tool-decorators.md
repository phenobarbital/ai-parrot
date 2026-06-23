---
id: F002
slug: tool-decorators
query: "@tool_schema and @tool decorator patterns"
type: read
---

## Finding: Two decorator patterns for tools

**File:** `packages/ai-parrot/src/parrot/tools/decorators.py`

### @tool_schema(PydanticModel) — lines 37-52
- Attaches `_args_schema` to method; `ToolkitTool` checks this first
- Used inside toolkit classes for explicit input validation
- Example: `@tool_schema(StoreInput)` on `WorkingMemoryToolkit.store()`

### @tool(...) — lines 55-160
- For standalone functions (not inside toolkits)
- Supports `requires_confirmation=True`, `confirm_template`, `confirm_window_seconds`
- Sets `func._is_tool = True` and `func._tool_metadata`

### Correction to SPEC:
- SPEC uses `@tool_schema` correctly but the import path should be `from parrot.tools.decorators import tool_schema`
