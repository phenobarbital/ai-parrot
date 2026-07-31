---
type: Wiki Entity
title: SharePointToolkit
id: class:parrot_tools.o365.bundle.SharePointToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: SharePoint file management toolkit for AI-Parrot agents.
---

# SharePointToolkit

Defined in [`parrot_tools.o365.bundle`](../summaries/mod:parrot_tools.o365.bundle.md).

```python
class SharePointToolkit
```

SharePoint file management toolkit for AI-Parrot agents.

This toolkit provides comprehensive SharePoint integration:
- List files in document libraries
- Search for files
- Download files
- Upload files

Usage:
    toolkit = SharePointToolkit(
        client_id='your-client-id',
        client_secret='your-client-secret',
        tenant_id='your-tenant-id'
    )

    # Add to agent
    agent = BasicAgent(
        name="SharePointAgent",
        tools=toolkit.get_tools()
    )

## Methods

- `def get_tools(self) -> List[Any]` — Get all toolkit tools.
- `def get_tool_by_name(self, name: str) -> Optional[Any]` — Get a specific tool by name.
- `async def cleanup(self)` — Clean up all tool resources.
