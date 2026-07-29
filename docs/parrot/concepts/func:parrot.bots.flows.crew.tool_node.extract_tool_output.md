---
type: Concept
title: extract_tool_output()
id: func:parrot.bots.flows.crew.tool_node.extract_tool_output
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the string form of a ``ToolResult`` payload.
---

# extract_tool_output

```python
def extract_tool_output(tool_result: ToolResult) -> str
```

Return the string form of a ``ToolResult`` payload.

Used wherever the crew stores node outputs as strings
(``FlowContext.results``, context summaries, ``NodeResult``).

Args:
    tool_result: The tool execution result to stringify.

Returns:
    The raw string when the payload already is one, otherwise its JSON
    encoding (falling back to ``str()`` for non-serialisable payloads).
