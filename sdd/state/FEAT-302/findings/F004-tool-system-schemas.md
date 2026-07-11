---
id: F004
slug: tool-system-schemas
query: Read tools/manager.py and tools/abstract.py
type: read
---

## Finding: Tool System and Schema Adaptation

**Paths**:
- `packages/ai-parrot/src/parrot/tools/manager.py` (line 43+)
- `packages/ai-parrot/src/parrot/tools/abstract.py` (line 298+)

`ToolFormat` enum: `OPENAI`, `ANTHROPIC`, `GOOGLE`, `GROQ`, `VERTEX`, `GENERIC`.
No `BEDROCK` value exists yet.

`ToolSchemaAdapter.clean_schema_for_provider()` adapts schemas per provider.

Tool schema from `AbstractTool.get_schema()`:
```json
{"name": "...", "description": "...", "parameters": {"type": "object", "properties": {...}, "required": [...], "additionalProperties": false}}
```

Bedrock Converse API expects:
```json
{"toolSpec": {"name": "...", "description": "...", "inputSchema": {"json": {...}}}}
```

Anthropic format (closest): `{"name": ..., "description": ..., "input_schema": {...}}`

**Action needed**: Add `ToolFormat.BEDROCK` and implement `_clean_for_bedrock()` that wraps the
schema in the `toolSpec`/`inputSchema.json` envelope.
