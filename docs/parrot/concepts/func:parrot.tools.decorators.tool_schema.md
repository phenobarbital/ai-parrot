---
type: Concept
title: tool_schema()
id: func:parrot.tools.decorators.tool_schema
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Decorator to specify a custom argument schema for a toolkit method.
---

# tool_schema

```python
def tool_schema(schema: Type[BaseModel], description: Optional[str]=None)
```

Decorator to specify a custom argument schema for a toolkit method.

Usage:
    @tool_schema(MyCustomSchema)
    async def my_tool(self, arg1: str, arg2: int) -> str:
        '''My custom tool.'''
        return result
