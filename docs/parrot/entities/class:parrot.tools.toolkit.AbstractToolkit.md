---
type: Wiki Entity
title: AbstractToolkit
id: class:parrot.tools.toolkit.AbstractToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base class for creating toolkits - collections of related tools.
---

# AbstractToolkit

Defined in [`parrot.tools.toolkit`](../summaries/mod:parrot.tools.toolkit.md).

```python
class AbstractToolkit(ABC)
```

Abstract base class for creating toolkits - collections of related tools.

A toolkit automatically converts all public async methods into tools.
Each method becomes a tool with:
- Name: method name
- Description: method docstring
- Schema: automatically generated from type hints

Usage:
    class MyToolkit(AbstractToolkit):
        async def search_web(self, query: str) -> str:
            '''Search the web for information.'''
            # Implementation here
            return result

        async def calculate(self, expression: str) -> float:
            '''Calculate a mathematical expression.'''
            # Implementation here
            return result

    # Get all tools
    toolkit = MyToolkit()
    tools = toolkit.get_tools()

## Methods

- `async def start(self) -> None` — Optional startup logic for the toolkit.
- `async def stop(self) -> None` — Optional shutdown logic for the toolkit.
- `async def cleanup(self) -> None` — Optional cleanup logic for the toolkit.
- `def get_tools(self, permission_context: Optional['PermissionContext']=None, resolver: Optional['AbstractPermissionResolver']=None) -> List[AbstractTool]` — Get all tools from this toolkit, optionally filtered by permissions.
- `async def get_tools_filtered(self, permission_context: 'PermissionContext', resolver: 'AbstractPermissionResolver') -> List[AbstractTool]` — Get tools filtered by async permission resolver.
- `def get_tools_sync(self, permission_context: Optional['PermissionContext']=None, resolver: Optional['AbstractPermissionResolver']=None) -> List[AbstractTool]` — Synchronous alias for get_tools(). Returns all tools (unfiltered).
- `def get_tool(self, name: str) -> Optional[AbstractTool]` — Get a specific tool by name.
- `def list_tool_names(self) -> List[str]` — Get a list of all tool names in this toolkit.
- `def get_toolkit_info(self) -> Dict[str, Any]` — Get information about this toolkit.
