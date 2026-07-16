---
type: Concept
title: create_sandbox_tool()
id: func:parrot_tools.sandboxtool.create_sandbox_tool
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Factory function to create gVisor tools.
---

# create_sandbox_tool

```python
def create_sandbox_tool(tool_type: str='sandbox', **kwargs) -> Union[SandboxTool, SandboxPandasTool]
```

Factory function to create gVisor tools.

Args:
    tool_type: Type of tool ('sandbox' or 'pandas')
    **kwargs: Configuration parameters

Returns:
    Configured gVisor tool instance
