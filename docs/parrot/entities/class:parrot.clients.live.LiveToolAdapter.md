---
type: Wiki Entity
title: LiveToolAdapter
id: class:parrot.clients.live.LiveToolAdapter
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Adapter to convert AI-Parrot AbstractTool instances to Gemini Live API
---

# LiveToolAdapter

Defined in [`parrot.clients.live`](../summaries/mod:parrot.clients.live.md).

```python
class LiveToolAdapter
```

Adapter to convert AI-Parrot AbstractTool instances to Gemini Live API
function declarations and handle execution/response formatting.

Reuses patterns from GoogleGenAIClient._prepare_tool_definitions()

## Methods

- `def get_function_declarations(self) -> List[types.FunctionDeclaration]` — Convert all tools to Gemini Live API function declarations.
- `async def execute_tool(self, function_call: Any, context: Optional[Dict[str, Any]]=None) -> tuple[types.FunctionResponse, Optional[Dict[str, Any]]]` — Execute a tool call and return a (FunctionResponse, display_data) tuple.
